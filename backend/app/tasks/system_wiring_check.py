"""System Wiring Check — Sara's standing self-audit (Phase 5.2, SARA_100_PLAN).

The recurring failure mode this project keeps rediscovering via manual audit:
things get built, then silently never get wired to a scheduler, or a wiring
bug ships and nobody notices until weeks later (see: notification_tuner.py
existing but missing from celery_app.py's `include` for however long, or
DBScheduler.apply_entry marking last_status='success' at DISPATCH time, not
completion — so a task that dispatches successfully into a void where no
worker has it registered still shows green).

Runs weekly (Sun 8 AM ET).

This check itself became the nag it was built to prevent. It pushed the same
finding to David's phone on Aug 2, 16, 23, 30, Sep 6 and Sep 13 — always
"…plus N more", with N growing and nothing ever changing hands. Four causes,
all fixed on 2026-09-13:

1. A hand-written on-demand allowlist that nobody extended, so every
   event-driven task added since was a permanent false positive. Replaced by
   ``TASK_CLASS``: a task absent from that map is class ``scheduled`` and must
   have a ``scheduled_job`` row; a key in the map that is no longer registered
   is itself a finding, so the map cannot rot the way the allowlist did.
2. No memory of the previous run, so an unchanged list was news every Sunday.
   Now each run stores a fingerprint set in ``app_settings`` and computes
   new/persisting/resolved.
3. A dedup key derived from the message text, which the phrasing stage
   rewrote every week so the cooldown never matched. Now a stable topic.
4. ``priority="important"``, which routes to a push, and ``[:5]`` truncation
   that always showed the same boring alphabetical five.

Only a finding not seen in the previous run reaches David, and it reaches the
inbox, not the phone.
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.core.config import get_owner_id
from app.services.world_state.thread_kinds import THREAD_KIND_CLOSERS  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)
SOLO_USER_ID = get_owner_id()

# Why a registered task may legitimately have no `scheduled_job` row.
#   event   — dispatched by a route, service or subscriber (.delay / send_task)
#   manual  — a human runs it on purpose
#   test    — diagnostic; may fail by design
# Anything NOT in here is class "scheduled" and must have a row. A key here
# that is no longer registered is reported as a stale classification, which is
# what keeps this map honest as tasks come and go.
TASK_CLASS: dict[str, str] = {
    "app.tasks.automation.automation_execute": "event",
    "app.tasks.autonomy.learning_pkg_sync": "event",
    "app.tasks.autonomy.run_consolidation": "event",
    "app.tasks.autonomy.trigger_deliberation": "event",
    "app.tasks.consolidation.run_consolidation": "event",
    "app.tasks.content_inbox.classify_and_file_content": "event",
    "app.tasks.content_inbox.extract_shared_content": "event",
    "app.tasks.dispatch.execute_dispatch": "event",
    "app.tasks.email_sync.analyze_recent_emails": "event",
    "app.tasks.email_sync.download_attachments": "event",
    "app.tasks.email_sync.process_riskninja_attachments": "event",
    "app.tasks.input_processing.process_audio_input": "event",
    "app.tasks.input_processing.process_calendar_event": "event",
    "app.tasks.input_processing.process_environmental": "event",
    "app.tasks.input_processing.process_notification": "event",
    "app.tasks.input_processing.process_screen_capture": "event",
    "app.tasks.input_processing.process_text_input": "event",
    "app.tasks.input_processing.process_visual_input": "event",
    "app.tasks.intelligence.intelligence_digest": "event",
    "app.tasks.intelligence.intelligence_scan": "event",
    "app.tasks.learning.auto_research_topic": "event",
    "app.tasks.learning.discover_blueprint_resources": "event",
    "app.tasks.learning.generate_blueprint_guides_worker": "event",
    "app.tasks.learning.generate_blueprint_lessons_worker": "event",
    "app.tasks.learning.process_uploaded_source": "event",
    "app.tasks.learning.transform_topic_chunks": "event",
    "app.tasks.notes.backfill_note_connections": "event",
    "app.tasks.reflection.assess_proposal_outcome": "event",
    "app.tasks.research.answer_research_question": "event",
    "app.tasks.research.run_research_plan": "event",
    "app.tasks.workspace_jobs.run_workspace_job": "event",
    "app.tasks.world_state.process_event": "event",
    "app.tasks.world_state.interpret_event": "event",
    "app.tasks.world_state.consider_attention": "event",
    "app.tasks.world_state.deliver_presence": "event",
    # manual: a human runs it on purpose
    "app.tasks.ml.backfill_features": "manual",
    "app.tasks.dreams.run_dream_cycle": "manual",   # §3.8, unscheduled by decision 2026-08-31
    # test: diagnostic, may fail by design
    "app.tasks.interoception.selftest": "test",
}

# Where the previous run's fingerprints live. Plain app_settings row, no
# migration — see _load_last_findings / _store_findings.
LAST_FINDINGS_KEY = "system_wiring_check.last_findings"

# key learning tables + the column that should be advancing, and how many
# days of silence is worth flagging.
_LEARNING_TABLE_CHECKS = [
    ("behavioral_pattern", "updated_at", 3, "user_id = :uid"),
    ("daily_rhythm", "computed_at", 3, "user_id = :uid"),
    ("attention_policy", "last_updated", 10, "user_id = :uid"),
    ("location_event", "created_at", 3, "user_id = :uid"),
]


def _check_task_coverage() -> dict:
    """Every registered task of class `scheduled` should have a scheduled_job
    row. Catches "built but never scheduled" — the #1 recurring failure mode
    in this codebase.

    Two findings, deliberately in one function so they stay in sync:
      unscheduled          — class `scheduled`, no row at all
      stale_classification — a TASK_CLASS key nothing registers any more

    A row with `enabled = FALSE` counts as covered. David disables jobs on
    purpose from routes/schedules.py (`curiosity-sweep` and `weekly-digest`
    are off right now); a deliberate off switch is not a wiring gap.
    """
    from sqlalchemy import text
    from app.db.base import SessionLocal

    registered = {n for n in celery_app.tasks.keys() if n.startswith("app.tasks")}
    with SessionLocal() as db:
        scheduled = {
            r[0] for r in db.execute(text("SELECT DISTINCT task_name FROM scheduled_job")).fetchall()
        }

    expect_row = {n for n in registered if TASK_CLASS.get(n, "scheduled") == "scheduled"}
    return {
        "unscheduled": sorted(expect_row - scheduled),
        "stale_classification": sorted(set(TASK_CLASS) - set(celery_app.tasks.keys())),
    }


def _queue_for_task(task_name: str) -> str:
    """Resolve a task name to its queue the way Celery's router does: first
    matching `task_routes` glob wins, else the default queue."""
    import fnmatch

    for pattern, route in (celery_app.conf.task_routes or {}).items():
        if fnmatch.fnmatchcase(task_name, pattern):
            queue = route.get("queue") if isinstance(route, dict) else route
            if queue:
                return queue
    return celery_app.conf.task_default_queue or "celery"


def _check_orphan_schedules() -> list:
    """The inverse of task coverage: an enabled scheduled_job row whose task
    no live worker can actually run.

    DBScheduler.apply_entry marks last_status='success' at DISPATCH time, so a
    job routed into a queue nobody consumes — or consumed by a worker that
    never imported the task — stays green forever. That is the void the module
    docstring warns about, and until now nothing looked for it.

    Being registered is not enough: the worker that registers the task must
    also consume the queue the task routes to. `critical`, `acs` and
    `david_priority` are separate containers from the main worker.
    """
    from sqlalchemy import text
    from app.db.base import SessionLocal

    inspector = celery_app.control.inspect(timeout=5)
    try:
        registered_by_worker = inspector.registered() or {}
        queues_by_worker = inspector.active_queues() or {}
    except Exception as e:
        logger.debug(f"Orphan-schedule inspect failed: {e}")
        registered_by_worker, queues_by_worker = {}, {}

    if not registered_by_worker or not queues_by_worker:
        # Never report an all-clear we did not observe: a silent broker looks
        # exactly like a healthy cluster from here.
        return ["Orphan-schedule check could not verify: no worker answered inspect"]

    # worker -> set of queue names it consumes
    consumed = {
        worker: {q.get("name") for q in (queues or []) if q.get("name")}
        for worker, queues in queues_by_worker.items()
    }

    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT key, task_name FROM scheduled_job WHERE enabled = TRUE"
        )).fetchall()

    problems = []
    for row in rows:
        queue = _queue_for_task(row.task_name)
        # `registered()` returns display names, not bare task names: this
        # cluster's are "app.tasks.x.y [rate_limit=60/m]". Take the first token.
        runnable = any(
            queue in consumed.get(worker, set())
            and any(str(t).split()[0] == row.task_name for t in (tasks or []) if str(t).strip())
            for worker, tasks in registered_by_worker.items()
        )
        if not runnable:
            problems.append(
                f"{row.key}: {row.task_name} routes to queue '{queue}' but no live worker "
                "both registers it and consumes that queue"
            )
    return problems


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


# Numbers that move on their own. A count going 4 -> 5, or "49h ago" becoming
# "73h ago", is the same finding and must fingerprint identically; a NEW kind
# of finding must not. Applied before hashing, never to the displayed text.
_VOLATILE_SUBS = (
    (re.compile(r"\b\d+(?:\.\d+)?\s*([hd])\s+(ago|newer)\b"), r"N\1 \2"),
    (re.compile(r"\b\d+(?:\.\d+)?(?=\s+(?:open|row|item|thread|job|task|day|finding)s?\b)"), "N"),
)


def _fingerprint(text: str) -> str:
    normalized = text
    for pattern, replacement in _VOLATILE_SUBS:
        normalized = pattern.sub(replacement, normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _load_last_findings() -> dict:
    """Previous run's fingerprints, or {} if this is the first run ever."""
    from sqlalchemy import text
    from app.db.base import SessionLocal

    try:
        with SessionLocal() as db:
            raw = db.execute(
                text("SELECT value FROM app_settings WHERE key = :k"),
                {"k": LAST_FINDINGS_KEY},
            ).scalar()
        return (json.loads(raw) or {}).get("findings", {}) if raw else {}
    except Exception as e:
        # A missing/corrupt state row must not cost us the run. Worst case we
        # treat everything as new once, which is the old behaviour for one week.
        logger.warning(f"[wiring-check] could not read {LAST_FINDINGS_KEY}: {e}")
        return {}


