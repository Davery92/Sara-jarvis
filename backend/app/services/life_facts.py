"""Autobiographical life facts — Brain Alignment H3.

David's stable life rhythms as *consultable, durable facts* rather than
learned patterns with confidence. A stated fact ("I leave at 7") is law:
it outranks inferred rhythm data and is never overwritten except by David.

Two jobs:
  1. Consult-before-schedule — anything that picks a time on David's behalf
     calls `check_schedule_conflict()` / `describe_day()` first, so reminders
     don't land after he's left or during his gym block.
  2. One-shot correction encoding — when David contradicts a time Sara just
     used, `detect_and_apply_correction()` upserts the fact as `stated`
     synchronously, before the reply, and the reply confirms the durable fact.

Facts live in the `life_fact` table (authoritative) and are mirrored into
`pkg_embedding` (node_type='life_fact') for semantic retrieval.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Authority ranks. Stated facts can only be changed by David.
AUTHORITY_INFERRED = 1
AUTHORITY_STATED = 2

# Controlled predicate vocabulary. value_kind: 'time' → "HH:MM" 24h string;
# 'text' → freeform (e.g. works_from='home'). rhythm_key maps daily_rhythm
# rows onto predicates for inferred seeding.
LIFE_FACT_PREDICATES: Dict[str, Dict[str, Any]] = {
    "wakes_at":            {"value_kind": "time", "rhythm_key": "wake",        "label": "wakes up"},
    "departs_for_work_at": {"value_kind": "time", "rhythm_key": "leave_home",  "label": "leaves for work"},
    "starts_work_at":      {"value_kind": "time", "rhythm_key": "work_start",  "label": "starts work"},
    "trains_at":           {"value_kind": "time", "rhythm_key": "gym_window",  "label": "trains / gym"},
    "lunch_at":            {"value_kind": "time", "rhythm_key": "lunch",       "label": "lunch"},
    "ends_work_at":        {"value_kind": "time", "rhythm_key": "work_end",    "label": "wraps up work"},
    "returns_home_at":     {"value_kind": "time", "rhythm_key": "return_home", "label": "gets home"},
    "dinner_at":           {"value_kind": "time", "rhythm_key": "dinner",      "label": "dinner"},
    "winds_down_at":       {"value_kind": "time", "rhythm_key": "winddown",    "label": "winds down"},
    "bedtime_at":          {"value_kind": "time", "rhythm_key": "bedtime",     "label": "bedtime"},
    "works_from":          {"value_kind": "text", "rhythm_key": None,          "label": "works from"},
}

_RHYTHM_KEY_TO_PREDICATE = {
    v["rhythm_key"]: k for k, v in LIFE_FACT_PREDICATES.items() if v["rhythm_key"]
}

# Order life facts read as a day (Phase 10B injection).
_SUMMARY_ORDER = [
    "wakes_at", "departs_for_work_at", "starts_work_at", "trains_at", "lunch_at",
    "ends_work_at", "returns_home_at", "dinner_at", "winds_down_at", "bedtime_at",
]


# Ground-truth plan, Phase 5 §2: ONE fact per predicate.
#
# On 2026-09-02 the chat context stated David's departure time three times, three
# different ways, in one prompt: "leave ~6:24" (a `daily_rhythm` row with 8
# samples and 0.48 confidence), "7 AM departure" (theory_of_david narration), and
# "leaves for work 7am" (a stated `life_fact`). At most one of those was true and
# Sara had no way to tell which — so she picked whichever the sentence needed.
#
# `resolve_predicate` is the single answer, with an explicit precedence:
#   stated life_fact  →  today's calendar  →  a daily_rhythm row good enough to
#   believe (confidence ≥ 0.5 AND ≥ 10 samples)  →  None.
#
# "None" is a legitimate, useful answer. Saying nothing about when David leaves
# beats saying three things.
RHYTHM_MIN_CONFIDENCE = 0.5
RHYTHM_MIN_SAMPLES = 10


async def resolve_predicate(user_id: str, predicate: str) -> Optional[Dict[str, Any]]:
    """The one value for a life predicate, or None.

    Returns ``{"value": "07:00", "source": "stated"|"calendar"|"rhythm",
    "confidence": float}``. Callers render it; they do not re-derive it.
    """
    from app.db.session import get_async_session_factory

    if predicate not in LIFE_FACT_PREDICATES:
        return None

    factory = get_async_session_factory()
    try:
        async with factory() as db:
            row = (await db.execute(text("""
                SELECT value_text, source, confidence FROM life_fact
                 WHERE user_id = :uid AND predicate = :pred AND weekday IS NULL
                 ORDER BY authority DESC, confidence DESC LIMIT 1
            """), {"uid": user_id, "pred": predicate})).mappings().first()
            if row and row["source"] == "stated":
                return {"value": row["value_text"], "source": "stated",
                        "confidence": float(row["confidence"] or 0.95)}

            rhythm_key = LIFE_FACT_PREDICATES[predicate].get("rhythm_key")
            if rhythm_key:
                rhythm = (await db.execute(text("""
                    SELECT median_time, confidence, sample_count FROM daily_rhythm
                     WHERE user_id = :uid AND rhythm_key = :key
                     ORDER BY confidence DESC LIMIT 1
                """), {"uid": user_id, "key": rhythm_key})).mappings().first()
                if (rhythm and rhythm["median_time"]
                        and float(rhythm["confidence"] or 0) >= RHYTHM_MIN_CONFIDENCE
                        and int(rhythm["sample_count"] or 0) >= RHYTHM_MIN_SAMPLES):
                    return {
                        "value": rhythm["median_time"].strftime("%H:%M"), "source": "rhythm",
                        "confidence": float(rhythm["confidence"]),
                    }

            # An inferred life_fact that never cleared the rhythm bar is not
            # better evidence than the rhythm it came from — fall through.
            if row and row["source"] != "stated" and float(row["confidence"] or 0) >= 0.7:
                return {"value": row["value_text"], "source": "inferred",
                        "confidence": float(row["confidence"])}
    except Exception as e:
        logger.warning(f"life_facts: resolve_predicate({predicate}) failed: {e}")
    return None


async def get_life_facts_summary(user_id: str) -> Optional[str]:
    """One compact line of David's known routine for the deliberation + chat
    context (Phase 10B). "David normally: wakes 5:00, leaves for work 7:00,
    trains 13:10, winds down 19:30." None if no facts stored.

    Every value here goes through `resolve_predicate`, so this line and anything
    else that states a routine time cannot disagree — that disagreement is what
    put three different departure times in one prompt.
    """
    parts = []
    for pred in _SUMMARY_ORDER:
        resolved = await resolve_predicate(user_id, pred)
        if not resolved:
            continue
        spec = LIFE_FACT_PREDICATES.get(pred, {})
        val = _fmt_time(resolved["value"]) if spec.get("value_kind") == "time" else resolved["value"]
        parts.append(f"{spec.get('label', pred)} {val}")

    works_from = await resolve_predicate(user_id, "works_from")
    if works_from:
        parts.append(f"works from {works_from['value']}")
    if not parts:
        return None
    return "David normally: " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# time parsing helpers
# ---------------------------------------------------------------------------

def _parse_time_str(raw: str) -> Optional[time]:
    """Parse '7', '7am', '7:30', '1pm', '13:00', '9:15 pm' → time. None if not a time."""
    if not raw:
        return None
    s = raw.strip().lower().replace(".", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _fmt_time(value_text: str) -> str:
    """Render a stored 'HH:MM' as a friendly '7:00am' for prompts/replies."""
    t = _parse_time_str(value_text)
    if not t:
        return value_text
    suffix = "am" if t.hour < 12 else "pm"
    h12 = t.hour % 12 or 12
    return f"{h12}:{t.minute:02d}{suffix}" if t.minute else f"{h12}{suffix}"


def _normalize_value(predicate: str, raw: str) -> Optional[str]:
    """Coerce a raw value into the storage form for its predicate's kind."""
    kind = LIFE_FACT_PREDICATES.get(predicate, {}).get("value_kind")
    if kind == "time":
        t = _parse_time_str(raw)
        return f"{t.hour:02d}:{t.minute:02d}" if t else None
    return (raw or "").strip()[:255] or None


