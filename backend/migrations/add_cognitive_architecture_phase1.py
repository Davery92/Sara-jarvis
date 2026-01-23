"""
Add cognitive architecture Phase 1 tables for Sara.

This migration creates the database tables needed for:
- Consolidation run tracking
- Consolidation discard logging (for reflection auditing)
- Consolidation configuration storage
"""
import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# ==============================================
# Raw Buffer Statistics Table
# ==============================================
# Tracks aggregate statistics about raw buffer processing
cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_buffer_stats (
        id SERIAL PRIMARY KEY,
        stream_type VARCHAR(50) NOT NULL,
        window_start TIMESTAMP NOT NULL,
        window_end TIMESTAMP NOT NULL,
        entries_count INT NOT NULL DEFAULT 0,
        processed_count INT NOT NULL DEFAULT 0,
        discarded_count INT NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_raw_buffer_stats_stream_time
    ON raw_buffer_stats(stream_type, window_start DESC)
""")

# ==============================================
# Consolidation Run Tracking Table
# ==============================================
# Records each consolidation sweep for auditing
cur.execute("""
    CREATE TABLE IF NOT EXISTS consolidation_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,
        started_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP,
        window_start TIMESTAMP NOT NULL,
        window_end TIMESTAMP NOT NULL,
        raw_entries_processed INT DEFAULT 0,
        entries_kept INT DEFAULT 0,
        entries_discarded INT DEFAULT 0,
        status VARCHAR(20) DEFAULT 'running',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_consolidation_runs_user_time
    ON consolidation_runs(user_id, started_at DESC)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_consolidation_runs_status
    ON consolidation_runs(status)
""")

# ==============================================
# Consolidation Discards Table
# ==============================================
# Logs discarded entries for reflection agent auditing
cur.execute("""
    CREATE TABLE IF NOT EXISTS consolidation_discards (
        id SERIAL PRIMARY KEY,
        consolidation_run_id UUID REFERENCES consolidation_runs(id) ON DELETE CASCADE,
        raw_entry_id VARCHAR(255) NOT NULL,
        stream_type VARCHAR(50) NOT NULL,
        content_preview TEXT,
        relevance_score FLOAT,
        discard_reason VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_consolidation_discards_run
    ON consolidation_discards(consolidation_run_id)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_consolidation_discards_time
    ON consolidation_discards(created_at DESC)
""")

# ==============================================
# Consolidation Configuration Table
# ==============================================
# Stores modifiable consolidation settings (can be updated by reflection agent)
cur.execute("""
    CREATE TABLE IF NOT EXISTS consolidation_config (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        config_key VARCHAR(100) NOT NULL,
        config_value JSONB NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(50) DEFAULT 'system',
        UNIQUE(user_id, config_key)
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_consolidation_config_user
    ON consolidation_config(user_id)
""")

# ==============================================
# Working Memory Threads Table (optional persistence)
# ==============================================
# Persists conversation threads beyond Redis TTL for continuity
cur.execute("""
    CREATE TABLE IF NOT EXISTS working_memory_threads (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,
        thread_id VARCHAR(255) NOT NULL,
        topic VARCHAR(255),
        participants JSONB DEFAULT '[]',
        status VARCHAR(20) DEFAULT 'active',
        summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, thread_id)
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_wm_threads_user_status
    ON working_memory_threads(user_id, status)
""")

# ==============================================
# Pending Actions Table (optional persistence)
# ==============================================
# Persists pending actions beyond Redis TTL
cur.execute("""
    CREATE TABLE IF NOT EXISTS working_memory_actions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,
        action_type VARCHAR(50) NOT NULL,
        priority FLOAT DEFAULT 0.5,
        context TEXT,
        deadline TIMESTAMP,
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_wm_actions_user_status
    ON working_memory_actions(user_id, status)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_wm_actions_deadline
    ON working_memory_actions(deadline) WHERE deadline IS NOT NULL
""")

# ==============================================
# Insert default consolidation config
# ==============================================
cur.execute("""
    INSERT INTO consolidation_config (user_id, config_key, config_value, updated_by)
    VALUES (
        '64f37c56-85cb-4590-8de9-adfc17d343ed',
        'consolidation_settings',
        '{
            "window_seconds": 60,
            "grouping_threshold_ms": 5000,
            "relevance_threshold": 0.3,
            "priority_rules": [
                {"pattern": "source:user_message", "boost": 0.5},
                {"pattern": "source:notification", "boost": 0.3},
                {"pattern": "source:calendar", "boost": 0.4},
                {"pattern": "stream_type:text", "boost": 0.2}
            ],
            "context_modifiers": {
                "sleeping": {"relevance_threshold": 0.7},
                "working": {"relevance_threshold": 0.4}
            }
        }'::jsonb,
        'migration'
    )
    ON CONFLICT (user_id, config_key) DO NOTHING
""")

conn.commit()
cur.close()
conn.close()

print("✅ Cognitive architecture Phase 1 tables created successfully")
print("   - raw_buffer_stats")
print("   - consolidation_runs")
print("   - consolidation_discards")
print("   - consolidation_config")
print("   - working_memory_threads")
print("   - working_memory_actions")
