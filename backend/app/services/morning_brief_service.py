"""
Morning Brief Service
Orchestrates daily morning brief generation with news synthesis, weather, calendar, and TTS.
"""

import asyncio
import aiohttp
import logging
import os
import json
import re
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

logger = logging.getLogger(__name__)

# --- LLM Brief Prompts ---

BRIEF_SYSTEM_PROMPT = """You are Sara, David's personal AI assistant. Write his morning brief.

Rules:
- First person ("you have", "your"), 300-500 words
- Use light markdown: **bold** for emphasis, bullets where natural, but keep it speakable
- Prioritize by relevance: busy day → lead with calendar; rest day → lighter brief
- Pick the 2-3 most interesting news items, skip the rest
- Do NOT include any health, fitness, body, or biometric data (no HRV, heart rate, sleep stats, recovery scores, workout plans, nutrition advice)
- Do NOT include action items, to-do lists, micro-tasks, suggestions, or productivity advice — this is an informational brief, not a task list
- If dream insights exist, integrate them conversationally — don't label them "Dream Insights"
- No "Good morning David!" clichés — start with something specific and useful
- End with a brief, natural sendoff (1 sentence max)

Tone directive: {tone_directive}"""

BRIEF_USER_PROMPT = """Generate David's morning brief for today.

== WHO DAVID IS ==
{stable_layer}

== ACTIVE CONTEXT ==
{context_layer}

== YESTERDAY ==
{yesterday_summary}

== WEATHER ==
{weather}

== CALENDAR ==
{calendar}

== DREAM INSIGHTS ==
{dream_insights}

== TECH NEWS ==
{news}

Write the brief now."""


