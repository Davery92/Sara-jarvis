"""ACS v2 daemon endpoints — heartbeat + ambient self-context for the Sara-VM
resident cognition daemon.

- Phase 1 surface: heartbeat (POST), daemon-status (GET).
- Phase 2 surface: activity log append/list, focus get/set.

Auth for the daemon is a shared bearer token (settings.acs_daemon_token);
user-facing reads use normal session auth.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.config import settings
from app.core.deps import get_current_user, get_current_user_optional
from app.db.session import get_async_session_factory, get_db
from sqlalchemy.orm import Session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acs/v2", tags=["ACS v2"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def verify_daemon_token(x_daemon_token: Optional[str] = Header(None)) -> None:
    """Shared-secret check for the in-VM daemon."""
    expected = getattr(settings, "acs_daemon_token", None) or ""
    if not expected:
        raise HTTPException(status_code=503, detail="daemon token not configured on backend")
    if not x_daemon_token or x_daemon_token != expected:
        raise HTTPException(status_code=401, detail="invalid daemon token")


# ── Schemas ───────────────────────────────────────────────────────────────────

class HeartbeatIn(BaseModel):
    state: str = Field(..., description="boot|idle|working|sleeping|error")
    version: str = Field(..., description="daemon code version, e.g. 0.1.0")
    pid: int
    hostname: str
    started_at: datetime
    last_tick_summary: Optional[str] = None
    want_delta: bool = Field(
        False,
        description="ACS1: set true on a think tick to receive (and consume) the "
                    "world_delta since the last one served.")
    # SINGULAR_SARA_MASTER_PLAN §C7 — additive, backward compatible: a daemon
    # binary that predates this field simply omits it and heartbeats exactly
    # as before. Feeds `body_capability` (the VM-workshop row), not the
    # daemon's own identity/prompt — that stays untouched until parity gates
    # in the plan are actually met.
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatOut(BaseModel):
    server_time: datetime
    accepted: bool = True
    # Reserved for Phase 4 (control channel). Empty list for now.
    pending_directives: list[dict] = Field(default_factory=list)
    # ACS1: compact "what changed while you were idle" since the last delta.
    world_delta: list[str] = Field(default_factory=list)


class DaemonStatusOut(BaseModel):
    state: str
    version: str
    pid: Optional[int]
    hostname: Optional[str]
    started_at: Optional[datetime]
    last_heartbeat_at: Optional[datetime]
    last_tick_summary: Optional[str]
    is_alive: bool
    seconds_since_heartbeat: Optional[int]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/heartbeat", response_model=HeartbeatOut, dependencies=[Depends(verify_daemon_token)])
async def daemon_heartbeat(payload: HeartbeatIn) -> HeartbeatOut:
    """Daemon → backend. Upserts the singleton state row."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO sara_daemon_state
                    (id, version, state, pid, hostname, started_at, last_heartbeat_at, last_tick_summary, updated_at)
                VALUES
                    ('singleton', :version, :state, :pid, :hostname, :started_at, NOW(), :summary, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    version = EXCLUDED.version,
                    state = EXCLUDED.state,
                    pid = EXCLUDED.pid,
                    hostname = EXCLUDED.hostname,
                    started_at = EXCLUDED.started_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    last_tick_summary = EXCLUDED.last_tick_summary,
                    updated_at = NOW()
                """
            ),
            {
                "version": payload.version,
                "state": payload.state,
                "pid": payload.pid,
                "hostname": payload.hostname,
                "started_at": payload.started_at,
                "summary": payload.last_tick_summary,
            },
        )

        world_delta: list[str] = []
        if payload.want_delta:
            world_delta = await _compute_world_delta(db)

        # SINGULAR_SARA_MASTER_PLAN §C7: additive body-capability record for
        # the VM workshop. Best-effort — a failure here must never fail the
        # heartbeat the daemon depends on to be considered alive.
        try:
            from app.services.body_capability_service import upsert_capability
            await upsert_capability(
                db, name="vm_workshop", kind="vm", version=payload.version,
                capabilities=payload.capabilities,
                metadata={"hostname": payload.hostname, "pid": payload.pid},
            )
        except Exception as e:
            logger.debug(f"body_capability upsert failed (non-fatal): {e}")

        await db.commit()

    return HeartbeatOut(server_time=datetime.now(timezone.utc), world_delta=world_delta)


async def _compute_world_delta(db) -> list[str]:
    """ACS1: compact list of what changed in David's world since the daemon last
    consumed a delta. Advances the watermark so each change is served once.

    The daemon must NOT grow its own pollers (ACS4): this is the single channel
    by which backend-computed world state reaches the slow mind.
    """
    row = (await db.execute(text(
        "SELECT last_delta_served_at FROM sara_daemon_state WHERE id='singleton'"
    ))).first()
    since = (row[0] if row and row[0] else None)
    # Bound the first-ever window so we don't dump hours of history.
    since_clause = "COALESCE(:since, NOW() - INTERVAL '2 hours')"
    params = {"since": since}
    delta: list[str] = []

    async def _safe(coro):
        try:
            return await coro
        except Exception as e:
            logger.debug("world_delta source failed: %s", e)
            return []

    # 1. What the backend already told David (ACS4 cross-awareness — so the two
    #    brains never repeat each other).
    rows = await _safe(db.execute(text(f"""
        SELECT title, sent_at FROM notification_log
        WHERE sent = true AND source <> 'acs_daemon'
          AND sent_at > {since_clause}
        ORDER BY sent_at DESC LIMIT 6
    """), params))
    for r in (rows or []):
        delta.append(f"Backend told David: {r[0]}")

    # 2. Backend deliberation handoff notes (what the fast mind is watching).
    rows = await _safe(db.execute(text(f"""
        SELECT handoff_note FROM agent_run_log
        WHERE handoff_note IS NOT NULL AND handoff_note <> ''
          AND created_at > {since_clause}
        ORDER BY created_at DESC LIMIT 3
    """), params))
    for r in (rows or []):
        delta.append(f"Backend deliberation: {str(r[0])[:200]}")

    # 3. David was active (his own turns) — a strong "the world moved" signal
    #    the slow mind would otherwise be blind to.
    rows = await _safe(db.execute(text(f"""
        SELECT count(*) FROM episode
        WHERE role = 'user' AND created_at > {since_clause}
    """), params))
    try:
        n = int(rows[0][0]) if rows else 0
    except Exception:
        n = 0
    if n:
        delta.append(f"David was active — {n} new message(s) since you last checked.")

    await db.execute(text(
        "UPDATE sara_daemon_state SET last_delta_served_at = NOW() WHERE id='singleton'"
    ))
    return delta[:12]


@router.get("/daemon-status", response_model=DaemonStatusOut)
async def daemon_status(current_user: User = Depends(get_current_user)) -> DaemonStatusOut:
    """David-facing view of whether Sara's daemon is alive."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                SELECT version, state, pid, hostname, started_at,
                       last_heartbeat_at, last_tick_summary
                FROM sara_daemon_state
                WHERE id = 'singleton'
                """
            )
        )).mappings().first()

    if not row:
        return DaemonStatusOut(
            state="never_started",
            version="-",
            pid=None,
            hostname=None,
            started_at=None,
            last_heartbeat_at=None,
            last_tick_summary=None,
            is_alive=False,
            seconds_since_heartbeat=None,
        )

    last_hb = row["last_heartbeat_at"]
    seconds_since = None
    is_alive = False
    if last_hb is not None:
        delta = datetime.now(timezone.utc) - last_hb
        seconds_since = int(delta.total_seconds())
        # Daemon ticks every 60s; allow 3x leeway before considering dead.
        is_alive = delta < timedelta(seconds=180)

    return DaemonStatusOut(
        state=row["state"],
        version=row["version"],
        pid=row["pid"],
        hostname=row["hostname"],
        started_at=row["started_at"],
        last_heartbeat_at=last_hb,
        last_tick_summary=row["last_tick_summary"],
        is_alive=is_alive,
        seconds_since_heartbeat=seconds_since,
    )


# ── Idle gate helper ─────────────────────────────────────────────────────────

class WakeCheckOut(BaseModel):
    has_queued_inbox: bool
    has_focus: bool
    new_event_count: int
    latest_event_at: Optional[datetime]
    server_time: datetime


@router.get("/wake-check", response_model=WakeCheckOut,
            dependencies=[Depends(verify_daemon_token)])
async def wake_check(
    since: datetime = Query(..., description="Inclusive lower bound for new external_event detection"),
) -> WakeCheckOut:
    """One round-trip the daemon hits each tick to decide whether to think.

    Returns whether there's queued inbox work, whether focus is set, and how
    many external_event rows have arrived since `since`. The daemon should
    skip the LLM call (and back off its sleep) when all three signals are empty.
    """
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                SELECT
                  EXISTS(
                    SELECT 1 FROM sara_inbox WHERE status = 'queued'
                  ) AS has_queued_inbox,
                  COALESCE(
                    (SELECT topic IS NOT NULL FROM sara_focus WHERE id = 'singleton'),
                    FALSE
                  ) AS has_focus,
                  (SELECT COUNT(*) FROM sara_activity_log
                    WHERE kind = 'external_event' AND created_at > :since) AS new_event_count,
                  (SELECT MAX(created_at) FROM sara_activity_log
                    WHERE kind = 'external_event' AND created_at > :since) AS latest_event_at
                """
            ),
            {"since": since},
        )).mappings().first()

    return WakeCheckOut(
        has_queued_inbox=bool(row["has_queued_inbox"]),
        has_focus=bool(row["has_focus"]),
        new_event_count=int(row["new_event_count"] or 0),
        latest_event_at=row["latest_event_at"],
        server_time=datetime.now(timezone.utc),
    )


