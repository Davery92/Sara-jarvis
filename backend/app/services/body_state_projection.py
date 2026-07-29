"""
Canonical body-state projection (SINGULAR_SARA_MASTER_PLAN §13/§4.2/C2).

Today Sara's own system health is computed FOUR different, disagreeing ways:

  1. `app.tasks.health.system_heartbeat` writes a full checks dict (every
     monitored subsystem, healthy or not) to Redis `system:health_status`
     every 5 minutes — read raw by `/api/metrics`.
  2. `app.services.body_sense.current_self_status()` reads a *persisted,
     diffed* degraded-only view (report failures + daemon + managed-host
     reachability) — read by `/api/sara/brief`'s self_status section.
  3. `/analytics/dashboard` in main_simple.py re-probes the database and
     embedding service live, inline, independently of the heartbeat.
  4. `app.services.self_model._health()` runs its own independent live DB
     queries (task_failure, scheduled_job.last_status, email_sync_state
     staleness) — read by `/mind/self` (the Mind page). Found live
     (SARA_ALIVE_BUILD_PLAN Arc 2.2): this one was never folded in, so
     `/api/sara/brief` and the Mind page could show different verdicts in
     the same minute — the exact "she says she's fine, brief says she's
     degraded" failure mode Arc 2.2 was scoped to kill.

Nothing here is a new truth store. This module reads (1), (2), and (4) — all
sources that already exist — and merges them into one `BodyStateV1`
projection so every consumer sees the same verdict for the same component at
the same `as_of`. Callers should read this instead of re-deriving health from
scratch (see §13 item 3: "canonical body-state projection that resolves
current health contradictions").
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.schemas.contracts import BodyComponentV1, BodyStateV1, ComponentStatus

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

_HEARTBEAT_KEY = "system:health_status"
# The heartbeat runs every 5 minutes; a report much older than that means the
# heartbeat task itself has stopped, so trust it less rather than presenting
# a possibly-stale verdict as current.
_STALE_AFTER_SECONDS = 15 * 60

_HEALTHY_STATUSES = {"healthy"}
_DEGRADED_STATUSES = {"warning", "error", "critical"}


async def _get_redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)


async def _load_raw_report() -> Optional[Dict[str, Any]]:
    try:
        r = await _get_redis()
        raw = await r.get(_HEARTBEAT_KEY)
        try:
            await r.close()
        except Exception:
            pass
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.debug(f"[body_state_projection] could not load heartbeat report: {e}")
        return None


def _component_status(status: str) -> ComponentStatus:
    if status in _HEALTHY_STATUSES:
        return ComponentStatus.OK
    if status in _DEGRADED_STATUSES:
        return ComponentStatus.DEGRADED
    return ComponentStatus.UNKNOWN


# self_model._health()'s thresholds, duplicated here rather than imported so
# this module never depends on self_model (self_model depends on THIS module
# instead — see build_self_model's health section).
_EMAIL_CURSOR_STALE_HOURS = 24


async def _load_self_model_health_components(user_id: str, now: datetime) -> Dict[str, BodyComponentV1]:
    """The DB-derived health signals self_model._health() computes — folded
    in here so /mind/self and /api/sara/brief can never disagree again."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    components: Dict[str, BodyComponentV1] = {}
    try:
        factory = get_async_session_factory()
        async with factory() as db:
            failures = (await db.execute(text("""
                SELECT task_name, error_class, occurrences, last_seen
                FROM task_failure
                WHERE resolved = FALSE
                ORDER BY occurrences DESC, last_seen DESC
                LIMIT 20
            """))).fetchall()
            for f in failures:
                components[f"task_failure:{f.task_name}"] = BodyComponentV1(
                    name=f"task_failure:{f.task_name}",
                    label=f"{f.task_name} failing",
                    status=ComponentStatus.DEGRADED,
                    impact=f"{f.error_class} ({f.occurrences}x)",
                    severity="error",
                    source="self_model_health",
                    as_of=f.last_seen or now,
                    confidence=1.0,
                )

            failed_jobs = (await db.execute(text("""
                SELECT key, last_error, last_run_at
                FROM scheduled_job
                WHERE enabled = TRUE AND last_status = 'failed'
                ORDER BY last_run_at DESC NULLS LAST
                LIMIT 20
            """))).fetchall()
            for j in failed_jobs:
                components[f"scheduled_job:{j.key}"] = BodyComponentV1(
                    name=f"scheduled_job:{j.key}",
                    label=f"job '{j.key}' last run failed",
                    status=ComponentStatus.DEGRADED,
                    impact=(j.last_error or "")[:200] or None,
                    severity="warning",
                    source="self_model_health",
                    as_of=j.last_run_at or now,
                    confidence=1.0,
                )

            cursors = (await db.execute(text("""
                SELECT mailbox, last_sync_at,
                       EXTRACT(EPOCH FROM (NOW() - last_sync_at)) / 3600.0 AS hours_stale
                FROM email_sync_state
                WHERE last_sync_at IS NOT NULL
            """))).fetchall()
            for c in cursors:
                if c.hours_stale and c.hours_stale > _EMAIL_CURSOR_STALE_HOURS:
                    components[f"email_cursor:{c.mailbox}"] = BodyComponentV1(
                        name=f"email_cursor:{c.mailbox}",
                        label=f"email cursor '{c.mailbox}' stalled",
                        status=ComponentStatus.DEGRADED,
                        impact=f"stalled {c.hours_stale:.0f}h",
                        severity="warning",
                        source="self_model_health",
                        as_of=c.last_sync_at or now,
                        confidence=1.0,
                    )
    except Exception as e:
        logger.debug(f"[body_state_projection] self_model health signals unavailable: {e}")

    return components


