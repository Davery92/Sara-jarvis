"""
Morning Proactive Service for Sara's Autonomous Suggestions.

Runs at 9 AM to check for patterns that should be suggested based on
current conditions (weather, day of week, etc.) and sends personalized
iOS push notifications.

Unlike generic notifications, each message is crafted by Sara using LLM
with full context awareness.
"""

import logging
import json
from datetime import datetime, time, date, timedelta
from typing import List, Dict, Any, Optional
import httpx

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.behavioral_pattern_service import (
    behavioral_pattern_service,
    TriggerContext,
    PatternStatus
)
from app.services.weather_service import weather_service
from app.core.config import settings

logger = logging.getLogger(__name__)


# LLM prompt for crafting proactive messages
MESSAGE_CRAFT_PROMPT = """You are Sara, David's personal AI assistant. You need to craft a short, natural push notification message.

CONTEXT:
- Current time: {current_time}
- Current weather: {weather_description}
- Current temperature: {current_temp}°F (feels like {feels_like}°F)
- Today's forecast: High of {temp_high}°F, low of {temp_low}°F

PATTERN DETECTED:
{pattern_description}

Evidence: {pattern_context}

YOUR TASK:
Write a brief, conversational push notification suggesting this action to David.

REQUIREMENTS:
1. Be warm and personal (you know David well)
2. Reference the specific current conditions
3. Reference what David did before (the pattern)
4. Ask if he'd like you to do the action
5. Keep it under 200 characters for the body
6. Don't be robotic or templated

OUTPUT FORMAT (JSON only, no markdown):
{{"title": "short title (under 30 chars)", "body": "conversational message (under 200 chars)"}}

EXAMPLE OUTPUT:
{{"title": "Cold morning! 🥶", "body": "It's 5°F out there - yesterday you had the heat running every 2 hours. Want me to set that up again?"}}"""


