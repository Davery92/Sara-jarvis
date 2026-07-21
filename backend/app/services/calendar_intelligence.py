"""
Calendar Intelligence Service

Adds semantic understanding to calendar events:
- Classifies events by category (sports, family, work, health, social)
- Detects recurring patterns (baseball every Tuesday = kids' practice)
- Infers participants (who is this event for?)
- Upserts detected routines to PKG
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

# Heuristic category mappings
_CATEGORY_RULES = [
    # (pattern, category, likely_participant)
    (r"\b(baseball|soccer|football|basketball|gymnastics|swim|hockey|lacrosse|volleyball|tennis|track|cheer)\b", "sports", "kids"),
    (r"\b(practice|game|tournament|meet|match|tryout|scrimmage)\b", "sports", "kids"),
    (r"\b(recital|concert|play|rehearsal|performance)\b", "arts", "kids"),
    (r"\b(school|pta|parent.teacher|conference|pickup|drop.?off|bus)\b", "school", "kids"),
    (r"\b(dentist|doctor|appointment|checkup|physical|therapy|vet)\b", "health", "self"),
    (r"\b(meeting|standup|sprint|retro|review|1:1|sync|demo|presentation)\b", "work", "self"),
    (r"\b(date|anniversary|birthday|dinner|brunch|lunch)\b", "social", "self"),
    (r"\b(gym|workout|run|yoga|crossfit|lift|peloton)\b", "fitness", "self"),
    (r"\b(flight|travel|hotel|airport|vacation|trip)\b", "travel", "family"),
    (r"\b(church|mass|service|bible|youth.group)\b", "religious", "family"),
]


def _naive_local_now() -> datetime:
    """Return app-local wall clock time as a naive datetime for calendar_event.

    calendar_event.start_time/end_time are stored as naive timestamps, so ACS
    prompt-building queries must compare against naive datetimes in the same
    local timezone semantics or asyncpg will reject the comparison.
    """
    return local_now().replace(tzinfo=None)


def classify_event(title: str, description: str = "") -> Dict[str, Any]:
    """Classify a calendar event by category and likely participant using heuristics."""
    combined = f"{title} {description}".lower()

    for pattern, category, participant in _CATEGORY_RULES:
        if re.search(pattern, combined):
            return {"category": category, "participant": participant}

    return {"category": "other", "participant": "unknown"}


async def extract_patterns(user_id: str, lookback_days: int = 90) -> List[Dict[str, Any]]:
    """
    Detect recurring calendar patterns over the lookback window.

    Groups events by normalized title + day_of_week. Events appearing 3+ times
    on the same weekday are flagged as recurring patterns.
    """
    from app.db.session import get_async_session_factory

    async_session = get_async_session_factory()
    patterns = []

    try:
        async with async_session() as db:
            # Use naive datetime — calendar_event.start_time is DateTime without timezone
            since = _naive_local_now() - timedelta(days=lookback_days)
            result = await db.execute(text("""
                SELECT title, start_time, end_time, location,
                       EXTRACT(DOW FROM start_time) AS dow,
                       EXTRACT(HOUR FROM start_time) AS hour
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time >= :since
                  AND is_completed = FALSE
                ORDER BY start_time
            """), {"uid": user_id, "since": since})
            rows = result.fetchall()

            if not rows:
                return []

            # Group by normalized title + day_of_week
            groups = defaultdict(list)
            for row in rows:
                normalized = _normalize_title(row[0])
                dow = int(row[4])
                key = (normalized, dow)
                groups[key].append({
                    "title": row[0],
                    "start_time": row[1],
                    "end_time": row[2],
                    "location": row[3] or "",
                    "hour": int(row[5]),
                })

            day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

            # A weekly routine is only *live* if it actually happened recently.
            # Without this gate, a routine that ended months ago still sits
            # inside the 90-day lookback (3+ historical occurrences) and gets
            # re-blessed as ongoing — exactly how "Everett has swimming today"
            # survived 3.5 months after lessons ended (P4). 4 weeks of silence
            # for a weekly cadence = dead.
            now_naive = _naive_local_now()
            FRESHNESS_DAYS = 28

            for (normalized, dow), events in groups.items():
                if len(events) < 3:
                    continue

                last_occurrence = max(e["start_time"] for e in events if e["start_time"])
                days_since_last = (now_naive - last_occurrence).days if last_occurrence else 9999
                if days_since_last > FRESHNESS_DAYS:
                    logger.info(
                        f"Calendar intelligence: skipping stale routine "
                        f"'{events[0]['title']}' — last occurrence {days_since_last}d ago"
                    )
                    continue

                # This is a recurring pattern
                classification = classify_event(events[0]["title"])
                avg_hour = sum(e["hour"] for e in events) // len(events)
                typical_location = _most_common([e["location"] for e in events if e["location"]])

                pattern = {
                    "title_pattern": events[0]["title"],
                    "normalized": normalized,
                    "day_of_week": day_names[dow],
                    "dow_number": dow,
                    "typical_hour": avg_hour,
                    "occurrences": len(events),
                    "last_occurrence": last_occurrence.isoformat() if last_occurrence else None,
                    "days_since_last": days_since_last,
                    "category": classification["category"],
                    "participant": classification["participant"],
                    "location": typical_location,
                    "confidence": min(0.5 + (len(events) * 0.1), 0.95),
                }
                patterns.append(pattern)

            logger.info(f"Calendar intelligence: {len(patterns)} recurring patterns detected")

    except Exception as e:
        logger.error(f"Calendar pattern extraction failed: {e}")

    return patterns


async def sync_patterns_to_pkg(user_id: str, patterns: List[Dict[str, Any]]) -> int:
    """Upsert detected recurring calendar patterns as PKG_Routine facts."""
    try:
        from app.services.personal_knowledge_graph import personal_kg
    except Exception:
        return 0

    synced = 0
    for pattern in patterns:
        try:
            activity = pattern["title_pattern"]
            if pattern["participant"] == "kids":
                activity = f"Kids' {activity}"

            personal_kg.upsert_fact(
                fact_type="Routine",
                properties={
                    "activity": activity,
                    "day_of_week": pattern["day_of_week"],
                    "typical_time": f"{pattern['typical_hour']}:00",
                    "frequency": "weekly",
                    "category": pattern["category"],
                    "participant": pattern["participant"],
                    "location": pattern.get("location", ""),
                    "description": (
                        f"Recurring {pattern['category']} event on {pattern['day_of_week']}s "
                        f"around {pattern['typical_hour']}:00 "
                        f"({pattern['occurrences']} occurrences in last 90 days)"
                    ),
                },
                confidence=pattern["confidence"],
                source="calendar_inference",
            )
            synced += 1
        except Exception as e:
            logger.debug(f"PKG sync failed for pattern {pattern['title_pattern']}: {e}")

    if synced:
        logger.info(f"Calendar intelligence: synced {synced} patterns to PKG")
    return synced


async def get_annotated_schedule(user_id: str, days_ahead: int = 7) -> str:
    """Get upcoming events with semantic annotations, formatted for prompt injection."""
    from app.db.session import get_async_session_factory

    async_session = get_async_session_factory()

    try:
        async with async_session() as db:
            # Use naive datetime — calendar_event.start_time is DateTime without timezone
            now = _naive_local_now()
            until = now + timedelta(days=days_ahead)

            result = await db.execute(text("""
                SELECT title, start_time, end_time, location, all_day
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time >= :now
                  AND start_time <= :until
                  AND is_completed = FALSE
                ORDER BY start_time
                LIMIT 30
            """), {"uid": user_id, "now": now, "until": until})
            rows = result.fetchall()

            if not rows:
                return ""

            # Also get detected patterns for annotation
            patterns = await extract_patterns(user_id, lookback_days=90)
            pattern_lookup = {}
            for p in patterns:
                pattern_lookup[p["normalized"]] = p

            lines = []
            current_date = None
            for row in rows:
                event_date = row[1].strftime("%A %b %d") if row[1] else "?"
                if event_date != current_date:
                    current_date = event_date
                    lines.append(f"\n**{event_date}**")

                time_str = row[1].strftime("%I:%M %p") if row[1] and not row[4] else "All day"
                classification = classify_event(row[0], "")

                # Check if this matches a known pattern
                normalized = _normalize_title(row[0])
                pattern_info = pattern_lookup.get(normalized)

                annotation = ""
                if pattern_info:
                    if pattern_info["participant"] == "kids":
                        annotation = f" [kids' {pattern_info['category']}, recurring]"
                    else:
                        annotation = f" [{pattern_info['category']}, recurring]"
                elif classification["category"] != "other":
                    annotation = f" [{classification['category']}]"

                location = f" @ {row[3]}" if row[3] else ""
                lines.append(f"- {time_str}: {row[0]}{annotation}{location}")

            return "\n".join(lines)

    except Exception as e:
        logger.error(f"Annotated schedule build failed: {e}")
        return ""


def _normalize_title(title: str) -> str:
    """Normalize an event title for grouping (lowercase, strip numbers/dates)."""
    t = title.lower().strip()
    t = re.sub(r'\d+', '', t)  # Strip numbers
    t = re.sub(r'\s+', ' ', t).strip()  # Collapse whitespace
    return t


def _most_common(items: List[str]) -> str:
    """Return the most common non-empty string from a list."""
    if not items:
        return ""
    counts = defaultdict(int)
    for item in items:
        counts[item] += 1
    return max(counts, key=counts.get)


# Prefixes sync_patterns_to_pkg / extraction bolt onto an activity name. Strip
# them so a Routine's `activity` normalizes back to the calendar_event title.
_ROUTINE_PREFIXES = ("kids' ", "kid's ", "david's ", "david ")


def _routine_core(activity: str) -> str:
    """Reduce a Routine's activity string to a normalized calendar-matchable core."""
    a = (activity or "").strip()
    low = a.lower()
    for pfx in _ROUTINE_PREFIXES:
        if low.startswith(pfx):
            a = a[len(pfx):]
            break
    return _normalize_title(a)


