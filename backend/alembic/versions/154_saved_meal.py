"""saved_meal — TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN_2026_09_18 Part B4.

A named snapshot of a logged meal's detailed_items David can re-log in one
tap ("Save as meal" on a diary section or the composer cart), plus an index
on food_log(user_id, logged_at DESC) — B1's `/food-log/last-used` and B2's
diary scan the same window repeatedly and both filter on exactly this pair.

Revision ID: 154_saved_meal
Revises: 153_chat_turn_trace
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "154_saved_meal"
down_revision = "153_chat_turn_trace"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS saved_meal (
            id                  VARCHAR(36) PRIMARY KEY,
            user_id             VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            name                VARCHAR(200) NOT NULL,
            default_meal_type   VARCHAR(20),
            -- Snapshot of detailed_items at save time — same v2 canonical
            -- shape food_log.detailed_items carries. A later edit/deletion
            -- of the underlying food doesn't change what this meal logs.
            items                JSONB NOT NULL DEFAULT '[]'::jsonb,
            archived_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_saved_meal_user_active
        ON saved_meal (user_id) WHERE archived_at IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_food_log_user_logged_at
        ON food_log (user_id, logged_at DESC)
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_food_log_user_logged_at"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_saved_meal_user_active"))
    bind.execute(sa.text("DROP TABLE IF EXISTS saved_meal"))
