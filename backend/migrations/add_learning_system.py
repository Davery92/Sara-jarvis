"""
Add learning system tables for Sara's self-improvement.

This migration adds:
1. lesson_applications - Track when lessons are applied and their outcomes
2. Modify sara_reflection - Add last_applied_at and trigger_context columns
3. Add 'learning' karma dimension for Sara

The learning system enables Sara to:
- Extract lessons from mistakes (negative feedback)
- Track lesson effectiveness over time
- Auto-deactivate ineffective lessons
- Improve karma based on learning success
"""
import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# ==============================================
# Modify sara_reflection table
# ==============================================
# Add columns for lesson tracking

# Add last_applied_at column
cur.execute("""
    ALTER TABLE sara_reflection
    ADD COLUMN IF NOT EXISTS last_applied_at TIMESTAMP
""")

# Add trigger_context column (JSONB for storing lesson metadata)
cur.execute("""
    ALTER TABLE sara_reflection
    ADD COLUMN IF NOT EXISTS trigger_context JSONB
""")

# Add index on reflection_type and is_active for lesson queries
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_sara_reflection_lesson_lookup
    ON sara_reflection(reflection_type, is_active)
    WHERE reflection_type = 'mistake' AND is_active = true
""")

# ==============================================
# Create lesson_applications table
# ==============================================
# Track when lessons are injected and whether they helped

cur.execute("""
    CREATE TABLE IF NOT EXISTS lesson_applications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        lesson_id VARCHAR(255) REFERENCES sara_reflection(id) ON DELETE CASCADE,
        conversation_id VARCHAR(255),
        message_id VARCHAR(255),
        outcome VARCHAR(20) DEFAULT 'unknown',  -- success, failure, unknown
        feedback_signal VARCHAR(50),  -- the trigger phrase that indicated success/failure
        feedback_strength VARCHAR(20),  -- strong, moderate, weak
        context_snippet TEXT,  -- brief context of the conversation
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Index for efficient lookup by lesson_id
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_lesson_applications_lesson
    ON lesson_applications(lesson_id, created_at DESC)
""")

# Index for finding applications by conversation
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_lesson_applications_conversation
    ON lesson_applications(conversation_id)
""")

# Index for finding recent applications for effectiveness calculation
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_lesson_applications_recent
    ON lesson_applications(created_at DESC)
    WHERE outcome != 'unknown'
""")

# ==============================================
# Add 'learning' karma dimension
# ==============================================
# This dimension tracks Sara's ability to learn from mistakes

cur.execute("""
    INSERT INTO karma_dimensions (agent_id, dimension_name, description, weight)
    VALUES ('sara', 'learning', 'Ability to learn from mistakes and apply lessons', 1.2)
    ON CONFLICT (agent_id, dimension_name) DO NOTHING
""")

# Initialize the learning karma score
cur.execute("""
    INSERT INTO karma_scores (agent_id, dimension_name, current_score, trend)
    VALUES ('sara', 'learning', 50.0, 0.0)
    ON CONFLICT (agent_id, dimension_name) DO NOTHING
""")

conn.commit()
cur.close()
conn.close()

print("Learning system migration complete!")
print("   - sara_reflection: Added last_applied_at, trigger_context columns")
print("   - lesson_applications: Created for tracking lesson effectiveness")
print("   - karma_dimensions: Added 'learning' dimension for Sara")
print("   - karma_scores: Initialized learning score at 50")
