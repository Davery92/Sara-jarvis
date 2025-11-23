"""
Create Phase 4 Intelligence tables in the database
"""
import os
import sys
from sqlalchemy import create_engine, text

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

print(f"Connecting to: {DATABASE_URL}")

engine = create_engine(DATABASE_URL)

# SQL statements to create tables
create_tables_sql = """
-- Daily Briefings table
CREATE TABLE IF NOT EXISTS daily_briefings (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    briefing_type VARCHAR NOT NULL,
    briefing_date TIMESTAMP NOT NULL,
    content TEXT NOT NULL,
    delivered INTEGER DEFAULT 0,
    read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Briefing Settings table
CREATE TABLE IF NOT EXISTS briefing_settings (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL UNIQUE,
    morning_enabled INTEGER DEFAULT 1,
    morning_time VARCHAR DEFAULT '07:00:00',
    evening_enabled INTEGER DEFAULT 1,
    evening_time VARCHAR DEFAULT '21:00:00',
    include_recovery INTEGER DEFAULT 1,
    include_schedule INTEGER DEFAULT 1,
    include_goals INTEGER DEFAULT 1,
    include_suggestions INTEGER DEFAULT 1,
    include_workout_rec INTEGER DEFAULT 1,
    include_accomplishments INTEGER DEFAULT 1,
    include_insights INTEGER DEFAULT 1,
    include_reflection INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Context Modes table
CREATE TABLE IF NOT EXISTS context_modes (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL UNIQUE,
    current_mode VARCHAR DEFAULT 'full',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Intelligence Reports table
CREATE TABLE IF NOT EXISTS intelligence_reports (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    report_type VARCHAR NOT NULL,
    report_date TIMESTAMP NOT NULL,
    title VARCHAR NOT NULL,
    summary TEXT NOT NULL,
    full_content TEXT,
    key_insights TEXT,
    metrics TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Proactive Suggestions table
CREATE TABLE IF NOT EXISTS proactive_suggestions (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR NOT NULL,
    priority VARCHAR DEFAULT 'medium',
    confidence FLOAT NOT NULL,
    reasoning TEXT,
    related_patterns TEXT,
    status VARCHAR DEFAULT 'pending',
    actioned_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Detected Patterns table
CREATE TABLE IF NOT EXISTS detected_patterns (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    pattern_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    frequency VARCHAR,
    data_points INTEGER,
    evidence TEXT,
    related_episodes TEXT,
    first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_confirmed TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

try:
    with engine.connect() as conn:
        # Execute each statement
        for statement in create_tables_sql.strip().split(';'):
            if statement.strip():
                conn.execute(text(statement))
                conn.commit()

    print("✅ Phase 4 tables created successfully!")
    print("Created tables:")
    print("  - daily_briefings")
    print("  - briefing_settings")
    print("  - context_modes")
    print("  - intelligence_reports")
    print("  - proactive_suggestions")
    print("  - detected_patterns")

except Exception as e:
    print(f"❌ Error creating tables: {e}")
    sys.exit(1)