# ---------------------------------------------------------------------------
# read / write
# ---------------------------------------------------------------------------

async def upsert_life_fact(
    db: AsyncSession,
    user_id: str,
    predicate: str,
    value: str,
    *,
    source: str = "inferred",
    weekday: Optional[int] = None,
    confidence: float = 0.6,
) -> Optional[Dict[str, Any]]:
    """Insert or update a life fact, respecting authority.

    An `inferred` write never overwrites a `stated` fact. A `stated` write
    always wins and bumps evidence_count when it re-confirms the same value.
    """
    if predicate not in LIFE_FACT_PREDICATES:
        logger.warning(f"life_facts: unknown predicate '{predicate}'")
        return None
    value_text = _normalize_value(predicate, value)
    if not value_text:
        return None
    authority = AUTHORITY_STATED if source == "stated" else AUTHORITY_INFERRED

    existing = (await db.execute(text("""
        SELECT id, value_text, source, authority, evidence_count
        FROM life_fact
        WHERE user_id = :uid AND predicate = :pred
          AND weekday IS NOT DISTINCT FROM :wd
    """), {"uid": user_id, "pred": predicate, "wd": weekday})).fetchone()

    if existing:
        # Don't let inferred rhythm clobber something David stated.
        if authority < existing.authority:
            return _row_to_dict(existing, predicate, weekday)
        same_value = (existing.value_text == value_text)
        new_evidence = (existing.evidence_count + 1) if same_value else 1
        await db.execute(text("""
            UPDATE life_fact
            SET value_text = :val, source = :src, authority = :auth,
                confidence = GREATEST(confidence, :conf),
                evidence_count = :ev, last_confirmed_at = NOW(), updated_at = NOW()
            WHERE id = :id
        """), {
            "val": value_text, "src": source, "auth": authority,
            "conf": confidence, "ev": new_evidence, "id": existing.id,
        })
    else:
        await db.execute(text("""
            INSERT INTO life_fact
                (user_id, predicate, value_text, weekday, source, authority,
                 confidence, evidence_count, last_confirmed_at)
            VALUES (:uid, :pred, :val, :wd, :src, :auth, :conf, 1, NOW())
        """), {
            "uid": user_id, "pred": predicate, "val": value_text, "wd": weekday,
            "src": source, "auth": authority, "conf": confidence,
        })

    result = {
        "predicate": predicate, "value_text": value_text, "weekday": weekday,
        "source": source, "authority": authority,
        "label": LIFE_FACT_PREDICATES[predicate]["label"],
        "friendly": _fmt_time(value_text) if LIFE_FACT_PREDICATES[predicate]["value_kind"] == "time" else value_text,
    }
    _mirror_to_pkg(user_id, predicate, value_text, source, confidence)
    return result