class MorningProactiveService:
    """
    Service that runs proactive pattern suggestions.

    Checks active patterns against current conditions and sends
    personalized notifications via iOS push.
    """

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def run_morning_check(
        self,
        db: Session,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Run the morning proactive check.

        1. Get current conditions (weather, time, day)
        2. Get active patterns for user
        3. Evaluate which patterns are triggered
        4. For each triggered pattern, craft message and send notification

        Returns:
            Summary of what was done
        """
        logger.info(f"Running morning proactive check for user {user_id}")

        # Build current context
        context = await self._build_current_context()

        if not context:
            logger.warning("Failed to build current context")
            return {"success": False, "reason": "Failed to get current context"}

        # Get active patterns
        patterns = await behavioral_pattern_service.get_active_patterns(db, user_id)

        if not patterns:
            logger.info("No active patterns to check")
            return {"success": True, "patterns_checked": 0, "suggestions_sent": 0}

        logger.info(f"Checking {len(patterns)} active patterns")

        suggestions_sent = []
        patterns_triggered = []

        for pattern in patterns:
            # Check if pattern can be suggested now
            can_suggest, reason = await behavioral_pattern_service.can_suggest_pattern(
                db, pattern, datetime.now()
            )

            if not can_suggest:
                logger.debug(f"Pattern {pattern['id']}: Cannot suggest - {reason}")
                continue

            # Evaluate trigger
            triggered, trigger_reason = await behavioral_pattern_service.evaluate_trigger(
                pattern, context
            )

            if not triggered:
                logger.debug(f"Pattern {pattern['id']}: Not triggered - {trigger_reason}")
                continue

            logger.info(f"Pattern triggered: {pattern['description']} ({trigger_reason})")
            patterns_triggered.append(pattern)

            # Craft personalized message
            message = await self._craft_message(pattern, context, trigger_reason)

            if not message:
                logger.warning(f"Failed to craft message for pattern {pattern['id']}")
                continue

            # Send iOS push notification
            success = await self._send_notification(db, user_id, message, pattern)

            if success:
                # Record the suggestion
                await behavioral_pattern_service.record_suggestion(
                    db=db,
                    pattern_id=pattern["id"],
                    trigger_context={
                        "weather": {
                            "temp": context.current_temp_f,
                            "description": context.weather_description
                        },
                        "time": context.current_time.isoformat() if context.current_time else None,
                        "day": context.current_day,
                        "trigger_reason": trigger_reason
                    },
                    message_sent=f"{message['title']}: {message['body']}"
                )

                suggestions_sent.append({
                    "pattern_id": pattern["id"],
                    "description": pattern["description"],
                    "message": message
                })

        return {
            "success": True,
            "patterns_checked": len(patterns),
            "patterns_triggered": len(patterns_triggered),
            "suggestions_sent": len(suggestions_sent),
            "suggestions": suggestions_sent
        }

    async def _build_current_context(self) -> Optional[TriggerContext]:
        """Build the current context for trigger evaluation."""
        try:
            # Get current weather
            weather = await weather_service.get_weather()

            now = datetime.now()
            current_day = now.strftime("%a")  # Mon, Tue, etc.

            context = TriggerContext(
                current_time=now.time(),
                current_day=current_day,
                current_date=now.date()
            )

            if weather:
                context.current_temp_f = weather.current.temperature
                context.current_humidity = weather.current.humidity
                context.weather_description = weather.current.description

            return context

        except Exception as e:
            logger.error(f"Failed to build current context: {e}")
            return None

    async def _craft_message(
        self,
        pattern: Dict[str, Any],
        context: TriggerContext,
        trigger_reason: str
    ) -> Optional[Dict[str, str]]:
        """
        Use LLM to craft a personalized notification message.

        Returns:
            {"title": "...", "body": "..."} or None if failed
        """
        try:
            # Get weather forecast for today
            weather = await weather_service.get_weather()

            temp_high = weather.forecast[0].temp_high if weather and weather.forecast else "?"
            temp_low = weather.forecast[0].temp_low if weather and weather.forecast else "?"

            prompt = MESSAGE_CRAFT_PROMPT.format(
                current_time=context.current_time.strftime("%I:%M %p") if context.current_time else "morning",
                weather_description=context.weather_description or "unknown",
                current_temp=context.current_temp_f or "?",
                feels_like=weather.current.feels_like if weather else "?",
                temp_high=temp_high,
                temp_low=temp_low,
                pattern_description=pattern["description"],
                pattern_context=pattern.get("action_payload", {}).get("description", "")
            )

            response = await self.client.post(
                f"{settings.bg_llm_primary_url}/chat/completions",
                json={
                    "model": settings.bg_llm_primary_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 200
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"}
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()

            # Parse JSON response
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            message = json.loads(content)

            # Validate structure
            if "title" not in message or "body" not in message:
                logger.warning(f"Invalid message structure: {message}")
                return None

            return message

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM message response: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to craft message: {e}")
            return None

    async def _send_notification(
        self,
        db: Session,
        user_id: str,
        message: Dict[str, str],
        pattern: Dict[str, Any]
    ) -> bool:
        """
        Send iOS push notification.

        Returns True if sent successfully.
        """
        try:
            from app.services.unified_notification import send_notification as unified_send_notification

            topic = f"pattern_suggestion:{pattern['id']}:{datetime.utcnow().strftime('%Y%m%d')}"
            result = await unified_send_notification(
                user_id=user_id,
                title=message["title"],
                message=message["body"],
                priority="normal",
                topic=topic,
                category="general",
                source="morning_proactive",
                db=db
            )

            if result.get("sent"):
                logger.info(f"Sent proactive notification: {message['title']}")
                return True
            logger.info(f"Proactive notification not sent: reason={result.get('reason')} topic={topic}")
            return False

        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    async def handle_suggestion_response(
        self,
        db: Session,
        pattern_id: str,
        accepted: bool,
        user_response: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle user's response to a pattern suggestion.

        Called when user taps accept/reject on the notification.
        """
        try:
            await behavioral_pattern_service.record_response(
                db=db,
                pattern_id=pattern_id,
                accepted=accepted,
                user_response=user_response
            )

            if accepted:
                # Execute the pattern's action
                result = await self._execute_pattern_action(db, pattern_id)
                return {
                    "success": True,
                    "action": "accepted",
                    "execution_result": result
                }
            else:
                return {
                    "success": True,
                    "action": "rejected"
                }

        except Exception as e:
            logger.error(f"Failed to handle suggestion response: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_pattern_action(
        self,
        db: Session,
        pattern_id: str
    ) -> Dict[str, Any]:
        """
        Execute the action associated with a pattern.

        For automation patterns, this triggers the automation.
        For suggestion patterns, this might create a reminder, etc.
        """
        try:
            # Get pattern details
            result = db.execute(
                text("""
                    SELECT action_type, action_payload
                    FROM behavioral_pattern
                    WHERE id = :pattern_id
                """),
                {"pattern_id": pattern_id}
            ).fetchone()

            if not result:
                return {"success": False, "error": "Pattern not found"}

            action_type = result.action_type
            action_payload = result.action_payload

            if isinstance(action_payload, str):
                action_payload = json.loads(action_payload)

            if action_type == "automation":
                return await self._trigger_automation_task(db, pattern_id, action_payload)

            elif action_type == "suggestion":
                # Just acknowledge the suggestion
                return {
                    "success": True,
                    "action": "suggestion_acknowledged"
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown action type: {action_type}"
                }

        except Exception as e:
            logger.error(f"Failed to execute pattern action: {e}")
            return {"success": False, "error": str(e)}

    async def _trigger_automation_task(
        self,
        db: Session,
        pattern_id: str,
        action_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Trigger an existing automation task by ID or name.
        """
        from app.services.automation.constants import AutomationStatus
        from app.tasks.automation import automation_execute

        automation_id = (
            action_payload.get("automation_id")
            or action_payload.get("task_id")
            or action_payload.get("id")
        )
        automation_name = (
            action_payload.get("automation_name")
            or action_payload.get("name")
        )

        if not automation_id and not automation_name:
            return {
                "success": False,
                "error": "Automation action_payload must include automation_id/task_id or automation_name."
            }

        owner = db.execute(
            text("SELECT user_id FROM behavioral_pattern WHERE id = :pattern_id"),
            {"pattern_id": pattern_id}
        ).fetchone()
        if not owner:
            return {"success": False, "error": "Pattern owner not found"}

        user_id = str(owner.user_id)
        task = None

        if automation_id:
            task = db.execute(
                text("""
                    SELECT id, name, status
                    FROM automation_task
                    WHERE id = :task_id AND user_id = :user_id
                    LIMIT 1
                """),
                {"task_id": automation_id, "user_id": user_id}
            ).fetchone()

        if not task and automation_name:
            task = db.execute(
                text("""
                    SELECT id, name, status
                    FROM automation_task
                    WHERE user_id = :user_id
                      AND LOWER(name) = LOWER(:name)
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"user_id": user_id, "name": automation_name}
            ).fetchone()

        if not task:
            return {
                "success": False,
                "error": f"Automation not found (id={automation_id}, name={automation_name})"
            }

        if task.status != AutomationStatus.ACTIVE:
            return {
                "success": False,
                "error": f"Automation '{task.name}' is not active (status={task.status}).",
                "automation_id": str(task.id),
                "automation_name": task.name,
                "status": task.status,
            }

        db.execute(
            text("""
                UPDATE automation_task
                SET next_wake_at = NOW()
                WHERE id = :task_id
            """),
            {"task_id": str(task.id)}
        )
        db.commit()

        try:
            dispatch = automation_execute.delay(str(task.id))
            dispatch_id = getattr(dispatch, "id", None)
        except Exception as e:
            logger.error(f"Failed to dispatch automation {task.id}: {e}")
            return {
                "success": False,
                "error": f"Failed to dispatch automation execution: {e}",
                "automation_id": str(task.id),
                "automation_name": task.name,
            }

        logger.info(
            f"Triggered automation from pattern {pattern_id}: "
            f"{task.name} ({str(task.id)[:8]}) dispatch_id={dispatch_id}"
        )
        return {
            "success": True,
            "action": "automation_triggered",
            "automation_id": str(task.id),
            "automation_name": task.name,
            "dispatch_id": dispatch_id,
        }