# ── Phase 2: ambient self-context ────────────────────────────────────────────

ALLOWED_ACTIVITY_KINDS = {
    "boot", "shutdown", "tick",
    "thought", "reflection",
    "focus_set", "focus_clear",
    "notify_david",
    "inbox_pickup", "inbox_complete", "inbox_dismiss",
    "tool_call", "tool_result",
    "external_event", "error",
}


class ActivityIn(BaseModel):
    kind: str = Field(..., description=f"one of: {sorted(ALLOWED_ACTIVITY_KINDS)}")
    summary: str = Field(..., max_length=500)
    body: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivityOut(BaseModel):
    id: str
    created_at: datetime
    kind: str
    summary: str
    body: Optional[str]
    tags: list[str]
    metadata: dict[str, Any]


class FocusIn(BaseModel):
    topic: str = Field(..., max_length=200)
    why: Optional[str] = Field(None, max_length=1000)


class FocusOut(BaseModel):
    topic: Optional[str]
    why: Optional[str]
    set_at: Optional[datetime]
    updated_at: Optional[datetime]


def _row_to_activity(row: dict) -> ActivityOut:
    return ActivityOut(
        id=str(row["id"]),
        created_at=row["created_at"],
        kind=row["kind"],
        summary=row["summary"],
        body=row["body"],
        tags=row["tags"] or [],
        metadata=row["metadata"] or {},
    )


