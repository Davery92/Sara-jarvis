"""ACS v2 tool endpoints — what Sara can actually DO from her daemon.

All endpoints are daemon-token only. Each wraps an existing service so the
daemon stays thin: she emits a tool_call, the daemon hits one of these
routes, the result lands in her activity log as a `tool_result` entry, and
her next think turn sees it.

Phase 7 toolkit:
  • web_search   — Tavily/SearxNG via search_service
  • web_fetch    — direct HTTP fetch with HTML→text extraction
  • write_note   — appends to David's notes table, attached to acs_owner_user_id
  • search_notes — fuzzy ILIKE over David's notes
  • search_memory — semantic search over David's episodes (memory)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from html.parser import HTMLParser
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_async_session_factory
from app.routes.acs_daemon import verify_daemon_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acs/v2/tools", tags=["ACS v2 — tools"])


# ── Date-folder resolution (Sara's Notes / YYYY / MM - Month / DD) ───────────

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


async def _ensure_folder(db, *, user_id: str, name: str, parent_id: Optional[str]) -> str:
    """Find or create a folder by (user_id, name, parent_id). Returns its id.

    Mirrors the unique constraint on `folder` (user_id, name, COALESCE(parent_id, '__ROOT__'))
    so a concurrent call never creates a duplicate.
    """
    row = (await db.execute(
        text(
            """
            SELECT id FROM folder
            WHERE user_id = :uid AND name = :name
              AND COALESCE(parent_id, '__ROOT__') = COALESCE(:parent, '__ROOT__')
            """
        ),
        {"uid": user_id, "name": name, "parent": parent_id},
    )).first()
    if row:
        return row[0]

    new_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO folder (id, user_id, name, parent_id, created_at, updated_at)
            VALUES (:id, :uid, :name, :parent, NOW(), NOW())
            ON CONFLICT (user_id, name, (COALESCE(parent_id, '__ROOT__'::character varying)))
            DO NOTHING
            """
        ),
        {"id": new_id, "uid": user_id, "name": name, "parent": parent_id},
    )
    # Re-read in case another concurrent call won the upsert race.
    row = (await db.execute(
        text(
            """
            SELECT id FROM folder
            WHERE user_id = :uid AND name = :name
              AND COALESCE(parent_id, '__ROOT__') = COALESCE(:parent, '__ROOT__')
            """
        ),
        {"uid": user_id, "name": name, "parent": parent_id},
    )).first()
    return row[0] if row else new_id


async def _resolve_today_date_folder(db, user_id: str) -> str:
    """Resolve today's day folder, creating intermediate folders as needed:

        Sara's Notes (root)
          ↳ 2026
            ↳ 05 - May
              ↳ 06   ← returned

    Uses ET (David's local time) so day-rollover happens at midnight Eastern.
    """
    from app.core.timezone import now as local_now
    today = local_now().date()
    year_str = f"{today.year}"
    month_str = f"{today.month:02d} - {_MONTH_NAMES[today.month - 1]}"
    day_str = f"{today.day:02d}"

    root_folder_id = getattr(settings, "acs_default_note_folder_id", "") or None
    if root_folder_id:
        # Verify it exists; otherwise let the year folder go to root.
        row = (await db.execute(
            text("SELECT id FROM folder WHERE id = :id AND user_id = :uid"),
            {"id": root_folder_id, "uid": user_id},
        )).first()
        if not row:
            root_folder_id = None

    year_id = await _ensure_folder(db, user_id=user_id, name=year_str, parent_id=root_folder_id)
    month_id = await _ensure_folder(db, user_id=user_id, name=month_str, parent_id=year_id)
    day_id = await _ensure_folder(db, user_id=user_id, name=day_str, parent_id=month_id)
    return day_id


# ── web_search ───────────────────────────────────────────────────────────────