async def retire_uncorroborated_routines(user_id: str) -> Dict[str, int]:
    """P4 routine decay: demote, then retire, PKG_Routine nodes whose calendar
    support has dried up.

    ONLY calendar-inferred routines are considered (source='calendar_inference').
    Behavioral routines from other sources — "sleep at 21:00", "leaves for work
    at 07:00", the fitness program — legitimately have no calendar_event and must
    never be retired for lacking one; those schedule facts live in life_fact,
    which is their authoritative store.

    For each such weekly/daily Routine, look for a matching calendar_event in the
    trailing corroboration window (28d weekly, 10d daily). If none:
      - no matching event in the last 90 days at all → retire outright
        (delete Neo4j node + pkg_embedding row together);
      - otherwise decay confidence and, once it falls below the floor, retire.

    Returns {"checked", "decayed", "retired"}. Best-effort; never raises.
    """
    stats = {"checked": 0, "decayed": 0, "retired": 0}
    try:
        from app.services.personal_knowledge_graph import personal_kg
    except Exception:
        return stats

    try:
        routines = personal_kg.browse(category="Routine", limit=200)
    except Exception as e:
        logger.debug(f"routine retirement: browse failed: {e}")
        return stats
    if not routines:
        return stats

    # Pull recent calendar_event titles once, bucketed by age, for matching.
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    recent_titles: List[tuple] = []  # (normalized_title, days_ago)
    try:
        async with async_session() as db:
            since = _naive_local_now() - timedelta(days=90)
            rows = (await db.execute(text("""
                SELECT title, start_time FROM calendar_event
                WHERE user_id = :uid AND start_time >= :since
            """), {"uid": user_id, "since": since})).fetchall()
        now_naive = _naive_local_now()
        for title, st in rows:
            if not title or not st:
                continue
            recent_titles.append((_normalize_title(title), (now_naive - st).days))
    except Exception as e:
        logger.debug(f"routine retirement: calendar fetch failed: {e}")
        return stats

    def _min_age_for(core: str) -> Optional[int]:
        """Smallest days-ago of any calendar_event whose title contains/equals core."""
        ages = [age for (nt, age) in recent_titles if core and (core in nt or nt in core)]
        return min(ages) if ages else None

    for r in routines:
        # Only routines Sara *inferred from the calendar* are held to a calendar
        # corroboration standard. Explicitly-stated and dream-inferred routines
        # (sleep, work departure, the workout plan) never appear as calendar
        # events and must not be retired for their absence.
        if (r.get("source") or "") != "calendar_inference":
            continue
        freq = (r.get("frequency") or "weekly").lower()
        if freq not in ("weekly", "daily"):
            continue  # monthly/occasional aren't calendar-corroborated the same way
        pkg_id = r.get("pkg_id")
        activity = r.get("activity") or r.get("description") or ""
        if not pkg_id or not activity:
            continue
        stats["checked"] += 1

        window = 10 if freq == "daily" else 28
        core = _routine_core(activity)
        min_age = _min_age_for(core)

        if min_age is not None and min_age <= window:
            continue  # corroborated — leave it alone

        # No corroboration in-window. Retire if there is NO instance in 90 days
        # at all, or if a decay has already pushed confidence below the floor.
        conf = float(r.get("confidence") or 0.7)
        if min_age is None:
            personal_kg.retire_node(pkg_id)
            stats["retired"] += 1
            logger.info(f"routine retirement: retired '{activity}' (no calendar support in 90d)")
        else:
            new_conf = personal_kg.decay_node_confidence(pkg_id, factor=0.8)
            if new_conf is not None and new_conf < 0.35:
                personal_kg.retire_node(pkg_id)
                stats["retired"] += 1
                logger.info(f"routine retirement: retired '{activity}' (decayed below floor)")
            else:
                stats["decayed"] += 1
                logger.info(
                    f"routine retirement: decayed '{activity}' "
                    f"(last calendar match {min_age}d ago, conf→{new_conf})"
                )

    if stats["retired"] or stats["decayed"]:
        logger.info(f"Calendar intelligence: routine retirement {stats}")
    return stats
