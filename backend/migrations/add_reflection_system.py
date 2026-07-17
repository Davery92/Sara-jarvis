"""
Add reflection system tables for Sara's cognitive architecture (Phase 3).

The reflection system provides meta-cognitive auditing and self-improvement:
- Observations tracking (consolidation audits, action outcomes, patterns)
- Pattern detection and storage
- Hypothesis testing
- Prompt modification proposals with approval workflow
"""
import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# ==============================================
# Reflection Observations Table
# ==============================================
# The reflection agent's observations over time
cur.execute("""
    CREATE TABLE IF NOT EXISTS reflection_observations (
        observation_id SERIAL PRIMARY KEY,

        observation_type VARCHAR(50) NOT NULL,
        -- types: consolidation_audit, action_outcome, pattern_detected,
        --        hypothesis, uncertainty_flag

        subject_agent VARCHAR(50),
        subject_dimension VARCHAR(100),

        summary TEXT NOT NULL,
        details JSONB,

        confidence FLOAT DEFAULT 0.5,

        evidence_refs JSONB,

        pattern_id VARCHAR(100),

        resolved BOOLEAN DEFAULT FALSE,
        resolution TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_obs_type_time
    ON reflection_observations(observation_type, created_at DESC)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_obs_pattern
    ON reflection_observations(pattern_id)
    WHERE pattern_id IS NOT NULL
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_obs_agent
    ON reflection_observations(subject_agent, created_at DESC)
""")

# ==============================================
# Reflection Patterns Table
# ==============================================
# Patterns the reflection agent has identified
cur.execute("""
    CREATE TABLE IF NOT EXISTS reflection_patterns (
        pattern_id VARCHAR(100) PRIMARY KEY,

        pattern_type VARCHAR(50) NOT NULL,
        -- types: recurring_error, missed_opportunity, successful_approach,
        --        calibration_issue, timing_pattern, consolidation_issue

        description TEXT NOT NULL,

        affected_agent VARCHAR(50),
        affected_dimension VARCHAR(100),

        observation_count INT DEFAULT 1,
        first_observed TIMESTAMP,
        last_observed TIMESTAMP,

        confidence FLOAT DEFAULT 0.5,

        status VARCHAR(20) DEFAULT 'active',
        -- status: active, addressed, dismissed, monitoring

        proposed_action TEXT,
        action_taken TEXT,

        metadata JSONB,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_patterns_status
    ON reflection_patterns(status)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_patterns_type
    ON reflection_patterns(pattern_type, confidence DESC)
""")

# ==============================================
# Reflection Hypotheses Table
# ==============================================
# Hypotheses being tested
cur.execute("""
    CREATE TABLE IF NOT EXISTS reflection_hypotheses (
        hypothesis_id SERIAL PRIMARY KEY,

        hypothesis TEXT NOT NULL,

        supporting_evidence JSONB DEFAULT '[]',
        contradicting_evidence JSONB DEFAULT '[]',

        confidence FLOAT DEFAULT 0.5,

        test_criteria TEXT,
        test_deadline TIMESTAMP,

        status VARCHAR(20) DEFAULT 'testing',
        -- status: testing, confirmed, rejected, inconclusive

        outcome TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_hypotheses_status
    ON reflection_hypotheses(status, test_deadline)
""")

# ==============================================
# Prompt Proposals Table
# ==============================================
# Prompt modification proposals with approval workflow
cur.execute("""
    CREATE TABLE IF NOT EXISTS prompt_proposals (
        proposal_id SERIAL PRIMARY KEY,

        target_agent VARCHAR(50) NOT NULL,
        target_prompt_section VARCHAR(100),

        current_content TEXT,
        proposed_content TEXT,

        reasoning TEXT NOT NULL,

        supporting_pattern_ids TEXT[],
        expected_improvement TEXT,

        status VARCHAR(20) DEFAULT 'pending',
        -- status: pending, approved, rejected, implemented, rolled_back

        reviewed_by VARCHAR(50),
        reviewed_at TIMESTAMP,
        review_notes TEXT,

        implemented_at TIMESTAMP,
        outcome_assessment TEXT,
        outcome_karma_delta FLOAT,

        karma_state_at_proposal JSONB,
        karma_state_at_implementation JSONB,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_prompt_proposals_status
    ON prompt_proposals(status)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_prompt_proposals_agent
    ON prompt_proposals(target_agent, created_at DESC)
""")

# ==============================================
# Action Log Table
# ==============================================
# Tracks Sara's actions for outcome analysis
cur.execute("""
    CREATE TABLE IF NOT EXISTS action_log (
        action_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

        user_id VARCHAR(255) NOT NULL,
        action_type VARCHAR(100) NOT NULL,
        action_content TEXT,

        context_snapshot JSONB,
        karma_state_at_action JSONB,

        outcome_status VARCHAR(20) DEFAULT 'pending',
        -- status: pending, success, failure, partial, unknown

        outcome_details TEXT,
        outcome_recorded_at TIMESTAMP,
        feedback_source VARCHAR(50),
        -- source: explicit, implicit, timeout

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_action_log_user_time
    ON action_log(user_id, created_at DESC)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_action_log_outcome
    ON action_log(outcome_status, created_at DESC)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_action_log_type
    ON action_log(action_type, created_at DESC)
""")

# ==============================================
# Prompt Version Control Table
# ==============================================
# Version history for prompt changes
cur.execute("""
    CREATE TABLE IF NOT EXISTS prompt_versions (
        version_id SERIAL PRIMARY KEY,

        agent VARCHAR(50) NOT NULL,
        section VARCHAR(100) NOT NULL,

        content TEXT NOT NULL,

        reason TEXT,
        proposal_id INT REFERENCES prompt_proposals(proposal_id),

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(50) DEFAULT 'system'
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_prompt_versions_agent_section
    ON prompt_versions(agent, section, created_at DESC)
""")

conn.commit()
cur.close()
conn.close()

print("Reflection system tables created successfully")
print("   - reflection_observations")
print("   - reflection_patterns")
print("   - reflection_hypotheses")
print("   - prompt_proposals")
print("   - action_log")
print("   - prompt_versions")