# Feed hygiene (Phase 6). Only things Sara did *for David* belong in the
# user-facing "While you were away" feed; her own bookkeeping is internal.
_USER_FACING_KINDS = {"notify_david", "inbox_complete"}
# Summaries that are Sara narrating her own internal state / goal lifecycle /
# loop management — forced internal even if the daemon tagged them notify_david
# (the JIT-goal-funeral class of leak).
import re as _re
_INTERNAL_PHRASE = _re.compile(
    r"\b(going quiet|idle loop|abandon(?:ing|ed)?|closing (?:the )?\w+ goal|jit goal|"
    r"stale goal|loop management|habituat|went quiet|staying quiet|no action needed|"
    r"formally clos|deprioritiz|self-audit)\b", _re.IGNORECASE)


def classify_audience(kind: str, summary: str, metadata: dict = None) -> str:
    """internal | user_facing. Explicit metadata.audience wins; then internal
    phrasing forces internal; then kind decides."""
    if metadata and metadata.get("audience") in ("internal", "user_facing"):
        return metadata["audience"]
    if summary and _INTERNAL_PHRASE.search(summary):
        return "internal"
    return "user_facing" if kind in _USER_FACING_KINDS else "internal"


def _dedup_key(kind: str, summary: str, metadata: dict = None) -> str:
    """Collapse near-identical repeats: (kind, subject). subject = explicit
    metadata.subject, else the first ~8 lowercased alnum words of the summary."""
    subj = (metadata or {}).get("subject")
    if not subj:
        words = _re.findall(r"[a-z0-9]+", (summary or "").lower())
        subj = " ".join(words[:8])
    return f"{kind}:{subj}"[:200]


