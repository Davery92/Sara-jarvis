"""ACS (Autonomous Cognition System) API routes."""

import asyncio
import json
import logging
import os
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone

from app.core.timezone import now as local_now, to_local

from app.core.deps import get_current_user, get_db
from app.core.auth import verify_token
from app.models.user import User
from app.services.acs import state_machine

logger = logging.getLogger(__name__)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
from app.services.acs.session_manager import start_session, pause_session, kill_session

router = APIRouter(prefix="/api/acs", tags=["ACS"])


# ── Status & Control ──

@router.get("/status")
async def get_acs_status(current_user=Depends(get_current_user)):
    """Get current ACS state, active session, and config. v2 adds interest graph stats."""
    status = await state_machine.get_full_status(current_user.id)

    # v2 additions
    from app.core.config import settings
    if settings.acs_v2_enabled:
        status["v2_enabled"] = True
        try:
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                r = await db.execute(text(
                    "SELECT COUNT(*) FROM acs_interest_node WHERE user_id = :uid AND status = 'active'"
                ), {"uid": current_user.id})
                total_active = r.scalar() or 0
                r2 = await db.execute(text(
                    "SELECT COUNT(*) FROM acs_interest_edge WHERE user_id = :uid"
                ), {"uid": current_user.id})
                total_edges = r2.scalar() or 0
            status["interest_graph_stats"] = {
                "total_active": total_active,
                "total_edges": total_edges,
            }
        except Exception:
            status["interest_graph_stats"] = {}
        try:
            from app.services.acs.self_model import SelfModel
            sm = SelfModel()
            model_data = await sm.get_current(current_user.id)
            status["self_model_version"] = model_data.get("version", 0)
        except Exception:
            status["self_model_version"] = 0
        # Current mode (if session active)
        try:
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                mode = await r.get(f"sara:acs:session_mode:{current_user.id}")
                status["current_mode"] = mode
            finally:
                await r.close()
        except Exception:
            pass
    else:
        status["v2_enabled"] = False

    return status


@router.get("/live")
async def acs_live_stream(
    request: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """SSE stream of real-time ACS session activity.
    Accepts auth via cookie, Authorization header, or ?token= query param.
    """
    # Resolve user and close DB session before entering the long-lived SSE
    # stream.  Holding db open for the stream's lifetime causes
    # idle-in-transaction timeouts.
    user = None
    try:
        from app.core.deps import get_current_user as _get_user
        user = await _get_user(request, request.cookies.get("access_token"), db)
    except Exception:
        pass

    if not user and token:
        payload = verify_token(token)
        if payload and payload.get("sub"):
            user = db.query(User).filter(User.id == payload["sub"]).first()

    if not user:
        raise HTTPException(401, "Could not validate credentials")

    user_id = str(user.id)

    # Release the DB connection now — the SSE generator only needs Redis.
    db.close()

    async def event_generator():
        r = None
        pubsub = None
        try:
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            channel = f"sara:acs:live:{user_id}"
            await pubsub.subscribe(channel)
            logger.info(f"ACS live SSE connected: user={user_id}")

            # Send initial status
            status = await state_machine.get_full_status(user_id)
            yield f"data: {json.dumps({'type': 'status', **status})}\n\n"

            keepalive = 0
            while True:
                # Poll for messages (compatible with redis-py 4.x)
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    keepalive = 0
                else:
                    await asyncio.sleep(0.4)
                    keepalive += 1
                    if keepalive >= 30:  # ~15s
                        yield f": keepalive\n\n"
                        keepalive = 0

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"ACS live SSE error: {e}")
        finally:
            try:
                if pubsub:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
            except Exception:
                pass
            try:
                if r:
                    await r.close()
            except Exception:
                pass
            logger.info(f"ACS live SSE disconnected: user={user_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/snapshot")
