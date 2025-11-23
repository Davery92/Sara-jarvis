"""
Phase 4 Intelligence Services
Daily Briefings, Context Modes, Intelligence Reports, Proactive Suggestions, Pattern Detection
"""
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)

async def generate_daily_briefing(
    db: Session,
    user_id: str,
    briefing_type: str,
    llm_call_fn,
    Episode,
    Note,
    CalendarEvent,
    DailyBriefing,
    BriefingSettings
) -> Dict:
    """
    Generate a personalized daily briefing using AI

    Args:
        db: Database session
        user_id: User ID
        briefing_type: "morning" or "evening"
        llm_call_fn: Function to call LLM
        Episode/Note/etc: SQLAlchemy models

    Returns:
        Dictionary with briefing data
    """
    try:
        # Get user settings
        settings = db.query(BriefingSettings).filter(BriefingSettings.user_id == user_id).first()
        if not settings:
            # Create default settings
            settings = BriefingSettings(user_id=user_id)
            db.add(settings)
            db.commit()

        # Gather context data
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        context_parts = []

        # Recent episodes (last 24 hours)
        if settings.include_insights:
            recent_episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= datetime.combine(yesterday, datetime.min.time())
            ).order_by(Episode.created_at.desc()).limit(10).all()

            if recent_episodes:
                context_parts.append("## Recent Activity")
                for ep in recent_episodes[:5]:
                    context_parts.append(f"- {ep.content[:100]}")

        # Calendar events
        if settings.include_schedule:
            events_query = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id)

            if briefing_type == "morning":
                # Today's events
                events = events_query.filter(
                    CalendarEvent.start_time >= datetime.combine(today, datetime.min.time()),
                    CalendarEvent.start_time < datetime.combine(today + timedelta(days=1), datetime.min.time())
                ).order_by(CalendarEvent.start_time).all()

                if events:
                    context_parts.append("## Today's Schedule")
                    for event in events[:5]:
                        time_str = event.start_time.strftime("%I:%M %p")
                        context_parts.append(f"- {time_str}: {event.title}")
            else:
                # Tomorrow's preview
                tomorrow = today + timedelta(days=1)
                events = events_query.filter(
                    CalendarEvent.start_time >= datetime.combine(tomorrow, datetime.min.time()),
                    CalendarEvent.start_time < datetime.combine(tomorrow + timedelta(days=1), datetime.min.time())
                ).order_by(CalendarEvent.start_time).all()

                if events:
                    context_parts.append("## Tomorrow's Preview")
                    for event in events[:5]:
                        time_str = event.start_time.strftime("%I:%M %p")
                        context_parts.append(f"- {time_str}: {event.title}")

        # Notes activity
        recent_notes = db.query(Note).filter(
            Note.user_id == user_id,
            Note.created_at >= datetime.combine(week_ago, datetime.min.time())
        ).order_by(Note.created_at.desc()).limit(5).all()

        if recent_notes:
            context_parts.append("## Recent Notes")
            for note in recent_notes[:3]:
                context_parts.append(f"- {note.title}")

        # Health data (if available from recent episodes)
        health_episodes = db.query(Episode).filter(
            Episode.user_id == user_id,
            Episode.memory_type.in_(["health_sync", "workout"]),
            Episode.created_at >= datetime.combine(yesterday, datetime.min.time())
        ).order_by(Episode.created_at.desc()).limit(3).all()

        if health_episodes and settings.include_recovery:
            context_parts.append("## Health & Fitness")
            for ep in health_episodes:
                context_parts.append(f"- {ep.content}")

        # Build prompt
        context_str = "\n".join(context_parts) if context_parts else "No recent activity."

        if briefing_type == "morning":
            system_prompt = """You are Sara, a personal AI assistant. Generate a warm, personalized morning briefing.
Include: key priorities for today, calendar highlights, health/fitness insights, and an encouraging message.
Keep it concise (200-300 words) and use markdown formatting with emojis."""
            user_prompt = f"""Generate a morning briefing for today ({today.strftime('%A, %B %d, %Y')}).

Available context:
{context_str}

Create an uplifting briefing that helps the user start their day with clarity and energy."""

        else:  # evening
            system_prompt = """You are Sara, a personal AI assistant. Generate a thoughtful evening briefing.
Include: today's accomplishments, reflections, tomorrow's preview, and wind-down suggestions.
Keep it concise (200-300 words) and use markdown formatting with emojis."""
            user_prompt = f"""Generate an evening briefing for today ({today.strftime('%A, %B %d, %Y')}).

Available context:
{context_str}

Create a reflective briefing that helps the user wind down and prepare for tomorrow."""

        # Generate briefing with LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        briefing_content = await llm_call_fn(messages, temperature=0.7, max_tokens=1000)

        # Save to database
        briefing = DailyBriefing(
            user_id=user_id,
            briefing_type=briefing_type,
            briefing_date=datetime.combine(today, datetime.min.time()),
            content=briefing_content,
            delivered=1,  # Consider it delivered once generated
            read=0
        )
        db.add(briefing)
        db.commit()
        db.refresh(briefing)

        return {
            "id": briefing.id,
            "user_id": briefing.user_id,
            "briefing_type": briefing.briefing_type,
            "briefing_date": briefing.briefing_date.isoformat(),
            "content": briefing.content,
            "delivered": bool(briefing.delivered),
            "read": bool(briefing.read),
            "created_at": briefing.created_at.isoformat()
        }

    except Exception as e:
        logger.error(f"Error generating briefing: {e}")
        raise


