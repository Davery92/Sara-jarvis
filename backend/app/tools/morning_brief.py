"""
Morning Brief Tool
Allows Sara to provide the user's morning briefing with news, weather, calendar, and training recommendations.
"""

from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
from datetime import date
import logging

logger = logging.getLogger(__name__)


class MorningBriefTool(BaseTool):
    """Tool for getting today's morning brief"""

    @property
    def name(self) -> str:
        return "morning_brief"

    @property
    def description(self) -> str:
        return """Get the user's morning briefing with synthesized tech news, weather forecast, calendar events, and recovery-aware training recommendations.

Use this when the user asks for their morning brief, daily briefing, or wants to know what's happening today.
Trigger phrases: "what's my morning brief", "give me my briefing", "what's happening today", "morning update", "daily brief"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_recovery": {
                    "type": "boolean",
                    "description": "Whether to include recovery-aware training recommendations (default: true)",
                    "default": True
                },
                "generate_if_missing": {
                    "type": "boolean",
                    "description": "Whether to generate a new brief if none exists for today (default: true)",
                    "default": True
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get or generate the morning brief"""

        include_recovery = kwargs.get("include_recovery", True)
        generate_if_missing = kwargs.get("generate_if_missing", True)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.morning_brief_service import morning_brief_service
            from sqlalchemy import text

            today = date.today().strftime("%Y-%m-%d")

            # Check if brief exists
            result = db.execute(text("""
                SELECT id, news_summary, weather_summary, calendar_summary,
                       full_text, recovery_text, generated_at
                FROM morning_brief
                WHERE user_id = :user_id AND brief_date = :brief_date
            """), {"user_id": user_id, "brief_date": today}).fetchone()

            if not result and generate_if_missing:
                # Generate a new brief
                logger.info(f"Generating morning brief for user {user_id}")
                brief = await morning_brief_service.generate_brief(user_id, db)

                return ToolResult(
                    success=True,
                    message="Here's your freshly generated morning brief!",
                    data={
                        "news_summary": brief.news_summary,
                        "weather_summary": brief.weather_summary,
                        "calendar_summary": brief.calendar_summary,
                        "full_text": brief.full_text,
                        "recovery_text": brief.recovery_text if include_recovery else None,
                        "generated_at": brief.generated_at,
                        "has_audio": bool(brief.audio_path)
                    }
                )

            elif not result:
                return ToolResult(
                    success=False,
                    message="No morning brief has been generated for today yet. Would you like me to generate one?"
                )

            else:
                # Return existing brief
                brief = dict(result._mapping)

                # Generate recovery section on demand if requested and not present
                recovery_text = brief.get("recovery_text")
                if include_recovery and not recovery_text:
                    recovery_text, _ = await morning_brief_service.generate_recovery_section(user_id, db)
                    # Save it
                    db.execute(text("""
                        UPDATE morning_brief SET recovery_text = :recovery_text WHERE id = :id
                    """), {"id": brief["id"], "recovery_text": recovery_text})
                    db.commit()

                return ToolResult(
                    success=True,
                    message="Here's your morning brief!",
                    data={
                        "news_summary": brief.get("news_summary"),
                        "weather_summary": brief.get("weather_summary"),
                        "calendar_summary": brief.get("calendar_summary"),
                        "full_text": brief.get("full_text"),
                        "recovery_text": recovery_text if include_recovery else None,
                        "generated_at": str(brief.get("generated_at")) if brief.get("generated_at") else None
                    }
                )

        except Exception as e:
            logger.error(f"Error getting morning brief: {e}")
            return ToolResult(
                success=False,
                message=f"Sorry, I couldn't retrieve your morning brief: {str(e)}"
            )

        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass


class WeatherTool(BaseTool):
    """Tool for getting current weather"""

    @property
    def name(self) -> str:
        return "weather"

    @property
    def description(self) -> str:
        return """Get the current weather and forecast.

Use this when the user asks about weather, temperature, or what to wear today.
Trigger phrases: "what's the weather", "how's the weather", "is it going to rain", "what should I wear"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get current weather"""

        try:
            from app.services.weather_service import weather_service

            weather = await weather_service.get_weather()

            if not weather:
                return ToolResult(
                    success=False,
                    message="Sorry, I couldn't retrieve the weather data right now."
                )

            # Format for conversational response
            current = weather.current
            forecast_today = weather.forecast[0] if weather.forecast else None

            response_text = weather_service.format_for_tts(weather)

            return ToolResult(
                success=True,
                message=response_text,
                data={
                    "location": weather.location,
                    "current": {
                        "temperature": current.temperature,
                        "feels_like": current.feels_like,
                        "description": current.description,
                        "humidity": current.humidity,
                        "wind_speed": current.wind_speed
                    },
                    "today_forecast": {
                        "high": forecast_today.temp_high if forecast_today else None,
                        "low": forecast_today.temp_low if forecast_today else None,
                        "rain_chance": forecast_today.pop if forecast_today else None
                    } if forecast_today else None
                }
            )

        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return ToolResult(
                success=False,
                message=f"Sorry, I couldn't get the weather: {str(e)}"
            )
