"""
Person service — upserts into the `person` table (PHENOMENAL_ASSISTANT_PLAN.md Phase 2).

Two live sources feed this, both going forward only (no backfill):
  - email_sync: every analyzed inbound email upserts the sender.
  - pkg_extractor: every chat-extracted Person fact bumps a mention.

Dedup is deliberately conservative (plan §12 risk note: "prefer missed merges
over wrong merges"). Identity match order: exact email match in `emails`,
then exact canonical_name match. No fuzzy name matching — two different
"Mike"s stay two rows rather than risk merging strangers.
"""

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_CADENCE_ALPHA = 0.25  # same smoothing as subconscious.update_numeric_baseline

# Bulk/automated senders that shouldn't become "people" David has a relationship
# with. Conservative substring list — false negatives (a real person slipping
# through) are fine, false positives (skipping a real person) are not.
_BULK_SENDER_PATTERNS = [
    "no-reply", "noreply", "donotreply", "do-not-reply", "mailer-daemon",
    "notifications@", "notification@", "notify@", "alerts@", "bounce@",
    "postmaster@", "automated@", "auto-confirm@",
]
_BULK_CATEGORIES = {"newsletter", "notification"}


def is_bulk_sender(sender_email: Optional[str], category: Optional[str] = None) -> bool:
    if category and category.lower() in _BULK_CATEGORIES:
        return True
    s = (sender_email or "").lower()
    return any(p in s for p in _BULK_SENDER_PATTERNS)


async def upsert_person_from_email(
    db: AsyncSession, user_id: str, sender_email: str, sender_name: Optional[str],
    category: Optional[str] = None, direction: str = "email_in",
) -> Optional[str]:
    """Upsert a person from an email sender. Returns the person id, or None if skipped."""
    if not sender_email or is_bulk_sender(sender_email, category):
        return None

    canonical_name = (sender_name or "").strip() or sender_email.split("@")[0]
    now = datetime.now(timezone.utc)

    # Identity match: exact email in `emails` jsonb array first (most reliable).
    row = (await db.execute(text("""
        SELECT id, canonical_name, emails, aliases, last_interaction_at FROM person
        WHERE user_id = :uid AND emails @> CAST(:email_json AS jsonb)
        LIMIT 1
    """), {"uid": user_id, "email_json": _to_jsonb([sender_email])})).fetchone()

    if not row:
        row = (await db.execute(text("""
            SELECT id, canonical_name, emails, aliases, last_interaction_at FROM person
            WHERE user_id = :uid AND canonical_name = :name
            LIMIT 1
        """), {"uid": user_id, "name": canonical_name})).fetchone()

    if row:
        person_id, existing_name, emails, aliases, prior_last_interaction_at = row
        emails = emails or []
        aliases = aliases or []
        if sender_email not in emails:
            emails = emails + [sender_email]
        if canonical_name != existing_name and canonical_name not in aliases:
            aliases = aliases + [canonical_name]
        await db.execute(text("""
            UPDATE person SET
                emails = CAST(:emails AS jsonb), aliases = CAST(:aliases AS jsonb),
                last_interaction_at = :now, last_interaction_kind = :kind,
                interaction_count = interaction_count + 1, updated_at = :now
            WHERE id = :id
        """), {"emails": _to_jsonb(emails), "aliases": _to_jsonb(aliases),
               "now": now, "kind": direction, "id": person_id})
        await _bump_cadence(db, user_id, person_id, prior_last_interaction_at, now)
        return person_id

    person_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO person (id, user_id, canonical_name, emails, aliases,
            first_seen_at, last_interaction_at, last_interaction_kind,
            interaction_count, mention_count, created_at, updated_at)
        VALUES (:id, :uid, :name, CAST(:emails AS jsonb), '[]'::jsonb, :now, :now, :kind, 1, 0, :now, :now)
        ON CONFLICT (user_id, canonical_name) DO NOTHING
    """), {"id": person_id, "uid": user_id, "name": canonical_name,
           "emails": _to_jsonb([sender_email]), "now": now, "kind": direction})
    return person_id


async def bump_person_mention(db: AsyncSession, user_id: str, canonical_name: str,
                               pkg_person_ref: Optional[str] = None) -> Optional[str]:
    """Upsert/bump a person from a chat-extracted mention (pkg_extractor)."""
    canonical_name = (canonical_name or "").strip()
    if not canonical_name:
        return None
    now = datetime.now(timezone.utc)

    row = (await db.execute(text("""
        SELECT id, last_interaction_at FROM person WHERE user_id = :uid AND canonical_name = :name LIMIT 1
    """), {"uid": user_id, "name": canonical_name})).fetchone()

    if row:
        person_id, prior_last_interaction_at = row
        await db.execute(text("""
            UPDATE person SET
                mention_count = mention_count + 1,
                last_interaction_at = :now, last_interaction_kind = 'mention',
                pkg_person_ref = COALESCE(:ref, pkg_person_ref), updated_at = :now
            WHERE id = :id
        """), {"now": now, "ref": pkg_person_ref, "id": person_id})
        await _bump_cadence(db, user_id, person_id, prior_last_interaction_at, now)
        return person_id

    person_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO person (id, user_id, canonical_name, emails, aliases, pkg_person_ref,
            first_seen_at, last_interaction_at, last_interaction_kind,
            interaction_count, mention_count, created_at, updated_at)
        VALUES (:id, :uid, :name, '[]'::jsonb, '[]'::jsonb, :ref, :now, :now, 'mention', 0, 1, :now, :now)
        ON CONFLICT (user_id, canonical_name) DO NOTHING
    """), {"id": person_id, "uid": user_id, "name": canonical_name, "ref": pkg_person_ref, "now": now})
    return person_id


