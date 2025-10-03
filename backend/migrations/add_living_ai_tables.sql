-- Migration: Add Living AI Assistant Tables
-- Date: 2025-10-03
-- Description: Adds conversation threading, achievements, and supporting tables

-- Conversation Threading
CREATE TABLE IF NOT EXISTS conversation_thread (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    title VARCHAR NOT NULL,
    summary TEXT,
    auto_generated BOOLEAN DEFAULT false,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    message_count INTEGER DEFAULT 0,
    tags TEXT[],
    archived BOOLEAN DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_thread_user_activity ON conversation_thread(user_id, last_activity DESC);
CREATE INDEX IF NOT EXISTS idx_thread_tags ON conversation_thread USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_thread_archived ON conversation_thread(user_id, archived);

-- Episode to Thread Mapping
CREATE TABLE IF NOT EXISTS episode_thread_mapping (
    episode_id VARCHAR REFERENCES episode(id) ON DELETE CASCADE,
    thread_id VARCHAR REFERENCES conversation_thread(id) ON DELETE CASCADE,
    PRIMARY KEY (episode_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_episode_thread ON episode_thread_mapping(thread_id);

-- Achievements
CREATE TABLE IF NOT EXISTS achievement (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT,
    icon VARCHAR,
    earned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    celebrated BOOLEAN DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_achievement_user ON achievement(user_id, earned_at DESC);
CREATE INDEX IF NOT EXISTS idx_achievement_type ON achievement(user_id, type);
CREATE INDEX IF NOT EXISTS idx_achievement_celebrated ON achievement(user_id, celebrated) WHERE celebrated = false;

-- Contextual Insights
CREATE TABLE IF NOT EXISTS contextual_insight (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 5,
    related_entities JSONB,
    action_suggestions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    dismissed_at TIMESTAMP WITH TIME ZONE,
    user_feedback VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_insight_user_priority ON contextual_insight(user_id, priority DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_insight_active ON contextual_insight(user_id, delivered_at) WHERE dismissed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_insight_type ON contextual_insight(user_id, type);

-- User Patterns (for learning and adaptation)
CREATE TABLE IF NOT EXISTS user_pattern (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    pattern_type VARCHAR NOT NULL,
    pattern_data JSONB NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_validated TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_pattern_user_type ON user_pattern(user_id, pattern_type);
CREATE INDEX IF NOT EXISTS idx_pattern_confidence ON user_pattern(user_id, confidence DESC);

-- Projects (for project intelligence)
CREATE TABLE IF NOT EXISTS project (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    description TEXT,
    auto_detected BOOLEAN DEFAULT false,
    status VARCHAR DEFAULT 'active',
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    tags TEXT[],
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_project_user_status ON project(user_id, status);
CREATE INDEX IF NOT EXISTS idx_project_tags ON project USING GIN(tags);

-- Project Entity Links
CREATE TABLE IF NOT EXISTS project_entity_link (
    project_id VARCHAR REFERENCES project(id) ON DELETE CASCADE,
    entity_type VARCHAR NOT NULL,
    entity_id VARCHAR NOT NULL,
    relevance_score FLOAT DEFAULT 1.0,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (project_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_project_entity ON project_entity_link(project_id, relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_entity_project ON project_entity_link(entity_type, entity_id);

-- User Relationship (rapport system)
CREATE TABLE IF NOT EXISTS user_relationship (
    user_id VARCHAR PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
    relationship_score FLOAT DEFAULT 0.0,
    days_together INTEGER DEFAULT 0,
    total_conversations INTEGER DEFAULT 0,
    bugs_solved_together INTEGER DEFAULT 0,
    notes_created_together INTEGER DEFAULT 0,
    shared_milestones JSONB,
    inside_references JSONB,
    last_interaction TIMESTAMP WITH TIME ZONE
);

-- Add comment for documentation
COMMENT ON TABLE conversation_thread IS 'Stores conversation threading for organized chat history';
COMMENT ON TABLE achievement IS 'User achievements for gamification and rapport building';
COMMENT ON TABLE contextual_insight IS 'AI-generated contextual insights and suggestions';
COMMENT ON TABLE user_pattern IS 'Learned user behavior patterns';
COMMENT ON TABLE project IS 'Auto-detected or manual projects';
COMMENT ON TABLE user_relationship IS 'User-AI rapport and relationship tracking';
