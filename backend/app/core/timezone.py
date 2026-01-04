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
