"""Diagnostics substrate — Sara's read-only sense of her own body (Phase 2).

Two stores (migration 101):
  - task_failure : upserted ledger, one row per (task_name, error_class)
  - system_event : ring buffer of WARNING+ logs / failures / deploy events

Everything here is *read-mostly* from Sara's perspective: the chat tools expose
read-only queries; only the Celery signal handler + logging handler write. Sara
can read everything about herself and modify nothing — hard policy.

All timestamps are aware UTC (new-table convention, no naive-datetime trap).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.timezone import now_utc

logger = logging.getLogger(__name__)

# Tasks whose *first* failure is worth escalating immediately (not just ≥3/24h).
CRITICAL_TASKS = {
    "app.tasks.reflection.run_reflection_cycle",
    "app.tasks.autonomy.run_consolidation",
    "app.tasks.autonomy.trigger_deliberation",
    "app.tasks.autonomy.periodic_deliberation_fallback",
    "app.tasks.autonomy.deep_deliberation",
    "app.tasks.autonomy.home_state_hourly_summary",
    "app.tasks.autonomy.proactive_checkin_sweep",
    "sync",  # health sync (substring match handled below)
    "morning_brief",
    "weekly_synthesis",
}

# Map a task name → the user-facing feature it breaks (for explain()).
FEATURE_MAP = {
    "run_reflection_cycle": "nightly reflection (pattern detection + self-assessment)",
    "run_consolidation": "memory consolidation (episodes → long-term memory, patterns)",
    "trigger_deliberation": "event-driven deliberation (Sara's proactive thinking)",
    "periodic_deliberation_fallback": "the 30-min deliberation safety net",
    "deep_deliberation": "the 2x-daily deep deliberation pass",
    "home_state_hourly_summary": "home-context awareness (rooms, motion, climate)",
    "proactive_checkin_sweep": "proactive check-ins / follow-ups",
    "pkg_deep_extract": "personal knowledge graph extraction",
    "weekly_synthesis": "the weekly brief synthesis",
    "morning_brief": "the morning brief",
    "email_sync": "email sync",
}


def _stable_event_id(*parts: str) -> str:
    h = hashlib.sha1("::".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"evt_{h[:16]}"


def feature_for_task(task_name: str) -> Optional[str]:
    for key, feature in FEATURE_MAP.items():
        if key in (task_name or ""):
            return feature
    return None


def _is_critical(task_name: str) -> bool:
    tn = task_name or ""
    for c in CRITICAL_TASKS:
        if c in tn:
            return True
    return False


# ---------------------------------------------------------------------------
# Writers (signal handler + logging handler only)
# ---------------------------------------------------------------------------
async def record_task_failure(
    task_name: str,
    error_class: str,
    error_message: Optional[str] = None,
    traceback_str: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert a task_failure row and mirror it into system_event. Returns a small
    dict incl. whether this failure should escalate (first critical / ≥3 in 24h)."""
    from app.db.session import get_async_session_factory
    event_id = _stable_event_id(task_name, error_class)
    now = now_utc()
    factory = get_async_session_factory()
    async with factory() as db:
        row = (await db.execute(
            text("""
                INSERT INTO task_failure
                    (task_name, error_class, error_message, traceback, event_id,
                     first_seen, last_seen, occurrences, resolved)
                VALUES (:tn, :ec, :em, :tb, :eid, :now, :now, 1, false)
                ON CONFLICT (task_name, error_class) DO UPDATE SET
                    error_message = EXCLUDED.error_message,
                    traceback = EXCLUDED.traceback,
                    last_seen = EXCLUDED.last_seen,
                    occurrences = task_failure.occurrences + 1,
                    resolved = false,
                    resolved_at = NULL
                RETURNING occurrences, first_seen
            """),
            {"tn": task_name, "ec": error_class, "em": (error_message or "")[:4000],
             "tb": (traceback_str or "")[:8000], "eid": event_id, "now": now},
        )).first()
        occurrences = row[0] if row else 1
        first_time = occurrences == 1
        await _insert_system_event(
            db, category="task_failure", service=task_name, level="ERROR",
            logger_name=task_name, message=(error_message or error_class)[:2000],
            traceback_str=traceback_str, event_id=event_id,
            meta={"error_class": error_class, "occurrences": occurrences},
        )
        await db.commit()

    # 24h count for escalation decision
    count_24h = await failure_count_24h(task_name, error_class)
    escalate = (first_time and _is_critical(task_name)) or count_24h >= 3
    return {"event_id": event_id, "occurrences": occurrences,
            "count_24h": count_24h, "escalate": escalate, "critical": _is_critical(task_name)}


