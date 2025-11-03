"""
Database Migration: Add Recovery Log, Recipes, and Workout Enhancement Tables

This migration adds:
1. daily_recovery_log - Daily recovery metrics (HRV, HR, sleep, soreness)
2. recipe - Recipe management with nutrition calculation
3. workout_session - Workout session tracking with calendar integration
4. exercise_history - Exercise performance history aggregation
5. Modifications to fitness_template (starting_weights field)
6. Modifications to workout_log (session_id FK)

Run with: python3 backend/migrations/add_recovery_recipes_workout_enhancements.py
"""

import psycopg
from datetime import datetime
import os

# Database connection from environment
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub')
# Convert SQLAlchemy format to psycopg format if needed
if DATABASE_URL.startswith('postgresql+psycopg://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql+psycopg://', 'postgresql://')

def run_migration():
    """Execute the database migration"""

    print("🚀 Starting Fitness Enhancement Database Migration...")
    print(f"📅 Migration Date: {datetime.now().isoformat()}")
    print(f"🔗 Database: {DATABASE_URL.split('@')[1]}")  # Hide credentials
    print()

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:

                # ============================================================
                # 1. CREATE daily_recovery_log TABLE
                # ============================================================
                print("📊 Creating daily_recovery_log table...")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS daily_recovery_log (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR NOT NULL,
                        log_date DATE NOT NULL,

                        -- Recovery metrics
                        hrv INTEGER,  -- Heart Rate Variability
                        heart_rate INTEGER,  -- Resting heart rate
                        sleep_hours DECIMAL(4,2),  -- Hours of sleep (e.g., 7.5)
                        soreness_level INTEGER CHECK (soreness_level >= 1 AND soreness_level <= 10),

                        -- Notes
                        notes TEXT,

                        -- Timestamps
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),

                        -- Constraints
                        UNIQUE(user_id, log_date)
                    );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recovery_log_user_date
                    ON daily_recovery_log(user_id, log_date DESC);
                """)
                print("✅ daily_recovery_log table created")

                # ============================================================
                # 2. CREATE recipe TABLE
                # ============================================================
                print("📊 Creating recipe table...")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS recipe (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR NOT NULL,

                        -- Recipe details
                        name VARCHAR NOT NULL,
                        description TEXT,
                        category VARCHAR,  -- breakfast, lunch, dinner, snack, dessert, etc.

                        -- Ingredients (JSON array)
                        -- Format: [{"name": "Chicken Breast", "quantity": 200, "unit": "g"}, ...]
                        ingredients JSON NOT NULL,

                        -- Instructions
                        instructions TEXT NOT NULL,

                        -- Metadata
                        prep_time_minutes INTEGER,  -- Preparation time
                        servings INTEGER NOT NULL DEFAULT 1,

                        -- Nutrition (auto-calculated, per serving)
                        calories DECIMAL(8,2),
                        protein DECIMAL(8,2),
                        carbs DECIMAL(8,2),
                        fats DECIMAL(8,2),

                        -- Timestamps
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recipe_user
                    ON recipe(user_id);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recipe_category
                    ON recipe(user_id, category);
                """)
                print("✅ recipe table created")

                # ============================================================
                # 3. CREATE workout_session TABLE
                # ============================================================
                print("📊 Creating workout_session table...")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS workout_session (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR NOT NULL,
                        template_id VARCHAR,  -- FK to fitness_template

                        -- Session details
                        session_date DATE NOT NULL,
                        status VARCHAR NOT NULL DEFAULT 'planned',  -- planned, in_progress, completed, skipped

                        -- Calendar integration
                        calendar_event_id VARCHAR,  -- FK to event table

                        -- Timestamps
                        started_at TIMESTAMPTZ,
                        completed_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),

                        -- Constraints
                        CHECK (status IN ('planned', 'in_progress', 'completed', 'skipped'))
                    );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workout_session_user_date
                    ON workout_session(user_id, session_date DESC);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workout_session_template
                    ON workout_session(template_id);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workout_session_status
                    ON workout_session(user_id, status);
                """)
                print("✅ workout_session table created")

                # ============================================================
                # 4. CREATE exercise_history TABLE
                # ============================================================
                print("📊 Creating exercise_history table...")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS exercise_history (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR NOT NULL,
                        exercise_name VARCHAR NOT NULL,
                        session_id VARCHAR,  -- FK to workout_session

                        -- Aggregated performance metrics
                        avg_weight DECIMAL(8,2),  -- Average weight used
                        total_sets INTEGER,
                        total_reps INTEGER,
                        avg_rpe DECIMAL(3,1),  -- Average RPE (Rate of Perceived Exertion)

                        -- Date tracking
                        performance_date DATE NOT NULL,

                        -- Timestamps
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_exercise_history_user_exercise
                    ON exercise_history(user_id, exercise_name, performance_date DESC);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_exercise_history_session
                    ON exercise_history(session_id);
                """)
                print("✅ exercise_history table created")

                # ============================================================
                # 5. MODIFY fitness_template - Add starting_weights column
                # ============================================================
                print("📊 Modifying fitness_template table...")

                # Check if column already exists
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='fitness_template' AND column_name='starting_weights';
                """)

                if cur.fetchone() is None:
                    cur.execute("""
                        ALTER TABLE fitness_template
                        ADD COLUMN starting_weights JSON;
                    """)
                    print("✅ Added starting_weights column to fitness_template")
                else:
                    print("⏭️  starting_weights column already exists")

                # ============================================================
                # 6. MODIFY workout_log - Add session_id column
                # ============================================================
                print("📊 Modifying workout_log table...")

                # Check if column already exists
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='workout_log' AND column_name='session_id';
                """)

                if cur.fetchone() is None:
                    cur.execute("""
                        ALTER TABLE workout_log
                        ADD COLUMN session_id VARCHAR;
                    """)

                    # Add index
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_workout_log_session
                        ON workout_log(session_id);
                    """)
                    print("✅ Added session_id column to workout_log")
                else:
                    print("⏭️  session_id column already exists")

                # Commit all changes
                conn.commit()

                print()
                print("=" * 60)
                print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
                print("=" * 60)
                print()
                print("📋 Summary:")
                print("  ✅ daily_recovery_log table created")
                print("  ✅ recipe table created")
                print("  ✅ workout_session table created")
                print("  ✅ exercise_history table created")
                print("  ✅ fitness_template.starting_weights column added")
                print("  ✅ workout_log.session_id column added")
                print()

    except Exception as e:
        print()
        print("=" * 60)
        print("❌ MIGRATION FAILED!")
        print("=" * 60)
        print(f"Error: {str(e)}")
        print()
        raise

if __name__ == "__main__":
    run_migration()
