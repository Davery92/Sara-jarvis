"""Durable corrections — conversation competence plan Phase 3.

life_facts.py already proved the pattern for one narrow correction shape (a
stated schedule time): synchronous, deterministic detection; an authoritative
upsert; a stated fact outranks anything inferred. This module generalizes
that pattern to the shapes David's actual corrections take beyond schedule
times: a fact was wrong, an event isn't his to attend, a preference changed,
an action must not repeat, something was retracted, or an exception applies
just this once.

A correction is not a chat reply. Its source is either an explicit user
statement (`source_turn` carries David's own words) or a real action he took
(a UI delete, `source_turn=None`, `explicit=False`) — never the assistant's
own apology or paraphrase, which proves nothing about what David actually
said or did.

Scope matters as much as the correction itself: "not attending this open
house" (scope="this_instance" or an interval) is not "never attends school
events" (scope="permanent"). Getting that wrong in either direction is its
own failure mode. That cuts both ways here: a bare "don't do that again" in
chat has no reliable referent without a coreference resolver, so this module
deliberately never turns one into a blanket, permanent ban on a whole tool —
that would repeat the exact overreach (one bad entry silently disabling all
future food logging) it exists to prevent. The correctly-scoped mechanism for
"don't recreate the entry" is content-fingerprinted retraction, tied to what
was actually removed (see `find_retracted_match`), not a tool-wide switch.

Read-time overlay, not a background rewrite: `get_active_corrections` and
`find_retracted_match` are called directly by the things that need to know
(a logging tool before it writes, a calendar renderer before it prints a
line), so a correction takes effect on its very next read — it does not wait
for some other projection to notice and catch up.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CORRECTION_TYPES = (
    "factual_correction", "event_attendance", "preference",
    "prohibition", "retraction", "temporary_exception",
)


def _tokenize(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


async def record_correction(
    db: AsyncSession,
    user_id: str,
    *,
    correction_type: str,
    subject: str,
    predicate: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    scope: str = "permanent",
    effective_until=None,
    superseded_ids: Optional[List[str]] = None,
    source_turn: Optional[str] = None,
    explicit: bool = True,
) -> Dict[str, Any]:
    """Persist a correction. Idempotent: re-recording the same (user, type,
    subject, new_value, scope) while an identical one is already active is a
    no-op — a retried request or a duplicate detection in the same turn must
    not pile up rows that would otherwise all read as independent evidence."""
    if correction_type not in CORRECTION_TYPES:
        raise ValueError(f"unknown correction_type: {correction_type}")

    existing = (await db.execute(text("""
        SELECT id FROM correction
        WHERE user_id = :uid AND correction_type = :ctype AND subject = :subject
          AND scope = :scope AND active = TRUE
          AND new_value IS NOT DISTINCT FROM :new_value
        ORDER BY created_at DESC LIMIT 1
    """), {
        "uid": user_id, "ctype": correction_type, "subject": subject,
        "scope": scope, "new_value": new_value,
    })).fetchone()
    if existing:
        logger.debug(f"[corrections] idempotent no-op: {correction_type}/{subject} already active")
        return await _get_by_id(db, existing.id)

    row = (await db.execute(text("""
        INSERT INTO correction
            (user_id, correction_type, subject, predicate, old_value, new_value,
             scope, effective_until, superseded_ids, source_turn, explicit)
        VALUES
            (:uid, :ctype, :subject, :predicate, :old_value, :new_value,
             :scope, :effective_until, CAST(:superseded_ids AS jsonb), :source_turn, :explicit)
        RETURNING id
    """), {
        "uid": user_id, "ctype": correction_type, "subject": subject,
        "predicate": predicate, "old_value": old_value, "new_value": new_value,
        "scope": scope, "effective_until": effective_until,
        "superseded_ids": _to_json_array(superseded_ids), "source_turn": source_turn,
        "explicit": explicit,
    })).fetchone()
    logger.info(f"[corrections] recorded {correction_type}/{subject} -> {new_value!r} (scope={scope})")
    return await _get_by_id(db, row.id)


def _to_json_array(ids: Optional[List[str]]) -> str:
    import json
    return json.dumps(ids or [])


async def _get_by_id(db: AsyncSession, correction_id: int) -> Dict[str, Any]:
    row = (await db.execute(text("""
        SELECT id, user_id, correction_type, subject, predicate, old_value, new_value,
               scope, effective_from, effective_until, superseded_ids, source_turn,
               explicit, active, created_at
        FROM correction WHERE id = :id
    """), {"id": correction_id})).mappings().first()
    return dict(row) if row else {}


async def get_active_corrections(
    db: AsyncSession, user_id: str,
    subject: Optional[str] = None,
    subject_prefix: Optional[str] = None,
    correction_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Active, unexpired corrections — the read-time overlay. `subject_prefix`
    matches e.g. 'calendar_event:' to check a whole family at once."""
    clauses = ["user_id = :uid", "active = TRUE",
               "(effective_until IS NULL OR effective_until > NOW())"]
    params: Dict[str, Any] = {"uid": user_id}
    if subject is not None:
        clauses.append("subject = :subject")
        params["subject"] = subject
    if subject_prefix is not None:
        clauses.append("subject LIKE :subject_prefix")
        params["subject_prefix"] = f"{subject_prefix}%"
    if correction_type is not None:
        clauses.append("correction_type = :ctype")
        params["ctype"] = correction_type

    rows = (await db.execute(text(f"""
        SELECT id, correction_type, subject, predicate, old_value, new_value,
               scope, effective_from, effective_until, source_turn, explicit, created_at
        FROM correction
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
    """), params)).mappings().all()
    return [dict(r) for r in rows]


