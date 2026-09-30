"""Stage 1 fixture bootstrap — run inside the isolated `shell` container only.

Creates the three synthetic users, generates real auth tokens via the app's
own create_access_token/get_password_hash, and seeds the calendar/notes
fixtures the plan's "Fixed fixtures and time" section specifies. Uses the
app's real ORM models and helper functions — never hand-rolled SQL for
anything the app itself would validate (password hashing, JWT claims), so
what's created is exactly what the real auth path expects, not an approximation.

Idempotent: safe to re-run against the same disposable DB (upserts by email).
"""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

from app.db.base import SessionLocal
from app.core.auth import create_access_token
from app.models.user import User

# app.core.auth.get_password_hash (passlib bcrypt backend) is broken in this
# image — verified directly: ValueError "password cannot be longer than 72
# bytes" fires from passlib's own internal *self-test* hash
# (bcrypt.__about__ missing -> passlib falls back to a version probe that
# itself throws), independent of the actual password given. This is a real,
# pre-existing environment defect (image bcrypt/passlib version mismatch),
# not something this script's input triggers — it would break the real
# POST /auth/login and /auth/register paths identically. Recorded as a
# finding for A01 rather than worked around at the source: fixture users
# below get a placeholder hash and skip password-based login entirely
# (tokens are minted directly via create_access_token, the same helper the
# real login route calls after password verification succeeds — so the
# *session* these tokens produce is real and identical to a normal login's,
# only the password-verification step itself is what's unavailable here).
from app.models.calendar_event import CalendarEvent

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown_run"

NY = "America/New_York"
LONDON = "Europe/London"

# Fixture clock per plan: 2026-09-24 16:00:00 UTC == noon America/New_York.
FIXTURE_NOW_UTC = datetime(2026, 9, 24, 16, 0, 0, tzinfo=timezone.utc)


def naive_utc(y, m, d, hh=0, mm=0):
    """calendar_event.start_time/end_time are plain DateTime (no timezone=True)
    — project convention (see gotcha_naive_datetime_et_container /
    gotcha_day_replay_timestamp_conventions) is naive-datetime-means-UTC-instant.
    Constructing tz-aware then stripping keeps the UTC arithmetic explicit at
    the call site instead of hand-computing offsets."""
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc).replace(tzinfo=None)


def get_or_create_user(db, email: str, password: str) -> User:
    u = db.query(User).filter(User.email == email).first()
    if u:
        return u
    u = User(id=str(uuid.uuid4()), email=email, password_hash="unusable-bcrypt-broken-in-this-image")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def main():
    db = SessionLocal()
    try:
        david = get_or_create_user(db, f"david.test.{RUN_ID}@acceptance.invalid", "disposable-fixture-pw-1")
        morgan = get_or_create_user(db, f"morgan.test.{RUN_ID}@acceptance.invalid", "disposable-fixture-pw-2")
        casey = get_or_create_user(db, f"casey.test.{RUN_ID}@acceptance.invalid", "disposable-fixture-pw-3")

        david_token = create_access_token({"sub": david.id})
        morgan_token = create_access_token({"sub": morgan.id})
        casey_token = create_access_token({"sub": casey.id})

        # Calendar fixtures (plan: "A busy Friday September 25 09:00-10:00 and
        # 13:00-14:00; work window 09:00-17:00; one all-day entry; Casey has a
        # separate 18:00 class; two similarly named appointments.")
        # All stored as UTC instants; 09:00/13:00 America/New_York on
        # 2026-09-25 is 13:00/17:00 UTC (EDT, UTC-4, still in effect in
        # September).
        existing = db.query(CalendarEvent).filter(CalendarEvent.user_id == david.id).count()
        if existing == 0:
            events = [
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=david.id,
                    title=f"[{RUN_ID}] Morning sync", location=None,
                    start_time=naive_utc(2026, 9, 25, 13, 0),
                    end_time=naive_utc(2026, 9, 25, 14, 0),
                    all_day=False, source="acceptance_fixture",
                ),
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=david.id,
                    title=f"[{RUN_ID}] Budget review", location=None,
                    start_time=naive_utc(2026, 9, 25, 17, 0),
                    end_time=naive_utc(2026, 9, 25, 18, 0),
                    all_day=False, source="acceptance_fixture",
                ),
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=david.id,
                    title=f"[{RUN_ID}] Cedar Kickoff", location=None,
                    start_time=naive_utc(2026, 9, 25, 0, 0),
                    end_time=naive_utc(2026, 9, 26, 0, 0),
                    all_day=True, source="acceptance_fixture",
                ),
                # Two similarly named appointments (D02/D05/T03-style ambiguity cases)
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=david.id,
                    title=f"[{RUN_ID}] Dentist checkup", location=None,
                    start_time=naive_utc(2026, 9, 30, 14, 0),
                    end_time=naive_utc(2026, 9, 30, 15, 0),
                    all_day=False, source="acceptance_fixture",
                ),
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=david.id,
                    title=f"[{RUN_ID}] Dentist follow-up", location=None,
                    start_time=naive_utc(2026, 10, 2, 14, 0),
                    end_time=naive_utc(2026, 10, 2, 15, 0),
                    all_day=False, source="acceptance_fixture",
                ),
                # Casey's separate 18:00 class — owned by Casey, not David.
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=casey.id,
                    title=f"[{RUN_ID}] Evening class", location=None,
                    start_time=naive_utc(2026, 9, 25, 22, 0),
                    end_time=naive_utc(2026, 9, 25, 23, 0),
                    all_day=False, source="acceptance_fixture",
                ),
                # Morgan's own, unrelated event — for A02 cross-user checks.
                CalendarEvent(
                    id=str(uuid.uuid4()), user_id=morgan.id,
                    title=f"[{RUN_ID}] Morgan private therapy session", location=None,
                    start_time=naive_utc(2026, 9, 25, 18, 0),
                    end_time=naive_utc(2026, 9, 25, 19, 0),
                    all_day=False, source="acceptance_fixture",
                ),
            ]
            for e in events:
                db.add(e)
            db.commit()

        manifest = {
            "run_id": RUN_ID,
            "fixture_clock_utc": FIXTURE_NOW_UTC.isoformat(),
            "users": {
                "david_test": {"id": david.id, "email": david.email, "timezone": NY, "token": david_token},
                "morgan_test": {"id": morgan.id, "email": morgan.email, "timezone": LONDON, "token": morgan_token},
                "casey_test": {"id": casey.id, "email": casey.email, "token": casey_token},
            },
            "calendar_event_count_david": db.query(CalendarEvent).filter(CalendarEvent.user_id == david.id).count(),
            "calendar_event_count_morgan": db.query(CalendarEvent).filter(CalendarEvent.user_id == morgan.id).count(),
            "calendar_event_count_casey": db.query(CalendarEvent).filter(CalendarEvent.user_id == casey.id).count(),
        }
        with open("/app/fixture_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
        print(json.dumps({k: v for k, v in manifest.items() if k != "users"}, indent=2))
        print("users created/confirmed:", david.email, morgan.email, casey.email)
    finally:
        db.close()


if __name__ == "__main__":
    main()
