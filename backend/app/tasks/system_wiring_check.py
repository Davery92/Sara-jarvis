"""System Wiring Check — Sara's standing self-audit (Phase 5.2, SARA_100_PLAN).

The recurring failure mode this project keeps rediscovering via manual audit:
things get built, then silently never get wired to a scheduler, or a wiring
bug ships and nobody notices until weeks later (see: notification_tuner.py
existing but missing from celery_app.py's `include` for however long, or
DBScheduler.apply_entry marking last_status='success' at DISPATCH time, not
completion — so a task that dispatches successfully into a void where no
worker has it registered still shows green).

Runs weekly (Sun 8 AM ET). Checks four things and pushes ONE summary line —
green folds into the weekly digest, red becomes a Needs-You inbox item
naming the broken loop. Never a per-item nag.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")

# Tasks that are legitimately on-demand only (API/event-triggered via
# send_task or apply_async from a route/subscriber) — never expected to have
# a scheduled_job row. Extend this when a genuinely on-demand task starts
# getting flagged; that's the intended way to quiet a false positive.
ON_DEMAND_ALLOWLIST = {
    "app.tasks.automation.automation_execute",
    "app.tasks.autonomy.learning_pkg_sync",
    "app.tasks.autonomy.run_consolidation",
    "app.tasks.autonomy.trigger_deliberation",
    "app.tasks.consolidation.run_consolidation",
    "app.tasks.content_inbox.extract_shared_content",
    "app.tasks.email_sync.analyze_recent_emails",
    "app.tasks.email_sync.download_attachments",
    "app.tasks.email_sync.process_riskninja_attachments",
    "app.tasks.input_processing.process_audio_input",
    "app.tasks.input_processing.process_calendar_event",
    "app.tasks.input_processing.process_environmental",
    "app.tasks.input_processing.process_notification",
    "app.tasks.input_processing.process_screen_capture",
    "app.tasks.input_processing.process_text_input",
    "app.tasks.input_processing.process_visual_input",
    "app.tasks.intelligence.intelligence_digest",
    "app.tasks.intelligence.intelligence_scan",
    "app.tasks.learning.auto_research_topic",
    "app.tasks.learning.discover_blueprint_resources",
    "app.tasks.learning.generate_blueprint_guides_worker",
    "app.tasks.learning.generate_blueprint_lessons_worker",
    "app.tasks.learning.process_uploaded_source",
    "app.tasks.learning.transform_topic_chunks",
    "app.tasks.notes.backfill_note_connections",
    "app.tasks.reflection.assess_proposal_outcome",
    "app.tasks.research.answer_research_question",
    "app.tasks.research.run_research_plan",
}

# key learning tables + the column that should be advancing, and how many
# days of silence is worth flagging.
_LEARNING_TABLE_CHECKS = [
    ("behavioral_pattern", "updated_at", 3, "user_id = :uid"),
    ("daily_rhythm", "computed_at", 3, "user_id = :uid"),
    ("attention_policy", "last_updated", 10, "user_id = :uid"),
    ("location_event", "created_at", 3, "user_id = :uid"),
]


def _check_task_coverage() -> list:
    """Every registered task not on the on-demand allowlist should have a
    scheduled_job row. Catches "built but never scheduled" — the #1 recurring
    failure mode in this codebase."""
    from sqlalchemy import text
    from app.db.base import SessionLocal

    registered = {n for n in celery_app.tasks.keys() if n.startswith("app.tasks")}
    with SessionLocal() as db:
        scheduled = {
            r[0] for r in db.execute(text("SELECT DISTINCT task_name FROM scheduled_job")).fetchall()
        }

    missing = sorted(registered - scheduled - ON_DEMAND_ALLOWLIST)
    return missing


def _cron_stale_floor_hours(cron_expr: str) -> float:
    """Estimate a generous "definitely late by now" threshold from a 5-field
    cron string, so a weekly job isn't flagged for not running in 48h.
    minute hour day_of_month month day_of_week."""
    try:
        _minute, _hour, dom, _month, dow = cron_expr.strip().split()
    except (ValueError, AttributeError):
        return 48.0
    if dow != "*":
        return 24 * 10  # weekly-ish — allow up to 10 days
    if dom != "*":
        return 24 * 40  # monthly-ish — allow up to 40 days
    return 48.0  # daily or finer


def _check_scheduled_job_health() -> list:
    """scheduled_job rows that are enabled but erroring or suspiciously
    stale (no run in >2x their expected cadence)."""
    from sqlalchemy import text
    from app.db.base import SessionLocal

    problems = []
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT key, task_name, last_status, last_run_at, last_error,
                   schedule_kind, interval_seconds, cron_expr
            FROM scheduled_job WHERE enabled = TRUE
        """)).fetchall()

    now = datetime.now(timezone.utc)
    for row in rows:
        if row.last_status == "error":
            problems.append(f"{row.key}: last run errored ({(row.last_error or '')[:120]})")
            continue
        if row.last_run_at is None:
            continue  # brand new row, hasn't had a tick yet — not an error
        age_hours = (now - row.last_run_at).total_seconds() / 3600
        if row.schedule_kind == "interval" and row.interval_seconds:
            stale_floor_hours = max(2, (row.interval_seconds / 3600) * 3)
        else:
            stale_floor_hours = _cron_stale_floor_hours(row.cron_expr or "")
        if age_hours > stale_floor_hours:
            problems.append(f"{row.key}: last ran {age_hours:.0f}h ago (expected sooner)")

    return problems