async def find_retracted_match(
    db: AsyncSession, user_id: str, description: str,
    subject_prefix: str = "food_log:", min_overlap: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Does `description` substantially match something already retracted?

    Used by a logging tool to refuse recreating an entry David explicitly
    removed, without banning the tool itself — the retraction is scoped to
    what was actually taken back, not to "never log food again."
    """
    candidates = await get_active_corrections(
        db, user_id, subject_prefix=subject_prefix, correction_type="retraction",
    )
    if not candidates:
        return None
    target_words = _tokenize(description)
    if not target_words:
        return None
    for c in candidates:
        old_words = _tokenize(c.get("old_value") or "")
        if not old_words:
            continue
        overlap = len(target_words & old_words) / max(1, min(len(target_words), len(old_words)))
        if overlap >= min_overlap:
            return c
    return None


# ---------------------------------------------------------------------------
# Chat-level detection (synchronous, deterministic — same rationale as
# life_facts._CORRECTION_PATTERNS: cheap, and a wrong write here is expensive)
# ---------------------------------------------------------------------------

_PROHIBITION_RE = re.compile(
    r"\b(don'?t (do|log|say|suggest|schedule|book|order) (that|it)( again)?|"
    r"stop (doing|logging|suggesting|scheduling) (that|it)|"
    r"never (do|log|suggest|schedule) (that|it) again|"
    r"undo (that|it)|take (that|it) back|"
    r"i (already )?(removed|deleted) (it|that))\b",
    re.IGNORECASE,
)

# Reuses the same "planning vs. eaten" vocabulary food_search_log.py already
# gates on — a message mentioning food alongside prohibition language is the
# only case with a plausible, food-specific referent for "that".
_FOOD_CONTEXT_RE = re.compile(
    r"\b(log|logged|logging|food|meal|eat|eating|ate|breakfast|lunch|dinner|snack)\b",
    re.IGNORECASE,
)


def detect_prohibition(message: str) -> Optional[Dict[str, Any]]:
    """True when `message` contains prohibition/retraction language. Returns
    a hint dict, not a decision — the caller (`apply_chat_prohibition`)
    decides whether that attaches to something specific or is too
    unscoped to act on."""
    if not message:
        return None
    if not _PROHIBITION_RE.search(message):
        return None
    return {"food_context": bool(_FOOD_CONTEXT_RE.search(message))}


async def apply_chat_prohibition(
    db: AsyncSession, user_id: str, message: str,
) -> Optional[Dict[str, Any]]:
    """Chat-stated 'don't do that again'/'I removed it' with food context.

    Never creates a blanket, permanent ban on a whole tool from ambiguous
    chat text alone — attaches to the most recent specific food-log
    retraction (from a real delete, see `record_food_log_retraction`) as
    explicit confirmation if one exists in the last 24h; otherwise records a
    short-lived (24h), unenforced note for the audit trail only, since
    without a specific referent there is nothing safe to act on.
    """
    hint = detect_prohibition(message)
    if not hint or not hint["food_context"]:
        return None

    recent_day = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = await get_active_corrections(
        db, user_id, subject_prefix="food_log:", correction_type="retraction",
    )
    recent = [c for c in recent if c.get("created_at") and c["created_at"] >= recent_day]
    if recent:
        latest = recent[0]
        await db.execute(text(
            "UPDATE correction SET source_turn = :st, explicit = TRUE WHERE id = :id"
        ), {"st": message, "id": latest["id"]})
        latest["source_turn"], latest["explicit"] = message, True
        logger.info(f"[corrections] chat confirmed retraction id={latest['id']} for user {user_id}")
        return latest

    return await record_correction(
        db, user_id, correction_type="prohibition", subject="food_logging:unscoped",
        new_value="prohibited", scope="this_instance",
        effective_until=datetime.now(timezone.utc) + timedelta(hours=24),
        source_turn=message, explicit=True,
    )


async def record_food_log_retraction(
    db: AsyncSession, user_id: str, log_id: str, description: str,
) -> Dict[str, Any]:
    """Called at the moment a food log entry is deleted (routes/fitness.py) —
    the actual ground truth for 'this was removed', independent of whether
    David ever mentions it again in chat. `explicit=False` because a UI
    delete is a real action, not a stated correction; `apply_chat_prohibition`
    upgrades it to explicit if he does bring it up."""
    return await record_correction(
        db, user_id, correction_type="retraction", subject=f"food_log:{log_id}",
        old_value=description, new_value=None, scope="permanent",
        source_turn=None, explicit=False,
    )
