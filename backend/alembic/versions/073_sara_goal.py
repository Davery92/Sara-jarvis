"""Sara goal table — persistent intent for the ACS daemon.

Revision ID: 073_sara_goal
Revises: 072_research_brief
Create Date: 2026-06-11

A goal is the unit of Sara's autonomy: a multi-day commitment with a plan,
a progress trail, and artifacts. Focus (sara_focus) is what she's doing
*right now*; a goal is what she's working toward across thinks, restarts,
and days. David-created goals come from "Sara, go do X" — she decomposes
and advances them herself. Sara-created goals come from her own interests.

Idle thinks are prompted to advance an open goal (or say why not), which
replaces "notify David" as the default pressure valve for idle cognition.
"""
from alembic import op
import sqlalchemy as sa


revision = "073_sara_goal"
down_revision = "072_research_brief"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sara_goal (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          title TEXT NOT NULL,
          why TEXT,
          created_by VARCHAR(32) NOT NULL DEFAULT 'sara',
          status VARCHAR(20) NOT NULL DEFAULT 'open',
          plan JSONB NOT NULL DEFAULT '[]'::jsonb,
          progress JSONB NOT NULL DEFAULT '[]'::jsonb,
          artifacts JSONB NOT NULL DEFAULT '[]'::jsonb,
          outcome TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          last_progress_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sara_goal_status "
        "ON sara_goal (status, last_progress_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sara_goal")