def _check_learning_freshness() -> list:
    """Key learning tables should show recent activity. A silent table is
    usually a silently-broken writer, not "nothing happened this week"."""
    from sqlalchemy import text
    from app.db.base import SessionLocal

    stale = []
    with SessionLocal() as db:
        for table, col, max_days, where in _LEARNING_TABLE_CHECKS:
            try:
                row = db.execute(text(
                    f"SELECT MAX({col}) AS latest FROM {table} WHERE {where}"
                ), {"uid": SOLO_USER_ID}).fetchone()
            except Exception as e:
                stale.append(f"{table}: query failed ({e})")
                # A failed query aborts the whole transaction in Postgres —
                # without this, every check after the first failure cascades
                # into a spurious "current transaction is aborted" error.
                db.rollback()
                continue
            if not row or not row.latest:
                stale.append(f"{table}: no rows at all")
                continue
            latest = row.latest if row.latest.tzinfo else row.latest.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - latest).total_seconds() / 86400
            if age_days > max_days:
                stale.append(f"{table}: last update {age_days:.1f}d ago (expected within {max_days}d)")

    # pkg_embedding count as a coarse growth signal, not a freshness column
    try:
        with SessionLocal() as db:
            count = db.execute(text("SELECT COUNT(*) FROM pkg_embedding")).scalar()
        if not count:
            stale.append("pkg_embedding: table empty")
    except Exception as e:
        stale.append(f"pkg_embedding: query failed ({e})")

    return stale


def _process_start_epoch() -> float:
    """Absolute epoch start time of PID 1 (the container's main process),
    computed from /proc/1/stat's boot-relative starttime + /proc/uptime.
    Docker containers don't namespace /proc/uptime (it's the host's), so we
    can't use it directly as "time since this process started" — this
    combination is the standard correct way to derive an absolute start time."""
    import time as _time

    with open("/proc/uptime") as f:
        host_uptime_seconds = float(f.read().split()[0])
    with open("/proc/1/stat") as f:
        # comm (field 2) may itself contain spaces/parens, so split on the
        # LAST closing paren rather than whitespace to find field 3 onward.
        # starttime is field 22 overall == index 19 once fields 1-2 are gone.
        fields = f.read().rsplit(")", 1)[1].split()
        starttime_ticks = int(fields[19])
    clk_tck = os.sysconf("SC_CLK_TCK")
    proc_uptime_seconds = host_uptime_seconds - (starttime_ticks / clk_tck)
    return _time.time() - proc_uptime_seconds


def _check_deployed_code_freshness() -> list:
    """Compare the newest .py mtime under app/ against this process's start
    time. In dev, code is bind-mounted and only loaded at container restart
    — mechanizes the "deployed code lags working tree" gotcha."""
    import glob

    try:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/app
        py_files = glob.glob(os.path.join(app_dir, "**", "*.py"), recursive=True)
        if not py_files:
            return []
        newest_mtime = max(os.path.getmtime(f) for f in py_files)
        proc_start = _process_start_epoch()

        if newest_mtime > proc_start + 300:  # 5 min grace for the restart itself
            age_hours = (newest_mtime - proc_start) / 3600
            return [f"code on disk is {age_hours:.1f}h newer than this container's boot — restart needed"]
    except Exception as e:
        logger.debug(f"Code freshness check skipped: {e}")
    return []


@celery_app.task(name="app.tasks.system_wiring_check.run_check", queue="low_priority")
def run_check():
    """Weekly self-audit. Green -> quiet digest line. Red -> Needs-You inbox item."""
    import asyncio

    unscheduled = _check_task_coverage()
    job_problems = _check_scheduled_job_health()
    stale_tables = _check_learning_freshness()
    stale_code = _check_deployed_code_freshness()

    all_problems = (
        [f"Unscheduled task: {t}" for t in unscheduled]
        + [f"Job unhealthy: {p}" for p in job_problems]
        + [f"Learning table stale: {s}" for s in stale_tables]
        + stale_code
    )

    async def _report():
        if all_problems:
            from app.services.unified_notification import send_notification
            from app.db.session import get_async_session_factory

            summary = "; ".join(all_problems[:5])
            if len(all_problems) > 5:
                summary += f" (+{len(all_problems) - 5} more)"

            AsyncSessionLocal = get_async_session_factory()
            async with AsyncSessionLocal() as db:
                await send_notification(
                    user_id=SOLO_USER_ID,
                    title="System wiring check found issues",
                    message=summary,
                    priority="important",
                    category="system",
                    source="system_wiring_check",
                    db=db,
                )
                # send_notification doesn't commit a caller-supplied session
                # (see mindv2_deliver.py's identical fix, 2026-07-30) — without
                # this the notification_log row silently rolled back.
                await db.commit()
            logger.warning(f"[wiring-check] {len(all_problems)} problem(s): {all_problems}")
        else:
            logger.info("[wiring-check] all clear — no unscheduled tasks, no unhealthy jobs, learning tables fresh")

    asyncio.run(_report())

    return {
        "healthy": not all_problems,
        "unscheduled_tasks": unscheduled,
        "job_problems": job_problems,
        "stale_tables": stale_tables,
        "stale_code": stale_code,
    }
