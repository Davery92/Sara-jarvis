"""
Add behavioral_pattern table for Sara's proactive autonomy system.

Behavioral patterns capture recurring user behaviors that Sara can learn
and proactively suggest. For example:
- "Turn heat on when temperature drops below 20°F"
- "User usually works out on Monday/Wednesday/Friday"
- "User checks email first thing in the morning"

Patterns have a lifecycle: learning → active → suggested → confirmed/rejected → dormant
"""
import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# ==============================================
# Behavioral Pattern Table
# ==============================================
cur.execute("""
    CREATE TABLE IF NOT EXISTS behavioral_pattern (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,

        -- What triggers this pattern
        trigger_type VARCHAR(50) NOT NULL,  -- weather, time, day_of_week, after_event, location, composite
        trigger_conditions JSONB NOT NULL,  -- {"temp_below_f": 20} or {"time": "09:00", "days": ["Mon"]}

        -- What action this pattern suggests
        action_type VARCHAR(50) NOT NULL,   -- automation, reminder, suggestion, question
        action_payload JSONB NOT NULL,      -- {"automation_id": "xxx"} or {"message": "..."}

        -- Pattern metadata
        description TEXT,                   -- Human-readable: "Turn heat on when cold"
        source_context TEXT,                -- How Sara discovered this
        category VARCHAR(50),               -- fitness, home, work, health, communication, etc.

        -- Evidence & confidence
        evidence_dates DATE[] DEFAULT '{}', -- Days this pattern was observed
        evidence_count INT DEFAULT 0,       -- Number of observations
        confidence FLOAT DEFAULT 0.0,       -- 0-1, increases with more evidence
        min_occurrences INT DEFAULT 2,      -- How many times before pattern is actionable

        -- Lifecycle
        status VARCHAR(20) DEFAULT 'learning',  -- learning, active, suggested, confirmed, rejected, dormant
        times_suggested INT DEFAULT 0,
        times_accepted INT DEFAULT 0,
        times_rejected INT DEFAULT 0,
        last_triggered_at TIMESTAMP,
        last_suggested_at TIMESTAMP,
        last_accepted_at TIMESTAMP,
        user_feedback TEXT,                 -- If user said "don't suggest this anymore"

        -- Scheduling
        suggestion_window_start TIME DEFAULT '08:00',  -- When to suggest (e.g., 09:00)
        suggestion_window_end TIME DEFAULT '21:00',    -- Don't suggest after this
        cooldown_hours INT DEFAULT 24,                  -- Don't re-suggest within this window

        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Index for finding active patterns for a user
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_behavioral_pattern_user_status
    ON behavioral_pattern(user_id, status)
""")

# Index for finding patterns by trigger type
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_behavioral_pattern_trigger
    ON behavioral_pattern(trigger_type, status)
""")

# Index for finding patterns by category
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_behavioral_pattern_category
    ON behavioral_pattern(user_id, category, status)
""")

# ==============================================
# Pattern Suggestion Log Table
# ==============================================
# Track when patterns were suggested and the outcome
cur.execute("""
    CREATE TABLE IF NOT EXISTS pattern_suggestion_log (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        pattern_id UUID REFERENCES behavioral_pattern(id) ON DELETE CASCADE,
        user_id VARCHAR(255) NOT NULL,

        -- Suggestion context
        trigger_context JSONB,              -- What triggered the suggestion (weather data, time, etc.)
        message_sent TEXT,                  -- The actual message Sara sent

        -- Outcome
        outcome VARCHAR(20),                -- accepted, rejected, ignored, expired
        user_response TEXT,                 -- What user said in response
        action_taken BOOLEAN DEFAULT FALSE, -- Did the action actually execute

        -- Timestamps
        suggested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        responded_at TIMESTAMP,
        expires_at TIMESTAMP                -- Suggestion expires if not responded to
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_pattern_suggestion_log_pattern
    ON pattern_suggestion_log(pattern_id, suggested_at DESC)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_pattern_suggestion_log_user
    ON pattern_suggestion_log(user_id, suggested_at DESC)
""")

# ==============================================
# Day Replay Cache Table
# ==============================================
# Cache the full day replay for pattern detection
cur.execute("""
    CREATE TABLE IF NOT EXISTS day_replay_cache (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,
        replay_date DATE NOT NULL,

        -- Aggregated data
        replay_data JSONB NOT NULL,         -- Full structured replay
        summary TEXT,                        -- LLM-generated summary

        -- Metadata
        data_sources TEXT[],                 -- Which sources were included
        episode_count INT DEFAULT 0,
        automation_count INT DEFAULT 0,

        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(user_id, replay_date)
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_day_replay_cache_lookup
    ON day_replay_cache(user_id, replay_date DESC)
""")

conn.commit()
cur.close()
conn.close()

print("✅ Behavioral patterns migration complete!")
print("   - behavioral_pattern: Pattern storage with triggers and actions")
print("   - pattern_suggestion_log: Track suggestions and outcomes")
print("   - day_replay_cache: Cache full day replays for analysis")