# Kinds we bother embedding — content kinds where semantic recall is useful.
# Booking/lifecycle (boot, shutdown, tick, error) gets skipped to keep the
# similarity search relevant. Focus_set and inbox transitions are kept because
# "I focused on X last Tuesday" is a useful recall signal.
EMBEDDABLE_KINDS = {
    "thought", "reflection",
    "focus_set", "focus_clear",
    "inbox_pickup", "inbox_complete", "inbox_dismiss",
    "notify_david",
    "tool_result",
    "external_event",
}


async def _embed_and_store(activity_id: str, text_to_embed: str) -> None:
    """Fire-and-forget: generate embedding and write it back to the row."""
    if not text_to_embed.strip():
        return
    try:
        from app.services.embeddings import get_embedding
        vec = await get_embedding(text_to_embed)
    except Exception as e:
        logger.warning(f"sara_activity embedding failed for {activity_id[:8]}: {e}")
        return
    async_session = get_async_session_factory()
    try:
        async with async_session() as db:
            await db.execute(
                text(
                    "UPDATE sara_activity_log SET embedding = CAST(:vec AS vector) WHERE id = :id"
                ),
                {"vec": str(vec), "id": activity_id},
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"sara_activity embedding write failed for {activity_id[:8]}: {e}")


@router.post("/activity", response_model=ActivityOut, dependencies=[Depends(verify_daemon_token)])
async def append_activity(payload: ActivityIn) -> ActivityOut:
    """Daemon-only: append one entry to the activity log.

    For embedding-eligible kinds, kicks off a fire-and-forget background task
    to generate and store the embedding so future think turns can recall this
    entry via similarity search.
    """
    if payload.kind not in ALLOWED_ACTIVITY_KINDS:
        raise HTTPException(status_code=422, detail=f"unknown kind '{payload.kind}'")
    audience = classify_audience(payload.kind, payload.summary, payload.metadata)
    dedup_key = _dedup_key(payload.kind, payload.summary, payload.metadata)
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Lifecycle dedup (Phase 6): collapse a near-identical entry within 24h into
        # the existing one (bump its timestamp) instead of appending a duplicate —
        # kills the "Closing abandoned JIT goal" x4 spam.
        existing = (await db.execute(
            text("""SELECT id FROM sara_activity_log
                    WHERE dedup_key = :dk AND created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC LIMIT 1"""),
            {"dk": dedup_key})).first()
        if existing:
            row = (await db.execute(
                text("""UPDATE sara_activity_log
                        SET created_at = NOW(), summary = :summary, body = :body
                        WHERE id = :id
                        RETURNING id, created_at, kind, summary, body, tags, metadata"""),
                {"id": existing[0], "summary": payload.summary, "body": payload.body})).mappings().first()
            await db.commit()
            return _row_to_activity(dict(row))

        row = (await db.execute(
            text(
                """
                INSERT INTO sara_activity_log (kind, summary, body, tags, metadata, audience, dedup_key)
                VALUES (:kind, :summary, :body, CAST(:tags AS jsonb), CAST(:metadata AS jsonb), :audience, :dedup_key)
                RETURNING id, created_at, kind, summary, body, tags, metadata
                """
            ),
            {
                "kind": payload.kind,
                "summary": payload.summary,
                "body": payload.body,
                "tags": json.dumps(payload.tags),
                "metadata": json.dumps(payload.metadata),
                "audience": audience,
                "dedup_key": dedup_key,
            },
        )).mappings().first()
        await db.commit()

    # Fire-and-forget embedding for content kinds.
    if payload.kind in EMBEDDABLE_KINDS:
        embed_text = (payload.summary or "").strip()
        if payload.body:
            embed_text = f"{embed_text}\n\n{payload.body.strip()}"
        if embed_text:
            import asyncio as _asyncio
            _asyncio.create_task(_embed_and_store(str(row["id"]), embed_text))

    return _row_to_activity(dict(row))


