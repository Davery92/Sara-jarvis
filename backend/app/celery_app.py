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

import os
from celery import Celery
from celery.schedules import crontab

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

    # Proactive check - consider if action needed (every 15 minutes)
    "proactive-check": {
        "task": "app.tasks.autonomy.proactive_check",
        "schedule": 900.0,
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

    # Idle processing - productive use of quiet time (every 10 minutes)
    "idle-processing": {
        "task": "app.tasks.autonomy.idle_processing",
        "schedule": 600.0,
        "options": {"queue": "low_priority"}
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