@dataclass
class FitnessRecoveryBrief:
    """Complete fitness and recovery data for morning brief."""
    recovery_text: str
    nutrition_text: str
    workout_recap_text: str
    today_plan_text: str
    insights_text: str
    recovery_tts: str
    nutrition_tts: str
    workout_recap_tts: str
    today_plan_tts: str
    insights_tts: str
    readiness_score: int
    has_data: bool = True


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
        health_digest: str = "",
        fitness_brief: Optional[FitnessRecoveryBrief] = None
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

        # FITNESS SECTIONS FIRST (per user preference)
        if fitness_brief and fitness_brief.has_data:
            # 1. Recovery Status (FIRST)
            if fitness_brief.recovery_text:
                sections.extend([
                    fitness_brief.recovery_text,
                    "",
                    "---",
                    "",
                ])

            # 2. Yesterday's Nutrition — skipped (Sara has its own nutrition section)

            # 3. Yesterday's Workout
            if fitness_brief.workout_recap_text:
                sections.extend([
                    fitness_brief.workout_recap_text,
                    "",
                    "---",
                    "",
                ])

            # 4. Today's Plan
            if fitness_brief.today_plan_text:
                sections.extend([
                    fitness_brief.today_plan_text,
                    "",
                    "---",
                    "",
                ])

            # 5. Smart Insights (data-driven analysis)
            if fitness_brief.insights_text:
                sections.extend([
                    fitness_brief.insights_text,
                    "",
                    "---",
                    "",
                ])

        # Add health digest if we have data (may overlap with fitness - can be removed if redundant)
        if health_digest and not (fitness_brief and fitness_brief.recovery_text):
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
        calendar_events: List[Dict],
        fitness_brief: Optional[FitnessRecoveryBrief] = None
    ) -> str:
        """Compose text optimized for TTS (more conversational)."""
        parts = [
            f"Good morning! It's {weekday}.",
            "",
            weather_tts,
            "",
        ]

        # FITNESS SECTIONS (full TTS as requested by user)
        if fitness_brief and fitness_brief.has_data:
            # 1. Recovery Status
            if fitness_brief.recovery_tts:
                parts.append(fitness_brief.recovery_tts)
                parts.append("")

            # 2. Yesterday's Nutrition — skipped (Sara has its own nutrition section)

            # 3. Yesterday's Workout
            if fitness_brief.workout_recap_tts:
                parts.append(fitness_brief.workout_recap_tts)
                parts.append("")

            # 4. Today's Plan
            if fitness_brief.today_plan_tts:
                parts.append(fitness_brief.today_plan_tts)
                parts.append("")

            # 5. Smart Insights
            if fitness_brief.insights_tts:
                parts.append(fitness_brief.insights_tts)
                parts.append("")

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

    def _derive_tone_directive(self, body_estimate) -> str:
        """Convert body state estimate into a tone instruction for the LLM."""
        directives = []

        if body_estimate.alertness < 0.35:
            directives.append("gentle, warm, and brief — he's still waking up")
        elif body_estimate.alertness > 0.7:
            directives.append("energetic and upbeat")

        if body_estimate.stress_load > 0.6:
            directives.append("keep things light, don't pile on")

        if body_estimate.overall_physical_readiness < 0.5:
            directives.append("encouraging about rest and recovery")

        if body_estimate.pattern_anomalies:
            directives.append(f"note unusual patterns: {', '.join(body_estimate.pattern_anomalies[:2])}")

        if not directives:
            return "Warm and natural morning energy."

        return ". ".join(directives) + "."

    def _strip_markdown_for_tts(self, text: str) -> str:
        """Remove markdown formatting for clean TTS output."""
        s = text
        s = re.sub(r'^#{1,6}\s+', '', s, flags=re.MULTILINE)  # headers
        s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)                 # bold
        s = re.sub(r'\*(.+?)\*', r'\1', s)                     # italic
        s = re.sub(r'`(.+?)`', r'\1', s)                       # inline code
        s = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', s)              # links
        s = re.sub(r'^-\s+', '', s, flags=re.MULTILINE)        # bullets
        s = re.sub(r'^---+$', '', s, flags=re.MULTILINE)       # rules
        s = re.sub(r'\n{3,}', '\n\n', s)                       # collapse newlines
        s = re.sub(r'\.\.+', '.', s)                           # double periods
        return s.strip()

    def _fallback_brief(self, weekday: str, date_str: str, weather_summary: str,
                        calendar_summary: str, news_summary: str) -> str:
        """Minimal template brief when LLM is unavailable."""
        return (
            f"Here's your brief for {weekday}, {date_str}.\n\n"
            f"{weather_summary}\n\n"
            f"{calendar_summary}\n\n"
            f"**Tech News**\n{news_summary}\n\n"
            f"Have a great day."
        )

    async def _generate_llm_brief(
        self, weekday: str, date_str: str, news_summary: str,
        weather_summary: str, calendar_summary: str, calendar_events: List[Dict],
        insights_summary: str,
        stable_layer: str, context_layer: str, yesterday_summary: str,
        tone_directive: str,
    ) -> str:
        """Generate a cohesive morning brief via a single LLM call."""
        try:
            system_msg = BRIEF_SYSTEM_PROMPT.format(tone_directive=tone_directive)

            user_msg = BRIEF_USER_PROMPT.format(
                stable_layer=stable_layer or "Not available yet.",
                context_layer=context_layer or "No active context.",
                yesterday_summary=yesterday_summary or "No summary from yesterday.",
                weather=weather_summary,
                calendar=calendar_summary,
                dream_insights=insights_summary or "None.",
                news=news_summary,
            )

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
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "stream": False
                    }
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"LLM brief generation failed ({response.status}): {error}")
                        return self._fallback_brief(weekday, date_str, weather_summary, calendar_summary, news_summary)

                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    word_count = len(content.split())
                    logger.info(f"LLM brief generated: {len(content)} chars, {word_count} words")
                    return content

        except Exception as e:
            logger.error(f"Error generating LLM brief: {e}")
            return self._fallback_brief(weekday, date_str, weather_summary, calendar_summary, news_summary)

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

    async def send_notification(self, user_id: str, weekday: str, db: Session = None) -> bool:
        """Send iOS push notification that brief is ready."""
        try:
            import httpx
            from sqlalchemy import text
            from sqlalchemy.orm import Session
            from app.db.base import SessionLocal

            # Get database session if not provided
            close_db = False
            if db is None:
                db = SessionLocal()
                close_db = True

            try:
                # Get user's push tokens
                result = db.execute(text("""
                    SELECT push_token FROM user_push_token
                    WHERE user_id = :user_id
                """), {"user_id": user_id})
                tokens = [row[0] for row in result.fetchall()]

                if not tokens:
                    logger.warning(f"No push tokens found for user {user_id}")
                    return False

                # Build Expo push messages
                messages = []
                for token in tokens:
                    messages.append({
                        "to": token,
                        "sound": "default",
                        "title": "Morning Brief Ready",
                        "body": f"Your {weekday} briefing is ready with tech news, weather, and your schedule.",
                        "data": {"screen": "MorningBrief"},
                        "priority": "high",
                    })

                # Send to Expo push notification service
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://exp.host/--/api/v2/push/send",
                        json=messages,
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        }
                    )

                    if response.status_code == 200:
                        logger.info(f"📱 iOS push notification sent for morning brief to user {user_id}")
                        return True
                    else:
                        logger.error(f"Push notification failed: {response.text}")
                        return False

            finally:
                if close_db:
                    db.close()

        except Exception as e:
            logger.error(f"Error sending iOS push notification: {e}")
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

        # Phase 2: Read daily brief context layers
        stable_content = ""
        context_content = ""
        yesterday_summary = ""
        try:
            from app.services.daily_brief import stable_layer as sl, context_layer as cl, archiver
            stable_content = sl.read(user_id)
            context_content = cl.read(user_id)
            archives = archiver.get_recent_archives(user_id, days=1)
            yesterday_summary = archives[0]["content"] if archives else ""
            logger.info(f"Context layers: stable={len(stable_content)} chars, context={len(context_content)} chars, yesterday={len(yesterday_summary)} chars")
        except Exception as e:
            logger.warning(f"Failed to read context layers: {e}")

        tone_directive = "Warm and natural morning energy."

        # Phase 3: Single LLM call for cohesive brief
        date_str = today.strftime("%B %d, %Y")
        full_text = await self._generate_llm_brief(
            weekday, date_str, news_summary, weather_summary,
            calendar_summary, calendar_events, insights_summary,
            stable_content, context_content,
            yesterday_summary, tone_directive,
        )

        # Phase 5: Strip markdown for TTS
        tts_text = self._strip_markdown_for_tts(full_text)

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

        # Send iOS push notification
        await self.send_notification(user_id, weekday, db)

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

    async def build_fitness_recovery_brief(self, user_id: str, db: Session) -> FitnessRecoveryBrief:
        """
        Build comprehensive fitness and recovery brief for morning briefing.
        Includes: recovery status, yesterday's nutrition, yesterday's workout, today's plan, smart insights.
        """
        try:
            today = date.today()
            yesterday = today - timedelta(days=1)
            today_str = today.strftime("%Y-%m-%d")
            yesterday_str = yesterday.strftime("%Y-%m-%d")

            # Build all sections (nutrition skipped — Sara has its own nutrition section)
            recovery_result = await self._build_recovery_status_section(user_id, db, today_str)
            nutrition_result = {"text": "", "tts": ""}
            workout_result = await self._build_workout_recap_section(user_id, db, yesterday_str)
            today_plan_result = await self._build_today_plan_section(user_id, db, today_str)
            insights_result = await self._build_smart_insights_section(user_id, db, yesterday_str)

            return FitnessRecoveryBrief(
                recovery_text=recovery_result["text"],
                nutrition_text=nutrition_result["text"],
                workout_recap_text=workout_result["text"],
                today_plan_text=today_plan_result["text"],
                insights_text=insights_result["text"],
                recovery_tts=recovery_result["tts"],
                nutrition_tts=nutrition_result["tts"],
                workout_recap_tts=workout_result["tts"],
                today_plan_tts=today_plan_result["tts"],
                insights_tts=insights_result["tts"],
                readiness_score=recovery_result.get("readiness_score", 100),
                has_data=True
            )

        except Exception as e:
            logger.error(f"Error building fitness recovery brief: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return FitnessRecoveryBrief(
                recovery_text="",
                nutrition_text="",
                workout_recap_text="",
                today_plan_text="",
                insights_text="",
                recovery_tts="",
                nutrition_tts="",
                workout_recap_tts="",
                today_plan_tts="",
                insights_tts="",
                readiness_score=100,
                has_data=False
            )

    async def _build_recovery_status_section(self, user_id: str, db: Session, today_str: str) -> Dict:
        """Build recovery status section with readiness score."""
        try:
            # Get today's recovery data
            recovery = db.execute(text("""
                SELECT sleep_hours, soreness_level, hrv, heart_rate, body_weight, weight_unit, notes
                FROM daily_recovery_log
                WHERE user_id = :user_id AND log_date = :today
            """), {"user_id": user_id, "today": today_str}).fetchone()

            # Get 7-day averages for comparison
            seven_days_ago = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
            averages = db.execute(text("""
                SELECT
                    AVG(sleep_hours) as avg_sleep,
                    AVG(hrv) as avg_hrv,
                    AVG(heart_rate) as avg_hr,
                    AVG(soreness_level) as avg_soreness,
                    AVG(body_weight) as avg_weight
                FROM daily_recovery_log
                WHERE user_id = :user_id AND log_date >= :seven_days_ago
            """), {"user_id": user_id, "seven_days_ago": seven_days_ago}).fetchone()

            if not recovery:
                return {
                    "text": "",
                    "tts": "No recovery data logged for today. Consider logging your sleep and soreness when you wake up.",
                    "readiness_score": 100
                }

            # Calculate readiness score (0-100)
            readiness_score = 100
            factors = []

            # Sleep factor (30% weight) - target 7-8 hrs
            if recovery.sleep_hours:
                if recovery.sleep_hours < 6:
                    readiness_score -= 30
                    factors.append(f"only {recovery.sleep_hours:.1f} hours of sleep")
                elif recovery.sleep_hours < 7:
                    readiness_score -= 15
                    factors.append(f"{recovery.sleep_hours:.1f} hours of sleep")
                elif recovery.sleep_hours > 9:
                    readiness_score -= 5  # Oversleep can indicate issues

            # HRV factor (25% weight) - compare to baseline
            if recovery.hrv and averages and averages.avg_hrv:
                hrv_diff = recovery.hrv - averages.avg_hrv
                if hrv_diff < -15:  # Significantly below baseline
                    readiness_score -= 25
                    factors.append(f"HRV {abs(hrv_diff):.0f}ms below baseline")
                elif hrv_diff < -8:
                    readiness_score -= 12
                    factors.append(f"HRV slightly below baseline")

            # Resting HR factor (20% weight) - elevated HR = poor recovery
            if recovery.heart_rate and averages and averages.avg_hr:
                hr_diff = recovery.heart_rate - averages.avg_hr
                if hr_diff > 10:  # Elevated
                    readiness_score -= 20
                    factors.append(f"elevated resting HR ({recovery.heart_rate} bpm)")
                elif hr_diff > 5:
                    readiness_score -= 10

            # Soreness factor (15% weight)
            if recovery.soreness_level:
                if recovery.soreness_level >= 8:
                    readiness_score -= 15
                    factors.append(f"high soreness ({recovery.soreness_level}/10)")
                elif recovery.soreness_level >= 6:
                    readiness_score -= 10
                    factors.append(f"moderate soreness ({recovery.soreness_level}/10)")
                elif recovery.soreness_level >= 4:
                    readiness_score -= 5

            # Cap score
            readiness_score = max(0, min(100, readiness_score))

            # Determine status message
            if readiness_score >= 85:
                status_msg = "Well recovered - good to push it today"
            elif readiness_score >= 70:
                status_msg = "Moderate recovery - train but listen to your body"
            elif readiness_score >= 50:
                status_msg = "Low recovery - consider lighter weights"
            else:
                status_msg = "Poor recovery - rest day recommended"

            # Build markdown text
            lines = ["## Recovery Status"]

            # Metrics table
            sleep_trend = ""
            if averages and averages.avg_sleep and recovery.sleep_hours:
                diff = recovery.sleep_hours - averages.avg_sleep
                sleep_trend = " ↑" if diff > 0.3 else " ↓" if diff < -0.3 else ""

            lines.append(f"- **Sleep**: {recovery.sleep_hours:.1f} hrs{sleep_trend}" +
                        (f" (7-day avg: {averages.avg_sleep:.1f})" if averages and averages.avg_sleep else ""))

            if recovery.hrv:
                hrv_trend = ""
                if averages and averages.avg_hrv:
                    diff = recovery.hrv - averages.avg_hrv
                    hrv_trend = " ↑" if diff > 5 else " ↓" if diff < -5 else ""
                lines.append(f"- **HRV**: {recovery.hrv:.0f} ms{hrv_trend}" +
                            (f" (avg: {averages.avg_hrv:.0f})" if averages and averages.avg_hrv else ""))

            if recovery.heart_rate:
                hr_trend = ""
                if averages and averages.avg_hr:
                    diff = recovery.heart_rate - averages.avg_hr
                    hr_trend = " ↑" if diff > 3 else " ↓" if diff < -3 else ""
                lines.append(f"- **Resting HR**: {recovery.heart_rate:.0f} bpm{hr_trend}" +
                            (f" (avg: {averages.avg_hr:.0f})" if averages and averages.avg_hr else ""))

            lines.append(f"- **Soreness**: {recovery.soreness_level}/10" if recovery.soreness_level else "- **Soreness**: Not logged")

            if recovery.body_weight:
                weight_unit = recovery.weight_unit or "lbs"
                weight_trend = ""
                if averages and averages.avg_weight:
                    diff = recovery.body_weight - averages.avg_weight
                    weight_trend = " ↑" if diff > 1 else " ↓" if diff < -1 else ""
                lines.append(f"- **Body Weight**: {recovery.body_weight:.1f} {weight_unit}{weight_trend}")

            lines.append(f"\n**Readiness Score: {readiness_score}/100** - {status_msg}")

            # Build TTS
            tts_parts = ["Let's start with your recovery status."]

            if recovery.sleep_hours:
                hrs = int(recovery.sleep_hours)
                mins = int((recovery.sleep_hours - hrs) * 60)
                if mins > 0:
                    tts_parts.append(f"You got {hrs} hours and {mins} minutes of sleep last night")
                else:
                    tts_parts.append(f"You got {hrs} hours of sleep last night")
                if recovery.sleep_hours >= 7 and recovery.sleep_hours <= 8:
                    tts_parts[-1] += ", right in your target range."
                elif recovery.sleep_hours < 7:
                    tts_parts[-1] += ", which is a bit low."
                else:
                    tts_parts[-1] += "."

            if recovery.hrv:
                tts_parts.append(f"Your HRV is {int(recovery.hrv)} milliseconds")
                if averages and averages.avg_hrv:
                    diff = recovery.hrv - averages.avg_hrv
                    if diff > 5:
                        tts_parts[-1] += f", which is {int(abs(diff))} points above your baseline. That's a good sign."
                    elif diff < -5:
                        tts_parts[-1] += f", which is {int(abs(diff))} points below your baseline."
                    else:
                        tts_parts[-1] += ", right around your baseline."
                else:
                    tts_parts[-1] += "."

            if recovery.heart_rate:
                tts_parts.append(f"Resting heart rate is {int(recovery.heart_rate)} beats per minute.")

            if recovery.soreness_level:
                if recovery.soreness_level <= 3:
                    tts_parts.append(f"Soreness is low at {recovery.soreness_level} out of 10.")
                elif recovery.soreness_level <= 6:
                    tts_parts.append(f"Soreness is moderate at {recovery.soreness_level} out of 10.")
                else:
                    tts_parts.append(f"Soreness is high at {recovery.soreness_level} out of 10.")

            if recovery.body_weight:
                weight_unit = recovery.weight_unit or "lbs"
                weight_str = f"{recovery.body_weight:.1f}".rstrip('0').rstrip('.')
                tts_parts.append(f"Body weight is {weight_str} {weight_unit}.")

            tts_parts.append(f"Overall, your readiness score is {readiness_score} out of 100. {status_msg}.")

            return {
                "text": "\n".join(lines),
                "tts": " ".join(tts_parts),
                "readiness_score": readiness_score
            }

        except Exception as e:
            logger.error(f"Error building recovery section: {e}")
            return {"text": "", "tts": "", "readiness_score": 100}

    def _parse_nutrition_from_program_notes(self, notes: str) -> Dict:
        """Parse nutrition targets from fitness program notes."""
        import re
        result = {}

        if not notes:
            return result

        # Parse calorie range like "2,400-2,600 kcal" or "2400 calories"
        cal_match = re.search(r'([\d,]+)(?:\s*-\s*([\d,]+))?\s*(?:kcal|calories?|cals?)', notes, re.IGNORECASE)
        if cal_match:
            low = int(cal_match.group(1).replace(',', ''))
            high = int(cal_match.group(2).replace(',', '')) if cal_match.group(2) else low
            result["calories"] = (low + high) // 2

        # Parse protein like "200g+ protein" or "180-200g protein"
        protein_match = re.search(r'([\d]+)(?:\s*-\s*([\d]+))?g?\+?\s*protein', notes, re.IGNORECASE)
        if protein_match:
            low = int(protein_match.group(1))
            high = int(protein_match.group(2)) if protein_match.group(2) else low
            # If it's "200g+" style, use the number as-is
            result["protein"] = (low + high) // 2 if protein_match.group(2) else low

        # Parse carbs like "250g carbs"
        carbs_match = re.search(r'([\d]+)(?:\s*-\s*([\d]+))?g?\s*carbs?', notes, re.IGNORECASE)
        if carbs_match:
            low = int(carbs_match.group(1))
            high = int(carbs_match.group(2)) if carbs_match.group(2) else low
            result["carbs"] = (low + high) // 2

        # Parse fats like "80g fat"
        fats_match = re.search(r'([\d]+)(?:\s*-\s*([\d]+))?g?\s*fats?', notes, re.IGNORECASE)
        if fats_match:
            low = int(fats_match.group(1))
            high = int(fats_match.group(2)) if fats_match.group(2) else low
            result["fats"] = (low + high) // 2

        return result

    async def _build_nutrition_recap_section(self, user_id: str, db: Session, yesterday_str: str) -> Dict:
        """Build yesterday's nutrition recap section."""
        try:
            # Get yesterday's food logs
            food_logs = db.execute(text("""
                SELECT meal_type, calories, protein, carbs, fats, logged_at
                FROM food_log
                WHERE user_id = :user_id AND DATE(logged_at) = :yesterday
                ORDER BY logged_at
            """), {"user_id": user_id, "yesterday": yesterday_str}).fetchall()

            # First try to get nutrition targets from active fitness program
            active_program = db.execute(text("""
                SELECT name, notes FROM fitness_program
                WHERE user_id = :user_id AND is_active = true
                ORDER BY created_at DESC LIMIT 1
            """), {"user_id": user_id}).fetchone()

            goals_dict = None
            program_name = None

            if active_program and active_program.notes:
                program_name = active_program.name
                parsed = self._parse_nutrition_from_program_notes(active_program.notes)
                if parsed.get("calories") and parsed.get("protein"):
                    goals_dict = {
                        "calories": parsed.get("calories", 2000),
                        "protein": parsed.get("protein", 150),
                        "carbs": parsed.get("carbs", 200),
                        "fats": parsed.get("fats", 65)
                    }
                    logger.info(f"Using nutrition targets from active program '{program_name}': {goals_dict}")

            # Fall back to fitness_goals table
            if not goals_dict:
                goals = db.execute(text("""
                    SELECT calories, protein, carbs, fats
                    FROM fitness_goals
                    WHERE user_id = :user_id
                """), {"user_id": user_id}).fetchone()

                if not goals:
                    goals_dict = {"calories": 2000, "protein": 150, "carbs": 200, "fats": 65}
                else:
                    goals_dict = {"calories": goals.calories or 2000, "protein": goals.protein or 150,
                                 "carbs": goals.carbs or 200, "fats": goals.fats or 65}

            if not food_logs:
                return {
                    "text": "",
                    "tts": "No meals were logged yesterday. Tracking your nutrition helps me give you better guidance."
                }

            # Sum up totals
            total_calories = sum(f.calories or 0 for f in food_logs)
            total_protein = sum(f.protein or 0 for f in food_logs)
            total_carbs = sum(f.carbs or 0 for f in food_logs)
            total_fats = sum(f.fats or 0 for f in food_logs)
            meal_count = len(food_logs)

            # Calculate percentages
            cal_pct = (total_calories / goals_dict["calories"] * 100) if goals_dict["calories"] else 0
            protein_pct = (total_protein / goals_dict["protein"] * 100) if goals_dict["protein"] else 0
            carbs_pct = (total_carbs / goals_dict["carbs"] * 100) if goals_dict["carbs"] else 0
            fats_pct = (total_fats / goals_dict["fats"] * 100) if goals_dict["fats"] else 0

            # Generate summary
            summaries = []
            if protein_pct >= 95:
                summaries.append("hit protein goal")
            elif protein_pct >= 80:
                summaries.append(f"close on protein ({int(goals_dict['protein'] - total_protein)}g short)")
            else:
                summaries.append(f"low on protein ({int(goals_dict['protein'] - total_protein)}g short)")

            cal_diff = total_calories - goals_dict["calories"]
            if abs(cal_diff) < 100:
                summaries.append("calories on target")
            elif cal_diff > 0:
                summaries.append(f"{int(cal_diff)} cal surplus")
            else:
                summaries.append(f"{int(abs(cal_diff))} cal deficit")

            summary_text = "; ".join(summaries)

            # Build markdown
            lines = ["## Yesterday's Nutrition"]
            lines.append(f"- **Calories**: {int(total_calories)} / {int(goals_dict['calories'])} ({int(cal_pct)}%)")
            lines.append(f"- **Protein**: {int(total_protein)}g / {int(goals_dict['protein'])}g ({int(protein_pct)}%)")
            lines.append(f"- **Carbs**: {int(total_carbs)}g / {int(goals_dict['carbs'])}g ({int(carbs_pct)}%)")
            lines.append(f"- **Fats**: {int(total_fats)}g / {int(goals_dict['fats'])}g ({int(fats_pct)}%)")
            lines.append(f"\n*{meal_count} meals logged. {summary_text.capitalize()}.*")

            # Build TTS
            tts_parts = ["Looking at yesterday's nutrition."]
            tts_parts.append(f"You logged {meal_count} meals totaling {int(total_calories)} calories.")

            cal_diff = total_calories - goals_dict["calories"]
            if abs(cal_diff) < 100:
                tts_parts.append(f"That's right on your {int(goals_dict['calories'])} calorie target.")
            elif cal_diff > 0:
                tts_parts.append(f"That's about {int(cal_diff)} calories over your {int(goals_dict['calories'])} target.")
            else:
                tts_parts.append(f"That's about {int(abs(cal_diff))} calories under your {int(goals_dict['calories'])} target.")

            if protein_pct >= 95:
                tts_parts.append(f"Protein was {int(total_protein)} grams, hitting your goal nicely.")
            else:
                tts_parts.append(f"Protein was {int(total_protein)} grams out of your {int(goals_dict['protein'])} gram goal.")

            tts_parts.append(f"Carbs came in at {int(total_carbs)} grams and fats at {int(total_fats)} grams.")

            return {
                "text": "\n".join(lines),
                "tts": " ".join(tts_parts)
            }

        except Exception as e:
            logger.error(f"Error building nutrition section: {e}")
            return {"text": "", "tts": ""}

    async def _build_workout_recap_section(self, user_id: str, db: Session, yesterday_str: str) -> Dict:
        """Build yesterday's workout recap section (summary level)."""
        try:
            # Get yesterday's workout logs
            workout_data = db.execute(text("""
                SELECT
                    exercise_id,
                    weight,
                    reps,
                    rpe,
                    session_time
                FROM workout_log
                WHERE user_id = :user_id
                  AND session_date = :yesterday
                  AND skipped = false
                ORDER BY created_at
            """), {"user_id": user_id, "yesterday": yesterday_str}).fetchall()

            if not workout_data:
                return {
                    "text": "",
                    "tts": "Yesterday was a rest day. No workout logged."
                }

            # Calculate summary stats
            total_volume = sum((w.weight or 0) * (w.reps or 0) for w in workout_data)
            total_sets = len(workout_data)
            exercises = list(set(w.exercise_id for w in workout_data if w.exercise_id))
            avg_rpe = sum(w.rpe or 0 for w in workout_data if w.rpe) / max(1, len([w for w in workout_data if w.rpe]))

            # Try to determine workout name from template or exercise pattern
            workout_name = self._infer_workout_name(exercises)

            # Estimate duration from session times if available
            times = [w.session_time for w in workout_data if w.session_time]
            duration_str = ""
            if len(times) >= 2:
                # Convert to minutes
                first_time = times[0]
                last_time = times[-1]
                if hasattr(first_time, 'hour'):
                    duration_mins = (last_time.hour * 60 + last_time.minute) - (first_time.hour * 60 + first_time.minute)
                    if duration_mins > 0:
                        duration_str = f" in about {duration_mins} minutes"

            # Infer muscle groups
            muscle_groups = self._infer_muscle_groups(exercises)

            # Build markdown
            lines = ["## Yesterday's Training"]
            lines.append(f"**{workout_name}**")
            lines.append(f"- Total Volume: {int(total_volume):,} lbs")
            lines.append(f"- Sets: {total_sets}")
            lines.append(f"- Exercises: {len(exercises)}")
            if avg_rpe > 0:
                lines.append(f"- Average RPE: {avg_rpe:.1f}/10")
            if muscle_groups:
                lines.append(f"- Muscles: {', '.join(muscle_groups)}")

            # Build TTS
            tts_parts = ["Now for yesterday's training."]
            tts_parts.append(f"You completed {workout_name}{duration_str}.")
            tts_parts.append(f"Total volume was {int(total_volume):,} pounds across {total_sets} sets.")
            if muscle_groups:
                tts_parts.append(f"You worked {', '.join(muscle_groups[:-1])}" +
                               (f" and {muscle_groups[-1]}." if len(muscle_groups) > 1 else "."))

            return {
                "text": "\n".join(lines),
                "tts": " ".join(tts_parts)
            }

        except Exception as e:
            logger.error(f"Error building workout recap section: {e}")
            return {"text": "", "tts": ""}

    def _infer_workout_name(self, exercises: List[str]) -> str:
        """Infer workout name from exercise list."""
        exercises_lower = [e.lower() for e in exercises]

        # Check for common patterns
        push_indicators = ["bench", "press", "fly", "dip", "pushdown", "tricep"]
        pull_indicators = ["row", "pull", "curl", "lat", "deadlift", "shrug"]
        leg_indicators = ["squat", "leg", "lunge", "calf", "hamstring", "quad"]

        push_count = sum(1 for e in exercises_lower for p in push_indicators if p in e)
        pull_count = sum(1 for e in exercises_lower for p in pull_indicators if p in e)
        leg_count = sum(1 for e in exercises_lower for p in leg_indicators if p in e)

        if leg_count > push_count and leg_count > pull_count:
            return "Leg Day"
        elif push_count > pull_count:
            return "Push Day"
        elif pull_count > push_count:
            return "Pull Day"
        else:
            return "Workout Session"

    def _infer_muscle_groups(self, exercises: List[str]) -> List[str]:
        """Infer muscle groups from exercise list."""
        exercises_lower = [e.lower() for e in exercises]
        groups = []

        muscle_keywords = {
            "chest": ["bench", "fly", "chest", "pec"],
            "back": ["row", "pull", "lat", "back"],
            "shoulders": ["press", "shoulder", "delt", "lateral", "rear delt"],
            "triceps": ["tricep", "pushdown", "skull", "dip"],
            "biceps": ["curl", "bicep"],
            "legs": ["squat", "leg", "lunge", "calf"],
            "quads": ["squat", "leg press", "extension", "lunge"],
            "hamstrings": ["deadlift", "curl", "hamstring", "rdl"],
            "glutes": ["hip thrust", "glute", "deadlift"]
        }

        for group, keywords in muscle_keywords.items():
            for e in exercises_lower:
                if any(k in e for k in keywords):
                    if group not in groups:
                        groups.append(group)
                    break

        return groups[:4]  # Limit to 4 groups

    async def _build_today_plan_section(self, user_id: str, db: Session, today_str: str) -> Dict:
        """Build today's workout plan section."""
        try:
            today = date.today()
            day_of_week = today.strftime("%A").lower()

            # Find active phase
            active_phase = db.execute(text("""
                SELECT id, name FROM fitness_phase
                WHERE user_id = :user_id AND status = 'active'
                LIMIT 1
            """), {"user_id": user_id}).fetchone()

            if not active_phase:
                return {
                    "text": "",
                    "tts": "No active training program. Enjoy your rest day or set up a workout plan."
                }

            # Find today's scheduled template
            templates = db.execute(text("""
                SELECT id, name, exercises, scheduled_days, notes
                FROM fitness_template
                WHERE user_id = :user_id AND phase_id = :phase_id
            """), {"user_id": user_id, "phase_id": active_phase.id}).fetchall()

            today_template = None
            for t in templates:
                if t.scheduled_days:
                    days = json.loads(t.scheduled_days or "[]")
                    if day_of_week in [d.lower() for d in days]:
                        today_template = t
                        break

            if not today_template:
                return {
                    "text": "## Today's Plan\n**Rest Day** - No workout scheduled. Focus on recovery.",
                    "tts": "Today is a rest day. No workout scheduled. Focus on recovery and stay hydrated."
                }

            # Parse exercises
            exercises = json.loads(today_template.exercises or "[]")
            exercise_names = [e.get("name", "") for e in exercises if e.get("name")]

            # Build markdown
            lines = ["## Today's Plan"]
            lines.append(f"**{today_template.name}**")
            if exercise_names:
                lines.append(f"- Exercises: {', '.join(exercise_names[:5])}" +
                           (" ..." if len(exercise_names) > 5 else ""))
            if today_template.notes:
                lines.append(f"- Notes: {today_template.notes}")

            # Build TTS
            tts_parts = [f"For today, you have {today_template.name} scheduled."]
            if exercise_names:
                if len(exercise_names) <= 3:
                    tts_parts.append(f"Key exercises include {', '.join(exercise_names)}.")
                else:
                    tts_parts.append(f"You've got {len(exercise_names)} exercises planned including {', '.join(exercise_names[:3])}.")

            return {
                "text": "\n".join(lines),
                "tts": " ".join(tts_parts)
            }

        except Exception as e:
            logger.error(f"Error building today's plan section: {e}")
            return {"text": "", "tts": ""}

    # ========== SMART INSIGHTS METHODS ==========

    async def _get_extended_baselines(self, user_id: str, db: Session) -> Dict:
        """Get 7-day, 30-day, and 90-day baselines for recovery metrics."""
        try:
            today = date.today()
            baselines = {}

            for period_name, days in [("7d", 7), ("30d", 30), ("90d", 90)]:
                start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
                result = db.execute(text("""
                    SELECT
                        AVG(sleep_hours) as avg_sleep,
                        AVG(hrv) as avg_hrv,
                        AVG(heart_rate) as avg_hr,
                        AVG(soreness_level) as avg_soreness,
                        COUNT(*) as data_points
                    FROM daily_recovery_log
                    WHERE user_id = :user_id AND log_date >= :start_date
                """), {"user_id": user_id, "start_date": start_date}).fetchone()

                if result and result.data_points and result.data_points > 0:
                    baselines[period_name] = {
                        "sleep": result.avg_sleep,
                        "hrv": result.avg_hrv,
                        "hr": result.avg_hr,
                        "soreness": result.avg_soreness,
                        "data_points": result.data_points
                    }

            return baselines
        except Exception as e:
            logger.error(f"Error getting extended baselines: {e}")
            return {}

    async def _check_for_prs(self, user_id: str, db: Session, yesterday_str: str) -> Optional[str]:
        """Check if any PRs were hit yesterday."""
        try:
            # Get yesterday's exercises with their max weights
            yesterday_lifts = db.execute(text("""
                SELECT exercise_id, MAX(weight) as max_weight, MAX(reps) as max_reps
                FROM workout_log
                WHERE user_id = :user_id
                  AND session_date = :yesterday
                  AND weight IS NOT NULL
                  AND skipped = false
                GROUP BY exercise_id
            """), {"user_id": user_id, "yesterday": yesterday_str}).fetchall()

            if not yesterday_lifts:
                return None

            prs = []
            for lift in yesterday_lifts:
                # Get all-time max for this exercise (before yesterday)
                all_time = db.execute(text("""
                    SELECT MAX(weight) as max_weight
                    FROM workout_log
                    WHERE user_id = :user_id
                      AND exercise_id = :exercise_id
                      AND session_date < :yesterday
                      AND weight IS NOT NULL
                      AND skipped = false
                """), {"user_id": user_id, "exercise_id": lift.exercise_id, "yesterday": yesterday_str}).fetchone()

                if all_time and all_time.max_weight:
                    if lift.max_weight > all_time.max_weight:
                        prs.append(f"{lift.exercise_id} at {int(lift.max_weight)} lbs")
                elif lift.max_weight:  # First time doing this exercise
                    prs.append(f"{lift.exercise_id} at {int(lift.max_weight)} lbs (first time!)")

            if prs:
                if len(prs) == 1:
                    return f"New PR on {prs[0]}!"
                else:
                    return f"New PRs on {', '.join(prs[:2])}!"
            return None

        except Exception as e:
            logger.error(f"Error checking for PRs: {e}")
            return None

    async def _check_fatigue_indicators(self, user_id: str, db: Session) -> Optional[str]:
        """Check for fatigue indicators that might suggest a deload."""
        try:
            today = date.today()
            two_weeks_ago = (today - timedelta(days=14)).strftime("%Y-%m-%d")

            # Check consecutive training days
            recent_workouts = db.execute(text("""
                SELECT DISTINCT session_date
                FROM workout_log
                WHERE user_id = :user_id
                  AND session_date >= :two_weeks_ago
                  AND skipped = false
                ORDER BY session_date DESC
            """), {"user_id": user_id, "two_weeks_ago": two_weeks_ago}).fetchall()

            consecutive_days = 0
            if recent_workouts:
                prev_date = today
                for row in recent_workouts:
                    if row.session_date:
                        workout_date = row.session_date if isinstance(row.session_date, date) else datetime.strptime(str(row.session_date), "%Y-%m-%d").date()
                        if (prev_date - workout_date).days <= 1:
                            consecutive_days += 1
                            prev_date = workout_date
                        else:
                            break

            # Check HRV trend (declining over 7+ days is concerning)
            hrv_trend = db.execute(text("""
                SELECT log_date, hrv
                FROM daily_recovery_log
                WHERE user_id = :user_id
                  AND hrv IS NOT NULL
                  AND log_date >= :two_weeks_ago
                ORDER BY log_date DESC
                LIMIT 10
            """), {"user_id": user_id, "two_weeks_ago": two_weeks_ago}).fetchall()

            hrv_declining = False
            if len(hrv_trend) >= 5:
                # Simple trend: compare first half avg to second half avg
                recent_avg = sum(r.hrv for r in hrv_trend[:len(hrv_trend)//2]) / (len(hrv_trend)//2)
                older_avg = sum(r.hrv for r in hrv_trend[len(hrv_trend)//2:]) / (len(hrv_trend) - len(hrv_trend)//2)
                if recent_avg < older_avg * 0.9:  # 10% decline
                    hrv_declining = True

            # Generate insight
            if consecutive_days >= 5 and hrv_declining:
                return f"You've trained {consecutive_days} days in a row and your HRV is trending down. Consider a rest day or deload."
            elif consecutive_days >= 6:
                return f"You've trained {consecutive_days} days straight. A rest day might help your gains."
            elif hrv_declining:
                return "Your HRV has been declining lately. Listen to your body and prioritize recovery."

            return None

        except Exception as e:
            logger.error(f"Error checking fatigue indicators: {e}")
            return None

    async def _check_nutrition_patterns(self, user_id: str, db: Session) -> Optional[str]:
        """Check for nutrition patterns and streaks."""
        try:
            today = date.today()
            two_weeks_ago = (today - timedelta(days=14)).strftime("%Y-%m-%d")

            # Get daily nutrition totals for past 2 weeks
            daily_nutrition = db.execute(text("""
                SELECT DATE(logged_at) as log_date,
                       SUM(calories) as total_calories,
                       SUM(protein) as total_protein
                FROM food_log
                WHERE user_id = :user_id
                  AND logged_at >= :two_weeks_ago
                GROUP BY DATE(logged_at)
                ORDER BY log_date DESC
            """), {"user_id": user_id, "two_weeks_ago": two_weeks_ago}).fetchall()

            if len(daily_nutrition) < 3:
                return None

            # First try to get goals from active fitness program
            cal_goal = None
            protein_goal = None

            active_program = db.execute(text("""
                SELECT notes FROM fitness_program
                WHERE user_id = :user_id AND is_active = true
                ORDER BY created_at DESC LIMIT 1
            """), {"user_id": user_id}).fetchone()

            if active_program and active_program.notes:
                parsed = self._parse_nutrition_from_program_notes(active_program.notes)
                cal_goal = parsed.get("calories")
                protein_goal = parsed.get("protein")

            # Fall back to fitness_goals table
            if not cal_goal or not protein_goal:
                goals = db.execute(text("""
                    SELECT calories, protein FROM fitness_goals WHERE user_id = :user_id
                """), {"user_id": user_id}).fetchone()

                if not goals:
                    return None

                cal_goal = cal_goal or goals.calories or 2000
                protein_goal = protein_goal or goals.protein or 150

            # Check protein streak
            protein_streak = 0
            for day in daily_nutrition:
                if day.total_protein and day.total_protein >= protein_goal * 0.95:
                    protein_streak += 1
                else:
                    break

            # Check calorie deficit streak
            deficit_streak = 0
            for day in daily_nutrition:
                if day.total_calories and day.total_calories < cal_goal:
                    deficit_streak += 1
                else:
                    break

            # Check calorie surplus streak
            surplus_streak = 0
            for day in daily_nutrition:
                if day.total_calories and day.total_calories > cal_goal:
                    surplus_streak += 1
                else:
                    break

            # Generate insight (prioritize most impressive streak)
            insights = []
            if protein_streak >= 5:
                insights.append(f"Great consistency - you've hit your protein goal {protein_streak} days in a row!")
            if deficit_streak >= 4:
                insights.append(f"You've been in a caloric deficit for {deficit_streak} days. Stay consistent!")
            if surplus_streak >= 4:
                insights.append(f"You've been in a surplus for {surplus_streak} days - good for building.")

            return insights[0] if insights else None

        except Exception as e:
            logger.error(f"Error checking nutrition patterns: {e}")
            return None

    async def _check_progression(self, user_id: str, db: Session) -> Optional[str]:
        """Check for progressive overload on key lifts."""
        try:
            today = date.today()
            four_weeks_ago = (today - timedelta(days=28)).strftime("%Y-%m-%d")
            eight_weeks_ago = (today - timedelta(days=56)).strftime("%Y-%m-%d")

            # Key compound lifts to track
            key_lifts = ["bench press", "squat", "deadlift", "overhead press", "barbell row"]

            progressions = []
            stalls = []

            for lift_pattern in key_lifts:
                # Get recent max (last 4 weeks)
                recent = db.execute(text("""
                    SELECT MAX(weight) as max_weight
                    FROM workout_log
                    WHERE user_id = :user_id
                      AND LOWER(exercise_id) LIKE :pattern
                      AND session_date >= :four_weeks_ago
                      AND weight IS NOT NULL
                      AND skipped = false
                """), {"user_id": user_id, "pattern": f"%{lift_pattern}%", "four_weeks_ago": four_weeks_ago}).fetchone()

                # Get older max (4-8 weeks ago)
                older = db.execute(text("""
                    SELECT MAX(weight) as max_weight
                    FROM workout_log
                    WHERE user_id = :user_id
                      AND LOWER(exercise_id) LIKE :pattern
                      AND session_date >= :eight_weeks_ago
                      AND session_date < :four_weeks_ago
                      AND weight IS NOT NULL
                      AND skipped = false
                """), {"user_id": user_id, "pattern": f"%{lift_pattern}%",
                       "eight_weeks_ago": eight_weeks_ago, "four_weeks_ago": four_weeks_ago}).fetchone()

                if recent and recent.max_weight and older and older.max_weight:
                    diff = recent.max_weight - older.max_weight
                    if diff >= 5:  # At least 5 lbs increase
                        lift_name = lift_pattern.replace(" ", " ").title()
                        progressions.append(f"{lift_name} up {int(diff)} lbs")
                    elif diff <= -5:  # Regression
                        stalls.append(lift_pattern.title())

            # Generate insight
            if progressions:
                return f"Progress check: {progressions[0]} from last month. Keep it up!"
            elif stalls:
                return f"{stalls[0]} has stalled - consider changing rep scheme or adding volume."

            return None

        except Exception as e:
            logger.error(f"Error checking progression: {e}")
            return None

    async def _build_smart_insights_section(self, user_id: str, db: Session, yesterday_str: str) -> Dict:
        """Build smart insights section with data-driven analysis."""
        try:
            insights = []

            # Check for PRs (highest priority)
            pr_insight = await self._check_for_prs(user_id, db, yesterday_str)
            if pr_insight:
                insights.append(("pr", pr_insight))

            # Check fatigue indicators
            fatigue_insight = await self._check_fatigue_indicators(user_id, db)
            if fatigue_insight:
                insights.append(("fatigue", fatigue_insight))

            # Nutrition patterns skipped — Sara has its own nutrition section

            # Check progression
            progression_insight = await self._check_progression(user_id, db)
            if progression_insight:
                insights.append(("progression", progression_insight))

            if not insights:
                return {"text": "", "tts": ""}

            # Build markdown - limit to 2-3 most important insights
            lines = ["## Insights"]
            for insight_type, insight_text in insights[:3]:
                emoji = {"pr": "🏆", "fatigue": "⚠️", "nutrition": "🍽️", "progression": "📈"}.get(insight_type, "💡")
                lines.append(f"{emoji} {insight_text}")

            # Build TTS
            tts_parts = ["Here are some insights based on your data."]
            for _, insight_text in insights[:2]:  # Limit TTS to 2 insights
                tts_parts.append(insight_text)

            return {
                "text": "\n".join(lines),
                "tts": " ".join(tts_parts)
            }

        except Exception as e:
            logger.error(f"Error building smart insights section: {e}")
            return {"text": "", "tts": ""}

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
