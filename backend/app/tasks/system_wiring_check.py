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
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)
SOLO_USER_ID = get_owner_id()

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


# Ground-truth invariant 3: "everything open has a closer and an expiry." A thread
# kind that nothing can close is a nag generator — the three Laura Weippert
# threads were `commitment` and `follow_up`, and no code path in the system could
# resolve either. Each kind here names how it gets closed; a new kind with no
# entry fails the check rather than quietly joining them.
THREAD_KIND_CLOSERS = {
    "active_conversation": "conversation.closed",
    "follow_up": "thread.resolved (sent reply / David / ack / expiry)",
    "commitment": "thread.resolved (commitment_service / David / expiry)",
    "plan": "task.completed / task.cancelled",
    "decision": "thread.resolved (David / expiry)",
    "dependency": "thread.resolved (David / expiry)",
    "prep": "calendar.ended",
    "meeting": "calendar.ended",
    "support_ticket": "thread.resolved (sent reply / David)",
}


def _check_one_task_world() -> list:
    """The tool, the API and the status tool must read the same task world.

    On 2026-09-01 David asked "is it running?" fifteen minutes after starting a
    research plan. `get_background_tasks` read `background_task` only — blind to
    `research_plan` — so Sara told him, with total confidence, that the plan did
    not exist. He asked three more times and got three more plans, all four of
    which then ran to completion. One function, or this fails.
    """
    import inspect

    problems: list = []
    try:
        from app.services import agent_activity
        from app.tools import agents as agents_tool
        from app.routes import background_tasks as tasks_route

        if not hasattr(agent_activity, "get_agent_activity"):
            return ["agent_activity.get_agent_activity is missing"]

        tool_source = inspect.getsource(agents_tool)
        if "get_agent_activity" not in tool_source:
            problems.append(
                "get_background_tasks does not call agent_activity.get_agent_activity "
                "— the tool and the app see different task worlds"
            )
        if "get_agent_activity" not in inspect.getsource(tasks_route):
            problems.append("/api/agent-activity does not use agent_activity.get_agent_activity")
        # research_plan_status must agree on what "running" means.
        if not hasattr(agent_activity, "RESEARCH_STATUS_MAP"):
            problems.append("agent_activity.RESEARCH_STATUS_MAP is missing — status vocabulary is unshared")
    except Exception as e:
        problems.append(f"task-world check failed to run: {e}")
    return problems


def _check_thread_closer_coverage() -> list:
    """Every live thread kind must have a way to end."""
    from sqlalchemy import text as sa_text
    from app.db.base import SessionLocal

    problems: list = []
    try:
        with SessionLocal() as db:
            rows = db.execute(sa_text("""
                SELECT kind, COUNT(*) AS n FROM world_thread
                 WHERE status IN ('proposed','open','waiting','blocked','overdue')
                 GROUP BY kind
            """)).fetchall()
            for row in rows:
                kind = (row.kind or "").strip()
                # Normalize the hyphen/underscore drift the interpreter produces
                # ("follow-up" vs "follow_up") before deciding it's unknown.
                if kind.replace("-", "_") not in THREAD_KIND_CLOSERS:
                    problems.append(
                        f"thread kind {kind!r} ({row.n} open) has no registered closer"
                    )

            orphans = db.execute(sa_text("""
                SELECT COUNT(*) FROM world_thread
                 WHERE status IN ('proposed','open','waiting','blocked')
                   AND due_at IS NULL AND next_review_at IS NULL
            """)).scalar() or 0
            if orphans:
                problems.append(f"{orphans} open thread(s) with neither a due date nor a review date")

            unverified = db.execute(sa_text("""
                SELECT COUNT(*) FROM world_thread
                 WHERE status IN ('proposed','open','waiting','blocked','overdue')
                   AND due_at IS NOT NULL
                   AND (due_provenance IS NULL OR due_provenance = 'legacy:unverified')
            """)).scalar() or 0
            if unverified:
                problems.append(f"{unverified} open thread(s) with a deadline nothing vouches for")
    except Exception as e:
        logger.debug(f"Thread closer check skipped: {e}")
    return problems


def _check_self_model_docs() -> list:
    """Sara can read her own documentation.

    `tools/self_knowledge.py` resolves SELF_MODEL_DIR to `/docs` inside the
    container. Nothing mounted it there until 2026-09-02, so every
    `get_self_knowledge` call in Docker returned a file-not-found error and the
    nightly self-model regeneration wrote nothing — for as long as she has run
    in Docker, and silently, because a missing directory looks the same as a
    tool David never happened to trigger.
    """
    from app.tools.self_knowledge import SELF_KNOWLEDGE_SECTIONS, SELF_MODEL_DIR

    problems: list = []
    if not SELF_MODEL_DIR.is_dir():
        return [f"SELF_MODEL_DIR {SELF_MODEL_DIR} does not exist — self-knowledge is dark"]
    missing = [
        name for name in SELF_KNOWLEDGE_SECTIONS.values()
        if not (SELF_MODEL_DIR / name).is_file()
    ]
    if missing:
        problems.append(f"self-model docs missing from {SELF_MODEL_DIR}: {', '.join(missing)}")
    return problems


@celery_app.task(name="app.tasks.system_wiring_check.run_check", queue="low_priority")
def run_check():
    """Weekly self-audit. Green -> quiet digest line. Red -> Needs-You inbox item."""
    import asyncio

    unscheduled = _check_task_coverage()
    job_problems = _check_scheduled_job_health()
    stale_tables = _check_learning_freshness()
    stale_code = _check_deployed_code_freshness()
    closer_gaps = _check_thread_closer_coverage()
    task_world_gaps = _check_one_task_world()
    self_model_gaps = _check_self_model_docs()

    all_problems = (
        [f"Unscheduled task: {t}" for t in unscheduled]
        + [f"Job unhealthy: {p}" for p in job_problems]
        + [f"Learning table stale: {s}" for s in stale_tables]
        + stale_code
        + [f"Closer coverage: {c}" for c in closer_gaps]
        + [f"Task world: {t}" for t in task_world_gaps]
        + [f"Self-knowledge: {s}" for s in self_model_gaps]
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
        "closer_gaps": closer_gaps,
        "task_world_gaps": task_world_gaps,
        "self_model_gaps": self_model_gaps,
    }