@router.get("/activity", response_model=list[ActivityOut])
async def list_activity(
    limit: int = Query(20, ge=1, le=200),
    kind: Optional[str] = Query(None),
    audience: Optional[str] = Query(None, description="'user_facing' for the While-you-were-away feed; omit for everything"),
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[ActivityOut]:
    """Recent activity entries. Auth: daemon token OR session user."""
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")

    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if kind:
        if kind not in ALLOWED_ACTIVITY_KINDS:
            raise HTTPException(status_code=422, detail=f"unknown kind '{kind}'")
        clauses.append("kind = :kind")
        params["kind"] = kind
    if audience in ("internal", "user_facing"):
        # Only the newer, classified rows have audience; treat NULL as internal so
        # the user-facing feed is conservative (never leaks unclassified chatter).
        if audience == "user_facing":
            clauses.append("audience = 'user_facing'")
        else:
            clauses.append("(audience = 'internal' OR audience IS NULL)")
    where_clause = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                f"""
                SELECT id, created_at, kind, summary, body, tags, metadata
                FROM sara_activity_log
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )).mappings().all()
    return [_row_to_activity(dict(r)) for r in rows]


@router.get("/focus", response_model=FocusOut)
async def get_focus(
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> FocusOut:
    """Current focus. Auth: daemon token OR session user."""
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")

    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                SELECT topic, why, set_at, updated_at
                FROM sara_focus
                WHERE id = 'singleton'
                """
            )
        )).mappings().first()
    if not row:
        return FocusOut(topic=None, why=None, set_at=None, updated_at=None)
    return FocusOut(
        topic=row["topic"],
        why=row["why"],
        set_at=row["set_at"],
        updated_at=row["updated_at"],
    )


class ACSSnapshotOut(BaseModel):
    daemon_status: DaemonStatusOut
    focus: FocusOut
    recent_activity: list[ActivityOut]


@router.get("/snapshot", response_model=ACSSnapshotOut)
async def acs_snapshot(current_user: User = Depends(get_current_user)) -> ACSSnapshotOut:
    """Aggregate daemon-status + focus + recent activity in one round-trip.

    The iOS status card polls this every 30s. It used to hit the
    never-implemented `/api/acs/snapshot` (only `/api/acs/v2/*` exists),
    404 silently, and render blank forever.
    """
    status_out = await daemon_status(current_user=current_user)
    focus_out = await get_focus(x_daemon_token=None, current_user=current_user)
    activity_out = await list_activity(
        limit=10, kind=None, x_daemon_token=None, current_user=current_user
    )
    return ACSSnapshotOut(
        daemon_status=status_out,
        focus=focus_out,
        recent_activity=activity_out,
    )


@router.post("/focus", response_model=FocusOut, dependencies=[Depends(verify_daemon_token)])
async def set_focus(payload: FocusIn) -> FocusOut:
    """Daemon-only: declare what she's working on. Upsert singleton row."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                INSERT INTO sara_focus (id, topic, why, set_at, updated_at)
                VALUES ('singleton', :topic, :why, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    topic = EXCLUDED.topic,
                    why = EXCLUDED.why,
                    set_at = NOW(),
                    updated_at = NOW()
                RETURNING topic, why, set_at, updated_at
                """
            ),
            {"topic": payload.topic, "why": payload.why},
        )).mappings().first()
        await db.commit()
    return FocusOut(
        topic=row["topic"], why=row["why"],
        set_at=row["set_at"], updated_at=row["updated_at"],
    )


@router.delete("/focus", response_model=FocusOut, dependencies=[Depends(verify_daemon_token)])
async def clear_focus() -> FocusOut:
    """Daemon-only: she's between things, no current focus."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO sara_focus (id, topic, why, set_at, updated_at)
                VALUES ('singleton', NULL, NULL, NULL, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    topic = NULL, why = NULL, set_at = NULL, updated_at = NOW()
                """
            )
        )
        await db.commit()
    return FocusOut(topic=None, why=None, set_at=None, updated_at=datetime.now(timezone.utc))


# ── Phase 3: honest notify_david ─────────────────────────────────────────────

class NotifyIn(BaseModel):
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=2000)
    priority: str = Field("normal", pattern="^(low|normal|important|high|urgent|critical)$")
    note_id: Optional[str] = Field(None, max_length=64,
                                   description="If set, included in push payload so iOS deep-links to the note.")
    why: Optional[str] = Field(None, max_length=500,
                               description="Sara's reason for sending — recorded on her activity log")
    deadline_within_24h: bool = Field(
        False,
        description="ACS4: the slow mind's work is not urgent by nature. Only set true "
                    "when this cites a deadline inside 24h — otherwise it's a silent inbox item.")


