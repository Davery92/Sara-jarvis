"""Nightly research brief table + scheduled job.

Adds the `research_brief` table (mirrors `morning_brief`) and registers a
nightly Celery job at 2 AM ET that fetches arXiv/HF/Interconnects feeds,
synthesizes them into a long-form report, and renders TTS audio.

Revision ID: 072_research_brief
Revises: 071_ios_event_block
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "072_research_brief"
down_revision = "071_ios_event_block"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "research_brief" not in insp.get_table_names():
        op.create_table(
            "research_brief",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("brief_date", sa.String(length=10), nullable=False),
            sa.Column("full_text", sa.Text(), nullable=True),
            sa.Column("audio_path", sa.Text(), nullable=True),
            sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
            sa.Column("sources", JSONB(), nullable=True),
            sa.Column("paper_count", sa.Integer(), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "brief_date", name="uq_research_brief_user_date"),
        )
        op.create_index("ix_research_brief_user_date", "research_brief", ["user_id", "brief_date"])

    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'research-brief-generate',
                'Nightly Research Brief',
                'Fetches arXiv cs.LG/cs.AI, Hugging Face Daily Papers, and Interconnects AI, then synthesizes a long-form research briefing with TTS audio. Runs at 2 AM ET so fresh arXiv feeds are available and audio is ready before the 6 AM morning brief.',
                'research_brief',
                'app.tasks.research_brief.generate_research_brief',
                'cron', '0 2 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 3600,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'research-brief-generate'"))
    op.drop_index("ix_research_brief_user_date", table_name="research_brief")
    op.drop_table("research_brief")