async def acs_snapshot(current_user=Depends(get_current_user)):
    """Compact snapshot of Sara's latest ACS activity for quick glance.

    Returns: state, current mode, latest note, latest journal entry,
    last session summary, and live session info if active.
    """
    user_id = str(current_user.id)
    status = await state_machine.get_full_status(user_id)

    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Latest Sara note (excluding journals)
        note_row = await db.execute(text("""
            SELECT n.title, n.content, n.created_at, f.name as folder_name
            FROM note n
            LEFT JOIN folder f ON n.folder_id = f.id
            WHERE n.user_id = :uid
              AND n.title NOT LIKE 'Sara''s Journal%%'
            ORDER BY n.created_at DESC LIMIT 1
        """), {"uid": user_id})
        note = note_row.fetchone()

        # Latest journal entry
        journal_row = await db.execute(text("""
            SELECT content, updated_at FROM note
            WHERE user_id = :uid AND title LIKE 'Sara''s Journal%%'
            ORDER BY updated_at DESC LIMIT 1
        """), {"uid": user_id})
        journal = journal_row.fetchone()

        # Last completed session
        session_row = await db.execute(text("""
            SELECT cognitive_mode, turns_completed, notes_created, started_at, ended_at, end_reason
            FROM acs_session
            WHERE user_id = :uid AND state = 'ended'
            ORDER BY started_at DESC LIMIT 1
        """), {"uid": user_id})
        last_session = session_row.fetchone()

        # Active session (if running)
        active_row = await db.execute(text("""
            SELECT id, cognitive_mode, turns_completed, notes_created, started_at
            FROM acs_session
            WHERE user_id = :uid AND state = 'autonomous'
            ORDER BY started_at DESC LIMIT 1
        """), {"uid": user_id})
        active = active_row.fetchone()

    result = {
        "state": status.get("state", "idle"),
        "emotional_state": status.get("emotional_state"),
    }

    if note:
        result["latest_note"] = {
            "title": note[0],
            "preview": (note[1] or "")[:200].strip(),
            "created_at": note[2].isoformat() if note[2] else None,
            "folder": note[3],
        }

    if journal:
        # Get last entry from journal (last paragraph)
        content = journal[0] or ""
        entries = [e.strip() for e in content.split("\n\n") if e.strip()]
        last_entry = entries[-1] if entries else ""
        # Strip markdown timestamp headers
        lines = last_entry.split("\n")
        clean_lines = [l for l in lines if not l.startswith("###")]
        result["latest_journal"] = {
            "snippet": "\n".join(clean_lines)[:300].strip(),
            "updated_at": journal[1].isoformat() if journal[1] else None,
        }

    if last_session:
        result["last_session"] = {
            "mode": last_session[0],
            "turns": last_session[1],
            "notes_created": last_session[2],
            "started_at": last_session[3].isoformat() if last_session[3] else None,
            "ended_at": last_session[4].isoformat() if last_session[4] else None,
            "end_reason": last_session[5],
        }

    if active:
        started_local = to_local(active[4]) if active[4] else local_now()
        elapsed = (local_now() - started_local).total_seconds() / 60
        result["live_session"] = {
            "id": active[0],
            "mode": active[1],
            "turns": active[2],
            "notes_created": active[3],
            "elapsed_minutes": round(elapsed, 1),
        }

    # Daily plan from Redis
    try:
        import redis.asyncio as aioredis
        import os
        r = await aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        try:
            plan = await r.get(f"sara:acs:daily_plan:{user_id}")
            if plan:
                result["daily_plan"] = plan
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
    except Exception:
        pass

    # Active directives
    try:
        async with async_session() as db:
            dir_rows = await db.execute(text("""
                SELECT id, directive_type, content, priority, status, source, response, created_at
                FROM acs_directive
                WHERE user_id = :uid AND status IN ('pending', 'acknowledged')
                ORDER BY created_at DESC LIMIT 10
            """), {"uid": user_id})
            directives = []
            for r in dir_rows.fetchall():
                directives.append({
                    "id": r[0], "directive_type": r[1], "content": r[2],
                    "priority": r[3], "status": r[4], "source": r[5],
                    "response": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                })
            if directives:
                result["directives"] = directives
    except Exception:
        pass

    return result


@router.post("/start")
async def start_acs(
    model_id: Optional[str] = Body(None, embed=True),
    current_user=Depends(get_current_user),
):
    """Manually start an autonomous session."""
    session_id = await start_session(current_user.id, model_id=model_id)
    if not session_id:
        raise HTTPException(400, "Cannot start ACS session in current state")
    return {"session_id": session_id, "state": "autonomous"}


@router.post("/pause")
async def pause_acs(current_user=Depends(get_current_user)):
    """Manually pause the running session."""
    ok = await pause_session(current_user.id)
    if not ok:
        raise HTTPException(400, "No active session to pause")
    return {"state": "pausing"}


