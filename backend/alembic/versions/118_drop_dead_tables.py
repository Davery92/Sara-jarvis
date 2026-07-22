"""Drop confirmed-dead tables (audit D6 / §4.3) — conservative pass.

Only tables that are ALL of: empty (0 rows, live-verified), named in the audit's
dead-sets, have NO code writer (no INSERT / no __tablename__ model), and have NO
inbound foreign key. Excludes the temerant_* family (audit said empty+no-writers,
but live check found rows + an llm_broker reference — left intact) and fitness_plan
(referenced by the active `workout` table). A full pg_dump was taken beforehand.

Tables WITH writers (insight_nudge, intelligence_report(s), autonomous_insight,
goal, goal_progress, daily_reflections, reflection_hypotheses, shadow_screenshot)
are deliberately NOT dropped here — they need coordinated reader/writer code
removal first.

Revision ID: 118_drop_dead_tables
Revises: 117_dreams_readiness_trust
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "118_drop_dead_tables"
down_revision = "117_dreams_readiness_trust"
branch_labels = None
depends_on = None


_DROP = [
    # abandoned insight/suggestion graveyard (no writers)
    "contextual_insight", "proactive_suggestion", "proactive_suggestions",
    # dead memory-stack experiment
    "memory_vector", "memory_hot", "memory_references",
    # earlier working-memory attempts that nothing read (the §3.1 lesson)
    "working_memory_threads", "working_memory_actions",
    # orphaned analytics
    "pattern_evidence", "activity_state_log", "karma_events",
    # triplicate / duplicate generations (keep the populated ones)
    "daily_briefing", "daily_reflection", "workout_sessions",
    # superseded fitness/goal sprawl (no writers, no inbound FK)
    "goal_milestone", "fitness_goal", "fitness_episode", "fitness_event",
    "fitness_profile", "fitness_progression_rule", "fitness_onboarding_sessions",
]


def upgrade():
    bind = op.get_bind()
    for t in _DROP:
        # Guarded: only drop if it still exists and is still empty (belt-and-braces
        # against anything having started writing since the audit).
        exists = bind.execute(sa.text("SELECT to_regclass('public.'||:t)"), {"t": t}).scalar()
        if not exists:
            continue
        n = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        if n and n > 0:
            # Something wrote to it after the audit — do NOT drop; leave for review.
            continue
        op.execute(f'DROP TABLE IF EXISTS "{t}"')


def downgrade():
    # These were empty dead tables; schema not restored here (full pg_dump exists
    # from the pre-cleanup backup if a stub is ever needed).
    pass