def _store_findings(findings: dict) -> None:
    from sqlalchemy import text
    from app.db.base import SessionLocal

    payload = json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
    })
    try:
        with SessionLocal() as db:
            db.execute(text("""
                INSERT INTO app_settings (key, value, updated_at, updated_by)
                VALUES (:k, :v, NOW(), 'system_wiring_check')
                ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value,
                       updated_at = EXCLUDED.updated_at,
                       updated_by = EXCLUDED.updated_by
            """), {"k": LAST_FINDINGS_KEY, "v": payload})
            db.commit()
    except Exception as e:
        logger.error(f"[wiring-check] could not persist {LAST_FINDINGS_KEY}: {e}")


def _compose_message(new: list, persisting: dict, resolved: dict, limit: int = 1500) -> str:
    """New findings in full, most severe first, then one tail line. The tail is
    what gets truncated — the whole point of the rewrite is that the new items
    are never the part that gets cut."""
    body = "\n".join(new)
    tail = f"\n{len(persisting)} known finding(s) still open, {len(resolved)} cleared."
    if len(body) + len(tail) <= limit:
        return body + tail
    if len(body) >= limit:
        return body[:limit]  # more than 1500 chars of NEW findings is its own alarm
    return body + tail[:limit - len(body)]


@celery_app.task(name="app.tasks.system_wiring_check.run_check", queue="low_priority")
def run_check(notify: bool = True):
    """Weekly self-audit. Only findings that are NEW since the previous run
    reach David, and they reach the Needs-You inbox, not his phone.

    `notify=False` runs the whole path — including persisting the fingerprint
    state — without sending, so a manual run can't wake anybody up.
    """
    import asyncio

    coverage = _check_task_coverage()
    unscheduled = coverage["unscheduled"]
    stale_classification = coverage["stale_classification"]
    orphan_schedules = _check_orphan_schedules()
    job_problems = _check_scheduled_job_health()
    stale_tables = _check_learning_freshness()
    stale_code = _check_deployed_code_freshness()
    closer_gaps = _check_thread_closer_coverage()
    task_world_gaps = _check_one_task_world()
    self_model_gaps = _check_self_model_docs()

    # Order IS severity. A broken loop nobody can run outranks a bookkeeping
    # mismatch in the classification map.
    all_problems = (
        [f"Orphan schedule: {o}" for o in orphan_schedules]
        + [f"Job unhealthy: {p}" for p in job_problems]
        + stale_code
        + [f"Closer coverage: {c}" for c in closer_gaps]
        + [f"Learning table stale: {s}" for s in stale_tables]
        + [f"Self-knowledge: {s}" for s in self_model_gaps]
        + [f"Task world: {t}" for t in task_world_gaps]
        + [f"Unscheduled task: {t}" for t in unscheduled]
        + [f"Stale classification: {t}" for t in stale_classification]
    )

    last = _load_last_findings()
    now_iso = datetime.now(timezone.utc).isoformat()
    current: dict = {}
    for problem in all_problems:
        fp = _fingerprint(problem)
        current[fp] = {
            "text": problem,
            "first_seen": (last.get(fp) or {}).get("first_seen", now_iso),
        }

    new_fps = [fp for fp in current if fp not in last]
    resolved = {fp: v for fp, v in last.items() if fp not in current}
    persisting = {fp: v for fp, v in current.items() if fp in last}
    # all_problems order is severity order, so filtering it preserves that.
    new = [current[fp]["text"] for fp in current if fp in new_fps]

    notified = False

    async def _report():
        nonlocal notified
        if not new:
            if all_problems:
                logger.info(
                    f"[wiring-check] nothing new: {len(persisting)} known finding(s) still open, "
                    f"{len(resolved)} cleared — staying quiet"
                )
            else:
                logger.info("[wiring-check] all clear — no unscheduled tasks, no unhealthy jobs, learning tables fresh")
            return

        logger.warning(
            f"[wiring-check] new={new} persisting={[v['text'] for v in persisting.values()]} "
            f"resolved={[v['text'] for v in resolved.values()]}"
        )
        if not notify:
            return

        from app.services.unified_notification import send_notification
        from app.db.session import get_async_session_factory

        AsyncSessionLocal = get_async_session_factory()
        async with AsyncSessionLocal() as db:
            await send_notification(
                user_id=SOLO_USER_ID,
                title=f"Wiring check: {len(new)} new finding(s)",
                message=_compose_message(new, persisting, resolved),
                # normal => attention item only, no push. See
                # route_through_attention_queue in unified_notification.py.
                priority="normal",
                topic="system_wiring_check:weekly",
                cooldown_hours=24 * 6,
                category="system",
                source="system_wiring_check",
                db=db,
            )
            # send_notification doesn't commit a caller-supplied session
            # (see mindv2_deliver.py's identical fix, 2026-07-30) — without
            # this the notification_log row silently rolled back.
            await db.commit()
        notified = True

    asyncio.run(_report())
    _store_findings(current)

    return {
        "healthy": not all_problems,
        "new": new,
        "persisting": [v["text"] for v in persisting.values()],
        "resolved": [v["text"] for v in resolved.values()],
        "all_findings": all_problems,
        "notified": notified,
        "unscheduled_tasks": unscheduled,
        "stale_classification": stale_classification,
        "orphan_schedules": orphan_schedules,
        "job_problems": job_problems,
        "stale_tables": stale_tables,
        "stale_code": stale_code,
        "closer_gaps": closer_gaps,
        "task_world_gaps": task_world_gaps,
        "self_model_gaps": self_model_gaps,
    }
