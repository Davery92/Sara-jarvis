"""
Cross-reference check: the one surviving piece of the old proactive
intelligence engine. Used by tasks/calendar_prep.py.

The rest of this module (ProactiveIntelligenceEngine — meal/workout/sleep
pattern detection, suggestion generation) was deleted 2026-07-03: zero
external callers anywhere in the codebase, its `detected_pattern` table had
been write-less since the pattern-detection methods were never wired to a
scheduler, and its `proactive_suggestion`/`detected_pattern` read routes
were only ever called by a frontend dashboard (SmartInsightsDashboard.tsx)
that was itself never imported/rendered anywhere. Superseded by
behavioral_pattern_service.py + daily_rhythm.py, which are actually wired.
"""
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


async def cross_reference_check(user_id: str) -> List[Dict[str, Any]]:
    """
    Cross-reference recent emails, upcoming calendar, and notes to find connections.

    Returns list of insights like:
    "You got an email from Mike about Q3 timeline, and you have a meeting with Mike tomorrow"
    """
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    async_session = get_async_session_factory()
    insights = []

    try:
        async with async_session() as db:
            # Get recent email senders + subjects (last 24h). Include the
            # email id so callers can form stable topics — without the id,
            # the old caller hashed the insight title and the hash drifted
            # every time a new matching email arrived, which broke dedup
            # in the attention escalator.
            # Window slightly over the hourly task cadence — NOT 24h. With a
            # day-long window, yesterday's mail kept re-qualifying as "recent"
            # and David got "Email from X may relate..." pushes for emails he
            # had already read the day before.
            emails = await db.execute(text("""
                SELECT id, sender_name, subject, importance_score
                FROM email
                WHERE user_id = :uid AND received_at > NOW() - INTERVAL '3 hours'
                ORDER BY received_at DESC LIMIT 20
            """), {"uid": user_id})
            email_rows = emails.fetchall()

            # Get upcoming calendar events (next 48h)
            events = await db.execute(text("""
                SELECT id, title, start_time, description
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time BETWEEN NOW() AND NOW() + INTERVAL '48 hours'
                ORDER BY start_time ASC LIMIT 10
            """), {"uid": user_id})
            event_rows = events.fetchall()

            # Get recent notes (last 7 days)
            notes = await db.execute(text("""
                SELECT title, tags
                FROM note
                WHERE user_id = :uid AND updated_at > NOW() - INTERVAL '7 days'
                ORDER BY updated_at DESC LIMIT 20
            """), {"uid": user_id})
            note_rows = notes.fetchall()

        if not email_rows or not event_rows:
            return insights

        # ONE insight per EMAIL listing ALL matched events (P2 punch-list fix). The
        # old code looped per event, so one email matching three "Risk Ninja" events
        # fired three notifications seconds apart; the per-pair dedup + 2h cooldown
        # even let a pair re-fire an hour later. Group by email, dedup on the email id
        # only, and notify at most once per email lifetime.
        email_xref_topics = []
        for email_id, sender, subject, _imp in email_rows:
            sender_first = sender.lower().split()[0] if sender else None
            subj_words = {w.lower() for w in (subject or "").split() if len(w) > 4 and w[0].isupper()}
            matched = []
            for event_id, title, start_time, description in event_rows:
                event_text = f"{title} {description or ''}".lower()
                if (sender_first and sender_first in event_text) or any(w in event_text for w in subj_words):
                    matched.append((title, start_time))
            if not matched:
                continue
            n = len(matched)
            ev_list = "; ".join(
                f"{t} ({st.strftime('%a %-I:%M %p') if st else 'soon'})" for t, st in matched[:5]
            )
            topic = f"xref:email:{email_id}"
            email_xref_topics.append(topic)
            insights.append({
                "type": "email_calendar_link",
                "title": f"Email from {sender} relates to {n} upcoming event{'s' if n > 1 else ''}",
                "message": (f"{sender}'s email about \"{subject}\" relates to {n} upcoming "
                            f"event{'s' if n > 1 else ''}: {ev_list}."),
                "priority": "normal",
                "confidence": 0.7,
                "topic": topic,
            })

        # Once per email lifetime: drop any xref insight whose topic was ever sent.
        if email_xref_topics:
            try:
                from app.db.session import get_async_session_factory
                factory = get_async_session_factory()
                async with factory() as adb:
                    sent = {r[0] for r in (await adb.execute(text(
                        "SELECT topic FROM notification_log WHERE user_id = :uid AND sent = TRUE "
                        "AND topic = ANY(:topics)"),
                        {"uid": user_id, "topics": email_xref_topics})).all()}
                if sent:
                    insights = [i for i in insights if i.get("topic") not in sent]
            except Exception as _e:
                logger.debug(f"xref lifetime dedup skipped: {_e}")

        # Check notes for calendar overlap
        for event_id, title, start_time, description in event_rows:
            event_words = set(w.lower() for w in f"{title} {description or ''}".split() if len(w) > 4)
            for note_title, note_tags in note_rows:
                note_words = set(w.lower() for w in (note_title or "").split() if len(w) > 4)
                overlap = event_words & note_words
                if len(overlap) >= 2:
                    time_str = start_time.strftime("%A at %I:%M %p") if start_time else "soon"
                    insights.append({
                        "type": "note_calendar_link",
                        "title": f"Your note \"{note_title}\" relates to upcoming event",
                        "message": f"Your note \"{note_title}\" overlaps with \"{title}\" ({time_str}) on: {', '.join(overlap)}",
                        "priority": "low",
                        "confidence": 0.5,
                        "topic": f"xref:note:{str(note_title)[:40]}:event:{str(event_id)[:12]}",
                    })
                    break

    except Exception as e:
        logger.warning(f"Cross-reference check failed: {e}")

    return insights[:3]  # Max 3 insights per check