class NotifyOut(BaseModel):
    delivered: bool
    reason: Optional[str] = None
    notification_id: Optional[int] = None


@router.post("/notify", response_model=NotifyOut, dependencies=[Depends(verify_daemon_token)])
async def notify_david(payload: NotifyIn) -> NotifyOut:
    """Sara → David. One push, no gates, no consolidation, no cooldown.

    She is responsible for not spamming. The point of this endpoint is honest
    delivery: whatever she says here lands as a real notification, and she
    sees the actual outcome so she can self-regulate.

    Hard-banned phrases (legal/category bans) still apply — that's not gating
    her, that's protecting David from regulated content categories.
    """
    import difflib
    import uuid as _uuid
    from sqlalchemy import text as _text
    from app.services.unified_notification import send_notification

    user_id = getattr(settings, "acs_owner_user_id", "") or ""
    if not user_id:
        raise HTTPException(status_code=503, detail="acs_owner_user_id not configured")

    extra_data: dict[str, Any] = {}
    if payload.note_id:
        extra_data["note_id"] = payload.note_id

    async_session = get_async_session_factory()
    async with async_session() as db:
        # Fact-anchored notifications are one-shot: a given note gets announced
        # once, ever. Her activity tail scrolls past old notify entries, so
        # "she'll see she already pinged David" stops being true after a day —
        # this is the durable memory her context window doesn't have. Novel
        # content (no note_id) still flows freely with a unique topic.
        if payload.note_id:
            topic = f"sara_note:{payload.note_id}"
            cooldown = 24.0 * 14
        else:
            topic = f"sara_notify:{_uuid.uuid4().hex[:12]}"
            cooldown = 0.0

            # Repeat-guard for un-anchored notifies: if she sent a near-identical
            # title in the past 7 days, suppress and TELL HER (the reason lands in
            # her activity log, so the honest-feedback loop still works).
            rows = (await db.execute(_text("""
                SELECT title FROM notification_log
                WHERE user_id = :uid AND source = 'acs_daemon' AND sent = true
                  AND sent_at > NOW() - INTERVAL '7 days'
                ORDER BY sent_at DESC LIMIT 50
            """), {"uid": user_id})).fetchall()
            norm = payload.title.strip().lower()
            for (old_title,) in rows:
                if difflib.SequenceMatcher(None, norm, (old_title or "").strip().lower()).ratio() >= 0.82:
                    return NotifyOut(
                        delivered=False,
                        reason=f"already_told_david_recently (matches: {old_title[:80]!r}) — don't re-send; move on",
                    )

        # ACS4 (Brain Alignment — one mouth): the daemon does NOT push directly.
        # It routes through the same attention queue, learned buzz decision,
        # category cooldowns, and H2 habituation as every other generator. Its
        # work is by nature not urgent, so priority is clamped to normal (silent
        # inbox) unless it explicitly cites a deadline within 24h.
        effective_priority = payload.priority if payload.deadline_within_24h else "normal"
        result = await send_notification(
            user_id=user_id,
            title=payload.title,
            message=payload.body,
            priority=effective_priority,
            topic=topic,
            category="general",
            source="acs_daemon",
            cooldown_hours=cooldown,
            db=db,
            _bypass_ban=False,          # legal/regulated bans still apply
            extra_push_data=extra_data or None,
            payload={
                "prediction_grade": "novel",
                "stimulus_key": f"acs_daemon:{topic}",
                "generator": "acs_daemon",
            },
        )
        await db.commit()

    return NotifyOut(
        delivered=bool(result.get("sent")),
        reason=result.get("reason"),
        notification_id=result.get("notification_id"),
    )


# ── Phase 4: inbox / hybrid trigger model ────────────────────────────────────

class InboxIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    context: Optional[str] = Field(None, max_length=8000)
    urgency: str = Field("normal", pattern="^(low|normal|high)$")
    created_by: str = Field("david_api", max_length=64)


