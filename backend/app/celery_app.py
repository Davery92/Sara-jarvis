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
from celery.schedules import crontab

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
        "app.tasks.karma",
        "app.tasks.reflection",
        "app.tasks.autonomy",
        "app.tasks.email_sync",
        "app.tasks.automation",
        "app.tasks.content_inbox",
        "app.tasks.learning",
        "app.tasks.intelligence",
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

    # Rate limiting
    task_default_rate_limit="60/m",  # Default: 60 tasks per minute

    # Retry settings
    task_default_retry_delay=60,  # 1 minute retry delay
    task_max_retries=3,

    # Worker settings
    worker_concurrency=4,  # Number of concurrent workers
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks (prevent memory leaks)
)

# Beat schedule - all periodic tasks
celery_app.conf.beat_schedule = {
    # ============================================
    # PHASE 1: Foundation
    # ============================================

    # Consolidation watcher - checks if quiet period reached, then triggers consolidation
    # Does NOT run on fixed timer - only consolidates after activity goes quiet
    "consolidation-watcher": {
        "task": "app.tasks.consolidation.check_consolidation_trigger",
        "schedule": 10.0,  # Check every 10 seconds
        "options": {"queue": "cognitive"}
    },

    # Working memory context refresh
    "context-refresh": {
        "task": "app.tasks.working_memory.refresh_context",
        "schedule": 60.0,  # Every 60 seconds
        "options": {"queue": "cognitive"}
    },

    # Raw buffer cleanup (TTL enforcement)
    "buffer-cleanup": {
        "task": "app.tasks.working_memory.cleanup_expired",
        "schedule": 300.0,  # Every 5 minutes
        "options": {"queue": "maintenance"}
    },

    # System heartbeat - health monitoring
    "system-heartbeat": {
        "task": "app.tasks.health.system_heartbeat",
        "schedule": 300.0,  # Every 5 minutes
        "options": {"queue": "health"}
    },

    # ============================================
    # PHASE 2: Karma
    # ============================================

    # Karma decay - daily drift toward neutral (4 AM)
    "karma-decay": {
        "task": "app.tasks.karma.apply_karma_decay",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "maintenance"}
    },

    # Karma alerts - check for critically low scores (every 6 hours)
    "karma-alerts": {
        "task": "app.tasks.karma.check_karma_alerts",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"queue": "maintenance"}
    },

    # Karma report - daily status summary (8 AM)
    "karma-report": {
        "task": "app.tasks.karma.generate_karma_report",
        "schedule": crontab(hour=8, minute=0),
        "options": {"queue": "low_priority"}
    },

    # ============================================
    # PHASE 3: Reflection
    # ============================================

    # Reflection cycle - meta-cognitive auditing (every 4 hours)
    "reflection-cycle": {
        "task": "app.tasks.reflection.run_reflection_cycle",
        "schedule": crontab(minute=0, hour="*/4"),
        "options": {"queue": "reflection"}
    },

    # Scratchpad cleanup - remove expired observations (daily at 5 AM)
    "scratchpad-cleanup": {
        "task": "app.tasks.reflection.cleanup_scratchpad",
        "schedule": crontab(hour=5, minute=0),
        "options": {"queue": "maintenance"}
    },

    # Reflection report - daily summary (9 AM)
    "reflection-report": {
        "task": "app.tasks.reflection.generate_reflection_report",
        "schedule": crontab(hour=9, minute=0),
        "options": {"queue": "low_priority"}
    },

    # ============================================
    # PHASE 4: Autonomy
    # ============================================

    # DEPRECATED: unified-agent replaced by event-driven deliberation system:
    #   - derived-signal-refresh (5 min) — keeps working memory fresh
    #   - salience-triggered deliberation (on-demand) — event subscribers trigger when needed
    #   - periodic-deliberation-fallback (30 min) — safety net
    #   - afternoon/evening-consolidation (2 PM, 9 PM) — deep pattern review
    # The unified_agent task definition is kept for rollback; beat entry removed.

    # Standing order time check — ensures time-based standing orders always fire
    # even without unified_agent scheduling.
    "standing-order-time-check": {
        "task": "app.tasks.autonomy.standing_order_time_check",
        "schedule": 60.0,  # every minute
        "options": {"queue": "cognitive"}
    },

    # Derived signal refresh — DB-dependent working memory updates
    # Body state, activity state, hours-since-chat/meal, habits, calendar, etc.
    "derived-signal-refresh": {
        "task": "app.tasks.autonomy.derived_signal_refresh",
        "schedule": 300.0,  # 5 minutes
        "options": {"queue": "low_priority"}
    },

    # Periodic deliberation fallback — safety net for event-driven deliberation
    # Checks accumulated salience and runs deliberation if needed
    "periodic-deliberation-fallback": {
        "task": "app.tasks.autonomy.periodic_deliberation_fallback",
        "schedule": 1800.0,  # 30 minutes
        "options": {"queue": "cognitive"}
    },

    # Consolidation — deep reflection on patterns (2 PM and 9 PM)
    "afternoon-consolidation": {
        "task": "app.tasks.autonomy.run_consolidation",
        "schedule": crontab(hour=14, minute=0),
        "options": {"queue": "cognitive"}
    },
    "evening-consolidation": {
        "task": "app.tasks.autonomy.run_consolidation",
        "schedule": crontab(hour=21, minute=0),
        "options": {"queue": "cognitive"}
    },

    # Morning anticipation (7 AM daily)
    "morning-anticipation": {
        "task": "app.tasks.autonomy.morning_anticipation",
        "schedule": crontab(hour=7, minute=0),
        "options": {"queue": "cognitive"}
    },

    # Evening anticipation (9 PM daily)
    "evening-anticipation": {
        "task": "app.tasks.autonomy.evening_anticipation",
        "schedule": crontab(hour=21, minute=0),
        "options": {"queue": "cognitive"}
    },

    # Nightly memory consolidation (3 AM daily)
    "nightly-consolidation": {
        "task": "app.tasks.autonomy.nightly_memory_consolidation",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "maintenance"}
    },

    # Weekly learning digest (Sunday 10 AM)
    "weekly-digest": {
        "task": "app.tasks.autonomy.weekly_learning_digest",
        "schedule": crontab(hour=10, minute=0, day_of_week="sunday"),
        "options": {"queue": "reflection"}
    },

    # PKG deep extraction - mine conversations for personal knowledge (12 PM + 6 PM)
    "pkg-midday-extract": {
        "task": "app.tasks.autonomy.pkg_deep_extract",
        "schedule": crontab(hour=12, minute=0),
        "kwargs": {"since_hours": 6},
        "options": {"queue": "cognitive"}
    },

    "pkg-evening-extract": {
        "task": "app.tasks.autonomy.pkg_deep_extract",
        "schedule": crontab(hour=18, minute=0),
        "kwargs": {"since_hours": 6},
        "options": {"queue": "cognitive"}
    },

    # Idle processing - productive use of quiet time (every 10 minutes)
    "idle-processing": {
        "task": "app.tasks.autonomy.idle_processing",
        "schedule": 600.0,
        "options": {"queue": "low_priority"}
    },

    # Weather context refresh - update temperature/conditions in unified snapshot (every 30 min)
    "weather-context-refresh": {
        "task": "app.tasks.autonomy.weather_context_refresh",
        "schedule": 1800.0,  # 30 minutes
        "options": {"queue": "low_priority"}
    },

    # Home state hourly summary - aggregate HA events for pattern analysis
    "home-state-summary": {
        "task": "app.tasks.autonomy.home_state_hourly_summary",
        "schedule": crontab(minute=5),  # 5 min past each hour
        "options": {"queue": "low_priority"}
    },

    # Daily autonomy digest - summary of agent runs and notifications (9 PM)
    "daily-autonomy-digest": {
        "task": "app.tasks.autonomy.daily_autonomy_digest",
        "schedule": crontab(hour=21, minute=0),
        "options": {"queue": "low_priority"}
    },

    # ============================================
    # PHASE 5: Email Integration
    # ============================================

    # Email sync - fetch new emails from MS Graph (every 3 minutes)
    "email-sync": {
        "task": "app.tasks.email_sync.sync_emails",
        "schedule": 180.0,  # 3 minutes
        "options": {"queue": "cognitive"}
    },

    # RiskNinja attachment filing - process important attachments (every 5 minutes)
    "riskninja-attachment-filing": {
        "task": "app.tasks.email_sync.process_riskninja_attachments",
        "schedule": 300.0,  # 5 minutes
        "options": {"queue": "cognitive"}
    },

    # ============================================
    # PHASE 6: Natural Language Automation
    # ============================================

    # Automation watcher - finds and dispatches due automation tasks (every 30 seconds)
    "automation-watcher": {
        "task": "app.tasks.automation.automation_watcher",
        "schedule": 30.0,
        "options": {"queue": "cognitive"}
    },

    # ============================================
    # PHASE 7: Learning System
    # ============================================

    # Deep research poller - processes queued research jobs (every 60 seconds)
    "deep-research-poller": {
        "task": "app.tasks.learning.deep_research_worker",
        "schedule": 60.0,
        "options": {"queue": "cognitive"}
    },

    # Pending source fetcher - auto-fetch sources with fetch_status='pending' (every 2 minutes)
    "pending-source-fetcher": {
        "task": "app.tasks.learning.fetch_pending_sources",
        "schedule": 120.0,
        "options": {"queue": "cognitive"}
    },

    # Autonomy retention cleanup - daily at 4 AM (Phase 0 — Cortana Evolution)
    "autonomy-retention-cleanup": {
        "task": "app.tasks.autonomy.autonomy_retention_cleanup",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "maintenance"}
    },

    # Mission worker - advance runnable missions (Phase 2 — Cortana Evolution)
    "mission-worker": {
        "task": "app.tasks.autonomy.mission_worker",
        "schedule": 30.0,
        "options": {"queue": "cognitive"}
    },

    # ============================================
    # PHASE 8: Intelligence Monitor
    # ============================================

    # Intelligence scan - discover new items from RSS, HN, GitHub releases (every 2 hours)
    "intelligence-scan": {
        "task": "app.tasks.intelligence.intelligence_scan",
        "schedule": 7200.0,  # 2 hours
        "options": {"queue": "low_priority"}
    },

    # Intelligence digest - synthesize high-scoring items at noon
    "intelligence-digest-noon": {
        "task": "app.tasks.intelligence.intelligence_digest",
        "schedule": crontab(hour=12, minute=30),
        "options": {"queue": "cognitive"}
    },

    # Intelligence digest - synthesize high-scoring items in the evening
    "intelligence-digest-evening": {
        "task": "app.tasks.intelligence.intelligence_digest",
        "schedule": crontab(hour=18, minute=30),
        "options": {"queue": "cognitive"}
    },
}

