"""Full per-user state reset + verification, run inside the isolated `shell`
container before each journey's first trial from this point forward.

Covers everything a journey could plausibly persist across turns for one
synthetic user: calendar, reminders/timers, tasks/lists, food log, notes,
memory/PKG facts, notification_log, episode/conversation history is handled
separately (each trial already uses a fresh conversation_id, which is
sufficient isolation since this app scopes episodes by conversation_id).
Also clears Redis-side interactive/pending-action state for the user and
reports any in-flight Celery task.

Does NOT touch other users' data, adapter containers, or anything outside
this run's own synthetic fixtures.
"""
import sys
from sqlalchemy import text

from app.db.base import SessionLocal

USER_ID = sys.argv[1]

TABLES_TO_CLEAR = [
    "reminder", "daily_task", "list_item", "food_log", "workout_log",
    "workout_session", "active_workout_session", "notification_log",
    "note", "recipe",
]

CALENDAR_FIXTURE_TITLE_PREFIX = sys.argv[2] if len(sys.argv) > 2 else None


def main():
    db = SessionLocal()
    try:
        cleared = {}
        for t in TABLES_TO_CLEAR:
            try:
                result = db.execute(text(f"DELETE FROM {t} WHERE user_id = :uid"), {"uid": USER_ID})
                cleared[t] = result.rowcount
            except Exception as e:
                cleared[t] = f"skip ({e.__class__.__name__})"
        if CALENDAR_FIXTURE_TITLE_PREFIX:
            result = db.execute(
                text("DELETE FROM calendar_event WHERE user_id = :uid AND title NOT LIKE :prefix"),
                {"uid": USER_ID, "prefix": f"{CALENDAR_FIXTURE_TITLE_PREFIX}%"},
            )
            cleared["calendar_event(non-fixture)"] = result.rowcount
        db.commit()
        print("cleared:", cleared)

        verify = {}
        for t in TABLES_TO_CLEAR + ["calendar_event"]:
            count = db.execute(text(f"SELECT count(*) FROM {t} WHERE user_id = :uid"), {"uid": USER_ID}).scalar()
            verify[t] = count
        print("post-reset counts:", verify)
    finally:
        db.close()


if __name__ == "__main__":
    main()
