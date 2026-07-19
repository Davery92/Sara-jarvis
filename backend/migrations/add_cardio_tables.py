"""
Migration Script: Add Cardio Tables
Creates the cardio tracking layer that mirrors the strength workout tracker but is
cardio-shaped (minutes / distance / HR / zone instead of sets & reps):

  - cardio_log      : logged cardio sessions (walks, rucks, KB-swing EMOMs, coaching, Tabata, ...)
  - cardio_settings : per-user weekly dose target + steps floor + the "density engine" menu
  - tabata_preset   : saved custom interval timers (work/rest/rounds/sets), synced across devices

Run:      docker exec jarvis-backend-1 python /app/migrations/add_cardio_tables.py
Rollback: docker exec jarvis-backend-1 python /app/migrations/add_cardio_tables.py --rollback
"""
import os
import sys
from sqlalchemy import (
    create_engine, Column, String, DateTime, Date, Text, Integer, Float, Boolean, JSON, text,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

Base = declarative_base()


class CardioLog(Base):
    """A single logged cardio session."""
    __tablename__ = "cardio_log"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    # walk, ruck, kb_swings, coaching, commute, run, row, bike, tabata, other
    activity_type = Column(String, nullable=False)
    title = Column(String, default="")
    duration_minutes = Column(Float, nullable=False)
    distance_miles = Column(Float, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    max_hr = Column(Integer, nullable=True)
    zone = Column(String, nullable=True)            # zone2, mixed, hard
    calories_burned = Column(Float, nullable=True)
    rpe = Column(Integer, nullable=True)            # 1-10 perceived effort
    source = Column(String, default="manual")       # manual, tabata, apple_health
    tabata_detail = Column(JSON, nullable=True)      # {work,rest,rounds,sets,completed_rounds}
    notes = Column(Text, default="")
    session_date = Column(Date, nullable=False, index=True)   # local (ET) calendar day
    logged_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CardioSettings(Base):
    """Per-user cardio dose target + the mix-and-match menu (one row per user)."""
    __tablename__ = "cardio_settings"

    user_id = Column(String, primary_key=True)
    weekly_min_minutes = Column(Integer, default=90)
    weekly_max_minutes = Column(Integer, default=120)
    steps_floor = Column(Integer, default=8000)
    # Array of {key, label, typical_minutes, worth_minutes, note}
    menu = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TabataPreset(Base):
    """A saved custom interval timer. Fully user-editable in the app."""
    __tablename__ = "tabata_preset"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    prepare_seconds = Column(Integer, default=10)
    work_seconds = Column(Integer, nullable=False)
    rest_seconds = Column(Integer, nullable=False)
    rounds = Column(Integer, nullable=False)                 # intervals per set
    sets = Column(Integer, default=1)
    rest_between_sets_seconds = Column(Integer, default=60)
    activity_type = Column(String, default="tabata")         # what a completed session logs as
    color = Column(String, nullable=True)
    is_built_in = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def create_indexes(engine):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_cardio_log_user_date ON cardio_log(user_id, session_date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_cardio_log_user_logged ON cardio_log(user_id, logged_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_tabata_preset_user ON tabata_preset(user_id, sort_order)",
    ]
    with engine.connect() as conn:
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
        conn.commit()
    print("   ✓ Indexes created")


def run_migration():
    print("=" * 60)
    print("CARDIO TABLES MIGRATION")
    print("=" * 60)
    engine = create_engine(DATABASE_URL)
    print("\n1. Creating cardio tables...")
    Base.metadata.create_all(engine)
    print("   ✓ cardio_log, cardio_settings, tabata_preset created")
    create_indexes(engine)
    print("\n✅ MIGRATION COMPLETED SUCCESSFULLY\n")


def rollback_migration():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        for table in ["cardio_log", "cardio_settings", "tabata_preset"]:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            print(f"   ✓ Dropped {table}")
        conn.commit()
    print("\n✅ ROLLBACK COMPLETED")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cardio Tables Migration")
    parser.add_argument("--rollback", action="store_true", help="Drop the cardio tables")
    args = parser.parse_args()
    if args.rollback:
        confirm = input("⚠️  This will DROP all cardio tables. Continue? (yes/no): ")
        if confirm.lower() == "yes":
            rollback_migration()
        else:
            print("Rollback cancelled.")
    else:
        run_migration()
