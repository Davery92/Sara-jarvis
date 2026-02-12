"""
Add Soul Layer and Heartbeat system tables.

SOUL LAYER:
Sara's persistent identity document - who she is, how she operates, where she's growing.
Sara can propose changes to her Soul, but they require David's approval.

HEARTBEAT:
A dynamic watchlist that the subconscious worker reads. Contains monitors, time-bound items,
and conditional triggers that Sara or David can add/remove.
"""
import psycopg
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# ==============================================
# SOUL LAYER TABLES
# ==============================================

# Sara's Soul - her core identity document
cur.execute("""
    CREATE TABLE IF NOT EXISTS sara_soul (
        id SERIAL PRIMARY KEY,
        section VARCHAR(50) NOT NULL,  -- identity, principles, boundaries, growth, evolution_log
        content TEXT NOT NULL,
        version INT DEFAULT 1,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(50) NOT NULL,  -- sara, david, sara_approved_by_david
        UNIQUE(section)
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_sara_soul_section
    ON sara_soul(section)
""")

# Soul change proposals - Sara's proposed modifications awaiting approval
cur.execute("""
    CREATE TABLE IF NOT EXISTS soul_change_proposals (
        id SERIAL PRIMARY KEY,
        section VARCHAR(50) NOT NULL,
        current_content TEXT,
        proposed_content TEXT NOT NULL,
        rationale TEXT NOT NULL,  -- Why Sara wants to change this
        status VARCHAR(20) DEFAULT 'pending',  -- pending, approved, rejected
        rejection_reason TEXT,  -- If rejected, why
        proposed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP WITH TIME ZONE,
        resolved_by VARCHAR(50)  -- david (manual) or system (auto-approved)
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_soul_proposals_status
    ON soul_change_proposals(status)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_soul_proposals_section
    ON soul_change_proposals(section)
""")

# ==============================================
# HEARTBEAT TABLES
# ==============================================

# Dynamic watchlist items
cur.execute("""
    CREATE TABLE IF NOT EXISTS heartbeat_items (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        item_type VARCHAR(20) NOT NULL,  -- monitor, time_bound, conditional
        description TEXT NOT NULL,  -- Human-readable description
        check_logic VARCHAR(50) NOT NULL,  -- How to evaluate: background_tasks, meal_logging, home_assistant, reminder, hrv_threshold, conversation_gap, custom

        -- For time-bound items
        expires_at TIMESTAMP WITH TIME ZONE,

        -- For conditional items
        condition TEXT,  -- e.g., "hrv < 40", "hours_since_conversation > 8"

        -- Extra configuration (JSON)
        config JSONB DEFAULT '{}',

        -- Metadata
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(50) NOT NULL,  -- david, sara
        source_context TEXT,  -- What conversation spawned this

        -- Tracking
        last_checked_at TIMESTAMP WITH TIME ZONE,
        last_triggered_at TIMESTAMP WITH TIME ZONE,
        times_checked INT DEFAULT 0,
        times_triggered INT DEFAULT 0,

        -- State
        is_active BOOLEAN DEFAULT TRUE,

        -- Notification settings
        notification_channel VARCHAR(20) DEFAULT 'both',  -- ios_push, context, both
        priority VARCHAR(10) DEFAULT 'normal'  -- low, normal, high
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_heartbeat_items_user
    ON heartbeat_items(user_id)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_heartbeat_items_active
    ON heartbeat_items(user_id, is_active)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_heartbeat_items_type
    ON heartbeat_items(item_type)
""")

# Heartbeat run logs
cur.execute("""
    CREATE TABLE IF NOT EXISTS heartbeat_logs (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        run_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        items_checked INT DEFAULT 0,
        items_triggered INT DEFAULT 0,
        triggered_item_ids INT[],  -- Array of item IDs that triggered
        actions_taken JSONB DEFAULT '[]',  -- What Sara did
        notification_sent BOOLEAN DEFAULT FALSE,
        run_duration_ms INT,  -- How long the check took
        error_message TEXT  -- If something went wrong
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_heartbeat_logs_user
    ON heartbeat_logs(user_id)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_heartbeat_logs_run_at
    ON heartbeat_logs(run_at DESC)
""")

# ==============================================
# COMMIT CHANGES
# ==============================================
conn.commit()
cur.close()
conn.close()

print("✅ Soul Layer and Heartbeat tables created successfully")
