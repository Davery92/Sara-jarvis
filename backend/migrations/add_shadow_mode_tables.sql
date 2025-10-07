-- Shadow Mode Tables Migration
-- Time-boxed work capture with intelligent summaries

-- Main session table
CREATE TABLE IF NOT EXISTS shadow_session (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    device_id VARCHAR,

    status VARCHAR DEFAULT 'active',
    duration_minutes INTEGER,
    privacy_mode BOOLEAN DEFAULT false,

    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    paused_at TIMESTAMP WITH TIME ZONE,
    resumed_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,

    context VARCHAR,
    calendar_event_id VARCHAR REFERENCES event(id) ON DELETE SET NULL,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Event capture table
CREATE TABLE IF NOT EXISTS shadow_event (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id VARCHAR NOT NULL REFERENCES shadow_session(id) ON DELETE CASCADE,

    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    event_type VARCHAR NOT NULL,
    app_name VARCHAR,

    metadata JSONB,
    classified_as VARCHAR,
    tags JSONB DEFAULT '[]'::jsonb
);

-- User notes table
CREATE TABLE IF NOT EXISTS shadow_note (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id VARCHAR NOT NULL REFERENCES shadow_session(id) ON DELETE CASCADE,

    note_type VARCHAR NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR DEFAULT 'chat',

    due_date TIMESTAMP WITH TIME ZONE,
    priority VARCHAR,

    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Summary table
CREATE TABLE IF NOT EXISTS shadow_summary (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id VARCHAR NOT NULL UNIQUE REFERENCES shadow_session(id) ON DELETE CASCADE,

    decisions JSONB DEFAULT '[]'::jsonb,
    tasks JSONB DEFAULT '[]'::jsonb,
    questions JSONB DEFAULT '[]'::jsonb,
    ideas JSONB DEFAULT '[]'::jsonb,
    refs JSONB DEFAULT '[]'::jsonb,

    timeline JSONB DEFAULT '[]'::jsonb,
    changeset JSONB DEFAULT '{}'::jsonb,

    full_text TEXT,

    committed BOOLEAN DEFAULT false,
    committed_note_id VARCHAR REFERENCES note(id) ON DELETE SET NULL,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_shadow_session_user ON shadow_session(user_id);
CREATE INDEX IF NOT EXISTS idx_shadow_session_status ON shadow_session(status);
CREATE INDEX IF NOT EXISTS idx_shadow_session_started ON shadow_session(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_shadow_event_session ON shadow_event(session_id);
CREATE INDEX IF NOT EXISTS idx_shadow_event_timestamp ON shadow_event(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_event_type ON shadow_event(event_type);

CREATE INDEX IF NOT EXISTS idx_shadow_note_session ON shadow_note(session_id);
CREATE INDEX IF NOT EXISTS idx_shadow_note_type ON shadow_note(note_type);

CREATE INDEX IF NOT EXISTS idx_shadow_summary_session ON shadow_summary(session_id);