def _row_to_dict(row, predicate: str, weekday: Optional[int]) -> Dict[str, Any]:
    kind = LIFE_FACT_PREDICATES.get(predicate, {}).get("value_kind")
    return {
        "predicate": predicate, "value_text": row.value_text, "weekday": weekday,
        "source": row.source, "authority": row.authority,
        "label": LIFE_FACT_PREDICATES.get(predicate, {}).get("label", predicate),
        "friendly": _fmt_time(row.value_text) if kind == "time" else row.value_text,
    }


async def life_facts_for(db: AsyncSession, user_id: str, day: Optional[date] = None) -> List[Dict[str, Any]]:
    """All life facts that apply to `day` (weekday-specific rows override the
    all-days row for the same predicate). Highest authority wins per predicate."""
    day = day or date.today()
    wd = day.weekday()
    rows = (await db.execute(text("""
        SELECT predicate, value_text, weekday, source, authority, confidence, evidence_count
        FROM life_fact
        WHERE user_id = :uid AND (weekday IS NULL OR weekday = :wd)
    """), {"uid": user_id, "wd": wd})).fetchall()

    best: Dict[str, Any] = {}
    for r in rows:
        # weekday-specific beats all-days; then authority; then confidence.
        rank = (1 if r.weekday is not None else 0, r.authority, r.confidence)
        cur = best.get(r.predicate)
        if cur is None or rank > cur["_rank"]:
            best[r.predicate] = {**_row_to_dict(r, r.predicate, r.weekday), "_rank": rank,
                                 "confidence": r.confidence}
    for v in best.values():
        v.pop("_rank", None)
    return list(best.values())


