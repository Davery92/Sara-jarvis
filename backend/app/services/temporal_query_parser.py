"""
Temporal Query Parser — detects time references in natural language queries.

Parses patterns like:
  "what happened Tuesday" → (last_tuesday_00:00, last_tuesday_23:59)
  "last week" → (monday_last_week, sunday_last_week)
  "yesterday morning" → (yesterday_06:00, yesterday_12:00)
  "in January" → (jan_1, jan_31)

Returns (start_datetime, end_datetime) or None if no temporal reference found.
"""

import re
from datetime import datetime, timedelta, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

# Day names → weekday numbers (Monday=0)
_DAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_TIME_OF_DAY = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(21, 0)),
    "night": (time(21, 0), time(23, 59, 59)),
}


def parse_temporal_reference(
    query: str,
    now: Optional[datetime] = None,
    timezone: str = "America/New_York",
) -> Optional[Tuple[datetime, datetime]]:
    """
    Parse natural language time references from a query string.

    Returns (start_datetime, end_datetime) in UTC, or None if no temporal reference found.
    """
    if not query:
        return None

    if now is None:
        try:
            now = datetime.now(ZoneInfo(timezone))
        except Exception:
            now = datetime.now(ZoneInfo("America/New_York"))

    q = query.lower().strip()
    today = now.date()

    # "yesterday"
    if re.search(r'\byesterday\b', q):
        d = today - timedelta(days=1)
        start = datetime.combine(d, time(0, 0))
        end = datetime.combine(d, time(23, 59, 59))
        # Check for time-of-day qualifier
        for period, (t_start, t_end) in _TIME_OF_DAY.items():
            if period in q:
                start = datetime.combine(d, t_start)
                end = datetime.combine(d, t_end)
                break
        return _localize_pair(start, end, now.tzinfo)

    # "today"
    if re.search(r'\btoday\b', q) or re.search(r'\bthis morning\b|\bthis afternoon\b|\bthis evening\b', q):
        d = today
        start = datetime.combine(d, time(0, 0))
        end = datetime.combine(d, time(23, 59, 59))
        for period, (t_start, t_end) in _TIME_OF_DAY.items():
            if period in q:
                start = datetime.combine(d, t_start)
                end = datetime.combine(d, t_end)
                break
        return _localize_pair(start, end, now.tzinfo)

    # "last week"
    if re.search(r'\blast week\b', q):
        days_since_monday = today.weekday()
        last_monday = today - timedelta(days=days_since_monday + 7)
        last_sunday = last_monday + timedelta(days=6)
        return _localize_pair(
            datetime.combine(last_monday, time(0, 0)),
            datetime.combine(last_sunday, time(23, 59, 59)),
            now.tzinfo,
        )

    # "this week"
    if re.search(r'\bthis week\b', q):
        days_since_monday = today.weekday()
        monday = today - timedelta(days=days_since_monday)
        return _localize_pair(
            datetime.combine(monday, time(0, 0)),
            datetime.combine(today, time(23, 59, 59)),
            now.tzinfo,
        )

    # "N days ago"
    m = re.search(r'(\d+)\s+days?\s+ago', q)
    if m:
        n = int(m.group(1))
        d = today - timedelta(days=n)
        return _localize_pair(
            datetime.combine(d, time(0, 0)),
            datetime.combine(d, time(23, 59, 59)),
            now.tzinfo,
        )

    # Day name: "on Tuesday", "last Wednesday"
    for day_name, weekday_num in _DAY_MAP.items():
        pattern = rf'\b(?:on\s+|last\s+)?{day_name}\b'
        if re.search(pattern, q):
            days_back = (today.weekday() - weekday_num) % 7
            if days_back == 0:
                days_back = 7  # "Tuesday" when today is Tuesday means last Tuesday
            d = today - timedelta(days=days_back)
            start = datetime.combine(d, time(0, 0))
            end = datetime.combine(d, time(23, 59, 59))
            for period, (t_start, t_end) in _TIME_OF_DAY.items():
                if period in q:
                    start = datetime.combine(d, t_start)
                    end = datetime.combine(d, t_end)
                    break
            return _localize_pair(start, end, now.tzinfo)

    # Month name: "in January", "last March"
    for month_name, month_num in _MONTH_MAP.items():
        pattern = rf'\b(?:in\s+|last\s+)?{month_name}\b'
        if re.search(pattern, q):
            year = now.year if month_num <= now.month else now.year - 1
            import calendar
            last_day = calendar.monthrange(year, month_num)[1]
            return _localize_pair(
                datetime(year, month_num, 1, 0, 0),
                datetime(year, month_num, last_day, 23, 59, 59),
                now.tzinfo,
            )

    return None


def _localize_pair(start: datetime, end: datetime, tz) -> Tuple[datetime, datetime]:
    """Attach timezone info and convert to UTC."""
    from datetime import timezone as tz_mod
    if tz:
        start = start.replace(tzinfo=tz)
        end = end.replace(tzinfo=tz)
    else:
        start = start.replace(tzinfo=tz_mod.utc)
        end = end.replace(tzinfo=tz_mod.utc)
    return (start.astimezone(tz_mod.utc), end.astimezone(tz_mod.utc))