async def _insert_system_event(db, *, category, service, level, logger_name,
                               message, traceback_str=None, event_id=None, meta=None):
    import json as _json
    if event_id is None:
        event_id = _stable_event_id(category, service or "", (message or "")[:120])
    await db.execute(
        text("""
            INSERT INTO system_event
                (event_id, category, service, level, logger, message, traceback, meta, created_at)
            VALUES (:eid, :cat, :svc, :lvl, :lg, :msg, :tb, CAST(:meta AS jsonb), :now)
        """),
        {"eid": event_id, "cat": category, "svc": (service or "")[:128],
         "lvl": (level or "")[:16], "lg": (logger_name or "")[:255],
         "msg": (message or "")[:4000], "tb": (traceback_str or None),
         "meta": _json.dumps(meta) if meta else None, "now": now_utc()},
    )


async def record_system_event(category: str, service: str, level: str, message: str,
                              logger_name: str = "", traceback_str: Optional[str] = None,
                              meta: Optional[dict] = None, event_id: Optional[str] = None) -> str:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        eid = event_id or _stable_event_id(category, service, (message or "")[:120])
        await _insert_system_event(
            db, category=category, service=service, level=level, logger_name=logger_name or service,
            message=message, traceback_str=traceback_str, event_id=eid, meta=meta)
        await db.commit()
    return eid


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
async def failure_count_24h(task_name: str, error_class: Optional[str] = None) -> int:
    """Occurrences in the last 24h. Uses last_seen as the recency signal (the
    ledger upserts, so a task failing repeatedly has a fresh last_seen)."""
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        # Prefer counting system_event rows (per-occurrence) for accuracy.
        q = """
            SELECT count(*) FROM system_event
            WHERE category = 'task_failure' AND service = :tn
              AND created_at > :since
        """
        params = {"tn": task_name, "since": now_utc().replace(microsecond=0) - _td(hours=24)}
        if error_class:
            q += " AND meta->>'error_class' = :ec"
            params["ec"] = error_class
        r = await db.execute(text(q), params)
        return int(r.scalar() or 0)


def _td(**kw):
    from datetime import timedelta
    return timedelta(**kw)


async def get_failing_tasks(hours: int = 24, include_resolved: bool = False) -> List[Dict[str, Any]]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    since = now_utc() - _td(hours=hours)
    async with factory() as db:
        q = """
            SELECT task_name, error_class, error_message, occurrences, first_seen,
                   last_seen, event_id, resolved
            FROM task_failure
            WHERE last_seen > :since
        """
        if not include_resolved:
            q += " AND resolved = false"
        q += " ORDER BY last_seen DESC"
        rows = (await db.execute(text(q), {"since": since})).mappings().all()
        out = []
        for r in rows:
            c24 = await failure_count_24h(r["task_name"], r["error_class"])
            out.append({
                "task_name": r["task_name"],
                "error_class": r["error_class"],
                "error_message": r["error_message"],
                "occurrences_total": r["occurrences"],
                "count_24h": c24,
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                "event_id": r["event_id"],
                "feature": feature_for_task(r["task_name"]),
                "critical": _is_critical(r["task_name"]),
            })
        return out


async def mark_recovered(task_name: str) -> int:
    """Mark all open failures of a task resolved (called when it next succeeds)."""
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        r = await db.execute(
            text("""UPDATE task_failure SET resolved = true, resolved_at = :now
                    WHERE task_name = :tn AND resolved = false"""),
            {"tn": task_name, "now": now_utc()})
        await db.commit()
        return r.rowcount or 0


