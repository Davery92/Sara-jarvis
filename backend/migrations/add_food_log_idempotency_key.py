"""
Migration Script: Add idempotency_key to food_log

SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16 Stage A — a retried POST
/food-log (network blip, double-tap) must not duplicate a meal. The client
generates a UUID once per commit attempt and resends the same one on retry;
a unique index lets the insert path detect and no-op the replay instead of
inserting a second row. NULL-able and unindexed-for-uniqueness on NULL (a
partial unique index) so existing rows and any caller that doesn't yet send
one are unaffected.

Run:      docker exec jarvis-backend-1 python /app/migrations/add_food_log_idempotency_key.py
Rollback: docker exec jarvis-backend-1 python /app/migrations/add_food_log_idempotency_key.py --rollback
"""
import os
import sys

from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")


def run_migration():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("Adding food_log.idempotency_key ...")
        conn.execute(text("""
            ALTER TABLE food_log ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR
        """))
        # Partial index: only enforce uniqueness where a key was actually
        # supplied, so historical NULL rows and old clients never collide.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_food_log_idempotency_key
            ON food_log (user_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """))
        conn.commit()
    print("✅ MIGRATION COMPLETED")


def rollback_migration():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_food_log_idempotency_key"))
        conn.execute(text("ALTER TABLE food_log DROP COLUMN IF EXISTS idempotency_key"))
        conn.commit()
    print("✅ ROLLBACK COMPLETED")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="food_log idempotency_key migration")
    parser.add_argument("--rollback", action="store_true", help="Drop the idempotency_key column")
    args = parser.parse_args()
    if args.rollback:
        confirm = input("⚠️  This will drop food_log.idempotency_key. Continue? (yes/no): ")
        if confirm.lower() == "yes":
            rollback_migration()
        else:
            print("Rollback cancelled.")
    else:
        run_migration()
