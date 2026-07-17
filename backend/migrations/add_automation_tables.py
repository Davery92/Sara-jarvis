#!/usr/bin/env python3
"""
Migration script to create automation system tables.

Run with: python migrations/add_automation_tables.py

Creates:
- automation_task: Main task definitions
- automation_execution_log: Execution history
- automation_state_store: Key-value state tracking
- registered_endpoint: Allowlisted HTTP endpoints
"""
import os
import sys
from datetime import datetime

# Add the backend directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.config import settings


def get_database_url():
    """Get database URL from settings."""
    return settings.database_url


def run_migration():
    """Create automation tables."""
    database_url = get_database_url()
    print(f"Connecting to database...")

    # Use sync driver for migration
    if "postgresql+asyncpg" in database_url:
        database_url = database_url.replace("postgresql+asyncpg", "postgresql")
    elif "postgresql+psycopg" in database_url:
        database_url = database_url.replace("postgresql+psycopg", "postgresql")

    engine = create_engine(database_url)

    with engine.connect() as conn:
        # Check if tables already exist
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'automation_task'
        """))
        if result.fetchone():
            print("⚠️  automation_task table already exists, skipping creation")
            print("    Run with --force to drop and recreate")
            if len(sys.argv) > 1 and sys.argv[1] == "--force":
                print("🗑️  Dropping existing tables...")
                conn.execute(text("DROP TABLE IF EXISTS automation_execution_log CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS automation_state_store CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS automation_task CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS registered_endpoint CASCADE"))
                conn.commit()
            else:
                return

        print("Creating automation_task table...")
        conn.execute(text("""
            CREATE TABLE automation_task (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,

                -- Definition
                name VARCHAR(255) NOT NULL,
                original_intent TEXT NOT NULL,
                description TEXT,

                -- Schedule (JSONB)
                schedule_definition JSONB NOT NULL,

                -- Actions (JSONB array)
                actions JSONB NOT NULL,

                -- Conditions (JSONB array)
                conditions JSONB DEFAULT '[]'::jsonb,

                -- Status
                status VARCHAR(20) NOT NULL DEFAULT 'pending_confirmation',

                -- Wake-up scheduling
                next_wake_at TIMESTAMPTZ,
                current_step INTEGER DEFAULT 0,
                step_state JSONB DEFAULT '{}'::jsonb,

                -- Safety limits
                expires_at TIMESTAMPTZ,
                max_executions INTEGER,
                execution_count INTEGER DEFAULT 0,
                consecutive_errors INTEGER DEFAULT 0,
                last_error TEXT,

                -- Audit
                created_at TIMESTAMPTZ DEFAULT NOW(),
                confirmed_at TIMESTAMPTZ,
                last_executed_at TIMESTAMPTZ
            )
        """))

        print("Creating automation_task indexes...")
        conn.execute(text("""
            CREATE INDEX idx_automation_task_user_id ON automation_task(user_id);
            CREATE INDEX idx_automation_task_status ON automation_task(status);
            CREATE INDEX idx_automation_task_next_wake ON automation_task(next_wake_at, status);
            CREATE INDEX idx_automation_task_user_status ON automation_task(user_id, status);
        """))

        print("Creating automation_execution_log table...")
        conn.execute(text("""
            CREATE TABLE automation_execution_log (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR NOT NULL REFERENCES automation_task(id) ON DELETE CASCADE,

                -- Timing
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,

                -- Execution details
                step_executed INTEGER NOT NULL,
                action_primitive VARCHAR(50) NOT NULL,
                action_details JSONB,

                -- Result
                status VARCHAR(20) NOT NULL,
                result JSONB,
                error_message TEXT
            )
        """))

        print("Creating automation_execution_log indexes...")
        conn.execute(text("""
            CREATE INDEX idx_automation_log_task_started
                ON automation_execution_log(task_id, started_at DESC);
        """))

        print("Creating automation_state_store table...")
        conn.execute(text("""
            CREATE TABLE automation_state_store (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR NOT NULL REFERENCES automation_task(id) ON DELETE CASCADE,

                key VARCHAR(255) NOT NULL,
                value JSONB,
                previous_value JSONB,

                updated_at TIMESTAMPTZ DEFAULT NOW(),

                CONSTRAINT uq_automation_state_task_key UNIQUE (task_id, key)
            )
        """))

        print("Creating automation_state_store indexes...")
        conn.execute(text("""
            CREATE INDEX idx_automation_state_task_id ON automation_state_store(task_id);
        """))

        print("Creating registered_endpoint table...")
        conn.execute(text("""
            CREATE TABLE registered_endpoint (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,

                -- Connection
                base_url VARCHAR(500) NOT NULL,

                -- Authentication
                auth_type VARCHAR(20) NOT NULL DEFAULT 'none',
                auth_header VARCHAR(100),
                auth_secret_env VARCHAR(100),

                -- Rate limiting
                rate_limit_per_minute INTEGER DEFAULT 60,

                -- Restrictions
                allowed_paths JSONB DEFAULT '[]'::jsonb,
                allowed_methods JSONB DEFAULT '["GET"]'::jsonb,

                -- Status
                is_active BOOLEAN DEFAULT TRUE,

                -- Audit
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        conn.commit()
        print("✅ All automation tables created successfully!")

        # Verify tables
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('automation_task', 'automation_execution_log',
                              'automation_state_store', 'registered_endpoint')
            ORDER BY table_name
        """))
        tables = [row[0] for row in result.fetchall()]
        print(f"✅ Verified tables: {', '.join(tables)}")


if __name__ == "__main__":
    run_migration()
