"""Person table — the people layer (PHENOMENAL_ASSISTANT_PLAN.md Phase 2).

Revision ID: 077_person_table
Revises: 076_system_awareness_tables
Create Date: 2026-07-02

relationship_state turned out to be Sara<->David phase tracking, not people.
PKG has PKG_Person nodes (semantic/fact layer) but nothing interactional.
This is the smallest real person store, fed by live sources that already
flow (email sync, chat mentions): who David actually talks to, how often,
and when he last did. Postgres is source of truth for interaction state;
pkg_person_ref links back to the semantic/fact layer.

See app/models/person.py, app/tasks/email_sync.py, app/services/pkg_extractor.py.
"""
from alembic import op


revision = "077_person_table"
down_revision = "076_system_awareness_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS person (
            id                     varchar PRIMARY KEY,
            user_id                varchar NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            canonical_name         varchar(255) NOT NULL,
            emails                 jsonb NOT NULL DEFAULT '[]'::jsonb,
            aliases                jsonb NOT NULL DEFAULT '[]'::jsonb,
            pkg_person_ref         varchar,
            first_seen_at          timestamptz NOT NULL DEFAULT now(),
            last_interaction_at    timestamptz,
            last_interaction_kind  varchar(32),
            interaction_count      integer NOT NULL DEFAULT 0,
            mention_count          integer NOT NULL DEFAULT 0,
            importance             double precision NOT NULL DEFAULT 0.5,
            is_vip                 boolean NOT NULL DEFAULT false,
            muted                  boolean NOT NULL DEFAULT false,
            notes                  text,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),
            UNIQUE (user_id, canonical_name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_person_user_id ON person (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_person_emails ON person USING GIN (emails)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_person_last_interaction "
        "ON person (user_id, last_interaction_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_person_last_interaction")
    op.execute("DROP INDEX IF EXISTS ix_person_emails")
    op.execute("DROP INDEX IF EXISTS ix_person_user_id")
    op.execute("DROP TABLE IF EXISTS person")
