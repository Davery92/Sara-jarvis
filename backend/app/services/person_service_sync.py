"""
Sync (SQLAlchemy Session, not AsyncSession) mirror of person_service.py's
upsert logic — needed because calendar_events.py's iOS sync route uses a
sync Session (Depends(get_db)), not the async engine email_sync/pkg_extractor
use. Deliberately minimal: only what calendar attendee linkage needs
(PHENOMENAL_ASSISTANT_PLAN.md Phase 5.3).
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.person_service import is_bulk_sender

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def link_attendees_to_people(db: Session, user_id: str, attendees: list,
                             event_start_time: Optional[datetime]) -> None:
    """Upsert a person row per attendee with an email. last_interaction_kind
    only becomes 'meeting' (and interaction_count bumps) once the event has
    actually happened — calendar_event.start_time is naive local (ET), so
    compare against a naive ET now, not an aware UTC now."""
    now_utc = datetime.now(timezone.utc)
    now_et_naive = datetime.now(_ET).replace(tzinfo=None)
    is_past = event_start_time is not None and event_start_time <= now_et_naive

    for attendee in attendees:
        email = (attendee.get("email") or "").strip().lower()
        name = (attendee.get("name") or "").strip()
        if not email or is_bulk_sender(email):
            continue
        canonical_name = name or email.split("@")[0]

        row = db.execute(text("""
            SELECT id, canonical_name, emails, aliases FROM person
            WHERE user_id=:u AND emails @> CAST(:email_json AS jsonb) LIMIT 1
        """), {"u": user_id, "email_json": json.dumps([email])}).fetchone()
        if not row:
            row = db.execute(text("""
                SELECT id, canonical_name, emails, aliases FROM person
                WHERE user_id=:u AND canonical_name=:name LIMIT 1
            """), {"u": user_id, "name": canonical_name}).fetchone()

        if row:
            person_id, existing_name, emails, aliases = row
            emails = emails or []
            aliases = aliases or []
            if email not in emails:
                emails = emails + [email]
            if canonical_name != existing_name and canonical_name not in aliases:
                aliases = aliases + [canonical_name]
            if is_past:
                db.execute(text("""
                    UPDATE person SET emails=CAST(:emails AS jsonb), aliases=CAST(:aliases AS jsonb),
                        last_interaction_at=:now, last_interaction_kind='meeting',
                        interaction_count=interaction_count+1, updated_at=:now
                    WHERE id=:id
                """), {"emails": json.dumps(emails), "aliases": json.dumps(aliases), "now": now_utc, "id": person_id})
            else:
                db.execute(text("""
                    UPDATE person SET emails=CAST(:emails AS jsonb), aliases=CAST(:aliases AS jsonb), updated_at=:now
                    WHERE id=:id
                """), {"emails": json.dumps(emails), "aliases": json.dumps(aliases), "now": now_utc, "id": person_id})
        else:
            person_id = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO person (id, user_id, canonical_name, emails, aliases,
                    first_seen_at, last_interaction_at, last_interaction_kind,
                    interaction_count, mention_count, created_at, updated_at)
                VALUES (:id, :u, :name, CAST(:emails AS jsonb), '[]'::jsonb, :now,
                    :last_at, :kind, :icount, 0, :now, :now)
                ON CONFLICT (user_id, canonical_name) DO NOTHING
            """), {"id": person_id, "u": user_id, "name": canonical_name,
                   "emails": json.dumps([email]), "now": now_utc,
                   "last_at": now_utc if is_past else None,
                   "kind": "meeting" if is_past else None,
                   "icount": 1 if is_past else 0})
    db.flush()
