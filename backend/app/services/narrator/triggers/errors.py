"""Error-pattern triggers. Reads agent_run_log for backend error fingerprints."""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.narrator.triggers.base import (
    Trigger,
    TriggerContext,
    register_trigger,
)

logger = logging.getLogger(__name__)


# Minimum recurrence over the window before it's worth narrating.
REPEAT_ERROR_MIN_COUNT = 3

# Lookback window for counting recurrences.
REPEAT_ERROR_WINDOW_HOURS = 24

# We extract the exception class name (e.g. "ConnectionRefusedError") as the
# error fingerprint. Two errors with the same class in the window count as
# the "same" error for the purposes of this trigger.
_EXCEPTION_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")


def _fingerprint(error_message: str) -> Optional[str]:
    """Pull the exception class name out of an error string, or None."""
    if not error_message:
        return None
    m = _EXCEPTION_NAME_RE.search(error_message)
    return m.group(1) if m else None


@register_trigger("repeat_error", cooldown_seconds=4 * 60 * 60)
class RepeatErrorTrigger(Trigger):
    """Same exception class ≥3× in the last 24h.

    Reads agent_run_log.error_message — that table is the main collector for
    backend run errors (heartbeats, deliberation, scheduled jobs). Fingerprinting
    on exception class is coarse but matches the spec's intent: catch the
    "this same error keeps happening" pattern, not the specific stack.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT error_message, run_at
                    FROM agent_run_log
                    WHERE error_message IS NOT NULL
                      AND error_message != ''
                      AND run_at > NOW() - make_interval(hours => :win_h)
                    ORDER BY run_at DESC
                    LIMIT 500
                    """
                ),
                {"win_h": REPEAT_ERROR_WINDOW_HOURS},
            )
        ).mappings().all()

        if not rows:
            return None

        # Group by fingerprinted exception class.
        counts: dict[str, int] = {}
        examples: dict[str, str] = {}
        for r in rows:
            fp = _fingerprint(r["error_message"])
            if not fp:
                continue
            counts[fp] = counts.get(fp, 0) + 1
            # Keep first (newest) example we see.
            examples.setdefault(fp, r["error_message"])

        if not counts:
            return None

        # Pick the most-recurrent class.
        top_class = max(counts, key=lambda k: counts[k])
        top_count = counts[top_class]

        if top_count < REPEAT_ERROR_MIN_COUNT:
            return None

        # Trim the example for the LLM context — full traces are noise.
        example = examples[top_class]
        example_short = example[:200].strip()

        facts = {
            "exception_class": top_class,
            "count": top_count,
            "window_hours": REPEAT_ERROR_WINDOW_HOURS,
            "example": example_short,
        }
        summary = (
            f"{top_class} has happened {top_count} times in the last "
            f"{REPEAT_ERROR_WINDOW_HOURS}h"
        )
        return TriggerContext(
            trigger_name="repeat_error",
            severity="roast",
            facts=facts,
            summary=summary,
            # Same class + count bucket within cooldown → one fire is enough.
            dedup_key=f"repeat_error:{top_class}",
        )


@register_trigger("the_bug_slain", cooldown_seconds=24 * 60 * 60)
class TheBugSlainTrigger(Trigger):
    """An exception class that used to fire regularly has gone silent for ≥7d.

    Grudging praise — the System acknowledges that an error which was once
    common no longer appears. Whether that's because it was fixed or because
    the code path was removed is left to David's judgment.

    Detection: find exception classes that had ≥3 occurrences in the 30-37 day
    window AND zero occurrences in the last 7 days.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        # Pull all errors from the last 37 days, fingerprint, and count by
        # window. Done in app code because we already have the regex
        # fingerprinter and the row counts are small.
        rows = (
            await db.execute(
                text(
                    """
                    SELECT error_message, run_at FROM agent_run_log
                    WHERE error_message IS NOT NULL AND error_message != ''
                      AND run_at > NOW() - INTERVAL '37 days'
                    """
                )
            )
        ).mappings().all()

        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        old_window_start = now - timedelta(days=37)
        old_window_end = now - timedelta(days=7)
        recent_window_start = now - timedelta(days=7)

        old_counts: dict[str, int] = {}
        recent_counts: dict[str, int] = {}
        last_seen: dict[str, datetime] = {}

        for r in rows:
            fp = _fingerprint(r["error_message"])
            if not fp:
                continue
            run_at = r["run_at"]
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
            if old_window_start <= run_at < old_window_end:
                old_counts[fp] = old_counts.get(fp, 0) + 1
            elif run_at >= recent_window_start:
                recent_counts[fp] = recent_counts.get(fp, 0) + 1
            if fp not in last_seen or run_at > last_seen[fp]:
                last_seen[fp] = run_at

        # Find a class that was once common and is now silent.
        candidates = [
            (fp, n)
            for fp, n in old_counts.items()
            if n >= 3 and recent_counts.get(fp, 0) == 0
        ]
        if not candidates:
            return None

        # Pick the one with the most prior occurrences.
        candidates.sort(key=lambda kv: kv[1], reverse=True)
        top_class, prior_count = candidates[0]
        last = last_seen.get(top_class)
        silent_days = (now - last).days if last else None

        facts = {
            "exception_class": top_class,
            "prior_count": prior_count,
            "silent_days": silent_days,
        }
        summary = (
            f"{top_class} was seen {prior_count} times in the prior month "
            f"and has been silent for ~{silent_days} day"
            f"{'s' if silent_days != 1 else ''}"
        )
        return TriggerContext(
            trigger_name="the_bug_slain",
            severity="grudging",
            facts=facts,
            summary=summary,
            dedup_key=f"the_bug_slain:{top_class}",
        )
