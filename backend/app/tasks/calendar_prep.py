"""Calendar prep task — checks upcoming events and sends prep notifications."""

import asyncio
import logging
import os

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = get_owner_id()


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.calendar_prep.check_upcoming", bind=True, max_retries=0)
def check_upcoming(self):
    """Check for upcoming events and send prep notifications."""
    try:
        from app.services.calendar_prep import check_and_send_preps
        _run_async(check_and_send_preps(DEFAULT_USER_ID))
    except Exception as e:
        logger.warning(f"Calendar prep check failed: {e}")


@celery_app.task(name="app.tasks.calendar_prep.research_upcoming", bind=True, max_retries=0)
def research_upcoming(self):
    """Pre-research the counterparty of upcoming business meetings (deduped)."""
    try:
        from app.services.meeting_research import research_upcoming_meetings
        triggered = research_upcoming_meetings(DEFAULT_USER_ID)
        if triggered:
            logger.info("Meeting research: triggered %d (%s)", len(triggered), triggered)
    except Exception as e:
        logger.warning(f"Meeting research scan failed: {e}")


@celery_app.task(name="app.tasks.calendar_prep.cross_system_check", bind=True, max_retries=0)
def cross_system_check(self):
    """Cross-reference email, calendar, notes for insights."""
    try:
        from app.core.timezone import now as et_now
        from app.services.proactive_intelligence import cross_reference_check

        # These are FYI nudges, never urgent — don't fire them overnight.
        # (This task pushed "Email from X may relate to upcoming event" at
        # 11:43 PM. Overnight email still surfaces via the morning brief.)
        hour = et_now().hour
        if hour >= 22 or hour < 7:
            return

        insights = _run_async(cross_reference_check(DEFAULT_USER_ID))
        for insight in insights:
            # Prefer the stable topic the generator emitted (tied to email
            # id + event id). Fall back to the legacy hash-of-title key
            # only if an older generator is somehow still in the tree.
            topic = insight.get("topic") or f"xref:{hash(insight['title']) % 100000}"
            # Arc 1.5 (SARA_ALIVE_BUILD_PLAN): the legacy direct send is
            # retired now that Arc 1.4's real delivery path is live — this
            # source speaks through the say_candidate queue only, same as
            # everything else. Legacy send_notification call removed here;
            # see git history (Arc 1.2 commit) for what it looked like.
            _run_async(_dual_write_candidate(insight, topic))
        if insights:
            logger.info(f"Cross-system synthesis: queued {len(insights)} insight(s) as candidates")
    except Exception as e:
        logger.warning(f"Cross-system synthesis failed: {e}")


async def _dual_write_candidate(insight: dict, topic: str) -> None:
    """Mind V2 rewire plan Workstream B.1 — feed the say_candidate queue
    with the same real content the legacy send above already delivers, so
    the judge/compose/review chain has something other than derived-signal
    counters to appraise. Wrapped in try/except: a candidate-queue failure
    must never break the legacy send while it's still the delivery path.
    Legacy send is untouched — this is additive only."""
    try:
        from datetime import timedelta
        from app.core.timezone import now as et_now, to_utc
        from app.services.say_candidate import create_candidate
        from app.db.session import get_async_session_factory

        event_start = insight.get("event_start")
        # calendar_event.start_time is naive ET wall-clock (see world_brief.py's
        # sweep_brief gotcha note) — convert before it reaches a
        # DateTime(timezone=True) column, else Postgres reads it as naive UTC
        # and the TTL lands 4-5h off.
        valid_until = to_utc(event_start) if event_start else (et_now() + timedelta(hours=24))

        factory = get_async_session_factory()
        async with factory() as db:
            await create_candidate(
                db, user_id=DEFAULT_USER_ID, source="cross_system_synthesis",
                kind="inform", summary=insight["message"],
                evidence=[{"type": insight.get("type"), "topic": topic}],
                topic_entities=[topic],
                value_guess=insight.get("confidence"),
                valid_until=valid_until,
                dedupe_key=topic,
            )
    except Exception as e:
        logger.warning(f"[say_candidate] cross_system_synthesis dual-write failed: {e}")