async def get_body_state_projection(user_id: str = DEFAULT_USER_ID) -> BodyStateV1:
    """The one canonical body-state projection. Cheap: reads two Redis keys,
    no live probing — same discipline as `current_self_status()`, so calling
    this from a request path is safe."""
    from app.services.body_sense import current_self_status

    now = datetime.now(timezone.utc)
    components: Dict[str, BodyComponentV1] = {}

    report = await _load_raw_report()
    confidence = 1.0
    if report:
        try:
            report_as_of = datetime.fromisoformat(report["timestamp"])
        except Exception:
            report_as_of = now
        age_seconds = (now - report_as_of).total_seconds()
        if age_seconds > _STALE_AFTER_SECONDS:
            confidence = 0.3
        for name, check in (report.get("checks") or {}).items():
            severity = str(check.get("status", "")).lower() or None
            components[name] = BodyComponentV1(
                name=name,
                status=_component_status(severity or ""),
                impact=check.get("message"),
                severity=severity,
                source="system_heartbeat",
                as_of=report_as_of,
                confidence=confidence,
            )
    else:
        # Never observed a heartbeat — say so rather than defaulting to healthy.
        confidence = 0.0

    # Layer in daemon/host failures body_sense tracks separately from the
    # heartbeat's `checks` dict (ACS daemon liveness, managed-host reachability).
    self_status = await current_self_status(user_id)
    for d in self_status.get("degraded") or []:
        subsystem = d["subsystem"]
        components[subsystem] = BodyComponentV1(
            name=subsystem,
            label=d.get("name", subsystem),
            status=ComponentStatus.DEGRADED,
            impact=d.get("impact"),
            severity=d.get("severity"),
            source="interoception",
            as_of=now,
            confidence=1.0,
        )

    # Layer in the DB-derived signals self_model._health() used to compute
    # independently (task failures, failed scheduled jobs, stalled email
    # cursors) — this is the fold-in that makes /mind/self agree with
    # /api/sara/brief (Arc 2.2).
    components.update(await _load_self_model_health_components(user_id, now))

    degraded = [c for c in components.values() if c.status == ComponentStatus.DEGRADED]
    as_of = max((c.as_of for c in components.values()), default=now)
    return BodyStateV1(
        as_of=as_of,
        healthy=not degraded,
        components=list(components.values()),
        degraded_count=len(degraded),
        confidence=confidence,
    )


async def get_component(name: str, user_id: str = DEFAULT_USER_ID) -> Optional[BodyComponentV1]:
    """Look up one named component (e.g. 'database', 'embeddings') from the
    canonical projection — for callers migrating off an ad hoc live probe."""
    projection = await get_body_state_projection(user_id)
    for c in projection.components:
        if c.name == name:
            return c
    return None