# Task routing - send tasks to appropriate queues
celery_app.conf.task_routes = {
    "app.tasks.consolidation.*": {"queue": "cognitive"},
    "app.tasks.working_memory.*": {"queue": "cognitive"},
    "app.tasks.health.*": {"queue": "health"},
    "app.tasks.input_processing.*": {"queue": "input"},
    "app.tasks.reflection.*": {"queue": "reflection"},
    "app.tasks.karma.*": {"queue": "maintenance"},
    "app.tasks.autonomy.*": {"queue": "cognitive"},
    "app.tasks.email_sync.*": {"queue": "cognitive"},
    "app.tasks.automation.*": {"queue": "cognitive"},
    "app.tasks.content_inbox.*": {"queue": "cognitive"},
    "app.tasks.learning.*": {"queue": "cognitive"},
    "app.tasks.intelligence.*": {"queue": "low_priority"},
}

# Define queues with priorities
celery_app.conf.task_queues = {
    "cognitive": {"exchange": "cognitive", "routing_key": "cognitive"},
    "health": {"exchange": "health", "routing_key": "health"},
    "input": {"exchange": "input", "routing_key": "input"},
    "reflection": {"exchange": "reflection", "routing_key": "reflection"},
    "maintenance": {"exchange": "maintenance", "routing_key": "maintenance"},
    "low_priority": {"exchange": "low_priority", "routing_key": "low_priority"},
}