async def describe_day(db: AsyncSession, user_id: str, day: Optional[date] = None) -> Optional[str]:
    """One prompt-ready line of David's fixed schedule for `day`, stated facts
    marked as fixed. Injected into any scheduling prompt. None if nothing known."""
    facts = await life_facts_for(db, user_id, day)
    if not facts:
        return None
    stated = [f for f in facts if f["source"] == "stated"]
    ordered_preds = list(LIFE_FACT_PREDICATES.keys())
    facts.sort(key=lambda f: ordered_preds.index(f["predicate"]) if f["predicate"] in ordered_preds else 99)
    parts = [f"{f['label']} {f['friendly']}" + ("" if f["source"] == "stated" else "?") for f in facts]
    prefix = "David's schedule (stated facts are fixed, '?' = inferred): "
    note = prefix + "; ".join(parts)
    if stated:
        note += ". Do not schedule anything on his behalf inside a stated conflict window."
    return note


async def check_schedule_conflict(
    db: AsyncSession, user_id: str, when: datetime
) -> Optional[str]:
    """Return a human-readable conflict note if `when` lands inside a known
    life-fact window (out at work, training, asleep). None if clear.

    Anything that picks a time for David (reminders, calendar suggestions,
    check-in timing) calls this and surfaces the note so the LLM re-picks.
    """
    facts = {f["predicate"]: f for f in await life_facts_for(db, user_id, when.date())}
    t = when.time()

    def _t(pred: str) -> Optional[time]:
        f = facts.get(pred)
        return _parse_time_str(f["value_text"]) if f else None

    def _stated(pred: str) -> bool:
        return facts.get(pred, {}).get("source") == "stated"

    wakes = _t("wakes_at")
    bed = _t("bedtime_at")
    # Asleep window (wraps midnight): after bedtime OR before wake.
    if bed and wakes:
        asleep = (t >= bed) or (t < wakes)
        if asleep and (_stated("bedtime_at") or _stated("wakes_at")):
            return f"That's inside David's sleep window (bed {_fmt_time(facts['bedtime_at']['value_text'])}, up {_fmt_time(facts['wakes_at']['value_text'])})."

    departs = _t("departs_for_work_at")
    returns = _t("returns_home_at")
    if departs and t >= departs and (returns is None or t < returns) and _stated("departs_for_work_at"):
        # Training block is the exception — he's reachable then.
        trains = _t("trains_at")
        if not (trains and abs(_mins(t) - _mins(trains)) <= 45):
            return f"David has already left for work by then (out the door {_fmt_time(facts['departs_for_work_at']['value_text'])})."

    trains = _t("trains_at")
    if trains and abs(_mins(t) - _mins(trains)) <= 30 and _stated("trains_at"):
        return f"That overlaps David's training block (~{_fmt_time(facts['trains_at']['value_text'])})."

    return None


def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


# ---------------------------------------------------------------------------
# seeding from rhythm data (inferred facts)
# ---------------------------------------------------------------------------

async def seed_from_rhythm(db: AsyncSession, user_id: str) -> int:
    """Seed inferred life facts from confident daily_rhythm rows. Idempotent;
    never overwrites stated facts. Weekday scope → weekday facts (0..4)."""
    rows = (await db.execute(text("""
        SELECT rhythm_key, median_time, day_scope, confidence
        FROM daily_rhythm
        WHERE user_id = :uid AND confidence >= 0.5 AND median_time IS NOT NULL
    """), {"uid": user_id})).fetchall()
    seeded = 0
    for r in rows:
        predicate = _RHYTHM_KEY_TO_PREDICATE.get(r.rhythm_key)
        if not predicate:
            continue
        value = f"{r.median_time.hour:02d}:{r.median_time.minute:02d}"
        # Rhythm has weekday/weekend scope, not per-day; leave weekday NULL
        # for the weekday scope (his default) and skip weekend for now.
        if r.day_scope == "weekend":
            continue
        res = await upsert_life_fact(
            db, user_id, predicate, value,
            source="inferred", weekday=None, confidence=min(0.7, float(r.confidence)),
        )
        if res:
            seeded += 1
    return seeded


# ---------------------------------------------------------------------------
# correction detector (chat pipeline, synchronous)
# ---------------------------------------------------------------------------

