"""
One-time cleanup: collapse duplicate calendar_event rows.

Arc 0.9 (SARA_ALIVE_BUILD_PLAN): email->calendar auto-creation had no
idempotency guard, so re-running analysis over the same email (or the same
recurring payday detection) produced multiple identical events — e.g. three
"Risk Ninja Demo" rows, two "Pay Day" rows. The tool-level create path now
guards on (user_id, title, start_time) going forward (see
app/tools/calendar.py CreateEventTool); this migration cleans up the rows
that already exist.

For each (user_id, title, start_time) group with >1 row:
  - keep the oldest (lowest created_at, tie-broken by id)
  - repoint any email.calendar_event_id from a loser to the keeper
  - delete reminders pointing at a loser
  - delete the loser rows
"""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
).replace("+asyncpg", "+psycopg")


def upgrade():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        groups = conn.execute(text("""
            SELECT user_id, title, start_time, COUNT(*) AS n
            FROM calendar_event
            GROUP BY user_id, title, start_time
            HAVING COUNT(*) > 1
        """)).fetchall()

        print(f"Found {len(groups)} duplicate (user_id, title, start_time) groups")

        total_deleted = 0
        for g in groups:
            rows = conn.execute(text("""
                SELECT id, created_at FROM calendar_event
                WHERE user_id = :uid AND title = :title AND start_time = :st
                ORDER BY created_at ASC, id ASC
            """), {"uid": g.user_id, "title": g.title, "st": g.start_time}).fetchall()

            keeper = rows[0].id
            losers = [r.id for r in rows[1:]]
            if not losers:
                continue

            conn.execute(text("""
                UPDATE email SET calendar_event_id = :keeper
                WHERE calendar_event_id = ANY(:losers)
            """), {"keeper": keeper, "losers": losers})

            conn.execute(text("""
                DELETE FROM reminder WHERE event_id = ANY(:losers)
            """), {"losers": losers})

            result = conn.execute(text("""
                DELETE FROM calendar_event WHERE id = ANY(:losers)
            """), {"losers": losers})
            total_deleted += result.rowcount
            print(f"  '{g.title}' @ {g.start_time}: kept {keeper}, deleted {len(losers)}")

        print(f"Deleted {total_deleted} duplicate calendar_event rows")


if __name__ == "__main__":
    upgrade()
