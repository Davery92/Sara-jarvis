"""
Migration: Add activity state and interruptibility columns to subconscious_state table.
Also creates notification_queue table for deferred notifications.

Run: python3 backend/migrations/add_activity_state.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)


def run_migration():
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        # Add activity state columns to subconscious_state
        columns_to_add = [
            ("activity_state", "VARCHAR(50)"),
            ("activity_confidence", "FLOAT"),
            ("activity_reason", "TEXT"),
            ("activity_room", "VARCHAR(100)"),
            ("interruptibility_score", "FLOAT"),
            ("interruptibility_channel", "VARCHAR(20)"),
        ]

        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(
                    f"ALTER TABLE subconscious_state ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                print(f"  Added column: subconscious_state.{col_name} ({col_type})")
            except Exception as e:
                print(f"  Column {col_name} may already exist: {e}")

        # Create notification_queue table for deferred notifications
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_queue (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                title VARCHAR(500) NOT NULL,
                message TEXT,
                urgency VARCHAR(20) NOT NULL DEFAULT 'normal',
                category VARCHAR(50) NOT NULL DEFAULT 'general',
                topic VARCHAR(500),
                source VARCHAR(100) DEFAULT 'system',
                queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                deliver_by TIMESTAMPTZ,
                delivered_at TIMESTAMPTZ,
                was_delivered BOOLEAN DEFAULT FALSE,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        print("  Created table: notification_queue")

        # Create activity_state_log for historical tracking
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS activity_state_log (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                activity_state VARCHAR(50) NOT NULL,
                confidence FLOAT,
                reason TEXT,
                room VARCHAR(100),
                interruptibility_score FLOAT,
                signals JSONB DEFAULT '[]',
                logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        print("  Created table: activity_state_log")

        # Index for efficient lookups
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_activity_state_log_user_time
            ON activity_state_log (user_id, logged_at DESC)
        """))
        print("  Created index: idx_activity_state_log_user_time")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_notification_queue_user_pending
            ON notification_queue (user_id, was_delivered, deliver_by)
            WHERE was_delivered = FALSE
        """))
        print("  Created index: idx_notification_queue_user_pending")

    print("\nMigration complete: activity_state + interruptibility")


if __name__ == "__main__":
    run_migration()
