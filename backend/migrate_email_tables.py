#!/usr/bin/env python3
"""
Migration script to create email tables for Microsoft Graph integration.
Run this script to create the email, email_attachment, and email_sync_state tables.
"""

import os
import sys

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)

def run_migration():
    """Create email tables."""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Create email table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS email (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                mailbox VARCHAR NOT NULL,
                conversation_id VARCHAR,
                subject VARCHAR NOT NULL,
                sender_email VARCHAR NOT NULL,
                sender_name VARCHAR,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL,
                importance VARCHAR DEFAULT 'normal',
                is_read BOOLEAN DEFAULT FALSE,
                internet_message_id VARCHAR,
                parent_folder_id VARCHAR,
                body_preview TEXT,
                body_text TEXT,
                body_html TEXT,
                to_recipients JSONB DEFAULT '[]',
                cc_recipients JSONB DEFAULT '[]',
                category VARCHAR,
                importance_score FLOAT DEFAULT 0.0,
                summary TEXT,
                action_required BOOLEAN DEFAULT FALSE,
                analyzed_at TIMESTAMP WITH TIME ZONE,
                notification_sent BOOLEAN DEFAULT FALSE,
                notification_sent_at TIMESTAMP WITH TIME ZONE,
                synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("Created email table")

        # Create indexes for email table
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_user_id ON email(user_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_mailbox ON email(mailbox)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_received_at ON email(received_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_sender_email ON email(sender_email)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_category ON email(category)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_conversation_id ON email(conversation_id)
        """))
        print("Created email indexes")

        # Create email_attachment table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS email_attachment (
                id VARCHAR PRIMARY KEY,
                email_id VARCHAR NOT NULL REFERENCES email(id) ON DELETE CASCADE,
                filename VARCHAR NOT NULL,
                content_type VARCHAR,
                size INTEGER DEFAULT 0,
                is_inline BOOLEAN DEFAULT FALSE,
                content_id VARCHAR,
                minio_bucket VARCHAR,
                minio_key VARCHAR,
                is_riskninja_relevant BOOLEAN DEFAULT FALSE,
                downloaded_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("Created email_attachment table")

        # Create indexes for email_attachment table
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_attachment_email_id ON email_attachment(email_id)
        """))
        print("Created email_attachment indexes")

        # Create email_sync_state table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS email_sync_state (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                mailbox VARCHAR NOT NULL,
                last_sync_at TIMESTAMP WITH TIME ZONE,
                last_sync_count INTEGER DEFAULT 0,
                last_sync_errors INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("Created email_sync_state table")

        # Create indexes for email_sync_state table
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_sync_state_user_mailbox ON email_sync_state(user_id, mailbox)
        """))
        print("Created email_sync_state indexes")

        conn.commit()
        print("\nMigration completed successfully!")


if __name__ == "__main__":
    run_migration()
