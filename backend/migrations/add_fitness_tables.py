"""
Migration Script: Add Fitness Tables
Creates dedicated fitness tables for notes, food logs, workout logs, and episodes
"""
import os
import sys
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float, JSON, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    print("Warning: pgvector not available, embeddings will not be created")
    Vector = None

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

Base = declarative_base()

# Define fitness models
class FitnessNote(Base):
    """Fitness-specific notes with category tagging"""
    __tablename__ = "fitness_note"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, default="")
    content = Column(Text, nullable=False)
    category = Column(String, nullable=False)  # nutrition, workout, goal, progress, general
    embedding = Column(Vector(1024)) if PGVECTOR_AVAILABLE else Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FoodLog(Base):
    """Daily food and nutrition tracking"""
    __tablename__ = "food_log"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    meal_type = Column(String, nullable=False)  # breakfast, lunch, dinner, snack
    food_items = Column(JSON, nullable=False)  # Array of {name, quantity, unit}
    calories = Column(Float, nullable=True)
    protein = Column(Float, nullable=True)  # grams
    carbs = Column(Float, nullable=True)  # grams
    fats = Column(Float, nullable=True)  # grams
    notes = Column(Text, default="")
    logged_at = Column(DateTime, nullable=False)  # When the meal was eaten
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class WorkoutLog(Base):
    """Workout and exercise tracking"""
    __tablename__ = "workout_log"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    workout_type = Column(String, nullable=False)  # cardio, strength, flexibility, sports
    exercises = Column(JSON, nullable=False)  # Array of {name, sets, reps, weight, duration}
    duration_minutes = Column(Integer, nullable=True)
    intensity = Column(String, nullable=True)  # low, moderate, high
    calories_burned = Column(Float, nullable=True)
    notes = Column(Text, default="")
    logged_at = Column(DateTime, nullable=False)  # When the workout occurred
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FitnessEpisode(Base):
    """Voice conversation history for fitness context"""
    __tablename__ = "fitness_episode"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)  # Voice session ID
    role = Column(String, nullable=False)  # user or assistant
    content = Column(Text, nullable=False)
    context_data = Column(JSON, default={})  # Additional context (turn number, timestamp, etc)
    created_at = Column(DateTime, server_default=func.now())


def add_document_category_column(engine):
    """Add category column to existing document table"""
    print("\n3. Adding category column to document table...")

    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='document' AND column_name='category'
        """))

        if result.fetchone() is None:
            # Add category column with default value 'general'
            conn.execute(text("""
                ALTER TABLE document
                ADD COLUMN category VARCHAR DEFAULT 'general'
            """))
            conn.commit()
            print("   ✓ Category column added to document table")
        else:
            print("   ✓ Category column already exists")


def create_indexes(engine):
    """Create indexes for better query performance"""
    print("\n4. Creating indexes...")

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_fitness_note_user_category ON fitness_note(user_id, category)",
        "CREATE INDEX IF NOT EXISTS idx_food_log_user_date ON food_log(user_id, logged_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_workout_log_user_date ON workout_log(user_id, logged_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_fitness_episode_session ON fitness_episode(session_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_document_user_category ON document(user_id, category)",
    ]

    with engine.connect() as conn:
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
            print(f"   ✓ Created index")
        conn.commit()


def run_migration():
    """Run the migration"""
    print("=" * 60)
    print("FITNESS TABLES MIGRATION")
    print("=" * 60)
    print(f"\nDatabase: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'local'}")
    print(f"pgvector available: {PGVECTOR_AVAILABLE}")

    # Create engine
    engine = create_engine(DATABASE_URL)

    print("\n1. Creating fitness tables...")
    Base.metadata.create_all(engine)
    print("   ✓ Fitness tables created")

    print("\n2. Adding document category column...")
    add_document_category_column(engine)

    create_indexes(engine)

    print("\n" + "=" * 60)
    print("✅ MIGRATION COMPLETED SUCCESSFULLY")
    print("=" * 60)
    print("\nNew tables created:")
    print("  - fitness_note: Fitness-specific notes with categories")
    print("  - food_log: Daily food and nutrition tracking")
    print("  - workout_log: Workout and exercise logging")
    print("  - fitness_episode: Voice conversation history")
    print("\nUpdated tables:")
    print("  - document: Added 'category' column for filtering")
    print("\n")


def rollback_migration():
    """Rollback the migration (drop tables)"""
    print("=" * 60)
    print("ROLLING BACK FITNESS TABLES MIGRATION")
    print("=" * 60)

    engine = create_engine(DATABASE_URL)

    tables_to_drop = [
        "fitness_episode",
        "workout_log",
        "food_log",
        "fitness_note"
    ]

    with engine.connect() as conn:
        for table in tables_to_drop:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                print(f"   ✓ Dropped table: {table}")
            except Exception as e:
                print(f"   ✗ Error dropping {table}: {e}")

        # Remove category column from document table (optional)
        try:
            conn.execute(text("ALTER TABLE document DROP COLUMN IF EXISTS category"))
            print("   ✓ Removed category column from document table")
        except Exception as e:
            print(f"   ✗ Error removing category column: {e}")

        conn.commit()

    print("\n✅ ROLLBACK COMPLETED")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fitness Tables Migration")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback the migration (drop fitness tables)"
    )

    args = parser.parse_args()

    if args.rollback:
        confirm = input("⚠️  WARNING: This will DROP all fitness tables. Continue? (yes/no): ")
        if confirm.lower() == "yes":
            rollback_migration()
        else:
            print("Rollback cancelled.")
    else:
        run_migration()