class WebSearchIn(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    num_results: int = Field(5, ge=1, le=10)


class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchOut(BaseModel):
    query: str
    results: list[WebSearchResult]
    count: int


@router.post("/web_search", response_model=WebSearchOut,
             dependencies=[Depends(verify_daemon_token)])
async def web_search(payload: WebSearchIn) -> WebSearchOut:
    try:
        from app.services.search_service import search_service
        result = await search_service.web_search(
            query=payload.query,
            max_results=payload.num_results,
            extract_top_n=min(payload.num_results, 6),
        )
    except Exception as e:
        logger.warning(f"web_search failed: {e}")
        raise HTTPException(status_code=502, detail=f"search failed: {e}")
    raw = result.get("results", []) or []
    parsed = [
        WebSearchResult(
            title=r.get("title") or "(no title)",
            url=r.get("url") or "",
            snippet=r.get("snippet") or "",
        )
        for r in raw
    ]
    return WebSearchOut(query=payload.query, results=parsed, count=len(parsed))


# ── web_fetch ────────────────────────────────────────────────────────────────

class WebFetchIn(BaseModel):
    url: str = Field(..., min_length=4, max_length=2000)
    max_length: int = Field(8000, ge=500, le=40000)


class WebFetchOut(BaseModel):
    url: str
    content: str
    truncated: bool


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "header", "footer", "aside", "noscript"}

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._skip:
            t = data.strip()
            if t:
                self.parts.append(t)


@router.post("/web_fetch", response_model=WebFetchOut,
             dependencies=[Depends(verify_daemon_token)])
async def web_fetch(payload: WebFetchIn) -> WebFetchOut:
    if not (payload.url.startswith("http://") or payload.url.startswith("https://")):
        raise HTTPException(status_code=422, detail="url must be http(s)")
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SaraResearchBot/1.0)"},
        ) as client:
            resp = await client.get(payload.url)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"fetch failed: {e}")

    ctype = resp.headers.get("content-type", "")
    if "text/html" in ctype or "application/xhtml" in ctype:
        ext = _TextExtractor()
        try:
            ext.feed(resp.text)
        except Exception:
            pass
        text_out = "\n".join(ext.parts).strip()
    else:
        text_out = resp.text

    truncated = False
    if len(text_out) > payload.max_length:
        text_out = text_out[: payload.max_length] + "\n\n[... truncated]"
        truncated = True

    return WebFetchOut(url=payload.url, content=text_out, truncated=truncated)


# ── write_note ───────────────────────────────────────────────────────────────

class WriteNoteIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1, max_length=200_000)
    folder_id: Optional[str] = Field(None, max_length=64,
                                     description="Optional folder; defaults to no folder.")
    tags: list[str] = Field(default_factory=list)


class WriteNoteOut(BaseModel):
    id: str
    title: str
    created_at: datetime


@router.post("/write_note", response_model=WriteNoteOut,
             dependencies=[Depends(verify_daemon_token)])
async def write_note(payload: WriteNoteIn) -> WriteNoteOut:
    """Create a note in David's notes table, owned by acs_owner_user_id.

    We deliberately skip the heavyweight intelligence-pipeline path that
    /api/notes uses — Sara writes simple notes; David's own UI does the
    fancy graph/embedding processing for his interactive ones. The note
    still gets an embedding via a fire-and-forget task so it's searchable.
    """
    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    if not user_id:
        raise HTTPException(status_code=503, detail="acs_owner_user_id not configured")

    note_id = str(uuid.uuid4())
    import json as _json

    # Default to today's date folder under "Sara's Notes" so daemon-written
    # notes land in the same YYYY → MM-Month → DD hierarchy David is used to.
    folder_id = payload.folder_id
    async_session = get_async_session_factory()
    async with async_session() as db:
        if not folder_id:
            try:
                folder_id = await _resolve_today_date_folder(db, user_id)
            except Exception as e:
                logger.warning(
                    f"could not resolve today's date folder ({e}); "
                    f"writing note with no folder"
                )
                folder_id = None

        await db.execute(
            text(
                """
                INSERT INTO note (id, user_id, folder_id, title, content, tags, created_at, updated_at)
                VALUES (:id, :uid, :folder, :title, :content, CAST(:tags AS json), NOW(), NOW())
                """
            ),
            {
                "id": note_id, "uid": user_id, "folder": folder_id,
                "title": payload.title, "content": payload.body,
                "tags": _json.dumps(payload.tags),
            },
        )
        await db.commit()

    # Fire-and-forget embedding so it shows up in semantic note search.
    import asyncio as _asyncio

    async def _embed():
        try:
            from app.services.embeddings import get_embedding
            embed_text = f"{payload.title}\n\n{payload.body}"[:6000]
            vec = await get_embedding(embed_text)
            async_session2 = get_async_session_factory()
            async with async_session2() as db2:
                await db2.execute(
                    text("UPDATE note SET embedding = CAST(:v AS vector) WHERE id = :id"),
                    {"v": str(vec), "id": note_id},
                )
                await db2.commit()
        except Exception as e:
            logger.warning(f"note embedding failed for {note_id[:8]}: {e}")

    _asyncio.create_task(_embed())

    return WriteNoteOut(id=note_id, title=payload.title,
                        created_at=datetime.now(timezone.utc))


