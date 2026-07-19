"""
Celery application configuration for Sara's cognitive architecture.

This provides the unified task scheduling and worker management for:
- Input processing (audio, visual, screen, text)
- Consolidation agent (context compression)
- Working memory management
- Reflection cycles
- Proactive checks and anticipation
- Memory consolidation
"""

import logging
import os
from celery import Celery

# Set up structured logging for Celery workers
from app.core.logging import setup_logging
setup_logging(
    service_name="sara-celery",
    environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    json_output=os.getenv("LOG_FORMAT", "text") == "json",
)
logger = logging.getLogger(__name__)

# Sentry error tracking for Celery workers (no-op if DSN not configured)
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        sentry_sdk.init(
            dsn=_sentry_dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            send_default_pii=False,
            integrations=[CeleryIntegration()],
        )
    except Exception:
        pass

# Get Redis URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Create the Celery app
celery_app = Celery(
    "sara_cognitive",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.consolidation",
        "app.tasks.working_memory",
        "app.tasks.health",
        "app.tasks.input_processing",
        "app.tasks.reflection",
        "app.tasks.autonomy",
        "app.tasks.email_sync",
        "app.tasks.automation",
        "app.tasks.content_inbox",
        "app.tasks.learning",
        "app.tasks.intelligence",
        "app.tasks.notes",
        "app.tasks.attention",
        "app.tasks.morning_brief",
        "app.tasks.research_brief",
        "app.tasks.inproc_schedulers",
        "app.tasks.research",
        "app.tasks.calendar_prep",
        "app.tasks.pkg_sync",
        "app.tasks.health_weekly",
        "app.tasks.health_baselines",
        "app.tasks.sara_self_queue",
        "app.tasks.subconscious_tier0",
        "app.tasks.morning_proactive",
        "app.tasks.dispatch_watchdog",
        "app.tasks.learning_digest",
        "app.tasks.location",
        "app.tasks.travel_nudge",
        "app.tasks.daily_rhythm",
        "app.tasks.notification_tuner",
        "app.tasks.system_wiring_check",
        "app.tasks.ml",
        "app.tasks.assistant_verbs",
        "app.tasks.workspace_jobs",
        "app.tasks.fleet",
        "app.tasks.interoception",
        "app.tasks.dispatch",
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/New_York",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,  # Acknowledge after task completes (safer)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # One task at a time per worker

    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour

    # Broker startup behavior
    broker_connection_retry_on_startup=True,

    # Rate limiting
    task_default_rate_limit="60/m",  # Default: 60 tasks per minute

    # Retry settings
    task_default_retry_delay=60,  # 1 minute retry delay
    task_max_retries=3,

    # Worker settings
    worker_concurrency=4,  # Number of concurrent workers
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks (prevent memory leaks)

    # Use the DB-backed scheduler. Schedule entries live in the `scheduled_job`
    # table and are editable via /api/settings/schedules. Beat reloads from DB
    # roughly once a minute, so changes take effect without a restart.
    beat_scheduler="app.celery_beat:DBScheduler",
)


# Task routing - send tasks to appropriate queues
celery_app.conf.task_routes = {
    "app.tasks.consolidation.*": {"queue": "cognitive"},
    "app.tasks.working_memory.*": {"queue": "cognitive"},
    "app.tasks.health.*": {"queue": "health"},
    "app.tasks.input_processing.*": {"queue": "input"},
    "app.tasks.reflection.*": {"queue": "reflection"},
    "app.tasks.autonomy.*": {"queue": "cognitive"},
    "app.tasks.email_sync.*": {"queue": "low_priority"},
    "app.tasks.automation.*": {"queue": "cognitive"},
    "app.tasks.content_inbox.*": {"queue": "cognitive"},
    "app.tasks.learning.*": {"queue": "cognitive"},
    "app.tasks.intelligence.*": {"queue": "low_priority"},
    "app.tasks.notes.*": {"queue": "maintenance"},
    # research.* defaults to cognitive; run_research_plan picks david_priority
    # at apply time when origin='david_chat' (see app.tasks.research).
    "app.tasks.research.*": {"queue": "cognitive"},
    "app.tasks.attention.*": {"queue": "cognitive"},
    "app.tasks.health_weekly.*": {"queue": "cognitive"},
    "app.tasks.health_baselines.*": {"queue": "health"},
    "app.tasks.sara_self_queue.*": {"queue": "cognitive"},
    "app.tasks.ml.*": {"queue": "cognitive"},
    "app.tasks.assistant_verbs.*": {"queue": "cognitive"},
    "app.tasks.workspace_jobs.*": {"queue": "cognitive"},
    # Durable agent dispatch (Phase 4) — long-running, isolated on its own queue so
    # a 20-min agent task never starves cognitive work and survives a backend restart.
    "app.tasks.dispatch.*": {"queue": "dispatch"},
    "app.tasks.interoception.*": {"queue": "maintenance"},
}

# Define queues with priorities
celery_app.conf.task_queues = {
    "critical": {"exchange": "critical", "routing_key": "critical"},
    "david_priority": {"exchange": "david_priority", "routing_key": "david_priority"},
    "cognitive": {"exchange": "cognitive", "routing_key": "cognitive"},
    "health": {"exchange": "health", "routing_key": "health"},
    "input": {"exchange": "input", "routing_key": "input"},
    "reflection": {"exchange": "reflection", "routing_key": "reflection"},
    "maintenance": {"exchange": "maintenance", "routing_key": "maintenance"},
    "low_priority": {"exchange": "low_priority", "routing_key": "low_priority"},
    "dispatch": {"exchange": "dispatch", "routing_key": "dispatch"},
}