@router.post("/resume")
async def resume_acs(current_user=Depends(get_current_user)):
    """Manually resume from cooldown."""
    current = await state_machine.get_state(current_user.id)
    if current not in (state_machine.ACSState.COOLDOWN, state_machine.ACSState.CONVERSATIONAL, None):
        raise HTTPException(400, f"Cannot resume from state: {current}")

    session_id = await start_session(current_user.id)
    if not session_id:
        raise HTTPException(500, "Failed to start session")
    return {"session_id": session_id, "state": "autonomous"}


@router.post("/stop")
async def stop_acs(current_user=Depends(get_current_user)):
    """Force-stop a running or stuck ACS session. Ends DB record, clears Redis state."""
    result = await kill_session(current_user.id)
    if not result["killed"]:
        raise HTTPException(400, "Failed to stop session")
    return {"state": "idle", **result}


# ── Sessions ──

@router.get("/sessions")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List ACS sessions (paginated)."""
    try:
        result = db.execute(text("""
            SELECT s.id, s.model_id, s.state, s.started_at, s.ended_at, s.end_reason,
                   s.turns_completed, s.notes_created, s.curiosities_explored,
                   s.cognitive_mode, s.engagement_score,
                   sl.outcome_type, sl.artifact_summary, sl.outbound_messages, sl.suppressed_messages
            FROM acs_session s
            LEFT JOIN acs_session_log sl ON sl.session_id = s.id
            WHERE s.user_id = :uid
            ORDER BY s.started_at DESC
            LIMIT :lim OFFSET :off
        """), {"uid": current_user.id, "lim": limit, "off": offset})
        enhanced_fields = True
    except Exception:
        db.rollback()
        result = db.execute(text("""
            SELECT id, model_id, state, started_at, ended_at, end_reason,
                   turns_completed, notes_created, curiosities_explored,
                   cognitive_mode, engagement_score
            FROM acs_session
            WHERE user_id = :uid
            ORDER BY started_at DESC
            LIMIT :lim OFFSET :off
        """), {"uid": current_user.id, "lim": limit, "off": offset})
        enhanced_fields = False
    rows = result.fetchall()

    count_result = db.execute(text(
        "SELECT COUNT(*) FROM acs_session WHERE user_id = :uid"
    ), {"uid": current_user.id})
    total = count_result.scalar()

    sessions = []
    for r in rows:
        started = r[3]
        ended = r[4]
        duration_min = None
        if started and ended:
            duration_min = round((ended - started).total_seconds() / 60, 1)

        sessions.append({
            "id": r[0],
            "model_id": r[1],
            "state": r[2],
            "started_at": started.isoformat() if started else None,
            "ended_at": ended.isoformat() if ended else None,
            "end_reason": r[5],
            "turns_completed": r[6],
            "notes_created": r[7],
            "curiosities_explored": r[8],
            "duration_minutes": duration_min,
            "duration_seconds": round(duration_min * 60, 1) if duration_min is not None else None,
            "cognitive_mode": r[9],
            "engagement_score": r[10],
            "outcome_type": r[11] if enhanced_fields else None,
            "artifact_summary": r[12] if enhanced_fields else None,
            "outbound_messages": (r[13] or 0) if enhanced_fields else 0,
            "suppressed_messages": (r[14] or 0) if enhanced_fields else 0,
        })

    return {"sessions": sessions, "total": total}


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed session info."""
    result = db.execute(text("""
        SELECT id, user_id, vm_session_id, model_id, state, started_at, paused_at,
               ended_at, end_reason, turns_completed, notes_created,
               curiosities_explored, token_usage, context_summary, error_log,
               cognitive_mode, engagement_score
        FROM acs_session
        WHERE id = :sid AND user_id = :uid
    """), {"sid": session_id, "uid": current_user.id})
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    detail = {
        "id": row[0], "user_id": row[1], "vm_session_id": row[2],
        "model_id": row[3], "state": row[4],
        "started_at": row[5].isoformat() if row[5] else None,
        "paused_at": row[6].isoformat() if row[6] else None,
        "ended_at": row[7].isoformat() if row[7] else None,
        "end_reason": row[8], "turns_completed": row[9],
        "notes_created": row[10], "curiosities_explored": row[11],
        "token_usage": row[12], "context_summary": row[13],
        "error_log": row[14],
        "cognitive_mode": row[15], "engagement_score": row[16],
    }

    # v2: add session log details
    try:
        log_result = db.execute(text("""
            SELECT nodes_created, nodes_updated, edges_created, notes_written,
                   self_model_updated, avg_engagement, early_termination,
                   primary_topic, primary_objective, expected_artifact,
                   outcome_type, artifact_summary, outbound_messages, suppressed_messages
            FROM acs_session_log
            WHERE session_id = :sid
            LIMIT 1
        """), {"sid": session_id})
        log_row = log_result.fetchone()
        if log_row:
            detail["interest_nodes_created"] = log_row[0]
            detail["interest_nodes_updated"] = log_row[1]
            detail["interest_edges_created"] = log_row[2]
            detail["notes_written"] = log_row[3]
            detail["self_model_updated"] = log_row[4]
            detail["avg_engagement"] = log_row[5]
            detail["early_termination"] = log_row[6]
            detail["primary_topic"] = log_row[7]
            detail["primary_objective"] = log_row[8]
            detail["expected_artifact"] = log_row[9]
            detail["outcome_type"] = log_row[10]
            detail["artifact_summary"] = log_row[11]
            detail["outbound_messages"] = log_row[12] or 0
            detail["suppressed_messages"] = log_row[13] or 0
    except Exception:
        pass

    return detail