# ── search_notes ─────────────────────────────────────────────────────────────

class SearchNotesIn(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(8, ge=1, le=30)


class NoteSearchHit(BaseModel):
    id: str
    title: Optional[str]
    snippet: str
    similarity: Optional[float]
    updated_at: datetime


@router.post("/search_notes", response_model=list[NoteSearchHit],
             dependencies=[Depends(verify_daemon_token)])
async def search_notes_endpoint(payload: SearchNotesIn) -> list[NoteSearchHit]:
    """Semantic search over David's notes. Falls back to ILIKE if embedding fails."""
    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    if not user_id:
        raise HTTPException(status_code=503, detail="acs_owner_user_id not configured")

    # Try semantic first.
    vec: Optional[list[float]] = None
    try:
        from app.services.embeddings import get_embedding
        vec = await get_embedding(payload.query)
    except Exception as e:
        logger.warning(f"search_notes embedding failed; falling back to ILIKE: {e}")

    async_session = get_async_session_factory()
    async with async_session() as db:
        if vec is not None:
            rows = (await db.execute(
                text(
                    """
                    SELECT id, title, content, updated_at,
                           1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                    FROM note
                    WHERE user_id = :uid AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector) ASC
                    LIMIT :lim
                    """
                ),
                {"vec": str(vec), "uid": user_id, "lim": payload.limit},
            )).mappings().all()
        else:
            pat = f"%{payload.query}%"
            rows = (await db.execute(
                text(
                    """
                    SELECT id, title, content, updated_at, NULL::float AS similarity
                    FROM note
                    WHERE user_id = :uid
                      AND (title ILIKE :pat OR content ILIKE :pat)
                    ORDER BY updated_at DESC
                    LIMIT :lim
                    """
                ),
                {"uid": user_id, "pat": pat, "lim": payload.limit},
            )).mappings().all()

    out: list[NoteSearchHit] = []
    for r in rows:
        body = (r["content"] or "").strip()
        snippet = body[:300] + ("…" if len(body) > 300 else "")
        out.append(NoteSearchHit(
            id=str(r["id"]), title=r["title"], snippet=snippet,
            similarity=(float(r["similarity"]) if r["similarity"] is not None else None),
            updated_at=r["updated_at"],
        ))
    return out


# ── search_memory ────────────────────────────────────────────────────────────

class SearchMemoryIn(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(8, ge=1, le=30)


class MemoryHit(BaseModel):
    id: str
    when: datetime
    role: Optional[str]
    content: str
    similarity: float


@router.post("/search_memory", response_model=list[MemoryHit],
             dependencies=[Depends(verify_daemon_token)])
async def search_memory(payload: SearchMemoryIn) -> list[MemoryHit]:
    """Semantic search over David's episodic memory (the `episode` table).

    These are the same memories conversational Sara queries — gives the
    daemon access to David's history (chats, decisions, life events) that
    aren't in the notes table.
    """
    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    if not user_id:
        raise HTTPException(status_code=503, detail="acs_owner_user_id not configured")
    try:
        from app.services.embeddings import get_embedding
        vec = await get_embedding(payload.query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"embedding failed: {e}")

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                """
                SELECT id, created_at, role, content,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM episode
                WHERE user_id = :uid AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector) ASC
                LIMIT :lim
                """
            ),
            {"vec": str(vec), "uid": user_id, "lim": payload.limit},
        )).mappings().all()

    return [
        MemoryHit(
            id=str(r["id"]),
            when=r["created_at"],
            role=r["role"],
            content=(r["content"] or "").strip()[:600],
            similarity=float(r["similarity"]),
        )
        for r in rows
    ]
