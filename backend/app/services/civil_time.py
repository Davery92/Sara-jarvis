"""One timestamp contract for every scheduling tool.

Reliable-assistant plan Phase F, Reminders/timers row: *"User-zone parsing,
explicit timestamp contract, DST ambiguity policy"*; Calendar row: *"Same time
contract."*

## What was wrong

Three confirmed findings, one cause:

* **16** — "Reminder write/read timezone-handling defect, reproduced
  repeatedly across both resumes."
* **37** — "Calendar and reminder tools use **opposite** conventions for
  offset-free timestamps." Reminders read a naive `2026-09-28T19:00:00` as
  **UTC**; the calendar read it as **local**. So the same string from the same
  model in the same turn meant two different instants, four or five hours
  apart, depending on which tool got it.
* **23** — `timers_status` crashed comparing a naive column to an aware `now`.

The model is told the current local time in its prompt and naturally emits
wall-clock times in that zone. Reading those as UTC silently books David's 7pm
reminder for 3pm. Nothing about "just always send an offset" survives contact
with a model that sometimes does not; the application has to have one answer.

## The contract

`parse_user_datetime` is that answer, and every scheduling tool uses it:

* An offset (`+00:00`, `-04:00`) or `Z` is authoritative — the caller said
  exactly which instant it meant.
* **A naive timestamp is David's wall clock**, resolved in his zone. This is
  the change from the reminder tools' old behavior, and it is the reading that
  matches both what the model is told and what a person means.
* A bare date (`2026-09-28`) resolves to 09:00 local, and says so — not
  midnight, which is nobody's intent for "remind me Monday".
* **DST ambiguity has a stated policy, not an accident.** In the fall-back
  hour a naive time occurs twice: the FIRST (still-DST) occurrence is chosen.
  In the spring-forward gap it does not occur at all: the time is moved forward
  past the gap. Both cases return a human-readable `note` so the reply can say
  what was booked rather than quietly picking one.

Everything returns an aware UTC datetime. `TimeInterpretation.note` is for the
user; `.assumed_zone` is for the log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

#: David's zone. Single-user app; the plan is explicit that this is not the
#: place to build multi-tenant timezone plumbing.
DEFAULT_USER_TZ = ZoneInfo("America/New_York")

#: A bare date means "that day", and a reminder for a day with no time is a
#: morning reminder. Midnight is never what was meant.
DEFAULT_TIME_OF_DAY = time(9, 0)

_DATE_ONLY_RE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s*$")


class AmbiguousTimeError(ValueError):
    """Raised only for input that cannot be read as a time at all."""


@dataclass(frozen=True)
class TimeInterpretation:
    """The instant, and an honest account of how it was arrived at."""

    instant: datetime                  # always aware, always UTC
    had_offset: bool
    assumed_zone: Optional[str] = None  # set when the zone was assumed
    note: str = ""                      # user-facing, empty when unremarkable
    local: Optional[datetime] = None    # the same instant in the user's zone

    @property
    def iso(self) -> str:
        return self.instant.isoformat()


def _fold_note(local_naive: datetime, tz: ZoneInfo) -> tuple[datetime, str]:
    """Resolve a naive local time, stating the DST policy where it applies."""
    first = local_naive.replace(tzinfo=tz, fold=0)
    second = local_naive.replace(tzinfo=tz, fold=1)

    # The GAP is checked before the REPEAT, and the order matters: on a
    # spring-forward night a gap time's two folds also disagree about offset
    # (EST vs EDT), so an offset-difference check alone reports "this happens
    # twice" for a time that happens zero times. Only the round trip tells
    # them apart — a repeated wall-clock time round-trips to itself, a
    # nonexistent one does not.
    roundtrip = first.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != local_naive:
        return roundtrip, (
            f"{local_naive.strftime('%-I:%M %p')} doesn't exist that night — the clocks "
            f"jump forward — so I used {roundtrip.strftime('%-I:%M %p')}."
        )

    if first.utcoffset() != second.utcoffset():
        # Fall back: this wall-clock time happens twice. Policy: the first
        # (still on the earlier, DST offset). Said out loud, because "1:30am"
        # on that night is a real choice between two instants an hour apart.
        return first, (
            f"{local_naive.strftime('%-I:%M %p')} happens twice that night when the "
            f"clocks go back — I used the first one ({first.tzname()})."
        )

    return first, ""


def parse_user_datetime(
    value: str | datetime | None,
    tz: ZoneInfo = DEFAULT_USER_TZ,
    *,
    default_time: time = DEFAULT_TIME_OF_DAY,
) -> TimeInterpretation:
    """Read a caller-supplied timestamp under the one shared contract.

    Raises `AmbiguousTimeError` only when the input is not a timestamp at all —
    a caller must be able to tell "I could not read that" from "I read it and
    here is what I assumed".
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AmbiguousTimeError("no time given")

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            instant = value.astimezone(timezone.utc)
            return TimeInterpretation(
                instant=instant, had_offset=True, local=instant.astimezone(tz),
            )
        aware, note = _fold_note(value, tz)
        instant = aware.astimezone(timezone.utc)
        return TimeInterpretation(
            instant=instant, had_offset=False, assumed_zone=str(tz), note=note,
            local=instant.astimezone(tz),
        )

    raw = value.strip()

    if _DATE_ONLY_RE.match(raw):
        day = date.fromisoformat(raw)
        naive = datetime.combine(day, default_time)
        aware, note = _fold_note(naive, tz)
        instant = aware.astimezone(timezone.utc)
        return TimeInterpretation(
            instant=instant, had_offset=False, assumed_zone=str(tz),
            note=note or (
                f"You gave a date with no time, so I used "
                f"{naive.strftime('%-I:%M %p')}."
            ),
            local=instant.astimezone(tz),
        )

    candidate = raw.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        # Tolerate a space instead of "T", and a trailing "UTC".
        cleaned = re.sub(r"\s+UTC$", "+00:00", raw, flags=re.IGNORECASE)
        cleaned = cleaned.replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AmbiguousTimeError(
                f"couldn't read {raw!r} as a date/time — use ISO 8601 "
                "(2026-09-28T19:00, or 2026-09-28T19:00-04:00 to be explicit)"
            ) from exc

    if parsed.tzinfo is not None:
        instant = parsed.astimezone(timezone.utc)
        return TimeInterpretation(
            instant=instant, had_offset=True, local=instant.astimezone(tz),
        )

    aware, note = _fold_note(parsed, tz)
    instant = aware.astimezone(timezone.utc)
    return TimeInterpretation(
        instant=instant, had_offset=False, assumed_zone=str(tz), note=note,
        local=instant.astimezone(tz),
    )


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Read a stored datetime as an aware UTC instant.

    Several scheduling columns in this schema are `timestamp WITHOUT time
    zone` even though their SQLAlchemy models declare `DateTime(timezone=
    True)` — `reminder.reminder_time`, `reminder.created_at`, `timer.start_time`
    and `timer.end_time` among them. The session's TimeZone is UTC, so what is
    stored is the UTC wall clock and what comes back is naive. Comparing that
    to an aware `now()` raises `TypeError`, which is finding 23 verbatim:
    "`timers_status` crashes unconditionally with a naive/aware datetime
    TypeError, and since cancel depends on the same lookup, active timers can
    be started but never checked or cancelled via chat."

    So every read of one of those columns goes through here. A naive value is
    UTC (which is what was written); an aware one is converted.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def describe_instant(instant: datetime, tz: ZoneInfo = DEFAULT_USER_TZ) -> str:
    """How a stored instant should be spoken back: David's wall clock, with
    the zone, so a readback can never be mistaken for a different hour."""
    local = as_utc(instant).astimezone(tz)
    return local.strftime("%a %-d %b, %-I:%M %p %Z")


#: The one sentence every scheduling tool's `*_time` parameter description
#: should carry, so the model is told the contract rather than guessing it.
TIME_PARAMETER_CONTRACT = (
    "ISO 8601. A time with no offset is read as David's local wall clock "
    "(America/New_York) — which is what the current-time line in your context "
    "is in, so just write the local time he means. Add an offset or 'Z' only "
    "if you specifically mean a different zone. A bare date gets a 9am local "
    "time."
)
