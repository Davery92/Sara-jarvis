"""Enhance event_outbox for reliable Neo4j sync with retry logic

Revision ID: 015_enhance_event_outbox
Revises: d71da1536a56
Create Date: 2025-11-30

This migration adds:
1. event_type column - categorizes events (episode_created, note_created, etc.)
2. status column - tracks processing state (pending, processing, completed, failed)
3. retry_count and max_retries - exponential backoff retry support
4. last_error - stores error message for failed events
5. next_retry_at - scheduled retry time for exponential backoff
6. Indexes for efficient polling queries

These changes implement the transactional outbox pattern for guaranteed
Postgres -> Neo4j sync with eventual consistency.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '015_enhance_event_outbox'
down_revision = 'd71da1536a56'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to event_outbox

    # event_type: categorizes the event for routing to appropriate handler
    op.execute("""
        ALTER TABLE event_outbox
        ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) DEFAULT 'legacy';
    """)

    # status: tracks processing lifecycle
    op.execute("""
        ALTER TABLE event_outbox
        ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending' NOT NULL;
    """)

    # retry_count: number of retry attempts
    op.execute("""
        ALTER TABLE event_outbox
        ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0 NOT NULL;
    """)

    # max_retries: maximum retry attempts before marking as failed
    op.execute("""
        ALTER TABLE event_outbox
        ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 5 NOT NULL;
    """)

    # last_error: stores the last error message for debugging
    op.execute("""
        ALTER TABLE event_outbox
        ADD COLUMN IF NOT EXISTS last_error TEXT;
    """)

    # next_retry_at: scheduled time for next retry (exponential backoff)
    op.execute("""
        ALTER TABLE event_outbox
        ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
    """)

    # Update existing rows to have proper event_type based on aggregate_type
    op.execute("""
        UPDATE event_outbox
        SET event_type = LOWER(aggregate_type) || '_created'
        WHERE event_type = 'legacy' OR event_type IS NULL;
    """)

    # Make event_type NOT NULL after backfilling
    op.execute("""
        ALTER TABLE event_outbox
        ALTER COLUMN event_type SET NOT NULL;
    """)

    # Create indexes for efficient polling queries

    # Index for finding pending events to process
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_event_outbox_status_created
        ON event_outbox (status, created_at)
        WHERE status IN ('pending', 'processing');
    """)

    # Index for finding events ready for retry
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_event_outbox_retry
        ON event_outbox (next_retry_at)
        WHERE status = 'pending' AND retry_count > 0;
    """)

    # Index for event type filtering
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_event_outbox_event_type
        ON event_outbox (event_type);
    """)

    # Composite index for the main polling query
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_event_outbox_poll
        ON event_outbox (status, next_retry_at, created_at)
        WHERE status = 'pending';
    """)


def downgrade():
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_poll;")
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_event_type;")
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_retry;")
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_status_created;")

    # Drop columns
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS next_retry_at;")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS last_error;")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS max_retries;")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS retry_count;")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS status;")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS event_type;")
