"""
Morning Brief Service
Orchestrates daily morning brief generation with news synthesis, weather, calendar, and TTS.
"""

import asyncio
import aiohttp
import logging
import os
import json
from datetime import datetime, date, timedelta, timezone as dt_timezone
from app.core.timezone import now as local_now, today as local_today, USER_TIMEZONE
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from sqlalchemy.orm import Session
from sqlalchemy import text

from .news_aggregator_service import news_aggregator_service, NewsItem
from .weather_service import weather_service, WeatherData
from .notification_service import notification_service, NotificationPriority
from .health_insight_service import health_insight_service

logger = logging.getLogger(__name__)


@dataclass
class DreamInsightBrief:
    """Dream insight for morning brief."""
    id: str
    insight_type: str
    title: str
    content: str
    evidence: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

# TTS Configuration
TTS_BASE_URL = "http://10.185.1.9:8880/v1/audio/speech"
TTS_VOICE = "af_sarah(1)+af_bella(1)"

# Storage paths
BRIEFINGS_BASE_PATH = Path("/home/david/jarvis/data/briefings")


@dataclass
class CalendarEvent:
    """Calendar event for brief."""
    title: str
    starts_at: str
    ends_at: str
    location: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MorningBrief:
    """Complete morning brief data."""
    user_id: str
    brief_date: str
    news_summary: str
    weather_summary: str
    calendar_summary: str
    full_text: str
    audio_path: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    news_sources: Optional[List[Dict]] = None
    weather_data: Optional[Dict] = None
    calendar_events: Optional[List[Dict]] = None
    generated_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class MorningBriefService:
    """Service for generating morning briefs."""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=120)  # Generous timeout for TTS
        # LLM Configuration (from environment)
        self.llm_base_url = os.environ.get("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
        self.llm_model = os.environ.get("OPENAI_MODEL", "gpt-oss:120b")
        self.llm_api_key = os.environ.get("OPENAI_API_KEY", "dummy")

    async def gather_news(self) -> tuple[str, List[Dict]]:
        """Gather and synthesize news from all sources."""
        try:
            categorized_news = await news_aggregator_service.aggregate_all()

            # Format for LLM
            raw_news = news_aggregator_service.format_for_llm(categorized_news)

            # Collect source info for metadata
            all_items = []
            for category, items in categorized_news.items():
                for item in items:
                    all_items.append(item.to_dict())

            # Synthesize with LLM
            synthesized = await self._synthesize_news(raw_news)

            return synthesized, all_items

        except Exception as e:
            logger.error(f"Error gathering news: {e}")
            return "Unable to gather news at this time.", []

    async def _synthesize_news(self, raw_news: str) -> str:
        """Use LLM to synthesize news into conversational summary."""
        try:
            prompt = f"""Create a conversational tech news summary for a morning briefing.

Focus on:
- AI/ML developments (most important)
- Major tech industry news
- Security updates
- Interesting Hacker News projects

Guidelines:
- Do NOT copy headlines word-for-word
- Synthesize into 3-5 short paragraphs
- Sound like a friend sharing interesting news
- Highlight what's actually significant
- Keep it concise (under 300 words)
- Start directly with the news (no "Good morning" or intro)

Raw news to synthesize:
{raw_news}

Synthesized summary:"""

            # Use longer timeout for LLM synthesis
            llm_timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=llm_timeout) as session:
                async with session.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "stream": False
                    }
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"LLM synthesis failed: {error}")
                        return raw_news  # Fall back to raw news

                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    finish_reason = data["choices"][0].get("finish_reason", "unknown")
                    logger.info(f"News synthesis complete: {len(content)} chars, finish_reason: {finish_reason}")
                    return content

        except Exception as e:
            logger.error(f"Error synthesizing news: {e}")
            return raw_news  # Fall back to raw news

    async def gather_weather(self) -> tuple[str, Optional[Dict]]:
        """Gather weather data."""
        try:
            weather = await weather_service.get_weather()
            if weather:
                summary = weather_service.format_for_brief(weather)
                return summary, weather.to_dict()
            return "Weather data unavailable.", None
        except Exception as e:
            logger.error(f"Error gathering weather: {e}")
            return "Weather data unavailable.", None

    async def gather_proactive_insights(self, user_id: str, db: Session) -> tuple[str, List[Dict]]:
        """Gather proactive dream insights for morning brief."""
        try:
            # Get proactive insights that haven't been surfaced yet
            result = db.execute(text("""
                SELECT id, insight_type, title, content, evidence
                FROM dream_insight
                WHERE user_id = :user_id
                    AND surface_strategy = 'proactive'
                    AND surfaced_count = 0
                    AND (expiry_at IS NULL OR expiry_at > NOW())
                    AND confidence >= 0.5
                ORDER BY confidence DESC, dream_date DESC
                LIMIT 3
            """), {"user_id": user_id})

            insights = []
            for row in result.fetchall():
                insights.append(DreamInsightBrief(
                    id=row.id,
                    insight_type=row.insight_type,
                    title=row.title,
                    content=row.content,
                    evidence=row.evidence
                ))

            if not insights:
                return "", []

            # Format insights summary
            lines = ["## Something I Noticed"]

            # Map types to conversational intros
            type_intros = {
                "behavioral_pattern": "I've noticed a pattern:",
                "connection": "I made a connection:",
                "unresolved_thread": "By the way,",
                "emerging_pattern": "I've been noticing:",
                "contradiction": "Something interesting:",
                "wellbeing_signal": "Checking in:",
            }

            for insight in insights:
                intro = type_intros.get(insight.insight_type, "Something to consider:")
                lines.append(f"\n**{intro}** {insight.content}")

            # Mark these insights as surfaced
            for insight in insights:
                db.execute(text("""
                    UPDATE dream_insight
                    SET surfaced_count = COALESCE(surfaced_count, 0) + 1,
                        last_surfaced_at = NOW(),
                        surfaced_at = COALESCE(surfaced_at, NOW())
                    WHERE id = :id
                """), {"id": insight.id})

            db.commit()

            return "\n".join(lines), [i.to_dict() for i in insights]

        except Exception as e:
            logger.error(f"Error gathering proactive insights: {e}")
            return "", []

    async def gather_health_digest(self, user_id: str, db: Session) -> tuple[str, Dict]:
        """
        Gather health digest for morning brief using the new health monitoring system.
        Returns health summary with metrics, trends, and insights.
        """
        try:
            # Get health summary from the new system
            health_summary = await health_insight_service.get_health_summary(user_id, db)

            if not health_summary or not health_summary.get('metrics'):
                return "", {}

            metrics = health_summary.get('metrics', {})
            alerts = health_summary.get('recent_alerts', [])

            # Build health digest text
            lines = ["## Health Overview"]

            # Key metrics summary
            if metrics:
                lines.append("")
                metric_display = {
                    'resting_hr': ('Resting HR', 'bpm'),
                    'hrv': ('HRV', 'ms'),
                    'sleep_hours': ('Sleep', 'hrs'),
                    'weight': ('Weight', 'kg'),
                    'steps': ('Steps', ''),
                    'active_energy': ('Active Cal', 'kcal'),
                }

                for metric_type, data in metrics.items():
                    if data.get('current_value') is None:
                        continue

                    display_name, unit = metric_display.get(metric_type, (metric_type.replace('_', ' ').title(), ''))
                    value = data['current_value']
                    baseline = data.get('baseline')
                    status = data.get('status', 'normal')

                    # Format the value
                    if metric_type in ['resting_hr', 'hrv', 'steps']:
                        value_str = f"{int(value)}"
                    elif metric_type == 'sleep_hours':
                        value_str = f"{value:.1f}"
                    elif metric_type == 'weight':
                        value_str = f"{value:.1f}"
                    else:
                        value_str = f"{value:.0f}"

                    # Status indicator
                    status_indicator = ""
                    if status == 'above_normal':
                        status_indicator = " ⬆️"
                    elif status == 'below_normal':
                        status_indicator = " ⬇️"

                    line = f"- **{display_name}**: {value_str} {unit}{status_indicator}"

                    # Add baseline comparison if available
                    if baseline:
                        if metric_type in ['resting_hr', 'hrv', 'steps']:
                            baseline_str = f"{int(baseline)}"
                        elif metric_type == 'sleep_hours':
                            baseline_str = f"{baseline:.1f}"
                        elif metric_type == 'weight':
                            baseline_str = f"{baseline:.1f}"
                        else:
                            baseline_str = f"{baseline:.0f}"
                        line += f" (7-day avg: {baseline_str})"

                    lines.append(line)

            # Add alerts if any
            if alerts:
                lines.append("")
                lines.append("### Alerts")
                for alert in alerts[:3]:  # Max 3 alerts
                    severity_emoji = {
                        'urgent': '🚨',
                        'warning': '⚠️',
                        'caution': '⚡',
                        'info': 'ℹ️',
                    }.get(alert.get('severity', 'info'), '•')
                    lines.append(f"{severity_emoji} {alert.get('message', 'Health alert')}")

            # Get unsurfaced health insights
            unsurfaced = db.execute(text("""
                SELECT id, title, content, severity
                FROM health_insight
                WHERE user_id = :user_id
                  AND surfaced_count = 0
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY
                    CASE severity
                        WHEN 'urgent' THEN 1
                        WHEN 'warning' THEN 2
                        WHEN 'caution' THEN 3
                        ELSE 4
                    END,
                    triggered_at DESC
                LIMIT 2
            """), {"user_id": user_id}).fetchall()

            if unsurfaced:
                lines.append("")
                lines.append("### Health Insights")
                insight_ids = []
                for insight in unsurfaced:
                    severity_emoji = {
                        'urgent': '🚨',
                        'warning': '⚠️',
                        'caution': '⚡',
                        'info': '💡',
                    }.get(insight.severity, '💡')
                    lines.append(f"{severity_emoji} **{insight.title}**: {insight.content[:200]}")
                    insight_ids.append(insight.id)

                # Mark insights as surfaced
                if insight_ids:
                    db.execute(text("""
                        UPDATE health_insight
                        SET surfaced_count = surfaced_count + 1,
                            surfaced_at = COALESCE(surfaced_at, NOW())
                        WHERE id = ANY(:ids)
                    """), {"ids": insight_ids})

            if len(lines) == 1:  # Only header
                return "", {}

            return "\n".join(lines), health_summary

        except Exception as e:
            logger.error(f"Error gathering health digest: {e}")
            return "", {}

    async def gather_calendar(self, user_id: str, db: Session) -> tuple[str, List[Dict]]:
        """Gather today's calendar events."""
        try:
            # Use user's timezone to determine "today", then convert to UTC for query
            today = local_today()
            start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=USER_TIMEZONE).astimezone(dt_timezone.utc)
            end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=USER_TIMEZONE).astimezone(dt_timezone.utc)

            result = db.execute(text("""
                SELECT title, starts_at, ends_at, location
                FROM event
                WHERE user_id = :user_id
                  AND starts_at >= :start_of_day
                  AND starts_at <= :end_of_day
                ORDER BY starts_at
            """), {
                "user_id": user_id,
                "start_of_day": start_of_day,
                "end_of_day": end_of_day
            })

            events = []
            for row in result.fetchall():
                events.append(CalendarEvent(
                    title=row.title,
                    starts_at=row.starts_at.strftime("%H:%M") if row.starts_at else "",
                    ends_at=row.ends_at.strftime("%H:%M") if row.ends_at else "",
                    location=row.location
                ))

            if not events:
                return "No events scheduled for today.", []

            # Format calendar summary
            lines = ["## Today's Schedule"]
            for event in events:
                time_str = event.starts_at
                if event.ends_at:
                    time_str += f" - {event.ends_at}"
                loc_str = f" @ {event.location}" if event.location else ""
                lines.append(f"- **{time_str}**: {event.title}{loc_str}")

            return "\n".join(lines), [e.to_dict() for e in events]

        except Exception as e:
            logger.error(f"Error gathering calendar: {e}")
            return "Calendar data unavailable.", []

    def _compose_full_brief(
        self,
        weekday: str,
        news_summary: str,
        weather_summary: str,
        calendar_summary: str,
        insights_summary: str = "",
        health_digest: str = ""
    ) -> str:
        """Compose the full morning brief text."""
        today_date = date.today().strftime("%B %d, %Y")

        sections = [
            f"# Good Morning! It's {weekday}, {today_date}",
            "",
            weather_summary,
            "",
            "---",
            "",
        ]

        # Add health digest if we have data
        if health_digest:
            sections.extend([
                health_digest,
                "",
                "---",
                "",
            ])

        # Add proactive insights if we have any
        if insights_summary:
            sections.extend([
                insights_summary,
                "",
                "---",
                "",
            ])

        sections.extend([
            "## Tech News",
            news_summary,
            "",
            "---",
            "",
            calendar_summary,
            "",
            "---",
            "",
            "Have a great day!"
        ])

        return "\n".join(sections)

    def _compose_tts_text(
        self,
        weekday: str,
        news_summary: str,
        weather_tts: str,
        calendar_events: List[Dict]
    ) -> str:
        """Compose text optimized for TTS (more conversational)."""
        parts = [
            f"Good morning! It's {weekday}.",
            "",
            weather_tts,
            "",
        ]

        # Calendar
        if calendar_events:
            if len(calendar_events) == 1:
                event = calendar_events[0]
                parts.append(f"You have one thing on the calendar today: {event['title']} at {event['starts_at']}.")
            else:
                parts.append(f"You have {len(calendar_events)} things scheduled today.")
                for event in calendar_events[:3]:  # Limit to 3 for TTS
                    parts.append(f"{event['title']} at {event['starts_at']}.")
        else:
            parts.append("Your calendar is clear today.")

        parts.append("")
        parts.append("Now for the tech news.")
        parts.append(news_summary)
        parts.append("")
        parts.append("That's your morning brief. Have a great day!")

        return " ".join(parts)

    async def generate_tts_audio(self, text: str, output_path: Path) -> Optional[float]:
        """Generate TTS audio using Kokoro."""
        try:
            # Ensure directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    TTS_BASE_URL,
                    json={
                        "input": text,
                        "voice": TTS_VOICE,
                        "model": "kokoro",
                        "response_format": "mp3"
                    }
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"TTS generation failed: {error}")
                        return None

                    audio_data = await response.read()

                    # Write to file
                    with open(output_path, "wb") as f:
                        f.write(audio_data)

                    # Estimate duration (rough estimate based on text length)
                    # Average speaking rate is ~150 words per minute
                    word_count = len(text.split())
                    estimated_duration = (word_count / 150) * 60

                    logger.info(f"TTS audio generated: {output_path} (~{estimated_duration:.0f}s)")
                    return estimated_duration

        except Exception as e:
            logger.error(f"Error generating TTS audio: {e}")
            return None

    async def send_notification(self, user_id: str, weekday: str) -> bool:
        """Send NTFY notification that brief is ready."""
        try:
            return await notification_service.send_notification(
                user_id=user_id,
                title="Morning Brief Ready",
                message=f"Your {weekday} briefing is ready with tech news, weather, and your schedule.",
                priority=NotificationPriority.NORMAL,
                tags=["sunrise", "brief"],
                topic="sara"  # Main topic
            )
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False

    async def generate_brief(self, user_id: str, db: Session) -> MorningBrief:
        """Generate complete morning brief."""
        logger.info(f"Generating morning brief for user {user_id}")

        today = date.today()
        weekday = today.strftime("%A")
        brief_date = today.strftime("%Y-%m-%d")

        # Gather all data in parallel
        news_task = self.gather_news()
        weather_task = self.gather_weather()
        calendar_task = self.gather_calendar(user_id, db)

        (news_summary, news_sources), (weather_summary, weather_data), (calendar_summary, calendar_events) = \
            await asyncio.gather(news_task, weather_task, calendar_task)

        # Gather proactive dream insights (not parallelized to ensure db session safety)
        insights_summary, insights_data = await self.gather_proactive_insights(user_id, db)
        if insights_data:
            logger.info(f"Including {len(insights_data)} proactive insights in morning brief")

        # Gather health digest from the new health monitoring system
        health_digest, health_data = await self.gather_health_digest(user_id, db)
        if health_data:
            logger.info(f"Including health digest with {len(health_data.get('metrics', {}))} metrics in morning brief")

        # Get weather TTS format if available
        weather_tts = ""
        if weather_data:
            from .weather_service import WeatherData, WeatherCondition, DailyForecast
            # Reconstruct for TTS formatting
            try:
                weather_obj = await weather_service.get_weather()
                if weather_obj:
                    weather_tts = weather_service.format_for_tts(weather_obj)
            except:
                weather_tts = weather_summary

        # Compose full brief with insights and health digest
        full_text = self._compose_full_brief(
            weekday, news_summary, weather_summary, calendar_summary,
            insights_summary, health_digest
        )

        # Compose TTS text
        tts_text = self._compose_tts_text(weekday, news_summary, weather_tts or weather_summary, calendar_events)

        # Generate TTS audio
        audio_dir = BRIEFINGS_BASE_PATH / user_id / brief_date
        audio_path = audio_dir / "morning_brief.mp3"
        audio_duration = await self.generate_tts_audio(tts_text, audio_path)

        # Create brief object
        brief = MorningBrief(
            user_id=user_id,
            brief_date=brief_date,
            news_summary=news_summary,
            weather_summary=weather_summary,
            calendar_summary=calendar_summary,
            full_text=full_text,
            audio_path=str(audio_path) if audio_duration else None,
            audio_duration_seconds=audio_duration,
            news_sources=news_sources,
            weather_data=weather_data,
            calendar_events=calendar_events,
            generated_at=local_now().isoformat()
        )

        # Save to database
        await self._save_brief_to_db(brief, db)

        # Send notification
        await self.send_notification(user_id, weekday)

        logger.info(f"Morning brief generated successfully for {user_id}")
        return brief

    async def _save_brief_to_db(self, brief: MorningBrief, db: Session) -> None:
        """Save brief to database."""
        try:
            # Check if brief already exists for today
            existing = db.execute(text("""
                SELECT id FROM morning_brief
                WHERE user_id = :user_id AND brief_date = :brief_date
            """), {"user_id": brief.user_id, "brief_date": brief.brief_date}).fetchone()

            if existing:
                # Update existing - also clear recovery data so it gets regenerated fresh
                db.execute(text("""
                    UPDATE morning_brief SET
                        news_summary = :news_summary,
                        weather_summary = :weather_summary,
                        calendar_summary = :calendar_summary,
                        full_text = :full_text,
                        audio_path = :audio_path,
                        audio_duration_seconds = :audio_duration_seconds,
                        news_sources = :news_sources,
                        weather_data = :weather_data,
                        calendar_events = :calendar_events,
                        generated_at = :generated_at,
                        recovery_text = NULL,
                        recovery_audio_path = NULL
                    WHERE user_id = :user_id AND brief_date = :brief_date
                """), {
                    "user_id": brief.user_id,
                    "brief_date": brief.brief_date,
                    "news_summary": brief.news_summary,
                    "weather_summary": brief.weather_summary,
                    "calendar_summary": brief.calendar_summary,
                    "full_text": brief.full_text,
                    "audio_path": brief.audio_path,
                    "audio_duration_seconds": brief.audio_duration_seconds,
                    "news_sources": json.dumps(brief.news_sources) if brief.news_sources else None,
                    "weather_data": json.dumps(brief.weather_data) if brief.weather_data else None,
                    "calendar_events": json.dumps(brief.calendar_events) if brief.calendar_events else None,
                    "generated_at": brief.generated_at
                })
            else:
                # Insert new
                db.execute(text("""
                    INSERT INTO morning_brief (
                        user_id, brief_date, news_summary, weather_summary, calendar_summary,
                        full_text, audio_path, audio_duration_seconds, news_sources,
                        weather_data, calendar_events, generated_at
                    ) VALUES (
                        :user_id, :brief_date, :news_summary, :weather_summary, :calendar_summary,
                        :full_text, :audio_path, :audio_duration_seconds, :news_sources,
                        :weather_data, :calendar_events, :generated_at
                    )
                """), {
                    "user_id": brief.user_id,
                    "brief_date": brief.brief_date,
                    "news_summary": brief.news_summary,
                    "weather_summary": brief.weather_summary,
                    "calendar_summary": brief.calendar_summary,
                    "full_text": brief.full_text,
                    "audio_path": brief.audio_path,
                    "audio_duration_seconds": brief.audio_duration_seconds,
                    "news_sources": json.dumps(brief.news_sources) if brief.news_sources else None,
                    "weather_data": json.dumps(brief.weather_data) if brief.weather_data else None,
                    "calendar_events": json.dumps(brief.calendar_events) if brief.calendar_events else None,
                    "generated_at": brief.generated_at
                })

            db.commit()
            logger.info(f"Brief saved to database for {brief.user_id} on {brief.brief_date}")

        except Exception as e:
            logger.error(f"Error saving brief to database: {e}")
            db.rollback()

    async def get_today_brief(self, user_id: str, db: Session) -> Optional[Dict]:
        """Get today's brief from database."""
        try:
            today = date.today().strftime("%Y-%m-%d")

            result = db.execute(text("""
                SELECT * FROM morning_brief
                WHERE user_id = :user_id AND brief_date = :brief_date
            """), {"user_id": user_id, "brief_date": today}).fetchone()

            if result:
                return dict(result._mapping)
            return None

        except Exception as e:
            logger.error(f"Error getting today's brief: {e}")
            return None

    async def generate_recovery_section(self, user_id: str, db: Session) -> tuple[str, Optional[str]]:
        """
        Generate recovery-aware workout recommendations with specific weight suggestions.
        Uses today's recovery metrics + recent exercise performance to suggest weights.
        Returns (text, audio_path) tuple.
        """
        try:
            today = date.today()
            today_str = today.strftime("%Y-%m-%d")
            day_of_week = today.strftime("%A").lower()

            # Get today's recovery data
            recovery = db.execute(text("""
                SELECT sleep_hours, soreness_level, hrv, heart_rate, body_weight, notes
                FROM daily_recovery_log
                WHERE user_id = :user_id AND log_date = :today
            """), {"user_id": user_id, "today": today_str}).fetchone()

            # Find active phase
            active_phase = db.execute(text("""
                SELECT id, name, goal FROM fitness_phase
                WHERE user_id = :user_id AND status = 'active'
                LIMIT 1
            """), {"user_id": user_id}).fetchone()

            # Find today's scheduled template
            template = None
            template_exercises = []
            if active_phase:
                templates = db.execute(text("""
                    SELECT id, name, exercises, notes, scheduled_days FROM fitness_template
                    WHERE user_id = :user_id AND phase_id = :phase_id
                """), {"user_id": user_id, "phase_id": active_phase.id}).fetchall()

                for t in templates:
                    if t.scheduled_days:
                        days = json.loads(t.scheduled_days or "[]")
                        if day_of_week in [d.lower() for d in days]:
                            template = t
                            template_exercises = json.loads(t.exercises or "[]")
                            break

            # If we have a scheduled workout, get recent performance for each exercise
            exercise_history = {}
            if template and template_exercises:
                exercise_names = [e.get("name", "") for e in template_exercises if e.get("name")]

                for exercise_name in exercise_names:
                    # Get the most recent performance for this exercise
                    recent = db.execute(text("""
                        SELECT weight, reps, rpe, session_date
                        FROM workout_log
                        WHERE user_id = :user_id
                        AND exercise_id = :exercise_name
                        ORDER BY session_date DESC, created_at DESC
                        LIMIT 4
                    """), {"user_id": user_id, "exercise_name": exercise_name}).fetchall()

                    if recent:
                        exercise_history[exercise_name] = {
                            "last_weight": recent[0].weight,
                            "last_reps": recent[0].reps,
                            "last_rpe": recent[0].rpe,
                            "last_date": str(recent[0].session_date),
                            "recent_sets": [(r.weight, r.reps, r.rpe) for r in recent]
                        }

            # Calculate recovery score (0-100)
            recovery_score = 100  # Default to good
            recovery_factors = []
            if recovery:
                # Sleep factor (< 6hrs = poor, 7-8 = good, > 8 = great)
                if recovery.sleep_hours:
                    if recovery.sleep_hours < 6:
                        recovery_score -= 25
                        recovery_factors.append(f"sleep only {recovery.sleep_hours}hrs")
                    elif recovery.sleep_hours < 7:
                        recovery_score -= 10

                # Soreness factor (1-10 scale, higher = worse)
                if recovery.soreness_level:
                    if recovery.soreness_level >= 7:
                        recovery_score -= 25
                        recovery_factors.append(f"high soreness ({recovery.soreness_level}/10)")
                    elif recovery.soreness_level >= 5:
                        recovery_score -= 15
                        recovery_factors.append(f"moderate soreness ({recovery.soreness_level}/10)")

                # HRV factor (low HRV = poor recovery)
                if recovery.hrv:
                    if recovery.hrv < 30:
                        recovery_score -= 20
                        recovery_factors.append(f"low HRV ({recovery.hrv}ms)")
                    elif recovery.hrv < 45:
                        recovery_score -= 10

            # Determine weight adjustment based on recovery
            if recovery_score >= 85:
                weight_adjustment = 1.0  # Normal weights, maybe push a bit
                adjustment_note = "Recovery looks solid - hit your target weights"
            elif recovery_score >= 70:
                weight_adjustment = 0.95  # Slight reduction
                adjustment_note = "Slightly reduced weights today"
            elif recovery_score >= 50:
                weight_adjustment = 0.90  # 10% reduction
                adjustment_note = "Take it easier - reduce weights 10%"
            else:
                weight_adjustment = 0.80  # Consider rest or very light
                adjustment_note = "Consider a rest day or very light session"

            # Build exercise recommendations with suggested weights
            exercise_recommendations = []
            for ex in template_exercises:
                ex_name = ex.get("name", "")
                target_sets = ex.get("sets", 3)
                target_reps = ex.get("reps", "8-10")
                target_rpe = ex.get("rpe_target", 7)

                if ex_name in exercise_history:
                    hist = exercise_history[ex_name]
                    last_weight = hist["last_weight"]
                    suggested_weight = int(last_weight * weight_adjustment / 5) * 5  # Round to nearest 5

                    days_since = (today - datetime.strptime(hist["last_date"], "%Y-%m-%d").date()).days

                    exercise_recommendations.append({
                        "name": ex_name,
                        "sets": target_sets,
                        "reps": target_reps,
                        "suggested_weight": suggested_weight,
                        "last_weight": last_weight,
                        "last_reps": hist["last_reps"],
                        "days_since": days_since
                    })
                else:
                    # No history - use starting weight if available
                    starting = ex.get("starting_weight")
                    exercise_recommendations.append({
                        "name": ex_name,
                        "sets": target_sets,
                        "reps": target_reps,
                        "suggested_weight": int(starting * weight_adjustment / 5) * 5 if starting else None,
                        "last_weight": None,
                        "last_reps": None,
                        "days_since": None
                    })

            # Build the output text
            if template:
                # Header
                recovery_text = f"## Today's Workout: {template.name}\n"
                if active_phase:
                    recovery_text += f"*Phase: {active_phase.name}*\n\n"

                # Recovery status
                if recovery:
                    recovery_text += "### Recovery Status\n"
                    recovery_text += f"- Sleep: {recovery.sleep_hours or 'N/A'} hrs\n"
                    recovery_text += f"- Soreness: {recovery.soreness_level or 'N/A'}/10\n"
                    recovery_text += f"- HRV: {recovery.hrv or 'N/A'} ms | HR: {recovery.heart_rate or 'N/A'} bpm\n"
                    recovery_text += f"- **Recovery Score: {recovery_score}/100** - {adjustment_note}\n\n"
                else:
                    recovery_text += "*No recovery data logged today - using standard weights*\n\n"

                # Exercise table with suggested weights
                recovery_text += "### Suggested Weights\n"
                recovery_text += "| Exercise | Sets × Reps | Today | Last |\n"
                recovery_text += "|----------|-------------|-------|------|\n"

                for rec in exercise_recommendations:
                    suggested = f"{rec['suggested_weight']} lbs" if rec['suggested_weight'] else "—"
                    last = f"{rec['last_weight']} lbs" if rec['last_weight'] else "—"
                    recovery_text += f"| {rec['name']} | {rec['sets']}×{rec['reps']} | **{suggested}** | {last} |\n"

                # Coaching note
                if recovery_factors:
                    recovery_text += f"\n*Note: Weights adjusted due to {', '.join(recovery_factors)}*"
            else:
                # Rest day
                recovery_text = "## Rest Day\n\n"
                if recovery:
                    recovery_text += "### Recovery Status\n"
                    recovery_text += f"- Sleep: {recovery.sleep_hours or 'N/A'} hrs\n"
                    recovery_text += f"- Soreness: {recovery.soreness_level or 'N/A'}/10\n"
                    recovery_text += f"- HRV: {recovery.hrv or 'N/A'} ms\n"
                    recovery_text += f"- Recovery Score: {recovery_score}/100\n\n"
                recovery_text += "No workout scheduled. Focus on recovery - stay hydrated and get good sleep."

            # Generate TTS
            audio_dir = BRIEFINGS_BASE_PATH / user_id / today_str
            recovery_audio_path = audio_dir / "recovery_brief.mp3"

            if template:
                tts_text = f"Today is {template.name}. "
                if recovery:
                    tts_text += f"Your recovery score is {recovery_score} out of 100. {adjustment_note}. "
                tts_text += f"You have {len(exercise_recommendations)} exercises planned."
            else:
                tts_text = "Today is a rest day. Focus on recovery."

            await self.generate_tts_audio(tts_text, recovery_audio_path)

            return recovery_text, str(recovery_audio_path) if recovery_audio_path.exists() else None

        except Exception as e:
            logger.error(f"Error generating recovery section: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return "Unable to generate recovery recommendations.", None


# Singleton instance
morning_brief_service = MorningBriefService()