# Default queue
celery_app.conf.task_default_queue = "cognitive"


def _validate_queue_topology():
    """Startup check: all queues used in routing/scheduling are declared and consumed."""
    declared_queues = set(celery_app.conf.task_queues.keys()) if celery_app.conf.task_queues else set()

    # Collect queues targeted by beat schedule
    beat_queues = set()
    for name, entry in (celery_app.conf.beat_schedule or {}).items():
        q = (entry.get("options") or {}).get("queue")
        if q:
            beat_queues.add(q)
            if q not in declared_queues:
                logger.warning(f"Queue topology: beat task '{name}' targets queue '{q}' not in task_queues")

    # Collect queues targeted by task routes
    route_queues = set()
    for pattern, route in (celery_app.conf.task_routes or {}).items():
        q = route.get("queue") if isinstance(route, dict) else route
        if q:
            route_queues.add(q)
            if q not in declared_queues:
                logger.warning(f"Queue topology: route '{pattern}' targets queue '{q}' not in task_queues")

    # Check worker subscription covers required queues (from env)
    required_queues = beat_queues | route_queues
    worker_queues_str = os.environ.get("CELERY_WORKER_QUEUES", "")
    if worker_queues_str:
        worker_queues = {q.strip() for q in worker_queues_str.split(",")}
        uncovered = required_queues - worker_queues
        if uncovered:
            logger.warning(f"Queue topology: required queues {uncovered} not in worker subscription")

    logger.info(f"Queue topology validated: {len(required_queues)} required queues, {len(declared_queues)} declared")


_validate_queue_topology()