class InboxOut(BaseModel):
    id: str
    created_at: datetime
    created_by: str
    urgency: str
    prompt: str
    context: Optional[str]
    status: str
    picked_up_at: Optional[datetime]
    completed_at: Optional[datetime]
    completion_summary: Optional[str]


class InboxComplete(BaseModel):
    summary: str = Field(..., min_length=1, max_length=4000)


class InboxDismiss(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


def _row_to_inbox(row: dict) -> InboxOut:
    return InboxOut(
        id=str(row["id"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
        urgency=row["urgency"],
        prompt=row["prompt"],
        context=row["context"],
        status=row["status"],
        picked_up_at=row["picked_up_at"],
        completed_at=row["completed_at"],
        completion_summary=row["completion_summary"],
    )


@router.post("/inbox", response_model=InboxOut)
async def queue_inbox(
    payload: InboxIn,
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> InboxOut:
    """David queues work for Sara. Either auth path is allowed so that
    chat handlers, the daemon (relaying an event), or a curl session can
    all create items."""
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")

    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                INSERT INTO sara_inbox (created_by, urgency, prompt, context)
                VALUES (:created_by, :urgency, :prompt, :context)
                RETURNING id, created_at, created_by, urgency, prompt, context,
                          status, picked_up_at, completed_at, completion_summary
                """
            ),
            {
                "created_by": payload.created_by,
                "urgency": payload.urgency,
                "prompt": payload.prompt,
                "context": payload.context,
            },
        )).mappings().first()
        await db.commit()
    return _row_to_inbox(dict(row))


@router.get("/inbox", response_model=list[InboxOut])
async def list_inbox(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[InboxOut]:
    """List inbox items. Default returns active (queued + in_progress).
    Use ?status=done|dismissed|all to widen."""
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")

    where = "status IN ('queued', 'in_progress')"
    params: dict[str, Any] = {"limit": limit}
    if status_filter and status_filter != "all":
        if status_filter not in {"queued", "in_progress", "done", "dismissed"}:
            raise HTTPException(status_code=422, detail=f"unknown status '{status_filter}'")
        where = "status = :status"
        params["status"] = status_filter
    elif status_filter == "all":
        where = "TRUE"

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                f"""
                SELECT id, created_at, created_by, urgency, prompt, context,
                       status, picked_up_at, completed_at, completion_summary
                FROM sara_inbox
                WHERE {where}
                ORDER BY
                  CASE urgency WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                  created_at ASC
                LIMIT :limit
                """
            ),
            params,
        )).mappings().all()
    return [_row_to_inbox(dict(r)) for r in rows]


@router.post("/inbox/{item_id}/pickup", response_model=InboxOut,
             dependencies=[Depends(verify_daemon_token)])
async def pickup_inbox(item_id: str) -> InboxOut:
    """Daemon: I'm starting on this one."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                UPDATE sara_inbox
                SET status = 'in_progress', picked_up_at = NOW(), updated_at = NOW()
                WHERE id = :id AND status = 'queued'
                RETURNING id, created_at, created_by, urgency, prompt, context,
                          status, picked_up_at, completed_at, completion_summary
                """
            ),
            {"id": item_id},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="not found or not in 'queued' state")
    return _row_to_inbox(dict(row))


@router.post("/inbox/{item_id}/complete", response_model=InboxOut,
             dependencies=[Depends(verify_daemon_token)])
async def complete_inbox(item_id: str, payload: InboxComplete) -> InboxOut:
    """Daemon: this one's done. Records her own summary of what came of it."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                UPDATE sara_inbox
                SET status = 'done',
                    completed_at = NOW(),
                    completion_summary = :summary,
                    updated_at = NOW()
                WHERE id = :id AND status IN ('queued', 'in_progress')
                RETURNING id, created_at, created_by, urgency, prompt, context,
                          status, picked_up_at, completed_at, completion_summary
                """
            ),
            {"id": item_id, "summary": payload.summary},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="not found or already terminal")
    return _row_to_inbox(dict(row))


@router.post("/inbox/{item_id}/dismiss", response_model=InboxOut,
             dependencies=[Depends(verify_daemon_token)])
async def dismiss_inbox(item_id: str, payload: InboxDismiss) -> InboxOut:
    """Daemon: I'm not going to do this one. Reason recorded as completion_summary."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                UPDATE sara_inbox
                SET status = 'dismissed',
                    completed_at = NOW(),
                    completion_summary = :reason,
                    updated_at = NOW()
                WHERE id = :id AND status IN ('queued', 'in_progress')
                RETURNING id, created_at, created_by, urgency, prompt, context,
                          status, picked_up_at, completed_at, completion_summary
                """
            ),
            {"id": item_id, "reason": payload.reason},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="not found or already terminal")
    return _row_to_inbox(dict(row))


# ── Phase 5: recall before research ──────────────────────────────────────────

class RelatedActivityOut(ActivityOut):
    similarity: float


@router.get("/activity/related", response_model=list[RelatedActivityOut])
async def related_activity(
    topic: str = Query(..., min_length=2, max_length=2000),
    limit: int = Query(5, ge=1, le=20),
    exclude_recent_minutes: int = Query(15, ge=0, le=1440,
                                        description="Skip entries newer than this; avoids surfacing pure repetition."),
    min_similarity: float = Query(0.55, ge=0.0, le=1.0),
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[RelatedActivityOut]:
    """Find Sara's prior activity entries semantically related to a topic.

    The daemon calls this before diving into a topic so it has ambient
    awareness of what she's already explored — the "no Wednesday seeds
    research" guarantee. Returns entries with cosine similarity ≥
    `min_similarity`, sorted by similarity desc.
    """
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")

    try:
        from app.services.embeddings import get_embedding
        vec = await get_embedding(topic)
    except Exception as e:
        logger.warning(f"related_activity embedding failed: {e}")
        return []

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                """
                SELECT id, created_at, kind, summary, body, tags, metadata,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM sara_activity_log
                WHERE embedding IS NOT NULL
                  AND created_at < NOW() - make_interval(mins => :excl_minutes)
                  AND 1 - (embedding <=> CAST(:vec AS vector)) >= :min_sim
                ORDER BY embedding <=> CAST(:vec AS vector) ASC
                LIMIT :limit
                """
            ),
            {
                "vec": str(vec),
                "excl_minutes": exclude_recent_minutes,
                "min_sim": min_similarity,
                "limit": limit,
            },
        )).mappings().all()

    out: list[RelatedActivityOut] = []
    for r in rows:
        base = _row_to_activity(dict(r))
        out.append(RelatedActivityOut(
            **base.model_dump(),
            similarity=float(r["similarity"]),
        ))
    return out


# ── SSE live stream ──────────────────────────────────────────────────────────

@router.get("/stream")
async def stream_activity(
    request: Request,
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
    _auth_db: Session = Depends(get_db),
) -> StreamingResponse:
    """Server-sent events stream of new activity log entries.

    Polls the DB every 2s for rows newer than the last emission and pushes
    them down. Cheap polling (one indexed query per tick); good enough for
    a single-user system. Drops the connection cleanly if the client goes away.
    """
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")

    # Release the auth session's connection before streaming — otherwise it sits
    # idle-in-transaction for the SSE lifetime and Postgres kills it (5-min timeout).
    try:
        _auth_db.close()
    except Exception:
        pass

    import json as _json

    async def event_generator():
        async_session = get_async_session_factory()
        last_seen_at: Optional[datetime] = datetime.now(timezone.utc)

        # Initial event so the client knows the stream is open.
        yield f"event: hello\ndata: {{\"server_time\": \"{datetime.now(timezone.utc).isoformat()}\"}}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                async with async_session() as db:
                    rows = (await db.execute(
                        text(
                            """
                            SELECT id, created_at, kind, summary, body, tags, metadata
                            FROM sara_activity_log
                            WHERE created_at > :since
                            ORDER BY created_at ASC
                            LIMIT 50
                            """
                        ),
                        {"since": last_seen_at},
                    )).mappings().all()
                if rows:
                    for r in rows:
                        payload = _row_to_activity(dict(r)).model_dump(mode="json")
                        yield f"event: activity\ndata: {_json.dumps(payload)}\n\n"
                    last_seen_at = rows[-1]["created_at"]
            except Exception as e:
                logger.warning(f"SSE stream tick failed: {e}")
                # keep the connection alive — next tick may recover
            # heartbeat so proxies don't kill idle SSE
            yield f": ping {datetime.now(timezone.utc).isoformat()}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
