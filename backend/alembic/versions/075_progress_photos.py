"""Progress photos — physique tracking with inline VLM critique.

Revision ID: 075_progress_photos
Revises: 074_interest_blocked
Create Date: 2026-07-01

Backs the iOS Fitness > Progress > Photos tab: uploaded body photos live in
MinIO (keyed by storage_key), metadata + on-demand vision-model critique live
here. See app/models/progress_photo.py and app/routes/progress_photos.py.
"""
from alembic import op


revision = "075_progress_photos"
down_revision = "074_interest_blocked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_photo (
          id VARCHAR PRIMARY KEY,
          user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          storage_key VARCHAR(500) NOT NULL,
          thumbnail_key VARCHAR(500),
          original_filename VARCHAR(500),
          mime_type VARCHAR(100),
          file_size INTEGER,
          width INTEGER,
          height INTEGER,
          taken_at TIMESTAMPTZ,
          notes TEXT,
          bodyweight DOUBLE PRECISION,
          bodyweight_unit VARCHAR(8) DEFAULT 'lbs',
          critique TEXT,
          critique_model VARCHAR(100),
          critiqued_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_progress_photo_user_created "
        "ON progress_photo (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_progress_photo_user_created")
    op.execute("DROP TABLE IF EXISTS progress_photo")
