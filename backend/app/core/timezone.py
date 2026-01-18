"""
Timezone utilities for consistent timezone handling across the application.
All datetime operations should use these helpers to ensure Eastern timezone.
"""

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

# User's timezone - Eastern Time
USER_TIMEZONE = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def now() -> datetime:
    """Get current datetime in user's timezone (Eastern)."""
    return datetime.now(USER_TIMEZONE)


def today() -> date:
    """Get today's date in user's timezone."""
    return now().date()


def now_utc() -> datetime:
    """Get current datetime in UTC (for database storage if needed)."""
    return datetime.now(UTC)


def to_local(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a datetime to user's local timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(USER_TIMEZONE)


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a datetime to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume local if no timezone info
        dt = dt.replace(tzinfo=USER_TIMEZONE)
    return dt.astimezone(UTC)


def format_time(dt: Optional[datetime], fmt: str = "%I:%M %p") -> str:
    """Format a datetime as time string in local timezone."""
    if dt is None:
        return ""
    local_dt = to_local(dt)
    return local_dt.strftime(fmt)


def format_datetime(dt: Optional[datetime], fmt: str = "%Y-%m-%d %I:%M %p") -> str:
    """Format a datetime as full datetime string in local timezone."""
    if dt is None:
        return ""
    local_dt = to_local(dt)
    return local_dt.strftime(fmt)


def format_date(d: Optional[date], fmt: str = "%Y-%m-%d") -> str:
    """Format a date."""
    if d is None:
        return ""
    return d.strftime(fmt)


def parse_datetime(s: str, fmt: str = "%Y-%m-%dT%H:%M:%S") -> Optional[datetime]:
    """Parse a datetime string and return it in local timezone."""
    try:
        dt = datetime.strptime(s, fmt)
        return dt.replace(tzinfo=USER_TIMEZONE)
    except ValueError:
        return None


def start_of_day(d: Optional[date] = None) -> datetime:
    """Get start of day (midnight) in local timezone."""
    if d is None:
        d = today()
    return datetime.combine(d, datetime.min.time(), tzinfo=USER_TIMEZONE)


def end_of_day(d: Optional[date] = None) -> datetime:
    """Get end of day (23:59:59) in local timezone."""
    if d is None:
        d = today()
    return datetime.combine(d, datetime.max.time(), tzinfo=USER_TIMEZONE)


def days_ago(n: int) -> date:
    """Get date N days ago in local timezone."""
    return today() - timedelta(days=n)


def is_today(dt: datetime) -> bool:
    """Check if a datetime is today in local timezone."""
    return to_local(dt).date() == today()


def is_yesterday(dt: datetime) -> bool:
    """Check if a datetime is yesterday in local timezone."""
    return to_local(dt).date() == today() - timedelta(days=1)


def format_iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """
    Format a datetime as ISO string with UTC timezone suffix.

    This ensures JavaScript correctly interprets the timestamp as UTC
    and can convert to the user's local timezone in the browser.
    """
    if dt is None:
        return None
    # If naive datetime, assume it's UTC (from PostgreSQL)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    # Convert to UTC and format with Z suffix
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def relative_time(dt: Optional[datetime], reference: Optional[datetime] = None) -> str:
    """
    Get a human-readable relative time string like "2 days ago" or "just now".

    Args:
        dt: The datetime to describe
        reference: Reference datetime to compare against (defaults to now)

    Returns:
        Human-readable string like "just now", "5 minutes ago", "yesterday",
        "3 days ago", "2 weeks ago", "last month", etc.
    """
    if dt is None:
        return "unknown time"

    # Convert to local timezone for comparison
    local_dt = to_local(dt)
    ref = reference if reference else now()

    diff = ref - local_dt
    seconds = diff.total_seconds()

    # Handle future times (shouldn't happen often with memories)
    if seconds < 0:
        return "in the future"

    # Less than a minute
    if seconds < 60:
        return "just now"

    # Less than an hour
    minutes = int(seconds / 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    # Less than a day
    hours = int(minutes / 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    # Check if it was yesterday
    if is_yesterday(dt):
        return "yesterday"

    # Less than a week
    days = int(hours / 24)
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''} ago"

    # Less than a month (approx 30 days)
    weeks = int(days / 7)
    if days < 30:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"

    # Less than a year
    months = int(days / 30)
    if days < 365:
        return f"{months} month{'s' if months != 1 else ''} ago"

    # More than a year
    years = int(days / 365)
    return f"{years} year{'s' if years != 1 else ''} ago"


def format_memory_timestamp(dt: Optional[datetime]) -> str:
    """
    Format a timestamp for memory context display.
    Shows both absolute date and relative time for clarity.

    Example: "Jan 5 (2 weeks ago)" or "Today at 2:30 PM"
    """
    if dt is None:
        return "unknown time"

    local_dt = to_local(dt)
    rel = relative_time(dt)

    # For today, show time
    if is_today(dt):
        return f"Today at {local_dt.strftime('%I:%M %p')}"

    # For yesterday, show that
    if is_yesterday(dt):
        return f"Yesterday at {local_dt.strftime('%I:%M %p')}"

    # For older dates, show date + relative time
    date_str = local_dt.strftime("%b %d")
    return f"{date_str} ({rel})"
