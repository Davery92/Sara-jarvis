"""Create notification_preference table and seed health/fitness as disabled

Revision ID: 046_notification_preferences
Revises: 045_intelligence_items
Create Date: 2026-02-20

Adds:
- notification_preference table with per-user, per-category toggles and custom ban phrases
- Seeds default rows for the primary user with health/fitness disabled
"""
from alembic import op


revision = "046_notification_preferences"
down_revision = "045_intelligence_items"
branch_labels = None
depends_on = None

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS notification_preference (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            custom_ban_phrases JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_notification_preference_user_id
        ON notification_preference (user_id);
    """)

    # Unique constraint so we don't get duplicate rows per user+category
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_preference_user_category
        ON notification_preference (user_id, category);
    """)

    # Seed default preferences for the primary user
    # health and fitness are OFF by default; everything else is ON.
    for category, enabled in [
        ("health", False),
        ("fitness", False),
        ("calendar", True),
        ("email", True),
        ("security", True),
        ("home", True),
        ("general", True),
    ]:
        enabled_str = "TRUE" if enabled else "FALSE"
        op.execute(f"""
            INSERT INTO notification_preference (user_id, category, enabled, custom_ban_phrases)
            VALUES ('{DEFAULT_USER_ID}', '{category}', {enabled_str}, '[]'::jsonb)
            ON CONFLICT (user_id, category) DO NOTHING;
        """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS notification_preference;")