def get_context_stats(db: Session, user_id: str, Episode, Note, Document, CalendarEvent) -> Dict:
    """Get statistics about user's context data"""
    try:
        # Count episodes
        episode_count = db.query(Episode).filter(Episode.user_id == user_id).count()

        # Count notes
        note_count = db.query(Note).filter(Note.user_id == user_id).count()

        # Count documents
        doc_count = db.query(Document).filter(Document.user_id == user_id).count()

        # Count events (future and recent past)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        event_count = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= thirty_days_ago
        ).count()

        # Estimate total size (rough approximation)
        total_size_bytes = (episode_count * 500) + (note_count * 1000) + (doc_count * 5000)
        total_size_mb = total_size_bytes / (1024 * 1024)

        return {
            "total_episodes": episode_count,
            "total_notes": note_count,
            "total_documents": doc_count,
            "total_events": event_count,
            "total_size": f"{total_size_mb:.2f} MB"
        }

    except Exception as e:
        logger.error(f"Error getting context stats: {e}")
        return {
            "total_episodes": 0,
            "total_notes": 0,
            "total_documents": 0,
            "total_events": 0,
            "total_size": "0 MB"
        }


async def generate_intelligence_report(
    db: Session,
    user_id: str,
    report_type: str,
    llm_call_fn,
    Episode,
    IntelligenceReport
) -> Dict:
    """Generate periodic intelligence report (weekly/monthly/quarterly)"""
    try:
        # Determine date range
        today = datetime.now()
        if report_type == "weekly":
            start_date = today - timedelta(days=7)
            title = f"Weekly Intelligence Report - {today.strftime('%b %d, %Y')}"
        elif report_type == "monthly":
            start_date = today - timedelta(days=30)
            title = f"Monthly Intelligence Report - {today.strftime('%B %Y')}"
        else:  # quarterly
            start_date = today - timedelta(days=90)
            title = f"Quarterly Intelligence Report - Q{(today.month-1)//3 + 1} {today.year}"

        # Gather episode data
        episodes = db.query(Episode).filter(
            Episode.user_id == user_id,
            Episode.created_at >= start_date
        ).order_by(Episode.importance.desc()).limit(50).all()

        # Build context
        context_summary = []
        for ep in episodes[:20]:
            context_summary.append(f"- {ep.content[:150]}")

        context_str = "\n".join(context_summary)

        # Generate report with LLM
        system_prompt = f"""You are Sara, a personal AI assistant. Generate a {report_type} intelligence report analyzing patterns, progress, and insights from the user's data.

Structure your report with:
1. Executive Summary
2. Key Patterns Observed
3. Progress & Achievements
4. Areas for Growth
5. Recommendations

Use markdown formatting with headers, bullet points, and emojis. Keep it concise but insightful (400-600 words)."""

        user_prompt = f"""Generate a {report_type} intelligence report covering {start_date.strftime('%b %d')} to {today.strftime('%b %d, %Y')}.

Recent activity:
{context_str}

Analyze patterns, provide insights, and make actionable recommendations."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        report_content = await llm_call_fn(messages, temperature=0.7, max_tokens=800)

        # Save report
        report = IntelligenceReport(
            user_id=user_id,
            report_type=report_type,
            report_date=today,
            title=title,
            summary=report_content[:300],
            full_content=report_content,
            key_insights=json.dumps([]),
            metrics=json.dumps({"episode_count": len(episodes)})
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        return {
            "id": report.id,
            "user_id": report.user_id,
            "report_type": report.report_type,
            "report_date": report.report_date.isoformat(),
            "title": report.title,
            "summary": report.summary,
            "full_content": report.full_content,
            "created_at": report.created_at.isoformat()
        }

    except Exception as e:
        logger.error(f"Error generating intelligence report: {e}")
        raise
