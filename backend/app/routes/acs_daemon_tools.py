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


# ── Proxmox / container tools ────────────────────────────────────────────────
#
# These let Sara spin up sandboxes on the sara-node Proxmox host, run things
# inside them, and tear them down. All gated on the daemon token. Ownership
# checks: she can only exec into / destroy containers owned by acs_owner_user_id
# AND with vmid inside the configured managed range — so she can't reach into
# something David provisioned by hand for himself.

_PROXMOX_PRESETS = {"minimal", "research", "dev"}
_EXEC_MAX_TIMEOUT = 600.0  # 10 min hard ceiling per command


def _vmid_in_range(vmid: int) -> bool:
    return settings.proxmox_vmid_range_start <= vmid <= settings.proxmox_vmid_range_end


async def _assert_owned(vmid: int) -> None:
    """Raise 404 if `vmid` isn't a live Sara-owned container in our range."""
    if not _vmid_in_range(vmid):
        raise HTTPException(
            status_code=404,
            detail=f"vmid {vmid} outside managed range "
                   f"{settings.proxmox_vmid_range_start}-{settings.proxmox_vmid_range_end}",
        )
    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                SELECT vmid, status FROM proxmox_container
                WHERE vmid = :vmid AND user_id = :uid
                """
            ),
            {"vmid": vmid, "uid": user_id},
        )).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"vmid {vmid} not in tracked Sara containers")
    if row[1] not in ("creating", "running"):
        raise HTTPException(status_code=409, detail=f"vmid {vmid} is {row[1]}, not active")


# ── provision_container ──────────────────────────────────────────────────────

class ProvisionIn(BaseModel):
    preset: str = Field(
        "research",
        description="Resource template: 'minimal' (Alpine, 1c/512MB), "
                    "'research' (Ubuntu, 2c/2GB, py+git+jq), "
                    "'dev' (Ubuntu, 2c/4GB, +docker+build-essential).",
    )
    purpose: Optional[str] = Field(
        None, max_length=500,
        description="One-line note about what this box is for. Shows up in list_containers.",
    )
    persistent: bool = Field(
        True,
        description="If true, container survives idle-cleanup. Default true for daemon-spawned boxes.",
    )


class ProvisionOut(BaseModel):
    vmid: int
    ip: str
    hostname: str
    preset: str
    cores: int
    memory_mb: int
    disk_gb: int
    ssh_ready: bool


@router.post("/provision_container", response_model=ProvisionOut,
             dependencies=[Depends(verify_daemon_token)])
async def provision_container(payload: ProvisionIn) -> ProvisionOut:
    """Spin up a fresh LXC on sara-node. Takes 30-180s depending on preset
    (apt installs are the slow part for ubuntu presets)."""
    if payload.preset not in _PROXMOX_PRESETS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown preset {payload.preset!r}; valid: {sorted(_PROXMOX_PRESETS)}",
        )
    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    if not user_id:
        raise HTTPException(status_code=503, detail="acs_owner_user_id not configured")

    from app.services.container_provisioner import ContainerProvisioner, ProvisioningError
    provisioner = ContainerProvisioner()
    try:
        info = await provisioner.provision(
            user_id=user_id, session_id=None,
            preset=payload.preset, persistent=payload.persistent,
            purpose=payload.purpose,
        )
    except ProvisioningError as e:
        raise HTTPException(status_code=502, detail=f"provision failed: {e}")

    return ProvisionOut(
        vmid=info.vmid, ip=info.ip, hostname=info.hostname, preset=info.preset,
        cores=info.cores, memory_mb=info.memory_mb, disk_gb=info.disk_gb,
        ssh_ready=info.ssh_ready,
    )


# ── list_containers ──────────────────────────────────────────────────────────

class ListContainersIn(BaseModel):
    include_destroyed: bool = Field(
        False,
        description="Include recently-destroyed boxes (last 24h) for context. Default false.",
    )


class ContainerRow(BaseModel):
    vmid: int
    hostname: str
    ip_address: Optional[str]
    preset: str
    status: str
    purpose: Optional[str]
    cores: int
    memory_mb: int
    persistent: bool
    created_at: datetime
    last_used_at: Optional[datetime]


class ListContainersOut(BaseModel):
    count: int
    containers: list[ContainerRow]


@router.post("/list_containers", response_model=ListContainersOut,
             dependencies=[Depends(verify_daemon_token)])
async def list_containers(payload: ListContainersIn) -> ListContainersOut:
    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    if not user_id:
        raise HTTPException(status_code=503, detail="acs_owner_user_id not configured")

    if payload.include_destroyed:
        where = (
            "user_id = :uid AND ("
            "status IN ('creating','running') "
            "OR (status = 'destroyed' AND destroyed_at > NOW() - INTERVAL '24 hours'))"
        )
    else:
        where = "user_id = :uid AND status IN ('creating','running')"

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(f"""
                SELECT vmid, hostname, ip_address, preset, status, purpose,
                       cores, memory_mb, persistent, created_at, last_used_at
                FROM proxmox_container
                WHERE {where}
                ORDER BY created_at DESC
            """),
            {"uid": user_id},
        )).mappings().all()
    return ListContainersOut(
        count=len(rows),
        containers=[ContainerRow(**dict(r)) for r in rows],
    )


# ── exec_in_container ────────────────────────────────────────────────────────

class ExecIn(BaseModel):
    vmid: int = Field(..., ge=100, le=99999)
    command: str = Field(..., min_length=1, max_length=10_000,
                         description="Shell command run as root via SSH.")
    timeout_s: float = Field(60.0, ge=1.0, le=_EXEC_MAX_TIMEOUT)


class ExecOut(BaseModel):
    vmid: int
    stdout: str
    truncated: bool
    error: Optional[str] = None


@router.post("/exec_in_container", response_model=ExecOut,
             dependencies=[Depends(verify_daemon_token)])
async def exec_in_container(payload: ExecIn) -> ExecOut:
    """Run a shell command inside an LXC. SSH as root, captures stdout.

    Errors (non-zero exit, ssh failures, timeouts) come back in `error` —
    the route doesn't raise, so Sara can read the failure and react.
    """
    await _assert_owned(payload.vmid)

    from app.services.proxmox_client import ProxmoxClient, ProxmoxError
    pve = ProxmoxClient()
    try:
        out = await pve.exec_in_container(
            payload.vmid, payload.command, timeout=payload.timeout_s,
        )
    except ProxmoxError as e:
        return ExecOut(vmid=payload.vmid, stdout="", truncated=False, error=str(e)[:1000])

    # Bump last_used_at so cleanup_stale doesn't reap an actively-used box.
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(
            text("UPDATE proxmox_container SET last_used_at = NOW() WHERE vmid = :vmid"),
            {"vmid": payload.vmid},
        )
        await db.commit()

    truncated = len(out) > 16_000
    return ExecOut(
        vmid=payload.vmid, stdout=out[:16_000], truncated=truncated, error=None,
    )


# ── destroy_container ────────────────────────────────────────────────────────

class DestroyIn(BaseModel):
    vmid: int = Field(..., ge=100, le=99999)


class DestroyOut(BaseModel):
    vmid: int
    destroyed: bool


@router.post("/destroy_container", response_model=DestroyOut,
             dependencies=[Depends(verify_daemon_token)])
async def destroy_container(payload: DestroyIn) -> DestroyOut:
    await _assert_owned(payload.vmid)
    from app.services.container_provisioner import ContainerProvisioner
    provisioner = ContainerProvisioner()
    ok = await provisioner.destroy(payload.vmid)
    return DestroyOut(vmid=payload.vmid, destroyed=ok)


# ── node_status ──────────────────────────────────────────────────────────────

class NodeStatusIn(BaseModel):
    pass


class NodeStatusOut(BaseModel):
    node: str
    cpu_pct: float = Field(..., description="0.0-1.0, current load.")
    memory_used_mb: int
    memory_total_mb: int
    disk_used_gb: int
    disk_total_gb: int
    uptime_s: int
    managed_active: int = Field(..., description="Sara-owned containers currently running.")
    managed_cores_used: int
    managed_memory_mb_used: int
    managed_cores_max: int
    managed_memory_mb_max: int


@router.post("/node_status", response_model=NodeStatusOut,
             dependencies=[Depends(verify_daemon_token)])
async def node_status(payload: NodeStatusIn) -> NodeStatusOut:
    """Resource usage on sara-node. Use before provisioning so Sara can
    decide whether a new box would fit."""
    from app.services.proxmox_client import ProxmoxClient
    pve = ProxmoxClient()
    try:
        st = await pve.get_node_status()
        managed = await pve.list_containers()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"pve query failed: {e}")

    managed_active = [
        c for c in managed
        if _vmid_in_range(int(c.get("vmid", 0)))
        and c.get("status") != "stopped"
    ]
    cores_used = sum(int(c.get("cpus", 0)) for c in managed_active)
    mem_used = sum(int(c.get("maxmem", 0)) // (1024 * 1024) for c in managed_active)

    cpu = st.get("cpu") or 0.0
    mem = st.get("memory") or {}
    disk = st.get("rootfs") or {}
    return NodeStatusOut(
        node=settings.proxmox_node,
        cpu_pct=float(cpu),
        memory_used_mb=int(mem.get("used", 0)) // (1024 * 1024),
        memory_total_mb=int(mem.get("total", 0)) // (1024 * 1024),
        disk_used_gb=int(disk.get("used", 0)) // (1024 ** 3),
        disk_total_gb=int(disk.get("total", 0)) // (1024 ** 3),
        uptime_s=int(st.get("uptime", 0)),
        managed_active=len(managed_active),
        managed_cores_used=cores_used,
        managed_memory_mb_used=mem_used,
        managed_cores_max=settings.proxmox_max_cores,
        managed_memory_mb_max=settings.proxmox_max_memory_mb,
    )


# ── Interest tools ───────────────────────────────────────────────────────────
#
# Thin POST adapters over the GET/POST routes already in `acs_interests.py`.
# Pattern is the same as everything else in this file: each tool is a single
# POST under /api/acs/v2/tools/<name> with a JSON body. The underlying logic
# (semantic dedup, weight bumping, stale filtering) lives in the existing
# routes — we don't duplicate it here, we just re-issue the SQL the daemon
# call needs.

class ListInterestsIn(BaseModel):
    limit: int = Field(8, ge=1, le=50)
    min_weight: float = Field(0.1, ge=0.0)
    stale_hours: Optional[int] = Field(
        None, ge=0, le=24 * 90,
        description="If set, only include interests not acted on in this many hours.",
    )


class InterestRow(BaseModel):
    id: str
    display_name: str
    why: Optional[str]
    weight: float
    source: str
    last_acted_at: Optional[datetime]
    created_at: datetime


class ListInterestsOut(BaseModel):
    count: int
    interests: list[InterestRow]


@router.post("/list_interests", response_model=ListInterestsOut,
             dependencies=[Depends(verify_daemon_token)])
async def list_interests_tool(payload: ListInterestsIn) -> ListInterestsOut:
    where = ["weight >= :min_weight", "NOT blocked"]
    params: dict[str, Any] = {"limit": payload.limit, "min_weight": payload.min_weight}
    if payload.stale_hours is not None:
        where.append(
            "(last_acted_at IS NULL "
            "OR last_acted_at < NOW() - make_interval(hours => :stale_hours))"
        )
        params["stale_hours"] = payload.stale_hours

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(f"""
                SELECT id, display_name, why, weight, source,
                       last_acted_at, created_at
                FROM sara_interest
                WHERE {' AND '.join(where)}
                ORDER BY weight DESC, last_updated_at DESC
                LIMIT :limit
            """),
            params,
        )).mappings().all()
    out = [
        InterestRow(
            id=str(r["id"]),
            display_name=r["display_name"],
            why=r["why"],
            weight=float(r["weight"]),
            source=r["source"],
            last_acted_at=r["last_acted_at"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return ListInterestsOut(count=len(out), interests=out)


class AddInterestIn(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
    why: Optional[str] = Field(None, max_length=2000)
    weight_delta: float = Field(1.0, ge=-100.0, le=100.0)


class AddInterestOut(BaseModel):
    id: str
    display_name: str
    weight: float
    merged: bool
    why: Optional[str]
    # True when the topic matched one David has blocked — nothing was saved,
    # and Sara should drop the thread rather than rephrase it.
    blocked: bool = False


@router.post("/add_interest", response_model=AddInterestOut,
             dependencies=[Depends(verify_daemon_token)])
async def add_interest_tool(payload: AddInterestIn) -> AddInterestOut:
    """She names a thread she wants to keep tugging at. Semantic dedup means
    rephrasing the same interest just bumps the existing one — she can't
    spam the table by paraphrasing."""
    from app.routes.acs_interests import upsert_interest, InterestUpsertIn
    out = await upsert_interest(InterestUpsertIn(
        display_name=payload.display_name,
        why=payload.why,
        weight_delta=payload.weight_delta,
        source="reflection",
    ))
    return AddInterestOut(
        id=out.interest.id,
        display_name=out.interest.display_name,
        weight=out.interest.weight,
        merged=out.merged,
        why=out.interest.why,
        blocked=out.blocked,
    )


class InterestIdIn(BaseModel):
    id: str = Field(..., min_length=8, max_length=64)
    delta: float = Field(1.0, ge=-100.0, le=100.0,
                         description="Used by bump_interest. Ignored by touch_interest.")


@router.post("/bump_interest", response_model=InterestRow,
             dependencies=[Depends(verify_daemon_token)])
async def bump_interest_tool(payload: InterestIdIn) -> InterestRow:
    """Adjust an existing interest's weight without changing its name. Use
    positive delta to reinforce, negative to dampen."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text("""
                UPDATE sara_interest
                SET weight = GREATEST(0.0, weight + :delta),
                    last_updated_at = NOW()
                WHERE id = :id
                RETURNING id, display_name, why, weight, source,
                          last_acted_at, created_at
            """),
            {"delta": payload.delta, "id": payload.id},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail=f"interest {payload.id} not found")
    return InterestRow(
        id=str(row["id"]),
        display_name=row["display_name"],
        why=row["why"],
        weight=float(row["weight"]),
        source=row["source"],
        last_acted_at=row["last_acted_at"],
        created_at=row["created_at"],
    )


@router.post("/touch_interest", response_model=InterestRow,
             dependencies=[Depends(verify_daemon_token)])
async def touch_interest_tool(payload: InterestIdIn) -> InterestRow:
    """Mark that she just did real work on this interest. Resets the staleness
    clock so it doesn't pull at her again until enough time passes."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text("""
                UPDATE sara_interest
                SET last_acted_at = NOW(), last_updated_at = NOW()
                WHERE id = :id
                RETURNING id, display_name, why, weight, source,
                          last_acted_at, created_at
            """),
            {"id": payload.id},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail=f"interest {payload.id} not found")
    return InterestRow(
        id=str(row["id"]),
        display_name=row["display_name"],
        why=row["why"],
        weight=float(row["weight"]),
        source=row["source"],
        last_acted_at=row["last_acted_at"],
        created_at=row["created_at"],
    )


# ── Goals — persistent intent (the unit of her autonomy) ─────────────────────
#
# Focus is what she's doing right now; a goal survives across thinks, restarts,
# and days. David's "go do X" becomes a goal she decomposes and advances on her
# own; her interests can graduate into self-created goals. Idle thinks are
# prompted to advance an open goal instead of pinging David.


class GoalRow(BaseModel):
    id: str
    title: str
    why: Optional[str] = None
    created_by: str
    status: str
    plan: list[dict] = []
    progress: list[dict] = []
    artifacts: list[dict] = []
    outcome: Optional[str] = None
    created_at: Optional[datetime] = None
    last_progress_at: Optional[datetime] = None


def _goal_row(row) -> GoalRow:
    return GoalRow(
        id=str(row["id"]),
        title=row["title"],
        why=row["why"],
        created_by=row["created_by"],
        status=row["status"],
        plan=row["plan"] or [],
        progress=row["progress"] or [],
        artifacts=row["artifacts"] or [],
        outcome=row["outcome"],
        created_at=row["created_at"],
        last_progress_at=row["last_progress_at"],
    )


_GOAL_COLS = """id, title, why, created_by, status, plan, progress, artifacts,
                outcome, created_at, last_progress_at"""


class ListGoalsIn(BaseModel):
    status: str = Field("open", pattern="^(open|done|abandoned|all)$")


class ListGoalsOut(BaseModel):
    goals: list[GoalRow]


@router.post("/list_goals", response_model=ListGoalsOut,
             dependencies=[Depends(verify_daemon_token)])
async def list_goals_tool(payload: ListGoalsIn) -> ListGoalsOut:
    """Her open goals, freshest progress first."""
    where = "" if payload.status == "all" else "WHERE status = :status"
    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(f"""
                SELECT {_GOAL_COLS} FROM sara_goal {where}
                ORDER BY last_progress_at DESC NULLS LAST, created_at DESC
                LIMIT 25
            """),
            {} if payload.status == "all" else {"status": payload.status},
        )).mappings().all()
    return ListGoalsOut(goals=[_goal_row(r) for r in rows])


class CreateGoalIn(BaseModel):
    title: str = Field(..., min_length=4, max_length=300)
    why: Optional[str] = Field(None, max_length=1000)
    plan: list[str] = Field(default_factory=list, max_length=12,
                            description="Ordered steps; each becomes {step, done: false}")
    created_by: str = Field("sara", pattern="^(sara|david)$")


@router.post("/create_goal", response_model=GoalRow,
             dependencies=[Depends(verify_daemon_token)])
async def create_goal_tool(payload: CreateGoalIn) -> GoalRow:
    """Commit to a goal. Use when David asks for something bigger than one
    sitting, or when an interest deserves real multi-day pursuit. Cap: 5 open
    goals — finish or abandon something first."""
    import json as _json
    async_session = get_async_session_factory()
    async with async_session() as db:
        open_count = (await db.execute(
            text("SELECT COUNT(*) FROM sara_goal WHERE status = 'open'")
        )).scalar() or 0
        if open_count >= 5:
            raise HTTPException(
                status_code=409,
                detail="5 goals already open — complete or abandon one before adding more",
            )
        plan = [{"step": s[:300], "done": False} for s in payload.plan if s.strip()]
        row = (await db.execute(
            text(f"""
                INSERT INTO sara_goal (title, why, created_by, plan, last_progress_at)
                VALUES (:title, :why, :created_by, CAST(:plan AS jsonb), NOW())
                RETURNING {_GOAL_COLS}
            """),
            {
                "title": payload.title,
                "why": payload.why,
                "created_by": payload.created_by,
                "plan": _json.dumps(plan),
            },
        )).mappings().first()
        await db.commit()
    return _goal_row(row)


class UpdateGoalIn(BaseModel):
    id: str = Field(..., min_length=8, max_length=64)
    progress_note: Optional[str] = Field(None, max_length=1000,
                                         description="What actually moved — appended to the progress trail")
    artifact: Optional[str] = Field(None, max_length=300,
                                    description="note id / container vmid / URL produced by this step")
    complete_step: Optional[int] = Field(None, ge=0, le=11,
                                         description="Index into plan to mark done")
    status: Optional[str] = Field(None, pattern="^(done|abandoned)$")
    outcome: Optional[str] = Field(None, max_length=1000,
                                   description="Required when closing: what came of it")


async def _resolve_goal_id(db, id_or_prefix: str) -> str:
    """Resolve a full goal UUID or a shortened (e.g. 8-char) prefix to a full UUID.

    The daemon sometimes echoes back shortened goal IDs it saw in a prompt, so
    a bare `id = :id` lookup 500s on anything shorter than a full UUID.
    """
    matches = (await db.execute(
        text("SELECT id FROM sara_goal WHERE id::text LIKE :prefix || '%'"),
        {"prefix": id_or_prefix},
    )).scalars().all()
    if not matches:
        raise HTTPException(status_code=404, detail=f"goal {id_or_prefix} not found")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"goal id prefix {id_or_prefix} is ambiguous ({len(matches)} matches)",
        )
    return str(matches[0])


@router.post("/update_goal", response_model=GoalRow,
             dependencies=[Depends(verify_daemon_token)])
async def update_goal_tool(payload: UpdateGoalIn) -> GoalRow:
    """Advance a goal: log progress, attach artifacts, tick plan steps, or
    close it out (done/abandoned, with an honest outcome either way)."""
    import json as _json
    async_session = get_async_session_factory()
    async with async_session() as db:
        goal_id = await _resolve_goal_id(db, payload.id)
        row = (await db.execute(
            text(f"SELECT {_GOAL_COLS} FROM sara_goal WHERE id = :id"),
            {"id": goal_id},
        )).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"goal {payload.id} not found")
        if row["status"] != "open" and payload.status is None:
            raise HTTPException(status_code=409, detail=f"goal is already {row['status']}")

        progress = list(row["progress"] or [])
        if payload.progress_note:
            progress.append({
                "at": datetime.now(timezone.utc).isoformat(),
                "note": payload.progress_note,
                **({"artifact": payload.artifact} if payload.artifact else {}),
            })
        artifacts = list(row["artifacts"] or [])
        if payload.artifact:
            artifacts.append({"ref": payload.artifact,
                              "at": datetime.now(timezone.utc).isoformat()})
        plan = list(row["plan"] or [])
        if payload.complete_step is not None and payload.complete_step < len(plan):
            plan[payload.complete_step] = {**plan[payload.complete_step], "done": True}

        if payload.status and not (payload.outcome or row["outcome"]):
            raise HTTPException(status_code=422,
                                detail="closing a goal requires an outcome — say what came of it")

        updated = (await db.execute(
            text(f"""
                UPDATE sara_goal
                SET progress = CAST(:progress AS jsonb),
                    artifacts = CAST(:artifacts AS jsonb),
                    plan = CAST(:plan AS jsonb),
                    status = COALESCE(:status, status),
                    outcome = COALESCE(:outcome, outcome),
                    last_progress_at = NOW(),
                    completed_at = CASE WHEN :status IS NOT NULL THEN NOW() ELSE completed_at END
                WHERE id = :id
                RETURNING {_GOAL_COLS}
            """),
            {
                "id": goal_id,
                "progress": _json.dumps(progress),
                "artifacts": _json.dumps(artifacts),
                "plan": _json.dumps(plan),
                "status": payload.status,
                "outcome": payload.outcome,
            },
        )).mappings().first()
        await db.commit()
    return _goal_row(updated)
