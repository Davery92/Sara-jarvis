"""
Timezone utilities for consistent timezone handling across the application.
All datetime operations should use these helpers to ensure Eastern timezone.
"""

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Union

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


def naive_local_now() -> datetime:
    """Current Eastern wall-clock time as a *naive* datetime.

    Use ONLY when writing to a ``timestamp without time zone`` column that stores
    ET wall-clock (the legacy convention in a few tables, e.g. home_state_summary,
    created_at columns). For everything else prefer ``now()`` (aware ET) or
    ``now_utc()``. asyncpg cannot encode an aware datetime into a naive column, so
    the two must be kept consistent — this helper makes that explicit.
    """
    return datetime.now(USER_TIMEZONE).replace(tzinfo=None)


def naive_utc_now() -> datetime:
    """Current UTC time as a *naive* datetime (drop-in for the banned datetime.utcnow()).

    Use ONLY when writing to a ``timestamp without time zone`` column that stores
    naive UTC. Prefer ``now_utc()`` (aware) for new code / timestamptz columns.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce any datetime to naive UTC wall-clock.

    Aware datetimes are converted to UTC then stripped of tzinfo; naive datetimes
    are assumed to already be UTC and returned unchanged. Use when binding a value
    into a ``timestamp without time zone`` column that stores UTC (the convention
    for the reflection/consolidation/action_log tables).
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.replace(tzinfo=None)


def to_naive_local(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce any datetime to naive Eastern wall-clock.

    Aware datetimes are converted to ET then stripped of tzinfo; naive datetimes
    are assumed to already be ET wall-clock and returned unchanged. Use when
    binding a value into a ``timestamp without time zone`` column.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(USER_TIMEZONE)
    return dt.replace(tzinfo=None)


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


def local_day_bounds(d: Optional[date] = None) -> tuple[datetime, datetime]:
    """[start, end) of a local (Eastern) day as **aware** datetimes.

    This is the one right answer to "what does today mean" for any
    ``timestamp with time zone`` column — `health_metric.recorded_at` chief
    among them. Binding a *naive* ET midnight against a timestamptz column on a
    UTC session made "today" start at 8 PM ET the previous day, which is how a
    2026-08-31 health snapshot could pick up the evening-before's readings and
    miss the morning's (see HEALTH_DATA_ACCURACY_FIX_PLAN, D5).

    For the legacy naive-ET columns (calendar_event.start_time, the various
    created_at columns) use ``naive_local_day_bounds`` instead — asyncpg can't
    encode an aware datetime into a naive column.
    """
    if d is None:
        d = today()
    start = datetime.combine(d, datetime.min.time(), tzinfo=USER_TIMEZONE)
    return start, start + timedelta(days=1)


def naive_local_day_bounds(d: Optional[date] = None) -> tuple[datetime, datetime]:
    """[start, end) of a local (Eastern) day as *naive* ET wall-clock — the
    correct bounds for a ``timestamp without time zone`` column storing ET."""
    start, end = local_day_bounds(d)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


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


def render_relative(dt: Optional[datetime], reference: Optional[datetime] = None) -> str:
    """Bidirectional relative-time phrasing for prompts (SARA_MIND_V2 §5.2):
    "3 days ago" for the past, "in 2 hours" / "in 2 days" for the future.
    `relative_time()` above only handles the past (memory-timestamp use
    case) and collapses every future moment to "in the future" — too coarse
    for the World Brief's AHEAD section, which needs to say when a prepped
    meeting actually is. A naked ISO timestamp in a prompt is a bug per the
    plan's time-correctness rules; this is the sanctioned way to render one
    for model consumption instead."""
    if dt is None:
        return "unknown time"

    local_dt = to_local(dt)
    ref = reference if reference else now()
    diff = local_dt - ref
    seconds = diff.total_seconds()

    if seconds <= 0:
        return relative_time(dt, reference=ref)

    if seconds < 60:
        return "in a moment"

    minutes = int(seconds / 60)
    if minutes < 60:
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"

    hours = int(minutes / 60)
    if hours < 24:
        remaining_minutes = minutes % 60
        if remaining_minutes and hours < 4:
            return f"in {hours}h {remaining_minutes}m"
        return f"in {hours} hour{'s' if hours != 1 else ''}"

    if local_dt.date() == ref.date() + timedelta(days=1):
        return f"tomorrow at {local_dt.strftime('%-I:%M %p')}"

    days = int(hours / 24)
    if days < 7:
        return f"in {days} day{'s' if days != 1 else ''} ({local_dt.strftime('%A')})"

    weeks = int(days / 7)
    if days < 30:
        return f"in {weeks} week{'s' if weeks != 1 else ''}"

    months = int(days / 30)
    if days < 365:
        return f"in {months} month{'s' if months != 1 else ''}"

    years = int(days / 365)
    return f"in {years} year{'s' if years != 1 else ''}"


def _delta_phrase(seconds: float) -> str:
    """"in 3h 10m" / "2h ago" / "now" — the parenthetical half of render_when."""
    past = seconds < 0
    seconds = abs(seconds)
    if seconds < 90:
        return "now"

    minutes = int(seconds // 60)
    if minutes < 60:
        body = f"{minutes}m"
    elif minutes < 60 * 24:
        hours, rest = divmod(minutes, 60)
        body = f"{hours}h {rest}m" if rest and hours < 6 else f"{hours}h"
    else:
        days, rest_minutes = divmod(minutes, 60 * 24)
        hours = rest_minutes // 60
        body = f"{days}d {hours}h" if hours and days < 3 else f"{days}d"
    return f"{body} ago" if past else f"in {body}"


def render_when(
    dt: Union[datetime, date, None],
    now: Optional[datetime] = None,
    source_convention: Optional[str] = None,
    all_day: bool = False,
) -> str:
    """The one way a moment is allowed to reach a prompt or a message.

    Ground-truth invariant 4, "one clock": no timestamp reaches a model or David
    except through here. Sara had three conventions in flight at once —
    `world_thread.due_at` in UTC handed raw to prompts, `calendar_event.start_time`
    naive ET, `notification_ack` formatting UTC with `%a %H:%M` — so a thread due
    1:00 PM ET was announced as "your 5:00 AM EDT call" and a journal entry
    written at 5:38 AM said 9:38 AM.

    Returns e.g. ``"Tue Sep 1, 1:00 PM ET (in 3h 10m)"``, or ``"Thu Sep 3 (all
    day)"`` for a date. Empty string for None — a missing time renders as nothing,
    never as midnight.

    A *naive* datetime is ambiguous and this function will not guess: pass
    ``source_convention='utc'`` or ``'et'`` to say which column it came from.
    Passing a naive datetime without one raises ValueError, which is the point —
    the guess is what produced the bug.
    """
    if dt is None:
        return ""

    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            convention = (source_convention or "").strip().lower()
            if convention == "utc":
                dt = dt.replace(tzinfo=UTC)
            elif convention == "et":
                dt = dt.replace(tzinfo=USER_TIMEZONE)
            else:
                raise ValueError(
                    "render_when received a naive datetime without a "
                    "source_convention; pass 'utc' or 'et' to say which column "
                    f"it came from (got {dt!r})"
                )
        local_dt = dt.astimezone(USER_TIMEZONE)
    elif isinstance(dt, date):
        all_day = True
        local_dt = datetime.combine(dt, datetime.min.time(), tzinfo=USER_TIMEZONE)
    else:
        raise TypeError(f"render_when expects a datetime or date, got {type(dt).__name__}")

    reference = now.astimezone(USER_TIMEZONE) if now is not None else datetime.now(USER_TIMEZONE)
    day = local_dt.strftime("%a %b %-d")
    if local_dt.year != reference.year:
        day = local_dt.strftime("%a %b %-d, %Y")

    if all_day:
        return f"{day} (all day)"

    clock = local_dt.strftime("%-I:%M %p")
    return f"{day}, {clock} ET ({_delta_phrase((local_dt - reference).total_seconds())})"


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
