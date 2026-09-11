"""Durable corrections — conversation competence plan Phase 3.

life_fact only ever encoded one correction shape: a stated schedule time.
"I removed it. Don't do that" or "Everett's appointment, not mine" had
nowhere durable to land, so nothing stopped Sara from repeating the mistake
next turn. This table is the general shape: a correction always names its
subject, what it supersedes, an explicit scope (a permanent fact is not the
same claim as "not attending this one"), and whether David said it outright
or it was inferred — never the assistant's own apology, which is not
evidence of anything David said.

Revision ID: 151_correction
Revises: 150_truth_maintenance_report
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "151_correction"
down_revision = "150_truth_maintenance_report"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS correction (
            id              BIGSERIAL PRIMARY KEY,
            user_id         VARCHAR(255) NOT NULL,
            -- factual_correction | event_attendance | preference | prohibition
            -- | retraction | temporary_exception
            correction_type VARCHAR(32) NOT NULL,
            -- what the correction is about: 'tool:food_search_and_log',
            -- 'calendar_event:<id>', 'person:Everett', a life_fact predicate, ...
            subject         VARCHAR(255) NOT NULL,
            predicate       VARCHAR(128),
            old_value       TEXT,
            new_value       TEXT,
            -- permanent | this_instance | interval (interval uses effective_until)
            scope           VARCHAR(32) NOT NULL DEFAULT 'permanent',
            effective_from  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_until TIMESTAMPTZ,
            superseded_ids  JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_turn     TEXT,
            explicit        BOOLEAN NOT NULL DEFAULT TRUE,
            active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_correction_user_subject
        ON correction (user_id, subject)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_correction_user_active
        ON correction (user_id, active)
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_correction_user_active"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_correction_user_subject"))
    bind.execute(sa.text("DROP TABLE IF EXISTS correction"))
