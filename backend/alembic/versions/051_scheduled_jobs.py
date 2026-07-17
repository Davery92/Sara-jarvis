"""Add scheduled_job table for DB-backed Celery beat schedule.

Revision ID: 051_scheduled_jobs
Revises: 050_subconscious_cols
Create Date: 2026-04-08

Creates a `scheduled_job` table that backs a custom Celery beat scheduler.
Replaces the static `celery_app.conf.beat_schedule` dict so the schedule
can be edited at runtime via the settings API/UI without restarting beat.

The migration also seeds rows for every entry currently in
`celery_app.beat_schedule`, plus a new `morning-brief-generate` row that
will replace the host crontab entry once the Celery task is wired up.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = "051_scheduled_jobs"
down_revision = "050_subconscious_cols"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


# Seed data — mirrors the current celery_app.beat_schedule dict.
# Each tuple: (key, display_name, description, category, task_name,
#              schedule_kind, cron_expr, interval_seconds, kwargs, queue, expires_seconds)
#
# cron_expr uses standard 5-field crontab format: "minute hour day_of_month month day_of_week"
# Times are interpreted in the timezone column (default America/New_York).
# Keys that should default to visibility='user' — surfaced in the settings UI
# without the "Show system jobs" toggle. Everything else is internal plumbing.
USER_FACING_KEYS = {
    "morning-brief-generate",
    "morning-anticipation",
    "evening-anticipation",
    "morning-inbox-digest",
    "afternoon-consolidation",
    "evening-consolidation",
    "nightly-consolidation",
    "nightly-dream-cycle",
    "daily-autonomy-digest",
    "weekly-digest",
    "reflection-report",
    "reflection-cycle",
    "pkg-midday-extract",
    "pkg-evening-extract",
    "acs-morning-winddown",
    "acs-daily-report",
    "acs-daily-plan",
    "acs-daily-audit",
    "acs-interest-decay",
    "notification-tuner",
    "autonomy-retention-cleanup",
    "scratchpad-cleanup",
    "daily-brief-context-update",
    "daily-brief-archive",
    "daily-brief-weekly-synthesis",
}

SEED_JOBS = [
    # ── Foundation ────────────────────────────────────────────────
    ("consolidation-watcher", "Consolidation Watcher",
     "Checks every minute if a quiet period has been reached, then triggers consolidation. Does not run on a fixed timer — only consolidates after activity goes quiet.",
     "foundation", "app.tasks.consolidation.check_consolidation_trigger",
     "interval", None, 60, {}, "critical", None),

    ("context-refresh", "Working Memory Context Refresh",
     "Refreshes the working memory context window every minute.",
     "foundation", "app.tasks.working_memory.refresh_context",
     "interval", None, 60, {}, "critical", None),

    ("buffer-cleanup", "Raw Buffer Cleanup",
     "Removes expired entries from the raw observation buffer (TTL enforcement).",
     "foundation", "app.tasks.working_memory.cleanup_expired",
     "interval", None, 300, {}, "maintenance", None),

    ("system-heartbeat", "System Heartbeat",
     "Health monitoring ping every 5 minutes.",
     "foundation", "app.tasks.health.system_heartbeat",
     "interval", None, 300, {}, "health", None),

    # ── Reflection ────────────────────────────────────────────────
    ("reflection-cycle", "Reflection Cycle",
     "Meta-cognitive auditing of recent activity, every 4 hours.",
     "reflection", "app.tasks.reflection.run_reflection_cycle",
     "cron", "0 */4 * * *", None, {}, "reflection", None),

    ("scratchpad-cleanup", "Scratchpad Cleanup",
     "Removes expired observations from the reflection scratchpad. Daily 5 AM.",
     "reflection", "app.tasks.reflection.cleanup_scratchpad",
     "cron", "0 5 * * *", None, {}, "maintenance", None),

    ("reflection-report", "Reflection Daily Report",
     "Generates the daily reflection report at 9 AM.",
     "reflection", "app.tasks.reflection.generate_reflection_report",
     "cron", "0 9 * * *", None, {}, "low_priority", None),

    # ── Autonomy ──────────────────────────────────────────────────
    ("standing-order-time-check", "Standing Order Time Check",
     "Ensures time-based standing orders fire even without unified_agent scheduling.",
     "autonomy", "app.tasks.autonomy.standing_order_time_check",
     "interval", None, 120, {}, "critical", 900),

    ("container-cleanup", "Proxmox Container Cleanup",
     "Destroys idle ephemeral containers, hourly.",
     "autonomy", "app.tasks.autonomy.cleanup_stale_containers",
     "cron", "0 * * * *", None, {}, "maintenance", None),

    ("derived-signal-refresh", "Derived Signal Refresh",
     "DB-dependent working memory updates: body state, activity, hours-since-chat/meal, habits, calendar.",
     "autonomy", "app.tasks.autonomy.derived_signal_refresh",
     "interval", None, 300, {}, "low_priority", None),

    ("periodic-deliberation-fallback", "Periodic Deliberation Fallback",
     "Safety net for event-driven deliberation. Checks accumulated salience every 30 min.",
     "autonomy", "app.tasks.autonomy.periodic_deliberation_fallback",
     "interval", None, 1800, {}, "cognitive", None),

    ("afternoon-consolidation", "Afternoon Consolidation",
     "Deep reflection on patterns at 2 PM.",
     "autonomy", "app.tasks.autonomy.run_consolidation",
     "cron", "0 14 * * *", None, {}, "cognitive", None),

    ("evening-consolidation", "Evening Consolidation",
     "Deep reflection on patterns at 9 PM.",
     "autonomy", "app.tasks.autonomy.run_consolidation",
     "cron", "0 21 * * *", None, {}, "cognitive", None),

    ("morning-anticipation", "Morning Anticipation",
     "Prepares anticipated context for the day at 6 AM.",
     "autonomy", "app.tasks.autonomy.morning_anticipation",
     "cron", "0 6 * * *", None, {}, "cognitive", None),

    ("morning-inbox-digest", "Morning Inbox Digest",
     "Reminds about unread Inbox items on phone at 8 AM.",
     "notifications", "app.tasks.content_inbox.send_morning_inbox_digest",
     "cron", "0 8 * * *", None, {}, "cognitive", None),

    ("attention-escalation-sweep", "Attention Escalation Sweep",
     "Pushes out attention items unread for >ESCALATION_HOURS so David sees them outside the webapp. Every 30 min.",
     "autonomy", "app.tasks.attention.escalate_unread_attention",
     "interval", None, 1800, {}, "cognitive", 1500),

    ("evening-anticipation", "Evening Anticipation",
     "Prepares for tomorrow at 9:20 PM (staggered from consolidation).",
     "autonomy", "app.tasks.autonomy.evening_anticipation",
     "cron", "20 21 * * *", None, {}, "cognitive", None),

    ("nightly-consolidation", "Nightly Memory Consolidation",
     "Processes the day's experiences at 3 AM.",
     "autonomy", "app.tasks.autonomy.nightly_memory_consolidation",
     "cron", "0 3 * * *", None, {}, "maintenance", None),

    ("weekly-digest", "Weekly Learning Digest",
     "Weekly summary of learning activity. Sundays 10 AM.",
     "autonomy", "app.tasks.autonomy.weekly_learning_digest",
     "cron", "0 10 * * 0", None, {}, "reflection", None),

    ("idle-processing", "Idle Processing",
     "Productive use of quiet time, every 10 minutes.",
     "autonomy", "app.tasks.autonomy.idle_processing",
     "interval", None, 600, {}, "low_priority", None),

    ("weather-context-refresh", "Weather Context Refresh",
     "Updates temperature/conditions in the unified snapshot every 30 min.",
     "autonomy", "app.tasks.autonomy.weather_context_refresh",
     "interval", None, 1800, {}, "low_priority", None),

    ("home-state-summary", "Home State Hourly Summary",
     "Aggregates HA events for pattern analysis, 5 min past each hour.",
     "autonomy", "app.tasks.autonomy.home_state_hourly_summary",
     "cron", "5 * * * *", None, {}, "low_priority", None),

    ("daily-autonomy-digest", "Daily Autonomy Digest",
     "Summary of agent runs and notifications at 9:40 PM.",
     "autonomy", "app.tasks.autonomy.daily_autonomy_digest",
     "cron", "40 21 * * *", None, {}, "low_priority", None),

    ("autonomy-retention-cleanup", "Autonomy Retention Cleanup",
     "Daily cleanup of old autonomy logs at 4 AM.",
     "autonomy", "app.tasks.autonomy.autonomy_retention_cleanup",
     "cron", "0 4 * * *", None, {}, "maintenance", None),

    ("mission-worker", "Mission Worker",
     "Advances runnable missions every 30 seconds.",
     "autonomy", "app.tasks.autonomy.mission_worker",
     "interval", None, 30, {}, "critical", 60),

    # ── PKG ────────────────────────────────────────────────────────
    ("pkg-midday-extract", "PKG Midday Extract",
     "Mines conversations for personal knowledge graph entries at 12 PM.",
     "pkg", "app.tasks.autonomy.pkg_deep_extract",
     "cron", "0 12 * * *", None, {"since_hours": 6}, "cognitive", None),

    ("pkg-evening-extract", "PKG Evening Extract",
     "Mines conversations for personal knowledge graph entries at 6 PM.",
     "pkg", "app.tasks.autonomy.pkg_deep_extract",
     "cron", "0 18 * * *", None, {"since_hours": 6}, "cognitive", None),

    ("pkg-reconciliation", "PKG Reconciliation",
     "Syncs Neo4j and pgvector shadow table hourly.",
     "pkg", "app.tasks.pkg_sync.reconcile_pkg",
     "interval", None, 3600, {}, "maintenance", 1800),

    # ── Email ──────────────────────────────────────────────────────
    ("email-sync", "Email Sync",
     "Fetches new emails from MS Graph every 3 minutes.",
     "email", "app.tasks.email_sync.sync_emails",
     "interval", None, 180, {}, "low_priority", 300),

    # ── Automation ─────────────────────────────────────────────────
    ("automation-watcher", "Automation Watcher",
     "Finds and dispatches due automation tasks every 30 seconds.",
     "automation", "app.tasks.automation.automation_watcher",
     "interval", None, 30, {}, "critical", 60),

    # ── Learning ───────────────────────────────────────────────────
    ("deep-research-poller", "Deep Research Poller",
     "Processes queued research jobs every 60 seconds.",
     "learning", "app.tasks.learning.deep_research_worker",
     "interval", None, 60, {}, "cognitive", 120),

    ("pending-source-fetcher", "Pending Source Fetcher",
     "Auto-fetches sources with fetch_status='pending' every 2 minutes.",
     "learning", "app.tasks.learning.fetch_pending_sources",
     "interval", None, 120, {}, "cognitive", 240),

    ("check-stuck-research", "Check Stuck Research",
     "Detects stuck research jobs every 3 minutes.",
     "learning", "app.tasks.research.check_stuck_research",
     "interval", None, 180, {}, "low_priority", 120),

    # ── ACS ────────────────────────────────────────────────────────
    ("acs-lifecycle-check", "ACS Lifecycle Check",
     "Manages ACS state transitions, cooldown expiry, and crash recovery every 2 minutes.",
     "acs", "app.tasks.acs.acs_lifecycle_check",
     "interval", None, 120, {}, "acs", 240),

    ("acs-interest-decay", "ACS Interest Decay",
     "Daily fascination decay on the interest graph at 3:30 AM.",
     "acs", "app.tasks.acs.acs_interest_decay",
     "cron", "30 3 * * *", None, {}, "cognitive", 3600),

    ("acs-daily-report", "ACS Daily Report",
     "Morning summary of yesterday's autonomous activity at 6 AM.",
     "acs", "app.tasks.acs.acs_daily_report",
     "cron", "0 6 * * *", None, {}, "cognitive", 3600),

    ("acs-morning-winddown", "ACS Morning Wind-down",
     "Stops sessions and consolidates before the morning plan, at 5 AM.",
     "acs", "app.tasks.acs.acs_morning_winddown",
     "cron", "0 5 * * *", None, {}, "acs", 3600),

    ("acs-daily-plan", "ACS Daily Plan",
     "Sara plans her day each morning at 7 AM.",
     "acs", "app.tasks.acs.acs_daily_plan",
     "cron", "0 7 * * *", None, {}, "cognitive", 3600),

    ("acs-periodic-auditor", "ACS Periodic Auditor",
     "Auditor LLM checks every 20 min whether active sessions are making meaningful progress.",
     "acs", "app.tasks.acs_auditor.periodic_audit_check",
     "interval", None, 1200, {}, "acs", 900),

    ("acs-daily-audit", "ACS Daily Audit",
     "End-of-day review of all ACS sessions at 8 PM. Stops ACS, generates feedback for tomorrow's plan.",
     "acs", "app.tasks.acs.acs_daily_audit",
     "cron", "0 20 * * *", None, {}, "cognitive", 3600),

    # ── Calendar / Cross-system ────────────────────────────────────
    ("calendar-prep-check", "Calendar Prep Check",
     "Checks upcoming events and sends prep notifications every 15 minutes.",
     "calendar", "app.tasks.calendar_prep.check_upcoming",
     "interval", None, 900, {}, "cognitive", 600),

    ("cross-system-synthesis", "Cross-System Synthesis",
     "Finds connections between email, calendar, and notes hourly.",
     "calendar", "app.tasks.calendar_prep.cross_system_check",
     "interval", None, 3600, {}, "low_priority", 1800),

    # ── Intelligence ───────────────────────────────────────────────
    ("predictive-engine", "Predictive Engine",
     "Pattern-based forward-looking suggestions every 30 min.",
     "intelligence", "app.tasks.intelligence.run_predictions",
     "interval", None, 1800, {}, "cognitive", 900),

    # ── Notifications ──────────────────────────────────────────────
    ("notification-tuner", "Notification Tuner",
     "Adjusts notification frequency based on engagement, daily 6:15 AM.",
     "notifications", "app.tasks.notification_tuner.tune_notifications",
     "cron", "15 6 * * *", None, {}, "maintenance", 3600),

    # ── Morning brief (NEW — replaces host crontab) ───────────────
    ("morning-brief-generate", "Morning Brief",
     "Generates the daily morning brief (news, weather, calendar, dream insights) and sends iOS push. Replaces the host crontab entry.",
     "morning_brief", "app.tasks.morning_brief.generate_morning_brief",
     "cron", "0 6 * * *", None, {}, "cognitive", 3600),

    # ── Daily Brief layer scheduler (formerly in-process loops) ───
    ("daily-brief-consolidate", "Daily Brief: Hourly Consolidation",
     "Hourly day-layer consolidation. Skips outside 8 AM–11 PM Eastern (the task self-skips).",
     "daily_brief", "app.tasks.inproc_schedulers.daily_brief_consolidate",
     "interval", None, 1800, {}, "cognitive", 1500),

    ("daily-brief-context-update", "Daily Brief: Context Layer Update",
     "Daily 11 PM context-layer update.",
     "daily_brief", "app.tasks.inproc_schedulers.daily_brief_context_update",
     "cron", "0 23 * * *", None, {}, "cognitive", 3600),

    ("daily-brief-archive", "Daily Brief: Day Layer Archive",
     "Midnight day-layer archival.",
     "daily_brief", "app.tasks.inproc_schedulers.daily_brief_archive",
     "cron", "0 0 * * *", None, {}, "maintenance", 3600),

    ("daily-brief-weekly-synthesis", "Daily Brief: Weekly Stable-Layer Synthesis",
     "Sunday 3 AM weekly synthesis of the stable layer.",
     "daily_brief", "app.tasks.inproc_schedulers.daily_brief_weekly_synthesis",
     "cron", "0 3 * * 0", None, {}, "cognitive", 3600),

    # ── Nightly Dream cycle (formerly in-process loop with Redis lock) ──
    ("nightly-dream-cycle", "Nightly Dream Cycle",
     "Memory consolidation 'dream' cycle at 2 AM Eastern. Processes yesterday's conversations and consolidates inbox items.",
     "autonomy", "app.tasks.inproc_schedulers.nightly_dream_cycle",
     "cron", "0 2 * * *", None, {}, "cognitive", 3600),

    # ── Notification pre-dispatch (formerly NotificationScheduler 5s loop) ──
    ("notification-predispatch", "Notification Pre-dispatch",
     "Finds timers/reminders due in the next ~20 seconds and sends their push notifications. Runs every 5 seconds.",
     "notifications", "app.tasks.inproc_schedulers.notification_predispatch",
     "interval", None, 5, {}, "critical", 30),
]


def upgrade():
    if not table_exists("scheduled_job"):
        op.create_table(
            "scheduled_job",
            sa.Column("key", sa.String(length=100), primary_key=True),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=False, server_default="general"),
            sa.Column("task_name", sa.String(length=255), nullable=False),
            sa.Column("schedule_kind", sa.String(length=20), nullable=False),  # "cron" | "interval"
            sa.Column("cron_expr", sa.String(length=255), nullable=True),
            sa.Column("interval_seconds", sa.Integer(), nullable=True),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="America/New_York"),
            sa.Column("args", JSONB(), nullable=False, server_default="[]"),
            sa.Column("kwargs", JSONB(), nullable=False, server_default="{}"),
            sa.Column("queue", sa.String(length=50), nullable=True),
            sa.Column("expires_seconds", sa.Integer(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("source", sa.String(length=20), nullable=False, server_default="system"),
            sa.Column("visibility", sa.String(length=20), nullable=False, server_default="system"),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_run_duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "(schedule_kind = 'cron' AND cron_expr IS NOT NULL) OR "
                "(schedule_kind = 'interval' AND interval_seconds IS NOT NULL)",
                name="ck_scheduled_job_schedule_consistent",
            ),
        )
        op.create_index("ix_scheduled_job_enabled", "scheduled_job", ["enabled"])
        op.create_index("ix_scheduled_job_category", "scheduled_job", ["category"])

    # Seed rows. Use ON CONFLICT DO NOTHING so re-running the migration after manual edits is safe.
    bind = op.get_bind()
    import json as _json
    for (key, display_name, description, category, task_name, schedule_kind,
         cron_expr, interval_seconds, kwargs, queue, expires_seconds) in SEED_JOBS:
        bind.execute(
            sa.text("""
                INSERT INTO scheduled_job (
                    key, display_name, description, category, task_name,
                    schedule_kind, cron_expr, interval_seconds, timezone,
                    args, kwargs, queue, expires_seconds,
                    enabled, editable, source
                ) VALUES (
                    :key, :display_name, :description, :category, :task_name,
                    :schedule_kind, :cron_expr, :interval_seconds, 'America/New_York',
                    '[]'::jsonb, CAST(:kwargs AS jsonb), :queue, :expires_seconds,
                    TRUE, TRUE, 'system'
                )
                ON CONFLICT (key) DO NOTHING
            """),
            {
                "key": key,
                "display_name": display_name,
                "description": description,
                "category": category,
                "task_name": task_name,
                "schedule_kind": schedule_kind,
                "cron_expr": cron_expr,
                "interval_seconds": interval_seconds,
                "kwargs": _json.dumps(kwargs or {}),
                "queue": queue,
                "expires_seconds": expires_seconds,
            },
        )

    # Promote user-facing rows out of the default 'system' visibility.
    if USER_FACING_KEYS:
        bind.execute(
            sa.text("UPDATE scheduled_job SET visibility = 'user' WHERE key = ANY(:keys)"),
            {"keys": list(USER_FACING_KEYS)},
        )


def downgrade():
    if table_exists("scheduled_job"):
        op.drop_index("ix_scheduled_job_category", "scheduled_job")
        op.drop_index("ix_scheduled_job_enabled", "scheduled_job")
        op.drop_table("scheduled_job")
