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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

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
            since = datetime.utcnow() - timedelta(days=lookback_days)
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

            for (normalized, dow), events in groups.items():
                if len(events) < 3:
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
            now = datetime.utcnow()
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