# Singleton instance
morning_proactive_service = MorningProactiveService()


async def run_morning_proactive_check(db: Session, user_id: str) -> Dict[str, Any]:
    """
    Convenience function to run the morning proactive check.
    """
    return await morning_proactive_service.run_morning_check(db, user_id)


class MorningProactiveScheduler:
    """
    Scheduler that runs the morning proactive check at 9 AM Eastern.

    Checks active behavioral patterns against current conditions and sends
    personalized iOS push notifications for relevant suggestions.
    """

    def __init__(self):
        import pytz
        self.eastern_tz = pytz.timezone('America/New_York')
        self.check_time = time(9, 0)  # 9:00 AM Eastern
        self.is_running = False
        self.last_check_date = None
        logger.info("☀️ MorningProactiveScheduler initialized - checks at 9:00 AM Eastern")

    async def start_scheduler(self):
        """Start the morning proactive scheduler"""
        import pytz
        import asyncio
        from app.db.session import SessionLocal
        from app.models.user import User

        logger.info("☀️ Starting morning proactive scheduler...")

        while True:
            try:
                # Get current time in Eastern timezone
                utc_now = datetime.now(pytz.UTC)
                eastern_now = utc_now.astimezone(self.eastern_tz)

                # Check if it's time to run and we haven't run today
                if self._should_run(eastern_now):
                    logger.info(f"☀️ Time for morning proactive check! It's {eastern_now.strftime('%I:%M %p')} Eastern")
                    await self._run_morning_checks()
                    self.last_check_date = eastern_now.date()

                # Sleep for 15 minutes before checking again
                await asyncio.sleep(900)  # 15 minutes

            except Exception as e:
                logger.error(f"❌ Morning proactive scheduler error: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour on error

    def _should_run(self, eastern_now: datetime) -> bool:
        """Check if we should run the morning check (Eastern time)"""
        current_time = eastern_now.time()
        current_date = eastern_now.date()

        # Check window: 9:00 AM - 10:00 AM Eastern only
        check_start = time(9, 0)
        check_end = time(10, 0)
        is_check_time = check_start <= current_time < check_end
        havent_run_today = (self.last_check_date is None or self.last_check_date < current_date)
        not_currently_running = not self.is_running

        if is_check_time and havent_run_today and not_currently_running:
            logger.info(f"☀️ Morning check conditions met: {eastern_now.strftime('%I:%M %p')} Eastern on {current_date}")
            return True

        return False

    async def _run_morning_checks(self):
        """Run the morning proactive checks for all users"""
        from app.db.session import SessionLocal
        from app.models.user import User

        if self.is_running:
            logger.info("☀️ Already running morning checks, skipping")
            return

        try:
            self.is_running = True
            logger.info("☀️ Starting morning proactive checks...")

            db = SessionLocal()
            try:
                users = db.query(User).all()

                for user in users:
                    try:
                        result = await morning_proactive_service.run_morning_check(db, user.id)
                        logger.info(f"☀️ Morning check for {user.email}: "
                                  f"{result.get('suggestions_sent', 0)} suggestions sent")
                        db.commit()
                    except Exception as e:
                        logger.error(f"❌ Morning check failed for user {user.id}: {e}")
                        db.rollback()
            finally:
                db.close()

            logger.info("☀️ Morning proactive checks complete!")

        except Exception as e:
            logger.error(f"❌ Morning proactive checks failed: {e}")
        finally:
            self.is_running = False


# Singleton scheduler instance
morning_proactive_scheduler = MorningProactiveScheduler()
