"""Dump the state a journey's hidden outcome card is checked against.

Reliable-assistant plan §10: *"Independently verify writes, readbacks,
authorization, and external receipts."* Nothing here is shown to the model and
nothing here asks the model anything — it reads the database and the receipt
ledger directly, so a journey's verdict never rests on Sara's own account of
what she did.

  python tests/assistant_acceptance/reliable_check.py <user_id> [seed-plants]

`seed-plants` adds the second plant-ish reminder J6 needs in order to be
genuinely ambiguous, so the clarify path is exercised rather than assumed.
"""
import json
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.base import SessionLocal


def rows(db, sql, **params):
    return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def iso(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def dump(user_id: str) -> dict:
    db = SessionLocal()
    try:
        state = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "notes": rows(db, """
                SELECT id, title, content, created_at, updated_at
                FROM note WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "reminders": rows(db, """
                SELECT id, title, description, reminder_time, is_completed,
                       notified_at, delivery_status, claimed_at, delivery_attempts,
                       created_at, updated_at
                FROM reminder WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "timers": rows(db, """
                SELECT id, title, duration_minutes, start_time, end_time,
                       is_active, is_completed
                FROM timer WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "list_items": rows(db, """
                SELECT id, list_name, item, quantity, checked, created_at
                FROM list_item WHERE user_id = :u ORDER BY list_name, created_at, id
            """, u=user_id),
            "daily_tasks": rows(db, """
                SELECT id, title, task_date, is_completed FROM daily_task
                WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "food_log": rows(db, """
                SELECT id, meal_type, food_items, calories, protein, carbs, fats,
                       logged_at, created_at, updated_at
                FROM food_log WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "calendar_events": rows(db, """
                SELECT id, title, start_time, end_time, is_completed, source
                FROM calendar_event WHERE user_id = :u ORDER BY start_time
            """, u=user_id),
            # action_receipt's columns are action_type/target/status/
            # executed_at (there is no tool_name/result_message column — the
            # chat wiring stores the tool in action_type).
            "action_receipts": rows(db, """
                SELECT action_type, status, target, permission_tier,
                       idempotency_key, executed_at, created_at
                FROM action_receipt WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "pending_proposals": rows(db, """
                SELECT tool_name, presented_summary, consumed_at, created_at
                FROM chat_pending_proposal WHERE user_id = :u ORDER BY created_at
            """, u=user_id),
            "conversation_turns": rows(db, """
                SELECT conversation_id, count(*) AS turns
                FROM conversation_turn WHERE user_id = :u
                GROUP BY conversation_id
            """, u=user_id),
        }
        return json.loads(json.dumps(state, default=iso))
    finally:
        db.close()


def seed_plants(user_id: str) -> dict:
    """A second plant-ish reminder, so 'cancel the plant one' really is
    ambiguous. Seeded directly, not through chat, so it costs no generation."""
    db = SessionLocal()
    try:
        rid = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO reminder (id, user_id, title, description, reminder_time,
                                  is_completed, delivery_attempts, created_at, updated_at)
            VALUES (:id, :u, 'Repot the plant in the office', '',
                    '2026-10-04 14:00:00', false, 0, now(), now())
        """), {"id": rid, "u": user_id})
        db.commit()
        return {"seeded_reminder_id": rid, "title": "Repot the plant in the office"}
    finally:
        db.close()


if __name__ == "__main__":
    uid = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "seed-plants":
        print(json.dumps(seed_plants(uid), indent=2))
    else:
        print(json.dumps(dump(uid), indent=2))