async def bump_meeting_attendees(db: AsyncSession, user_id: str, attendees: list) -> int:
    """SARA_UNLEASHED Phase D.5: when a meeting genuinely ends, its attendees
    get an interaction bump (last_interaction_kind='meeting'). Distinct from
    person_service_sync.link_attendees_to_people, which only bumps at
    calendar-SYNC time if the event already happened to be in the past at
    that moment — most meetings sync BEFORE they happen, so that path alone
    would rarely fire the bump for a real meeting. Call this from the
    ended-meeting scan instead, when the event has actually just concluded.
    Returns the number of attendees bumped."""
    now = datetime.now(timezone.utc)
    bumped = 0
    for attendee in attendees or []:
        email = (attendee.get("email") or "").strip().lower()
        name = (attendee.get("name") or "").strip()
        if not email or is_bulk_sender(email):
            continue
        canonical_name = name or email.split("@")[0]

        row = (await db.execute(text("""
            SELECT id, canonical_name, emails, aliases, last_interaction_at FROM person
            WHERE user_id = :uid AND emails @> CAST(:email_json AS jsonb) LIMIT 1
        """), {"uid": user_id, "email_json": _to_jsonb([email])})).fetchone()
        if not row:
            row = (await db.execute(text("""
                SELECT id, canonical_name, emails, aliases, last_interaction_at FROM person
                WHERE user_id = :uid AND canonical_name = :name LIMIT 1
            """), {"uid": user_id, "name": canonical_name})).fetchone()

        if row:
            person_id, existing_name, emails, aliases, prior_last_interaction_at = row
            emails = emails or []
            aliases = aliases or []
            if email not in emails:
                emails = emails + [email]
            if canonical_name != existing_name and canonical_name not in aliases:
                aliases = aliases + [canonical_name]
            await db.execute(text("""
                UPDATE person SET emails = CAST(:emails AS jsonb), aliases = CAST(:aliases AS jsonb),
                    last_interaction_at = :now, last_interaction_kind = 'meeting',
                    interaction_count = interaction_count + 1, updated_at = :now
                WHERE id = :id
            """), {"emails": _to_jsonb(emails), "aliases": _to_jsonb(aliases), "now": now, "id": person_id})
            await _bump_cadence(db, user_id, person_id, prior_last_interaction_at, now)
        else:
            person_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO person (id, user_id, canonical_name, emails, aliases,
                    first_seen_at, last_interaction_at, last_interaction_kind,
                    interaction_count, mention_count, created_at, updated_at)
                VALUES (:id, :uid, :name, CAST(:emails AS jsonb), '[]'::jsonb, :now, :now, 'meeting', 1, 0, :now, :now)
                ON CONFLICT (user_id, canonical_name) DO NOTHING
            """), {"id": person_id, "uid": user_id, "name": canonical_name,
                   "emails": _to_jsonb([email]), "now": now})
        bumped += 1
    return bumped


async def _bump_cadence(db: AsyncSession, user_id: str, person_id: str,
                         prior_last_interaction_at, now: datetime) -> None:
    """EWMA of the gap (in hours) between this person's interactions — feeds
    reconnect_overdue in subconscious.py. Reuses signal_baseline (domain=people,
    signal_key=cadence.<person_id>), the same async-safe math as
    subconscious.update_numeric_baseline (that one is sync, this context isn't)."""
    if not prior_last_interaction_at:
        return
    gap_hours = (now - prior_last_interaction_at).total_seconds() / 3600.0
    if gap_hours <= 0:
        return
    signal_key = f"cadence.{person_id}"
    row = (await db.execute(text("""
        SELECT ewma, ewmvar, sample_count FROM signal_baseline
        WHERE user_id=:u AND domain='people' AND signal_key=:k
    """), {"u": user_id, "k": signal_key})).fetchone()

    if not row or row[0] is None:
        await db.execute(text("""
            INSERT INTO signal_baseline (id, user_id, domain, signal_key, ewma, ewmvar,
                last_value, sample_count, last_observed_at, updated_at)
            VALUES (:id, :u, 'people', :k, :v, 0, :v, 1, :ts, :ts)
            ON CONFLICT (user_id, domain, signal_key) DO UPDATE
              SET ewma=:v, last_value=:v, sample_count=signal_baseline.sample_count+1,
                  last_observed_at=:ts, updated_at=:ts
        """), {"id": str(uuid.uuid4()), "u": user_id, "k": signal_key, "v": gap_hours, "ts": now})
        return

    ewma_prev, ewmvar_prev, n = row[0], row[1] or 0.0, row[2] or 0
    delta = gap_hours - ewma_prev
    ewma = ewma_prev + _CADENCE_ALPHA * delta
    ewmvar = (1 - _CADENCE_ALPHA) * (ewmvar_prev + _CADENCE_ALPHA * delta * delta)
    await db.execute(text("""
        UPDATE signal_baseline SET ewma=:e, ewmvar=:var, last_value=:v,
               sample_count=:n, last_observed_at=:ts, updated_at=:ts
        WHERE user_id=:u AND domain='people' AND signal_key=:k
    """), {"e": ewma, "var": ewmvar, "v": gap_hours, "n": n + 1, "ts": now,
           "u": user_id, "k": signal_key})


def _to_jsonb(values: list) -> str:
    import json
    return json.dumps(values)
