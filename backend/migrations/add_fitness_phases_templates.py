#!/usr/bin/env python3
"""
Migration: Add fitness phases, templates, and progression rules
for intelligent workout planning and progressive overload tracking
"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)

engine = create_engine(DATABASE_URL)

def migrate():
    with engine.begin() as conn:
        # ============================================
        # 1. FITNESS_PHASE: Training phases (hierarchical)
        # ============================================
        print("📋 Creating fitness_phase table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fitness_phase (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                goal VARCHAR,  -- hypertrophy, strength, deload, cutting, etc.
                parent_phase_id VARCHAR,  -- For hierarchical phases (e.g., sub-phases within a main phase)
                start_date DATE,
                end_date DATE,
                status VARCHAR DEFAULT 'planned',  -- planned, active, completed, paused
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (parent_phase_id) REFERENCES fitness_phase(id) ON DELETE CASCADE
            );
        """))

        # ============================================
        # 2. FITNESS_TEMPLATE: Workout templates
        # ============================================
        print("📋 Creating fitness_template table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fitness_template (
                id VARCHAR PRIMARY KEY,
                phase_id VARCHAR,  -- Optional: link to phase
                user_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,  -- e.g., "Push Day A", "Pull Day B"
                scheduled_days TEXT,  -- JSON array: ["monday", "thursday"]
                exercises TEXT,  -- JSON array of exercises with sets/reps/rpe targets
                order_in_phase INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (phase_id) REFERENCES fitness_phase(id) ON DELETE CASCADE
            );
        """))

        # ============================================
        # 3. FITNESS_PROGRESSION_RULE: Per-exercise progression rules
        # ============================================
        print("📋 Creating fitness_progression_rule table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fitness_progression_rule (
                id VARCHAR PRIMARY KEY,
                template_id VARCHAR NOT NULL,
                exercise_name VARCHAR NOT NULL,
                progression_type VARCHAR DEFAULT 'linear',  -- linear, percentage, double_progression
                weight_increase FLOAT DEFAULT 5.0,  -- e.g., 5 lbs
                rep_increase INTEGER DEFAULT 1,  -- e.g., 1 rep
                trigger_condition VARCHAR,  -- e.g., "completed_all_sets_rpe_under_8"
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (template_id) REFERENCES fitness_template(id) ON DELETE CASCADE
            );
        """))

        # ============================================
        # 4. FITNESS_SETTINGS: User fitness settings including system prompt
        # ============================================
        print("📋 Creating fitness_settings table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fitness_settings (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL UNIQUE,
                system_prompt TEXT,  -- Custom fitness system prompt with {{VARIABLES}}
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # ============================================
        # 5. Modify workout_log to link to templates and track sessions
        # ============================================
        print("📋 Updating workout_log table...")

        # Check if columns exist before adding them
        columns_to_add = [
            ("template_id", "VARCHAR"),
            ("session_date", "DATE"),
            ("day_of_week", "VARCHAR")
        ]

        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(f"""
                    ALTER TABLE workout_log
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type};
                """))
                print(f"  ✓ Added {col_name} column")
            except Exception as e:
                print(f"  ℹ {col_name} column already exists or error: {e}")

        # Add foreign key constraint for template_id if it doesn't exist
        try:
            conn.execute(text("""
                ALTER TABLE workout_log
                ADD CONSTRAINT fk_workout_log_template
                FOREIGN KEY (template_id) REFERENCES fitness_template(id)
                ON DELETE SET NULL;
            """))
            print("  ✓ Added foreign key constraint for template_id")
        except Exception as e:
            print(f"  ℹ Foreign key constraint may already exist: {e}")

        # ============================================
        # 6. Create indexes for performance
        # ============================================
        print("📋 Creating indexes...")

        indexes = [
            ("idx_fitness_phase_user", "fitness_phase(user_id, status)"),
            ("idx_fitness_phase_dates", "fitness_phase(start_date, end_date)"),
            ("idx_fitness_template_user", "fitness_template(user_id)"),
            ("idx_fitness_template_phase", "fitness_template(phase_id)"),
            ("idx_fitness_progression_template", "fitness_progression_rule(template_id)"),
            ("idx_workout_log_template", "workout_log(template_id)"),
            ("idx_workout_log_session", "workout_log(session_date, user_id)"),
            ("idx_fitness_settings_user", "fitness_settings(user_id)"),
        ]

        for idx_name, idx_def in indexes:
            try:
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def};
                """))
                print(f"  ✓ Created index {idx_name}")
            except Exception as e:
                print(f"  ℹ Index {idx_name} may already exist: {e}")

        print("\n✅ Migration completed successfully!")
        print("\nNew tables created:")
        print("  - fitness_phase: Training phases with hierarchical support")
        print("  - fitness_template: Workout templates with day-of-week scheduling")
        print("  - fitness_progression_rule: Per-exercise progressive overload rules")
        print("  - fitness_settings: User fitness settings and custom system prompts")
        print("\nModified tables:")
        print("  - workout_log: Added template_id, session_date, day_of_week")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        raise
