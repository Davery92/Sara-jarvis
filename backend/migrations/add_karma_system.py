"""
Add karma system tables for Sara's cognitive architecture (Phase 2).

The karma system gives Sara and her sub-agents persistent internal stakes:
- Multi-dimensional performance tracking per agent
- Full history for trend analysis
- Configurable thresholds and decay mechanics
"""
import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# ==============================================
# Karma Agents Table
# ==============================================
# Agents being tracked in the karma system
cur.execute("""
    CREATE TABLE IF NOT EXISTS karma_agents (
        agent_id VARCHAR(50) PRIMARY KEY,
        agent_type VARCHAR(50) NOT NULL,
        display_name VARCHAR(100),
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE
    )
""")

# ==============================================
# Karma Dimensions Table
# ==============================================
# Different dimensions tracked per agent
cur.execute("""
    CREATE TABLE IF NOT EXISTS karma_dimensions (
        dimension_id SERIAL PRIMARY KEY,
        agent_id VARCHAR(50) REFERENCES karma_agents(agent_id) ON DELETE CASCADE,
        dimension_name VARCHAR(100) NOT NULL,
        description TEXT,
        weight FLOAT DEFAULT 1.0,
        UNIQUE(agent_id, dimension_name)
    )
""")

# ==============================================
# Karma Scores Table
# ==============================================
# Current karma scores (denormalized for fast access)
cur.execute("""
    CREATE TABLE IF NOT EXISTS karma_scores (
        score_id SERIAL PRIMARY KEY,
        agent_id VARCHAR(50) REFERENCES karma_agents(agent_id) ON DELETE CASCADE,
        dimension_name VARCHAR(100) NOT NULL,
        current_score FLOAT DEFAULT 50.0,
        trend FLOAT DEFAULT 0.0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(agent_id, dimension_name)
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_karma_scores_agent
    ON karma_scores(agent_id)
""")

# ==============================================
# Karma Events Table
# ==============================================
# Full karma history (append-only for auditing)
cur.execute("""
    CREATE TABLE IF NOT EXISTS karma_events (
        event_id SERIAL PRIMARY KEY,
        agent_id VARCHAR(50) REFERENCES karma_agents(agent_id) ON DELETE CASCADE,
        dimension_name VARCHAR(100) NOT NULL,
        delta FLOAT NOT NULL,
        new_score FLOAT NOT NULL,
        reason TEXT NOT NULL,
        evidence_type VARCHAR(50),
        evidence_ids JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_karma_events_agent_time
    ON karma_events(agent_id, created_at DESC)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_karma_events_dimension
    ON karma_events(agent_id, dimension_name, created_at DESC)
""")

# ==============================================
# Karma Configuration Table
# ==============================================
# Thresholds and configuration
cur.execute("""
    CREATE TABLE IF NOT EXISTS karma_config (
        config_key VARCHAR(100) PRIMARY KEY,
        config_value JSONB NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# ==============================================
# Insert Default Agents
# ==============================================
cur.execute("""
    INSERT INTO karma_agents (agent_id, agent_type, display_name, description)
    VALUES
        ('sara', 'primary', 'Sara', 'Primary cognitive agent - the main AI assistant'),
        ('consolidation', 'worker', 'Consolidation Agent', 'Compresses raw inputs into digestible context'),
        ('reflection', 'worker', 'Reflection Agent', 'Meta-cognitive auditing and self-improvement')
    ON CONFLICT (agent_id) DO NOTHING
""")

# ==============================================
# Insert Default Dimensions
# ==============================================
# Sara's dimensions
cur.execute("""
    INSERT INTO karma_dimensions (agent_id, dimension_name, description, weight)
    VALUES
        ('sara', 'helpfulness', 'Did actions/responses actually help?', 1.5),
        ('sara', 'proactivity', 'Anticipated needs vs just reacted', 1.0),
        ('sara', 'timing', 'Right information at the right time', 1.0),
        ('sara', 'calibration', 'Appropriate uncertainty when uncertain', 1.2),
        ('sara', 'accuracy', 'Factual correctness', 1.5)
    ON CONFLICT (agent_id, dimension_name) DO NOTHING
""")

# Consolidation agent dimensions
cur.execute("""
    INSERT INTO karma_dimensions (agent_id, dimension_name, description, weight)
    VALUES
        ('consolidation', 'accuracy', 'Kept what mattered, discarded what did not', 1.5),
        ('consolidation', 'compression_quality', 'Summaries preserved meaning', 1.2)
    ON CONFLICT (agent_id, dimension_name) DO NOTHING
""")

# Reflection agent dimensions
cur.execute("""
    INSERT INTO karma_dimensions (agent_id, dimension_name, description, weight)
    VALUES
        ('reflection', 'insight_quality', 'Observations lead to real improvements', 1.5),
        ('reflection', 'proposal_acceptance', 'Proposals are approved by David', 1.2),
        ('reflection', 'false_positive_rate', 'Flags real problems, not non-issues', 1.0)
    ON CONFLICT (agent_id, dimension_name) DO NOTHING
""")

# ==============================================
# Initialize Default Scores
# ==============================================
cur.execute("""
    INSERT INTO karma_scores (agent_id, dimension_name, current_score, trend)
    SELECT d.agent_id, d.dimension_name, 50.0, 0.0
    FROM karma_dimensions d
    ON CONFLICT (agent_id, dimension_name) DO NOTHING
""")

# ==============================================
# Insert Default Configuration
# ==============================================
cur.execute("""
    INSERT INTO karma_config (config_key, config_value)
    VALUES (
        'karma_settings',
        '{
            "thresholds": {
                "critical_low": 20,
                "low": 35,
                "neutral": 50,
                "good": 65,
                "excellent": 80
            },
            "decay": {
                "enabled": true,
                "rate_per_day": 1.0,
                "target": 50,
                "min_score_for_decay": 55,
                "max_score_for_recovery": 45
            },
            "trend_window_hours": 72,
            "alert_on_critical": true,
            "score_bounds": {
                "min": 0,
                "max": 100,
                "starting": 50
            },
            "delta_scaling": {
                "enabled": true,
                "positive_diminishing": true,
                "negative_diminishing": true
            }
        }'::jsonb
    )
    ON CONFLICT (config_key) DO NOTHING
""")

conn.commit()
cur.close()
conn.close()

print("✅ Karma system tables created successfully")
print("   - karma_agents (3 agents initialized)")
print("   - karma_dimensions (10 dimensions)")
print("   - karma_scores (initialized at 50)")
print("   - karma_events")
print("   - karma_config")
