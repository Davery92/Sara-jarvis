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

from app.core.config import settings
from .news_aggregator_service import news_aggregator_service, NewsItem
from .weather_service import weather_service, WeatherData
from .notification_service import notification_service, NotificationPriority

logger = logging.getLogger(__name__)

# --- LLM Brief Prompts ---

BRIEF_SYSTEM_PROMPT = """You are Sara, David's personal AI assistant. Write his morning brief.

Rules:
- First person ("you have", "your"), {word_min}-{word_max} words
- Use light markdown: **bold** for emphasis, bullets where natural, but keep it speakable
- Prioritize by relevance: busy day → lead with calendar; rest day → lighter brief
- Pick the 2-3 most interesting news items, skip the rest
- Do NOT include any health, fitness, body, or biometric data (no HRV, heart rate, sleep stats, recovery scores, workout plans, nutrition advice)
- Do NOT include action items, to-do lists, micro-tasks, suggestions, or productivity advice — this is an informational brief, not a task list
- If dream insights exist, integrate them conversationally — don't label them "Dream Insights"
- No "Good morning David!" clichés — start with something specific and useful
- End with a brief, natural sendoff (1 sentence max)

Tone directive: {tone_directive}"""

BRIEF_USER_PROMPT = """Generate David's morning brief for today, {today_date}.

== WHO DAVID IS ==
{stable_layer}

== ACTIVE CONTEXT (filtered for today) ==
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

Remember: today is {today_date}. Do not reference events, locations, or meals from previous days
as if they are current. If the active context mentions something from yesterday or earlier,
treat it as past — do not present it as today's plan.

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
    calendar_name: Optional[str] = None

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
        self._refresh_llm_config()
        self.llm_api_key = os.environ.get("OPENAI_API_KEY", "dummy")

    def _refresh_llm_config(self):
        """Reload background LLM settings so model switches apply live."""
        # Background LLM configuration (separate from interactive chat model)
        self.llm_base_url = settings.bg_llm_primary_url
        self.llm_model = settings.bg_llm_primary_model

    async def _bootstrap_stable_layer(self, user_id: str, db: Session) -> str:
        """
        Generate a lightweight stable layer on-the-fly when the weekly synthesis
        hasn't run yet. Uses PKG summary + recent episodic memory to build a
        minimal personal context so the morning brief personal section isn't empty.
        """
        logger.info(f"Bootstrapping stable layer for user {user_id[:8]} (weekly synthesis not yet available)")
        parts = []

        # 1. Pull from Personal Knowledge Graph
        try:
            from app.services.pkg_context_provider import pkg_context
            pkg_summary = pkg_context.get_david_summary_brief(user_id, max_facts=10)
            if pkg_summary and pkg_summary.strip():
                parts.append(pkg_summary.strip())
                logger.debug(f"PKG contributed {len(pkg_summary)} chars to stable bootstrap")
        except Exception as e:
            logger.warning(f"PKG unavailable for stable bootstrap: {e}")

        # 2. Pull recent episodic memory highlights (high-importance episodes).
        # Recency cutoff is critical: without it, a single high-importance
        # assistant message from weeks ago (e.g. "your 10:30 with Matt about the
        # operating agreement") gets recycled into the morning brief every day
        # and the LLM rephrases it as if it's still pending. Restrict to the
        # last 3 days and to user-stated content (assistant turns are advice,
        # not facts about David).
        try:
            rows = db.execute(text("""
                SELECT content, importance
                FROM episode
                WHERE user_id = :user_id
                  AND importance >= 0.7
                  AND role = 'user'
                  AND created_at >= NOW() - INTERVAL '3 days'
                ORDER BY created_at DESC
                LIMIT 8
            """), {"user_id": user_id}).fetchall()

            if rows:
                memory_lines = []
                for row in rows:
                    # Truncate long episodes for the brief summary
                    snippet = (row.content or "")[:200]
                    if len(row.content or "") > 200:
                        snippet += "..."
                    memory_lines.append(f"- {snippet}")
                parts.append("Key recent memories:\n" + "\n".join(memory_lines))
                logger.debug(f"Episodic memory contributed {len(rows)} items to stable bootstrap")
        except Exception as e:
            logger.warning(f"Episodic memory unavailable for stable bootstrap: {e}")

        if not parts:
            logger.info("Stable bootstrap produced no content (PKG and memory both empty)")
            return ""

        bootstrapped = "\n\n".join(parts)
        logger.info(f"Stable layer bootstrapped with {len(bootstrapped)} chars for user {user_id[:8]}")
        return bootstrapped

    def _get_fresh_context_content(self, user_id: str, raw_context: str) -> str:
        """
        Return context layer content only if it is fresh enough for a morning brief.
        Prevents stale project/nutrition context from older days bleeding into today's brief.
        """
        try:
            context_path = Path("/home/david/jarvis/data/briefs") / user_id / "layers" / "context.md"
            if not context_path.exists() or not raw_context:
                return ""

            modified_at = datetime.fromtimestamp(context_path.stat().st_mtime, tz=dt_timezone.utc)
            age = local_now() - modified_at
            if age > timedelta(hours=18):
                logger.info(
                    "Skipping stale context layer for morning brief: age=%sh user=%s",
                    round(age.total_seconds() / 3600, 1),
                    user_id[:8],
                )
                return ""

            # Guard against content that was rewritten recently but still references old dates.
            # Extract all date references and reject content where the *latest* mention
            # is before yesterday.  Also strip out individual lines/paragraphs that
            # reference dates older than yesterday so partial staleness doesn't leak through.
            today_local = local_today()
            yesterday = today_local - timedelta(days=1)

            month_map = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }

            # Also match day-of-week references like "Monday", "Tuesday" etc.
            # to catch phrases like "Monday ribs" or "in Sparta today" with a weekday anchor.
            day_of_week_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6,
            }

            def _parse_date_refs(text: str) -> list[date]:
                """Extract all date references from text."""
                refs = []
                # Match "Month Day" patterns (e.g. "Feb 18", "February 18")
                for m in re.finditer(
                    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})\b",
                    text,
                    re.IGNORECASE,
                ):
                    month_num = month_map.get(m.group(1)[:3].lower())
                    if not month_num:
                        continue
                    try:
                        refs.append(date(today_local.year, month_num, int(m.group(2))))
                    except ValueError:
                        continue

                # Match "YYYY-MM-DD" patterns
                for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
                    try:
                        refs.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                    except ValueError:
                        continue

                # Match weekday names and map to most recent occurrence
                for m in re.finditer(
                    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
                    text,
                    re.IGNORECASE,
                ):
                    target_dow = day_of_week_map.get(m.group(1).lower())
                    if target_dow is None:
                        continue
                    # Find the most recent past occurrence of this weekday
                    days_back = (today_local.weekday() - target_dow) % 7
                    if days_back == 0:
                        # Could be today — include it (it's fresh)
                        refs.append(today_local)
                    else:
                        refs.append(today_local - timedelta(days=days_back))

                return refs

            # Detect relative temporal phrases that are stale when read the next morning.
            # These are phrases written "yesterday evening" that reference "tonight" or "tomorrow"
            # which have now passed.
            _STALE_RELATIVE_PATTERNS = [
                r"\bpending\s+(?:tonight|this\s+evening)\b",
                r"\bawaiting\s+.*?\btonight\b",
                r"\btonight['']?s?\b.*?\b(?:evaluation|assessment|verdict|check)\b",
                r"\b(?:evaluation|assessment|verdict|check)\b.*?\btonight\b",
                r"\bwill\s+(?:be\s+)?(?:checking|evaluating|assessing)\b",
            ]
            _stale_relative_re = re.compile("|".join(_STALE_RELATIVE_PATTERNS), re.IGNORECASE)

            # First: check if ALL date references in the entire content are stale
            all_refs = _parse_date_refs(raw_context)
            if all_refs:
                latest_ref = max(all_refs)
                if latest_ref < yesterday:
                    logger.info(
                        "Skipping stale context layer by content date: latest_ref=%s today=%s user=%s",
                        latest_ref.isoformat(),
                        today_local.isoformat(),
                        user_id[:8],
                    )
                    return ""

            # Second: line-by-line filtering to strip stale paragraphs while keeping fresh ones.
            # Lines referencing yesterday or older are stripped (the brief is for TODAY).
            # Lines with stale relative phrases ("pending tonight") are also stripped.
            cleaned_lines = []
            for line in raw_context.split("\n"):
                # Strip lines with stale relative temporal phrases
                if _stale_relative_re.search(line):
                    logger.debug("Stripping stale relative-time line: %.80s", line)
                    continue

                line_refs = _parse_date_refs(line)
                if line_refs:
                    line_latest = max(line_refs)
                    # Strip lines referencing yesterday or older — the brief is for TODAY
                    if line_latest <= yesterday:
                        logger.debug(
                            "Stripping stale context line (ref=%s): %.80s",
                            line_latest.isoformat(),
                            line,
                        )
                        continue
                cleaned_lines.append(line)

            cleaned = "\n".join(cleaned_lines).strip()
            if not cleaned:
                logger.info("Context layer entirely stale after line filtering, user=%s", user_id[:8])
                return ""

            return cleaned
        except Exception as e:
            logger.warning(f"Failed context freshness check, using raw context: {e}")
            return raw_context

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
            self._refresh_llm_config()
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
                        "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    }
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"LLM synthesis failed: {error}")
                        return raw_news  # Fall back to raw news

                    data = await response.json()
                    content = data["choices"][0]["message"]["content"] or ""
                    finish_reason = data["choices"][0].get("finish_reason", "unknown")
                    logger.info(f"News synthesis complete: {len(content)} chars, finish_reason: {finish_reason}")
                    # If thinking mode consumed all tokens, fall back to raw news
                    if not content.strip():
                        logger.warning("News synthesis returned empty content, falling back to raw news")
                        return raw_news
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
                    'hrv_morning': ('HRV (morning)', 'ms'),
                    'sleep_hours': ('Sleep', 'hrs'),
                    'sleep_deep_min': ('Deep sleep', 'min'),
                    'sleep_rem_min': ('REM sleep', 'min'),
                    'sleep_core_min': ('Core sleep', 'min'),
                    'sleep_awake_min': ('Awake', 'min'),
                    'weight': ('Weight', 'lbs'),
                    'steps': ('Steps', ''),
                    'active_energy': ('Active Cal', 'kcal'),
                    'spo2': ('Blood Oxygen', '%'),
                    'respiratory_rate': ('Resp Rate', 'br/min'),
                    'body_temp': ('Body Temp', '°F'),
                    'vo2_max': ('VO2 max', 'ml/kg/min'),
                    'walking_hr_avg': ('Walking HR', 'bpm'),
                    'hr_recovery_1min': ('HR Recovery', 'bpm'),
                    'stand_minutes': ('Stand', 'min'),
                    'exercise_minutes': ('Exercise', 'min'),
                    'flights_climbed': ('Flights', ''),
                    'mindful_minutes': ('Mindful', 'min'),
                }

                for metric_type, data in metrics.items():
                    if data.get('current_value') is None:
                        continue

                    display_name, unit = metric_display.get(metric_type, (metric_type.replace('_', ' ').title(), ''))
                    value = data['current_value']
                    baseline = data.get('baseline')
                    status = data.get('status', 'normal')

                    # Format the value
                    if metric_type in ['resting_hr', 'hrv', 'hrv_morning', 'steps',
                                       'walking_hr_avg', 'hr_recovery_1min',
                                       'stand_minutes', 'exercise_minutes',
                                       'flights_climbed', 'mindful_minutes',
                                       'sleep_deep_min', 'sleep_rem_min',
                                       'sleep_core_min', 'sleep_awake_min']:
                        value_str = f"{int(value)}"
                    elif metric_type in ('sleep_hours', 'weight', 'body_temp',
                                         'spo2', 'respiratory_rate', 'vo2_max'):
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
                        if metric_type in ['resting_hr', 'hrv', 'hrv_morning', 'steps',
                                           'walking_hr_avg', 'hr_recovery_1min',
                                           'stand_minutes', 'exercise_minutes',
                                           'flights_climbed', 'mindful_minutes',
                                           'sleep_deep_min', 'sleep_rem_min',
                                           'sleep_core_min', 'sleep_awake_min']:
                            baseline_str = f"{int(baseline)}"
                        elif metric_type in ('sleep_hours', 'weight', 'body_temp',
                                             'spo2', 'respiratory_rate', 'vo2_max'):
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

    def _check_calendar_sync_freshness(self, user_id: str, db: Session) -> tuple[bool, Optional[datetime]]:
        """
        Check how fresh the calendar data is by looking at the most recent updated_at
        on the calendar_event table (iOS-synced events). Returns (is_fresh, last_sync_time).
        Fresh = updated within the last 24 hours.
        """
        try:
            row = db.execute(text("""
                SELECT MAX(updated_at) AS last_sync
                FROM calendar_event
                WHERE user_id = :user_id
            """), {"user_id": user_id}).fetchone()

            if not row or not row.last_sync:
                return False, None

            last_sync = row.last_sync
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=dt_timezone.utc)

            age = local_now() - last_sync
            is_fresh = age < timedelta(hours=24)
            return is_fresh, last_sync
        except Exception as e:
            logger.warning(f"Could not check calendar sync freshness: {e}")
            return False, None

    async def gather_calendar(self, user_id: str, db: Session) -> tuple[str, List[Dict]]:
        """Gather today's calendar events from iOS-synced calendar_event table."""
        try:
            # Check sync freshness before querying
            is_fresh, last_sync_time = self._check_calendar_sync_freshness(user_id, db)

            # calendar_event stores naive local times (already in user's timezone)
            today = local_today()
            start_of_day = datetime.combine(today, datetime.min.time())
            end_of_day = datetime.combine(today, datetime.max.time())

            # Exclude gym/workout calendar entries — David's split routine
            # doesn't belong in the morning brief schedule. Workouts get
            # surfaced through the dedicated fitness section instead.
            result = db.execute(text("""
                SELECT title, start_time, end_time, location, all_day, ios_calendar_name
                FROM calendar_event
                WHERE user_id = :user_id
                  AND start_time >= :start_of_day
                  AND start_time <= :end_of_day
                  AND title NOT LIKE '%🏋️%'
                  AND LOWER(title) NOT LIKE '%push a%'
                  AND LOWER(title) NOT LIKE '%push b%'
                  AND LOWER(title) NOT LIKE '%pull a%'
                  AND LOWER(title) NOT LIKE '%pull b%'
                  AND LOWER(title) NOT LIKE '%legs a%'
                  AND LOWER(title) NOT LIKE '%legs b%'
                ORDER BY start_time
            """), {
                "user_id": user_id,
                "start_of_day": start_of_day,
                "end_of_day": end_of_day
            })

            from app.services.calendar_ownership import classify_event, ownership_prefix

            events = []
            for row in result.fetchall():
                ownership = classify_event(row.title, row.ios_calendar_name)
                events.append(CalendarEvent(
                    title=f"{ownership_prefix(ownership)}{row.title}",
                    starts_at=row.start_time.strftime("%H:%M") if row.start_time and not row.all_day else ("All day" if row.all_day else ""),
                    ends_at=row.end_time.strftime("%H:%M") if row.end_time and not row.all_day else "",
                    location=row.location,
                    calendar_name=row.ios_calendar_name
                ))

            # Build staleness warning if needed
            stale_warning = ""
            if not is_fresh:
                if last_sync_time:
                    age_hours = (local_now() - last_sync_time).total_seconds() / 3600
                    stale_warning = f"\n\n*Note: Calendar data may be outdated (last sync {age_hours:.0f}h ago). Some events might be missing.*"
                else:
                    stale_warning = "\n\n*Note: Calendar sync status unknown. Events shown may be incomplete.*"

            if not events:
                if not is_fresh:
                    return "No calendar events found — Google Calendar sync is not active. Check your Google Calendar directly for today's schedule.", []
                return "No events scheduled for today.", []

            # Format calendar summary. Titles carry an owner prefix ("Everett: …")
            # for events that aren't David's, so downstream phrasing never
            # claims someone else's appointment as his.
            lines = ["## Today's Schedule"]
            lines.append(
                "*(Events prefixed with a name belong to that family member, "
                "not David.)*"
            )
            for event in events:
                time_str = event.starts_at
                if event.ends_at:
                    time_str += f" - {event.ends_at}"
                loc_str = f" @ {event.location}" if event.location else ""
                cal_str = f" [{event.calendar_name}]" if event.calendar_name else ""
                lines.append(f"- **{time_str}**: {event.title}{loc_str}{cal_str}")

            if stale_warning:
                lines.append(stale_warning)

            return "\n".join(lines), [e.to_dict() for e in events]

        except Exception as e:
            logger.error(f"Error gathering calendar: {e}")
            return "Calendar data unavailable.", []

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
            self._refresh_llm_config()
            from app.services.tunables import get_tunable_int
            word_min = get_tunable_int("morning_brief.target_word_count_min", 300)
            word_max = get_tunable_int("morning_brief.target_word_count_max", 500)
            system_msg = BRIEF_SYSTEM_PROMPT.format(
                tone_directive=tone_directive,
                word_min=word_min,
                word_max=word_max,
            )

            today_str = local_today().strftime("%B %d, %Y")
            user_msg = BRIEF_USER_PROMPT.format(
                stable_layer=stable_layer or "Not available yet.",
                context_layer=context_layer or "No active context.",
                yesterday_summary=yesterday_summary or "No summary from yesterday.",
                weather=weather_summary,
                calendar=calendar_summary,
                dream_insights=insights_summary or "None.",
                news=news_summary,
                today_date=today_str,
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
                        "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    }
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"LLM brief generation failed ({response.status}): {error}")
                        return self._fallback_brief(weekday, date_str, weather_summary, calendar_summary, news_summary)

                    data = await response.json()
                    content = data["choices"][0]["message"]["content"] or ""
                    word_count = len(content.split())
                    logger.info(f"LLM brief generated: {len(content)} chars, {word_count} words")
                    # If thinking mode consumed all tokens, use fallback
                    if not content.strip():
                        logger.warning("LLM brief returned empty content, using fallback")
                        return self._fallback_brief(weekday, date_str, weather_summary, calendar_summary, news_summary)
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
            from app.db.base import SessionLocal
            from app.services.unified_notification import send_notification as unified_send_notification

            # Get database session if not provided
            close_db = False
            if db is None:
                db = SessionLocal()
                close_db = True

            try:
                unread_row = db.execute(text("""
                    SELECT COUNT(*)::int AS unread_count
                    FROM shared_content
                    WHERE user_id = :user_id
                      AND status = 'unread'
                """), {"user_id": user_id}).fetchone()
                unread_count = int(unread_row.unread_count if unread_row else 0)

                body = f"Your {weekday} briefing is ready with tech news, weather, and your schedule."
                if unread_count > 0:
                    item_word = "item" if unread_count == 1 else "items"
                    body += f" Plus {unread_count} unread inbox {item_word}."

                result = await unified_send_notification(
                    user_id=user_id,
                    title="Morning Brief Ready",
                    message=body,
                    priority="high",
                    topic=f"morning_brief:{local_today().isoformat()}",
                    category="general",
                    source="morning_brief",
                    cooldown_hours=24.0,
                    db=db,
                )
                if result.get("sent"):
                    logger.info(f"📱 iOS push notification sent for morning brief to user {user_id}")
                    return True
                logger.info(f"Morning brief push not sent for user {user_id}: {result}")
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

        today = local_today()
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
            context_content = self._get_fresh_context_content(user_id, cl.read(user_id))
            archives = archiver.get_recent_archives(user_id, days=1)
            yesterday_summary = archives[0]["content"] if archives else ""
            logger.info(f"Context layers: stable={len(stable_content)} chars, context={len(context_content)} chars, yesterday={len(yesterday_summary)} chars")
        except Exception as e:
            logger.warning(f"Failed to read context layers: {e}")

        # Bootstrap stable layer if empty (prevents blank personal sections
        # when the weekly synthesis hasn't run yet)
        if not stable_content.strip():
            stable_content = await self._bootstrap_stable_layer(user_id, db)

        # Check if PKG has items needing review and append to context
        try:
            from app.services.personal_knowledge_graph import personal_kg
            review_items = personal_kg.get_needs_review()
            if review_items:
                count = len(review_items)
                pkg_note = (
                    f"\n\nBy the way, I have {count} knowledge item{'s' if count != 1 else ''} "
                    "that may need your review — some things I know about you might be outdated."
                )
                context_content = (context_content or "") + pkg_note
                logger.info(f"Morning brief: {count} PKG items need review, note added to context")
        except Exception as e:
            logger.debug(f"Morning brief: PKG review check failed: {e}")

        from app.services.tunables import get_tunable_str
        tone_directive = get_tunable_str(
            "morning_brief.tone_directive",
            "Warm and natural morning energy.",
        )

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
            today = local_today().strftime("%Y-%m-%d")

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
            today = local_today()
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
            seven_days_ago = (local_today() - timedelta(days=7)).strftime("%Y-%m-%d")
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

            # Calculate readiness score via the single shared scorer (same
            # weights the recovery API + iOS app now display — no drift).
            from app.services.recovery_score import compute_readiness
            _readiness = compute_readiness(
                {
                    "sleep_hours": recovery.sleep_hours,
                    "hrv": recovery.hrv,
                    "heart_rate": recovery.heart_rate,
                    "soreness_level": recovery.soreness_level,
                },
                {
                    "avg_hrv": averages.avg_hrv if averages else None,
                    "avg_hr": averages.avg_hr if averages else None,
                },
            )
            readiness_score = _readiness["score"]
            # Keep the brief's original hyphenated phrasing for TTS continuity.
            status_msg = {
                "Excellent": "Well recovered - good to push it today",
                "Good": "Moderate recovery - train but listen to your body",
                "Low": "Low recovery - consider lighter weights",
                "Poor": "Poor recovery - rest day recommended",
            }[_readiness["label"]]

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
            today = local_today()
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
                # No scheduled template — but a logged/started session still
                # makes it a training day. Use the shared definition so this
                # never contradicts the nutrition targets.
                from app.services.training_day import is_training_day
                if is_training_day(db, user_id, today)["is_training_day"]:
                    return {
                        "text": "## Today's Plan\n**Training Day** - Workout logged. No template scheduled for today.",
                        "tts": "You've got a workout logged today, though nothing was scheduled from your plan."
                    }
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
            today = local_today()
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
            today = local_today()
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
            today = local_today()
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
            today = local_today()
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
            today = local_today()
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