async def search_events(service: Optional[str] = None, level: Optional[str] = None,
                        since_hours: int = 24, query: Optional[str] = None,
                        limit: int = 50) -> List[Dict[str, Any]]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    since = now_utc() - _td(hours=since_hours)
    async with factory() as db:
        q = "SELECT event_id, category, service, level, logger, message, created_at FROM system_event WHERE created_at > :since"
        params: Dict[str, Any] = {"since": since, "lim": limit}
        if service:
            q += " AND service ILIKE :svc"; params["svc"] = f"%{service}%"
        if level:
            q += " AND level = :lvl"; params["lvl"] = level.upper()
        if query:
            q += " AND message ILIKE :qq"; params["qq"] = f"%{query}%"
        q += " ORDER BY created_at DESC LIMIT :lim"
        rows = (await db.execute(text(q), params)).mappings().all()
        return [{
            "event_id": r["event_id"], "category": r["category"], "service": r["service"],
            "level": r["level"], "logger": r["logger"], "message": r["message"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        } for r in rows]


async def explain_event(event_id: str) -> Optional[Dict[str, Any]]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        ev = (await db.execute(
            text("""SELECT event_id, category, service, level, logger, message, traceback,
                           meta, created_at FROM system_event
                    WHERE event_id = :eid ORDER BY created_at DESC LIMIT 1"""),
            {"eid": event_id})).mappings().first()
        tf = (await db.execute(
            text("""SELECT task_name, error_class, error_message, traceback, occurrences,
                           first_seen, last_seen, resolved FROM task_failure
                    WHERE event_id = :eid"""),
            {"eid": event_id})).mappings().first()
    if not ev and not tf:
        return None
    out: Dict[str, Any] = {"event_id": event_id}
    if tf:
        out.update({
            "kind": "task_failure",
            "task_name": tf["task_name"],
            "error_class": tf["error_class"],
            "error_message": tf["error_message"],
            "occurrences_total": tf["occurrences"],
            "first_seen": tf["first_seen"].isoformat() if tf["first_seen"] else None,
            "last_seen": tf["last_seen"].isoformat() if tf["last_seen"] else None,
            "resolved": tf["resolved"],
            "breaks_feature": feature_for_task(tf["task_name"]),
            "traceback": tf["traceback"],
            "count_24h": await failure_count_24h(tf["task_name"], tf["error_class"]),
        })
    elif ev:
        out.update({
            "kind": ev["category"], "service": ev["service"], "level": ev["level"],
            "message": ev["message"], "traceback": ev["traceback"],
            "created_at": ev["created_at"].isoformat() if ev["created_at"] else None,
            "breaks_feature": feature_for_task(ev["service"] or ""),
        })
    return out


# ---------------------------------------------------------------------------
# Aggregation / digest
# ---------------------------------------------------------------------------
async def diagnostics_overview() -> Dict[str, Any]:
    """One-call health summary: failing tasks, error counts by service (24h),
    queue depths, funnel status, daemon heartbeat freshness."""
    failing = await get_failing_tasks(hours=24)
    events = await search_events(level="ERROR", since_hours=24, limit=200)
    by_service: Dict[str, int] = {}
    for e in events:
        by_service[e["service"] or "?"] = by_service.get(e["service"] or "?", 0) + 1

    overview: Dict[str, Any] = {
        "generated_at": now_utc().isoformat(),
        "failing_tasks": failing,
        "failing_task_count": len(failing),
        "error_counts_by_service_24h": dict(sorted(by_service.items(), key=lambda kv: -kv[1])[:15]),
    }

    # Queue depths (best-effort)
    try:
        overview["queue_depths"] = await _queue_depths()
    except Exception as e:
        overview["queue_depths"] = {"error": str(e)}

    # Daemon heartbeat freshness (best-effort)
    try:
        overview["daemon_heartbeat"] = await _daemon_heartbeat_status()
    except Exception as e:
        overview["daemon_heartbeat"] = {"error": str(e)}

    # Backup freshness — placeholder slot (11A: David builds backups separately)
    overview["backup"] = {"status": "not_configured", "note": "no backup system configured yet"}

    return overview


async def _queue_depths() -> Dict[str, int]:
    import redis.asyncio as aredis
    import os
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = aredis.Redis.from_url(url, decode_responses=True)
    try:
        depths = {}
        for q in ["cognitive", "health", "input", "maintenance", "low_priority", "reflection"]:
            depths[q] = int(await r.llen(q))
        return depths
    finally:
        await r.close()


async def _daemon_heartbeat_status() -> Dict[str, Any]:
    """Freshness of the ACS daemon heartbeat (from acs_daemon state if present)."""
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        # acs_daemon writes a heartbeat somewhere; check the most recent agent_run_log
        # from the daemon source as a proxy, plus any explicit heartbeat table.
        try:
            r = (await db.execute(text(
                "SELECT to_regclass('acs_heartbeat') IS NOT NULL AS has_tbl"))).scalar()
        except Exception:
            r = False
        if r:
            row = (await db.execute(text(
                "SELECT max(created_at) FROM acs_heartbeat"))).scalar()
            if row:
                age = (now_utc() - row).total_seconds()
                return {"last_seen": row.isoformat(), "age_seconds": int(age),
                        "fresh": age < 300}
        return {"status": "unknown", "note": "no acs_heartbeat table"}


async def build_health_digest(max_items: int = 5) -> Optional[str]:
    """Compact health digest for the deliberation context. Returns None if healthy."""
    failing = await get_failing_tasks(hours=24)
    # Only surface tasks that cross the escalation threshold.
    notable = [f for f in failing if f["count_24h"] >= 3 or f["critical"]]
    if not notable:
        return None
    lines = ["## Something's wrong with me (internal health)"]
    for f in notable[:max_items]:
        feat = f["feature"] or f["task_name"].split(".")[-1]
        lines.append(
            f"- {f['task_name'].split('.')[-1]}: {f['count_24h']} failures/24h "
            f"({f['error_class']}) — breaks {feat}. event {f['event_id']}"
        )
    return "\n".join(lines)


async def build_report(topic: str) -> str:
    """Compile a markdown handoff bundle for David to hand to Claude Code."""
    ov = await diagnostics_overview()
    lines = [f"# Sara diagnostics report: {topic}",
             f"_generated {ov['generated_at']}_", ""]
    failing = ov["failing_tasks"]
    if not failing:
        lines.append("No failing tasks in the last 24h.")
    else:
        lines.append(f"## Failing tasks ({len(failing)})")
        for f in failing:
            lines += [
                f"### {f['task_name']}  ",
                f"- error: `{f['error_class']}` — {f['error_message']}",
                f"- {f['count_24h']} failures in 24h (total {f['occurrences_total']}); "
                f"first {f['first_seen']}, last {f['last_seen']}",
                f"- breaks: {f['feature'] or 'unknown feature'}",
                f"- event: `{f['event_id']}`",
            ]
            ex = await explain_event(f["event_id"])
            if ex and ex.get("traceback"):
                tb = ex["traceback"].strip().splitlines()
                lines.append("- traceback (tail):")
                lines.append("```")
                lines += tb[-15:]
                lines.append("```")
            lines.append("")
    lines.append("## Error counts by service (24h)")
    for svc, n in ov["error_counts_by_service_24h"].items():
        lines.append(f"- {svc}: {n}")
    lines += ["", "## Queue depths", "```", str(ov.get("queue_depths")), "```"]
    lines += ["", "_Sara diagnoses and writes this up; a human + Claude Code makes the code change._"]
    return "\n".join(lines)


async def purge_old_events(days: int = 30) -> int:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    cutoff = now_utc() - _td(days=days)
    async with factory() as db:
        r = await db.execute(text("DELETE FROM system_event WHERE created_at < :c"), {"c": cutoff})
        await db.commit()
        return r.rowcount or 0