# Default queue
celery_app.conf.task_default_queue = "cognitive"


def _validate_queue_topology():
    """Startup check: queues used in routing/scheduling are declared.

    Worker subscription coverage is only meaningful at the cluster level, so a
    queue-specific worker should not warn just because it intentionally
    subscribes to a subset of the application's queues.
    """
    declared_queues = set(celery_app.conf.task_queues.keys()) if celery_app.conf.task_queues else set()

    # Collect queues targeted by the DB-backed beat schedule.
    # We can't call into the DB at module import time (workers may boot
    # before the DB is reachable), so query best-effort and skip on failure.
    beat_queues: set[str] = set()
    try:
        from app.db.base import SessionLocal
        from app.models.scheduled_job import ScheduledJob
        with SessionLocal() as db:
            for row in db.query(ScheduledJob.key, ScheduledJob.queue).filter(ScheduledJob.enabled.is_(True)).all():
                if row.queue:
                    beat_queues.add(row.queue)
                    if row.queue not in declared_queues:
                        logger.warning(f"Queue topology: scheduled_job '{row.key}' targets queue '{row.queue}' not in task_queues")
    except Exception as e:
        logger.debug(f"Queue topology: skipping scheduled_job check ({e})")

    # Collect queues targeted by task routes
    route_queues = set()
    for pattern, route in (celery_app.conf.task_routes or {}).items():
        q = route.get("queue") if isinstance(route, dict) else route
        if q:
            route_queues.add(q)
            if q not in declared_queues:
                logger.warning(f"Queue topology: route '{pattern}' targets queue '{q}' not in task_queues")

    # Check worker subscription declares valid queues. Full coverage is a
    # cluster-level property and cannot be inferred from a single worker.
    required_queues = beat_queues | route_queues
    worker_queues_str = os.environ.get("CELERY_WORKER_QUEUES", "")
    if worker_queues_str:
        worker_queues = {q.strip() for q in worker_queues_str.split(",")}
        undeclared_worker_queues = worker_queues - declared_queues
        if undeclared_worker_queues:
            logger.warning(
                f"Queue topology: worker subscription includes undeclared queues {undeclared_worker_queues}"
            )
        uncovered = required_queues - worker_queues
        if uncovered:
            logger.info(
                f"Queue topology: worker subscribes to {worker_queues}; remaining queues {uncovered} "
                "must be covered elsewhere in the cluster"
            )

    logger.info(f"Queue topology validated: {len(required_queues)} required queues, {len(declared_queues)} declared")


_validate_queue_topology()


# ---------------------------------------------------------------------------
# Interoception — Sara feels her own body (Phase 2)
# Every Celery FAILURE writes to the task_failure ledger + system_event, and
# escalates critical/recurring failures to a Needs-You item + health notification.
# A matching success clears the ledger entry. A redis set gates the recovery
# path so successful tasks don't each incur a DB write.
# ---------------------------------------------------------------------------
_FAILING_SET_KEY = "sara:failing_tasks"


def _sync_redis():
    import os
    import redis as _redis
    return _redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"),
                                 decode_responses=True)


try:
    from celery.signals import task_failure as _task_failure_sig
    from celery.signals import task_success as _task_success_sig

    @_task_failure_sig.connect
    def _interoception_on_failure(sender=None, task_id=None, exception=None,
                                  traceback=None, einfo=None, **kw):
        try:
            import asyncio
            task_name = getattr(sender, "name", None) or str(sender)
            error_class = type(exception).__name__ if exception else "Unknown"
            tb = ""
            try:
                tb = einfo.traceback if einfo is not None and hasattr(einfo, "traceback") else str(einfo or "")
            except Exception:
                tb = str(einfo or "")

            async def _go():
                from app.services.diagnostics_service import record_task_failure
                res = await record_task_failure(task_name, error_class, str(exception), tb)
                if res.get("escalate"):
                    try:
                        from app.services.interoception_alerts import escalate_task_failure
                        await escalate_task_failure(task_name, error_class, res)
                    except Exception as _e:
                        logger.debug(f"health escalation skipped: {_e}")
                return res

            asyncio.run(_go())
            try:
                r = _sync_redis(); r.sadd(_FAILING_SET_KEY, task_name); r.close()
            except Exception:
                pass
        except Exception as e:  # never let interoception break the worker
            logger.error(f"interoception failure-handler crashed: {e}")

    @_task_success_sig.connect
    def _interoception_on_success(sender=None, result=None, **kw):
        try:
            task_name = getattr(sender, "name", None)
            if not task_name:
                return
            # Only touch the DB if this task was known to be failing.
            try:
                r = _sync_redis()
                if not r.sismember(_FAILING_SET_KEY, task_name):
                    r.close()
                    return
                r.srem(_FAILING_SET_KEY, task_name)
                r.close()
            except Exception:
                return
            import asyncio
            from app.services.diagnostics_service import mark_recovered
            asyncio.run(mark_recovered(task_name))
            logger.info(f"[interoception] {task_name} recovered — cleared from ledger")
        except Exception as e:
            logger.error(f"interoception success-handler crashed: {e}")

except Exception as _sig_e:  # pragma: no cover
    logger.error(f"Failed to register interoception signal handlers: {_sig_e}")