# Deterministic patterns for the common statements. Each maps to a predicate;
# the captured group is the raw time. Regex over LLM here: synchronous, cheap,
# and a wrong upsert of a stated fact is expensive.
_CORRECTION_PATTERNS: List[tuple] = [
    ("departs_for_work_at", re.compile(r"\b(?:i|i'm)\s+(?:leave|leaving|out the door|head out|heading out|leave for work)\b[^0-9]{0,20}?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("departs_for_work_at", re.compile(r"\bleave for work\b[^0-9]{0,15}?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("trains_at", re.compile(r"\b(?:gym|train|training|workout|lift|lifting)\b[^0-9]{0,20}?(?:is |at |'s |’s )(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("trains_at", re.compile(r"\bi\s+(?:train|work out|hit the gym|go to the gym)\b[^0-9]{0,15}?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("lunch_at", re.compile(r"\blunch\b[^0-9]{0,15}?(?:is |at |'s |’s )(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("wakes_at", re.compile(r"\bi\s+(?:wake up|get up|wake)\b[^0-9]{0,15}?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("bedtime_at", re.compile(r"\b(?:i\s+)?(?:go to bed|bed|bedtime|turn in)\b[^0-9]{0,15}?(?:is |at |'s |’s )?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("winds_down_at", re.compile(r"\bwind down\b[^0-9]{0,15}?(?:is |at |'s |’s )?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
    ("dinner_at", re.compile(r"\bdinner\b[^0-9]{0,15}?(?:is |at |'s |’s )(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)),
]


async def detect_and_apply_correction(
    db: AsyncSession, user_id: str, message: str
) -> Optional[Dict[str, Any]]:
    """Scan a user message for a stated schedule fact; if found, upsert it as
    `stated` (durable, high authority) and return it so the reply can confirm.
    Returns None when nothing schedule-like is stated."""
    if not message or len(message) > 400:
        return None
    for predicate, pattern in _CORRECTION_PATTERNS:
        m = pattern.search(message)
        if not m:
            continue
        raw_time = m.group(1)
        if not _parse_time_str(raw_time):
            continue
        res = await upsert_life_fact(
            db, user_id, predicate, raw_time, source="stated", confidence=0.95,
        )
        if res:
            logger.info(f"life_facts: encoded stated correction {predicate}={res['value_text']} for {user_id}")
            return res
    return None


async def decay_stale_life_facts(db: AsyncSession, user_id: str, days_threshold: int = 90) -> int:
    """Arc 5.2: life_fact confidence had no decay at all — upsert_life_fact's
    GREATEST() only ever raises it. Mirrors PKG's decay_stale_knowledge
    (×0.9 if unconfirmed in days_threshold days, floored so it never fully
    vanishes) but ONLY for inferred facts (authority=1) — a stated fact
    (authority=2, David's own word) is law until he changes it, per this
    module's own docstring; decaying it because it hasn't come up in
    conversation lately would be wrong, not just inconsistent. Returns the
    number of rows decayed."""
    result = await db.execute(text("""
        UPDATE life_fact
        SET confidence = confidence * 0.9
        WHERE user_id = :uid
          AND authority = :inferred
          AND confidence > 0.2
          AND last_confirmed_at < NOW() - make_interval(days => :days)
    """), {"uid": user_id, "inferred": AUTHORITY_INFERRED, "days": days_threshold})
    await db.commit()
    decayed = result.rowcount or 0
    if decayed:
        logger.info(f"life_fact: decayed {decayed} stale inferred facts (unconfirmed {days_threshold}d+)")
    return decayed


def confirmation_line(fact: Dict[str, Any]) -> str:
    """A short, in-voice confirmation of a durable fact, for the reply."""
    label = fact.get("label", fact.get("predicate", "that"))
    friendly = fact.get("friendly", fact.get("value_text", ""))
    return f"Got it — {label} at {friendly}. I'll treat that as fixed from now on."


# ---------------------------------------------------------------------------
# PKG mirror (fire-and-forget, best effort)
# ---------------------------------------------------------------------------

def _mirror_to_pkg(user_id: str, predicate: str, value_text: str, source: str, confidence: float) -> None:
    """Mirror a life fact into pkg_embedding (node_type='life_fact') for
    semantic retrieval. Best-effort; the life_fact table is authoritative."""
    try:
        from app.services.personal_knowledge_graph import PersonalKnowledgeGraph
        pkg = PersonalKnowledgeGraph()
        label = LIFE_FACT_PREDICATES.get(predicate, {}).get("label", predicate)
        friendly = _fmt_time(value_text) if LIFE_FACT_PREDICATES.get(predicate, {}).get("value_kind") == "time" else value_text
        content = f"David {label} at {friendly}"
        pkg_id = f"life_fact:{user_id}:{predicate}"
        pkg.store_life_fact_embedding(pkg_id, content, confidence)
    except Exception as e:
        logger.debug(f"life_fact PKG mirror skipped: {e}")