@router.get("/sessions/{session_id}/notes")
async def get_session_notes(
    session_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get notes created during a session."""
    # Get Sara's Notes folder
    folder_id = await state_machine.get_notes_folder_id(current_user.id)
    if not folder_id:
        return {"notes": []}

    # Notes don't directly track session_id, so we filter by folder + time range
    result = db.execute(text("""
        SELECT s.started_at, s.ended_at FROM acs_session AS s
        WHERE s.id = :sid AND s.user_id = :uid
    """), {"sid": session_id, "uid": current_user.id})
    session_row = result.fetchone()
    if not session_row:
        raise HTTPException(404, "Session not found")

    started = session_row[0]
    ended = session_row[1] or datetime.now(timezone.utc).replace(tzinfo=None)

    notes_result = db.execute(text("""
        SELECT id, title, content, tags, created_at
        FROM note
        WHERE user_id = :uid AND folder_id = :fid
          AND created_at >= :started AND created_at <= :ended
        ORDER BY created_at
    """), {"uid": current_user.id, "fid": folder_id, "started": started, "ended": ended})
    rows = notes_result.fetchall()

    return {"notes": [{
        "id": r[0], "title": r[1], "content": r[2],
        "tags": r[3] if r[3] else [],
        "created_at": r[4].isoformat() if r[4] else None,
    } for r in rows]}


@router.get("/sessions/{session_id}/transcript")
async def get_session_transcript(
    session_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the full raw transcript for an ACS session.

    Transcripts are stored in Redis with a 48h TTL by
    `app.services.acs.audit_logger.persist_transcript`. Sessions older than
    that — or sessions that ended before transcript persistence shipped —
    will return `available: False` with an explanatory reason.
    """
    # Verify the session belongs to this user
    row = db.execute(text("""
        SELECT id FROM acs_session
        WHERE id = :sid AND user_id = :uid
    """), {"sid": session_id, "uid": current_user.id}).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    raw = None
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            raw = await r.get(f"sara:acs:transcript:{session_id}")
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
    except Exception as e:
        logger.warning(f"Failed to read transcript for {session_id[:8]} from Redis: {e}")
        return {
            "session_id": session_id,
            "available": False,
            "reason": "transcript_store_unavailable",
            "entries": [],
        }

    if not raw:
        try:
            db_row = db.execute(text("""
                SELECT transcript_json
                FROM acs_session_transcript
                WHERE session_id = :sid AND user_id = :uid
                LIMIT 1
            """), {"sid": session_id, "uid": current_user.id}).fetchone()
        except Exception:
            db_row = None
        if not db_row or not db_row[0]:
            return {
                "session_id": session_id,
                "available": False,
                "reason": "Transcript not found in Redis or durable store",
                "entries": [],
            }
        data = db_row[0]
        return {
            "session_id": data.get("session_id", session_id),
            "mode": data.get("mode"),
            "started_at": data.get("started_at"),
            "entries": data.get("entries", []),
            "available": True,
        }

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.error(f"Corrupt transcript JSON for session {session_id[:8]}: {e}")
        return {
            "session_id": session_id,
            "available": False,
            "reason": "transcript_corrupt",
            "entries": [],
        }

    return {
        "session_id": data.get("session_id", session_id),
        "mode": data.get("mode"),
        "started_at": data.get("started_at"),
        "entries": data.get("entries", []),
        "available": True,
    }


# ── Curiosity Queue ──

@router.get("/curiosity")
async def list_curiosities(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List interest nodes (replaces legacy curiosity queue)."""
    query = "SELECT id, label AS topic, source, fascination AS priority, status, depth, created_at FROM acs_interest_node WHERE user_id = :uid"
    params = {"uid": current_user.id}
    if status:
        query += " AND status = :status"
        params["status"] = status
    query += " ORDER BY fascination DESC LIMIT :lim"
    params["lim"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()
    keys = result.keys()

    items = [dict(zip(keys, r)) for r in rows]
    # Serialize datetimes
    for item in items:
        for k in ("created_at", "updated_at"):
            if item.get(k) and hasattr(item[k], "isoformat"):
                item[k] = item[k].isoformat()

    return {"items": items, "count": len(items)}


@router.post("/curiosity")
async def add_curiosity(
    topic: str = Body(...),
    priority: float = Body(0.5),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a topic to the interest graph."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    node = await graph.add_node(
        user_id=current_user.id,
        label=topic,
        source="conversation",
        fascination=priority,
    )
    return {"id": node["id"] if node else None, "topic": topic, "status": "active"}


@router.delete("/curiosity/{item_id}")
async def delete_curiosity(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive an interest node."""
    result = db.execute(text(
        "UPDATE acs_interest_node SET status = 'archived', updated_at = NOW() WHERE id = :id AND user_id = :uid"
    ), {"id": item_id, "uid": current_user.id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Interest node not found")
    return {"archived": True}


# ── Show David Buffer ──

@router.get("/show-david")
async def list_show_david(
    unshown_only: bool = Query(True),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List show-David buffer items."""
    params = {"uid": current_user.id, "lim": limit}
    try:
        query = "SELECT * FROM acs_show_david_buffer WHERE user_id = :uid"
        if unshown_only:
            query += " AND delivery_status = 'queued'"
        else:
            query += " AND delivery_status IN ('queued', 'delivered')"
        query += " ORDER BY priority DESC, created_at DESC LIMIT :lim"
        result = db.execute(text(query), params)
    except Exception:
        db.rollback()
        query = "SELECT * FROM acs_show_david_buffer WHERE user_id = :uid"
        if unshown_only:
            query += " AND shown = FALSE"
        query += " ORDER BY priority DESC, created_at DESC LIMIT :lim"
        result = db.execute(text(query), params)
    rows = result.fetchall()
    keys = result.keys()

    items = [dict(zip(keys, r)) for r in rows]
    for item in items:
        for k in ("created_at", "shown_at"):
            if item.get(k) and hasattr(item[k], "isoformat"):
                item[k] = item[k].isoformat()

    return {"items": items, "count": len(items)}


@router.post("/show-david/{item_id}/shown")
async def mark_shown(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a show-David item as shown."""
    try:
        result = db.execute(text("""
            UPDATE acs_show_david_buffer
            SET shown = TRUE, shown_at = NOW(), delivery_status = 'delivered'
            WHERE id = :id AND user_id = :uid
        """), {"id": item_id, "uid": current_user.id})
    except Exception:
        db.rollback()
        result = db.execute(text("""
            UPDATE acs_show_david_buffer
            SET shown = TRUE, shown_at = NOW()
            WHERE id = :id AND user_id = :uid
        """), {"id": item_id, "uid": current_user.id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Item not found")
    return {"shown": True}


# ── Settings ──

@router.put("/settings")
async def update_acs_settings(
    model_id: Optional[str] = Body(None),
    cooldown_minutes: Optional[int] = Body(None),
    max_duration_minutes: Optional[int] = Body(None),
    current_user=Depends(get_current_user),
):
    """Update ACS configuration."""
    if model_id is not None:
        await state_machine.set_model_id(current_user.id, model_id)
    if cooldown_minutes is not None:
        await state_machine.set_cooldown_minutes(current_user.id, max(1, min(180, cooldown_minutes)))
    if max_duration_minutes is not None:
        await state_machine.set_max_duration_minutes(current_user.id, max(5, min(120, max_duration_minutes)))

    return await state_machine.get_full_status(current_user.id)


# ── Interest Graph (v2) ──

@router.get("/interest-graph")
async def get_interest_graph(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
):
    """Get interest graph nodes and edges (paginated)."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    return await graph.get_all_nodes(current_user.id, status=status, limit=limit, offset=offset)


@router.get("/interest-graph/nodes/{node_id}")
async def get_interest_node(
    node_id: str,
    current_user=Depends(get_current_user),
):
    """Get an interest node with its neighborhood."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    result = await graph.get_node_with_neighborhood(node_id)
    if not result:
        raise HTTPException(404, "Node not found")
    # Verify ownership
    if result["node"].get("user_id") != current_user.id:
        raise HTTPException(404, "Node not found")
    return result


@router.post("/interest-graph/nodes")
async def create_interest_node(
    label: str = Body(...),
    description: str = Body(""),
    fascination: float = Body(0.5),
    source: str = Body("manual"),
    current_user=Depends(get_current_user),
):
    """Manually create an interest node."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    result = await graph.add_node(
        user_id=current_user.id,
        label=label,
        description=description,
        source=source,
        fascination=fascination,
    )
    if not result:
        raise HTTPException(500, "Failed to create node")
    return result


@router.put("/interest-graph/nodes/{node_id}")
async def update_interest_node(
    node_id: str,
    fascination: Optional[float] = Body(None),
    depth: Optional[float] = Body(None),
    confidence: Optional[float] = Body(None),
    description: Optional[str] = Body(None),
    status: Optional[str] = Body(None),
    current_user=Depends(get_current_user),
):
    """Update an interest node's scores or metadata."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    # Verify ownership
    node = await graph.get_node_with_neighborhood(node_id)
    if not node or node["node"].get("user_id") != current_user.id:
        raise HTTPException(404, "Node not found")

    kwargs = {}
    if fascination is not None:
        kwargs["fascination"] = fascination
    if depth is not None:
        kwargs["depth"] = depth
    if confidence is not None:
        kwargs["confidence"] = confidence
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status

    ok = await graph.update_node(node_id, **kwargs)
    if not ok:
        raise HTTPException(400, "No updates applied")
    return {"updated": True}


@router.delete("/interest-graph/nodes/{node_id}")
async def archive_interest_node(
    node_id: str,
    current_user=Depends(get_current_user),
):
    """Archive an interest node (soft delete)."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    node = await graph.get_node_with_neighborhood(node_id)
    if not node or node["node"].get("user_id") != current_user.id:
        raise HTTPException(404, "Node not found")

    ok = await graph.archive_node(node_id)
    if not ok:
        raise HTTPException(400, "Failed to archive node")
    return {"archived": True}


@router.get("/interest-graph/frontier")
async def get_frontier_nodes(
    limit: int = Query(10, ge=1, le=50),
    current_user=Depends(get_current_user),
):
    """Get top exploration candidates (high fascination, low depth)."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    nodes = await graph.get_frontier_nodes(current_user.id, limit=limit)
    return {"nodes": nodes}


@router.get("/interest-graph/search")
async def search_interest_graph(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    current_user=Depends(get_current_user),
):
    """Semantic search over interest graph nodes."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    results = await graph.semantic_search(current_user.id, q, limit=limit)
    return {"results": results}


@router.get("/interest-graph/bridges")
async def get_bridge_opportunities(
    limit: int = Query(5, ge=1, le=20),
    current_user=Depends(get_current_user),
):
    """Find pairs of similar but unlinked interest nodes."""
    from app.services.acs.interest_graph import InterestGraph
    graph = InterestGraph()
    bridges = await graph.find_bridge_opportunities(current_user.id, limit=limit)
    return {"bridges": bridges}


# ── Self-Model (v2) ──

@router.get("/self-model")
async def get_self_model(current_user=Depends(get_current_user)):
    """Get the current self-model."""
    from app.services.acs.self_model import SelfModel
    sm = SelfModel()
    model = await sm.get_current(current_user.id)
    return {"model": model}


@router.get("/self-model/history")
async def get_self_model_history(
    limit: int = Query(10, ge=1, le=50),
    current_user=Depends(get_current_user),
):
    """Get self-model version history."""
    from app.services.acs.self_model import SelfModel
    sm = SelfModel()
    history = await sm.get_version_history(current_user.id, limit=limit)
    return {"history": history}


@router.get("/self-model/context")
async def get_self_model_context(current_user=Depends(get_current_user)):
    """Get the self-model formatted as context text."""
    from app.services.acs.self_model import SelfModel
    sm = SelfModel()
    context = await sm.get_for_context(current_user.id)
    return {"context": context}


@router.put("/self-model")
async def replace_self_model(
    payload: dict = Body(...),
    current_user=Depends(get_current_user),
):
    """
    Manually replace the self-model with user-provided content.

    Body: {"content": {...full self-model JSON...}}

    Creates a new version (does NOT mutate the existing one). Sara's next
    reflection cycle may merge over the top of this — manual edits are not
    permanent unless the underlying observations also change.
    """
    content = payload.get("content")
    if not isinstance(content, dict):
        raise HTTPException(400, "payload.content must be a JSON object")

    from app.services.acs.self_model import SelfModel
    sm = SelfModel()
    try:
        result = await sm.replace(current_user.id, content)
    except Exception as e:
        logger.error(f"Self-model replace failed for user {current_user.id}: {e}")
        raise HTTPException(500, f"Failed to replace self-model: {e}")
    return {"model": result}


# ── Directives (David → ACS communication) ──

@router.post("/directive")
async def create_directive(
    directive_type: str = Body(..., embed=False),
    content: str = Body(..., embed=False),
    priority: str = Body("normal", embed=False),
    source: str = Body("frontend", embed=False),
    current_user=Depends(get_current_user),
):
    """Create a directive for the ACS. Published to Redis for immediate pickup."""
    import uuid
    aliases = {
        "research": "focus",
        "explore": "focus",
        "monitor": "context",
        "create": "redirect",
        "reflect": "question",
        "custom": "context",
    }
    directive_type = aliases.get(directive_type, directive_type)
    if directive_type not in ("focus", "stop", "context", "redirect", "question"):
        raise HTTPException(400, f"Invalid directive_type: {directive_type}")
    if priority not in ("urgent", "normal", "low"):
        raise HTTPException(400, f"Invalid priority: {priority}")

    directive_id = str(uuid.uuid4())
    user_id = str(current_user.id)

    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(text("""
            INSERT INTO acs_directive (id, user_id, directive_type, content, priority, status, source)
            VALUES (:id, :uid, :dtype, :content, :priority, 'pending', :source)
        """), {
            "id": directive_id, "uid": user_id, "dtype": directive_type,
            "content": content, "priority": priority, "source": source,
        })
        await db.commit()

    # Publish to Redis for immediate pickup by running sessions
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.publish(
                f"sara:acs:directives:{user_id}",
                json.dumps({
                    "id": directive_id, "directive_type": directive_type,
                    "content": content, "priority": priority,
                }),
            )
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
    except Exception as e:
        logger.warning(f"Failed to publish directive to Redis: {e}")

    return {"id": directive_id, "status": "pending", "message": f"Directive created: [{directive_type}] {content[:80]}"}


@router.get("/directives")
async def list_directives(
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    include_expired: bool = Query(False),
    current_user=Depends(get_current_user),
):
    """List directives.

    By default, expired (soft-deleted) directives are hidden — the DELETE
    endpoint flips status to 'expired' rather than removing the row, so the
    UI must filter them out or "deleted" directives reappear on next refresh.

    Pass `include_expired=true` to fetch the full history, or `status=expired`
    to fetch only expired ones (explicit status filter overrides the default).
    """
    user_id = str(current_user.id)
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    async with async_session() as db:
        if status:
            # Explicit status filter — caller knows what they want, including
            # `status=expired` to inspect soft-deleted rows.
            result = await db.execute(text("""
                SELECT id, directive_type, content, priority, status, source, response,
                       created_at, acknowledged_at, expired_at
                FROM acs_directive
                WHERE user_id = :uid AND status = :status
                ORDER BY created_at DESC LIMIT :lim
            """), {"uid": user_id, "status": status, "lim": limit})
        elif include_expired:
            result = await db.execute(text("""
                SELECT id, directive_type, content, priority, status, source, response,
                       created_at, acknowledged_at, expired_at
                FROM acs_directive
                WHERE user_id = :uid
                ORDER BY created_at DESC LIMIT :lim
            """), {"uid": user_id, "lim": limit})
        else:
            result = await db.execute(text("""
                SELECT id, directive_type, content, priority, status, source, response,
                       created_at, acknowledged_at, expired_at
                FROM acs_directive
                WHERE user_id = :uid AND status != 'expired'
                ORDER BY created_at DESC LIMIT :lim
            """), {"uid": user_id, "lim": limit})

        directives = []
        for r in result.fetchall():
            directives.append({
                "id": r[0], "directive_type": r[1], "content": r[2],
                "priority": r[3], "status": r[4], "source": r[5],
                "response": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
                "acknowledged_at": r[8].isoformat() if r[8] else None,
                "expired_at": r[9].isoformat() if r[9] else None,
            })

    return {"directives": directives, "count": len(directives)}


@router.patch("/directive/{directive_id}")
async def update_directive(
    directive_id: str,
    status: Optional[str] = Body(None),
    response: Optional[str] = Body(None),
    current_user=Depends(get_current_user),
):
    """Update a directive's status or add a response."""
    user_id = str(current_user.id)
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    updates = []
    params = {"id": directive_id, "uid": user_id}

    if status:
        if status not in ("pending", "acknowledged", "acted_on", "expired"):
            raise HTTPException(400, f"Invalid status: {status}")
        updates.append("status = :status")
        params["status"] = status
        if status == "acknowledged":
            updates.append("acknowledged_at = NOW()")
        elif status == "expired":
            updates.append("expired_at = NOW()")
    if response is not None:
        updates.append("response = :response")
        params["response"] = response

    if not updates:
        raise HTTPException(400, "No updates provided")

    async with async_session() as db:
        result = await db.execute(text(f"""
            UPDATE acs_directive SET {', '.join(updates)}
            WHERE id = :id AND user_id = :uid
            RETURNING id, status
        """), params)
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Directive not found")
        await db.commit()

    return {"id": row[0], "status": row[1], "updated": True}


@router.delete("/directive/{directive_id}")
async def expire_directive(directive_id: str, current_user=Depends(get_current_user)):
    """Expire (soft-delete) a directive."""
    user_id = str(current_user.id)
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    async with async_session() as db:
        result = await db.execute(text("""
            UPDATE acs_directive SET status = 'expired', expired_at = NOW()
            WHERE id = :id AND user_id = :uid
            RETURNING id
        """), {"id": directive_id, "uid": user_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Directive not found")
        await db.commit()

    return {"id": directive_id, "status": "expired"}


# ── Analytics ──

@router.get("/analytics")
async def acs_analytics(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """ACS analytics for the last 7 days."""
    user_id = str(current_user.id)

    # Sessions by day
    daily = db.execute(text("""
        SELECT DATE(started_at) as day,
               count(*) as sessions,
               avg(turns_completed) as avg_turns,
               count(*) FILTER (WHERE end_reason = 'error') as errors,
               sum(notes_created) as notes
        FROM acs_session
        WHERE user_id = :uid AND started_at > NOW() - INTERVAL '7 days'
        GROUP BY DATE(started_at)
        ORDER BY day DESC
    """), {"uid": user_id})
    daily_rows = [
        {"day": str(r[0]), "sessions": r[1], "avg_turns": round(r[2] or 0, 1), "errors": r[3], "notes": r[4] or 0}
        for r in daily.fetchall()
    ]

    # Error breakdown
    errors = db.execute(text("""
        SELECT end_reason, count(*) as cnt
        FROM acs_session
        WHERE user_id = :uid AND started_at > NOW() - INTERVAL '7 days'
        GROUP BY end_reason ORDER BY cnt DESC
    """), {"uid": user_id})
    error_breakdown = {r[0]: r[1] for r in errors.fetchall()}

    # Mode distribution
    modes = db.execute(text("""
        SELECT cognitive_mode, count(*) as cnt
        FROM acs_session
        WHERE user_id = :uid AND started_at > NOW() - INTERVAL '7 days' AND cognitive_mode IS NOT NULL
        GROUP BY cognitive_mode ORDER BY cnt DESC
    """), {"uid": user_id})
    mode_dist = {r[0]: r[1] for r in modes.fetchall()}

    # Top engaged interest nodes
    top_nodes = db.execute(text("""
        SELECT label, fascination, times_engaged, depth
        FROM acs_interest_node
        WHERE user_id = :uid AND status = 'active'
        ORDER BY times_engaged DESC LIMIT 10
    """), {"uid": user_id})
    top = [
        {"label": r[0], "fascination": round(r[1], 2), "engaged": r[2], "depth": round(r[3] or 0, 2)}
        for r in top_nodes.fetchall()
    ]

    return {
        "daily": daily_rows,
        "error_breakdown": error_breakdown,
        "mode_distribution": mode_dist,
        "top_interests": top,
    }
