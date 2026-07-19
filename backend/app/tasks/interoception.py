"""Interoception Celery tasks (Phase 2).

- drain_system_events : move redis-buffered WARNING+ logs into system_event
- self_check          : daily body-scan (heartbeat, voice, drift, funnel, queues,
                        backup placeholder) → ledger + optional health alert
- purge_events        : 30-day retention on system_event
"""
import asyncio
import json
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
_REDIS_KEY = "sara:system_events"


def _run(coro):
    return asyncio.run(coro)


@celery_app.task(name="app.tasks.interoception.drain_system_events", queue="maintenance")
def drain_system_events(batch: int = 500):
    """Pop buffered log records off redis and batch-insert into system_event."""
    return _run(_drain_async(batch))


async def _drain_async(batch: int):
    import os
    import redis.asyncio as aredis
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.diagnostics_service import _stable_event_id

    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = aredis.Redis.from_url(url, decode_responses=True)
    inserted = 0
    try:
        items = []
        for _ in range(batch):
            raw = await r.rpop(_REDIS_KEY)
            if raw is None:
                break
            try:
                items.append(json.loads(raw))
            except Exception:
                continue
        if not items:
            return {"drained": 0}

        from datetime import datetime, timezone
        factory = get_async_session_factory()
        async with factory() as db:
            for it in items:
                ts = it.get("ts")
                try:
                    created = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
                except Exception:
                    created = datetime.now(timezone.utc)
                svc = it.get("service", "")
                msg = it.get("message", "")
                eid = _stable_event_id("log", svc, msg[:120])
                await db.execute(text("""
                    INSERT INTO system_event
                        (event_id, category, service, level, logger, message, traceback, meta, created_at)
                    VALUES (:eid, 'log', :svc, :lvl, :lg, :msg, :tb, NULL, :created)
                """), {"eid": eid, "svc": svc[:128], "lvl": (it.get("level") or "")[:16],
                       "lg": (it.get("logger") or svc)[:255], "msg": msg[:4000],
                       "tb": it.get("traceback"), "created": created})
                inserted += 1
            await db.commit()
        return {"drained": inserted}
    finally:
        await r.close()


@celery_app.task(name="app.tasks.interoception.self_check", queue="health")
def self_check():
    """Daily body-scan. Records problems into the ledger and, if unhealthy,
    sends one health alert."""
    return _run(_self_check_async())


async def _self_check_async():
    from app.services.diagnostics_service import (
        diagnostics_overview, record_system_event,
    )
    findings = []
    ov = await diagnostics_overview()

    # 1. Failing tasks already tracked — surface count
    if ov["failing_task_count"] > 0:
        findings.append(f"{ov['failing_task_count']} task(s) failing in 24h")

    # 2. Queue depths sane
    qd = ov.get("queue_depths", {})
    if isinstance(qd, dict):
        deep = {q: n for q, n in qd.items() if isinstance(n, int) and n > 100}
        if deep:
            findings.append(f"deep queues: {deep}")

    # 3. Daemon heartbeat freshness
    hb = ov.get("daemon_heartbeat", {})
    if isinstance(hb, dict) and hb.get("fresh") is False:
        findings.append(f"daemon heartbeat stale ({hb.get('age_seconds')}s)")

    # 4. Jetson voice event within 24h (best-effort)
    try:
        voice_fresh = await _voice_fresh_24h()
        if voice_fresh is False:
            findings.append("no Jetson voice event in 24h")
    except Exception:
        pass

    # 5. Unmapped calendars — surface once (Phase 3.2), respecting acknowledged ones
    try:
        from app.services.calendar_ownership import find_unmapped_calendars
        unmapped = find_unmapped_calendars()
        if unmapped:
            names = ", ".join(f"{u['calendar']} ({u['events']})" for u in unmapped[:3])
            findings.append(f"unmapped calendars: {names} — who owns them?")
    except Exception:
        pass

    # 6. Version drift (Phase 7) — placeholder, filled once version endpoints land
    # 7. Backup freshness — placeholder (11A: David builds backups separately)
    #    Reported as informational, never an alert.

    status = "healthy" if not findings else "degraded"
    await record_system_event(
        category="selfcheck", service="interoception.self_check",
        level="INFO" if status == "healthy" else "WARNING",
        message=f"self-check {status}: " + ("; ".join(findings) if findings else "all clear"),
        meta={"findings": findings, "overview_failing": ov["failing_task_count"]},
    )

    # Alert once if there are genuinely new problems (the health-category cooldown
    # in interoception_alerts prevents nagging).
    if findings:
        try:
            from app.services.interoception_alerts import _cooldown_ok
            from app.services.unified_notification import send_notification
            if _cooldown_ok("self_check"):
                await send_notification(
                    user_id=DEFAULT_USER_ID,
                    title="Sara: daily self-check",
                    message="My daily self-check found: " + "; ".join(findings)
                            + ". Ask me 'what's broken?' for details.",
                    priority="normal", topic="health:self_check", category="system_health",
                    source="interoception", extra_push_data={"target": "chat"},
                    payload={"generator": "interoception", "diagnostics": True},
                )
        except Exception as e:
            logger.debug(f"self-check alert skipped: {e}")

    return {"status": status, "findings": findings, "backup": "not_configured"}


async def _voice_fresh_24h():
    """Return True/False/None — whether a Jetson voice event landed in 24h."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        has = (await db.execute(text("SELECT to_regclass('voice_event') IS NOT NULL"))).scalar()
        if not has:
            return None
        row = (await db.execute(text(
            "SELECT max(created_at) FROM voice_event"))).scalar()
        if not row:
            return False
        from app.core.timezone import now_utc
        # created_at may be naive; coerce for comparison
        import datetime as _dt
        if row.tzinfo is None:
            row = row.replace(tzinfo=_dt.timezone.utc)
        return (now_utc() - row).total_seconds() < 86400


@celery_app.task(name="app.tasks.interoception.selftest", queue="maintenance")
def selftest(should_fail: bool = True):
    """Harmless task used to verify the interoception loop end-to-end. Dispatch
    with should_fail=True to exercise the failure ledger + escalation, then
    should_fail=False to verify recovery clears the ledger entry. Never scheduled."""
    if should_fail:
        raise RuntimeError("interoception selftest: intentional failure")
    return {"status": "ok", "selftest": "recovered"}


@celery_app.task(name="app.tasks.interoception.purge_events", queue="maintenance")
def purge_events(days: int = 30):
    return _run(_purge_async(days))


async def _purge_async(days: int):
    from app.services.diagnostics_service import purge_old_events
    n = await purge_old_events(days)
    return {"purged": n}
