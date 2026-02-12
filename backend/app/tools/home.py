"""Home Assistant Control Tools for Sara

Provides tools for Sara to control smart home devices via Home Assistant.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.tools.base import BaseTool, ToolResult
from app.services.ha_control_service import ha_control
from app.core.config import settings
from app.core.timezone import USER_TIMEZONE
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
import logging

logger = logging.getLogger(__name__)


def _get_async_session_maker():
    """Create async session maker for database operations."""
    database_url = os.getenv("DATABASE_URL")
    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url
    engine = create_async_engine(async_url, echo=False)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


class HomeGetDevicesTool(BaseTool):
    """Get list of controllable devices."""

    @property
    def name(self) -> str:
        return "home_get_devices"

    @property
    def description(self) -> str:
        return (
            "Get a list of smart home devices (lights, switches, climate, etc.) and their current states. "
            "Use this to see what devices are available before controlling them. "
            "Can filter by domain (light, switch, climate, cover, fan, media_player) or search by name."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter by device type: light, switch, climate, cover, fan, lock, media_player, scene, script",
                    "enum": ["light", "switch", "climate", "cover", "fan", "lock", "media_player", "scene", "script"]
                },
                "search": {
                    "type": "string",
                    "description": "Search for devices by name (e.g., 'living room', 'kitchen', 'christmas')"
                }
            }
        }

    async def execute(self, user_id: str, domain: Optional[str] = None, search: Optional[str] = None) -> ToolResult:
        try:
            if search:
                devices = await ha_control.find_entity(search)
            elif domain:
                devices = await ha_control.get_entities_by_domain(domain)
            else:
                # Get common controllable domains
                lights = await ha_control.get_entities_by_domain("light")
                switches = await ha_control.get_entities_by_domain("switch")
                climate = await ha_control.get_entities_by_domain("climate")
                devices = lights + switches + climate

            # Format for readability
            formatted = []
            for d in devices:
                formatted.append({
                    "entity_id": d["entity_id"],
                    "name": d.get("friendly_name", d["entity_id"]),
                    "state": d["state"],
                    "domain": d.get("domain", d["entity_id"].split(".")[0])
                })

            return ToolResult(
                success=True,
                message=f"Found {len(formatted)} devices",
                data={"devices": formatted, "count": len(formatted)}
            )
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return ToolResult(success=False, message=f"Failed to get devices: {e}")


class HomeLightControlTool(BaseTool):
    """Control lights - turn on, off, toggle, set brightness/color."""

    @property
    def name(self) -> str:
        return "home_light_control"

    @property
    def description(self) -> str:
        return (
            "Control smart lights - turn on, turn off, toggle, or adjust brightness and color. "
            "You must provide the entity_id (e.g., 'light.living_room_lights'). "
            "Use home_get_devices first if you don't know the exact entity_id."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The light entity ID (e.g., 'light.living_room_lights', 'light.wled_2')"
                },
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "toggle"],
                    "description": "Action to perform"
                },
                "brightness": {
                    "type": "integer",
                    "description": "Brightness level 0-255 (only for 'on' action)",
                    "minimum": 0,
                    "maximum": 255
                },
                "brightness_percent": {
                    "type": "integer",
                    "description": "Brightness as percentage 0-100 (alternative to brightness)",
                    "minimum": 0,
                    "maximum": 100
                },
                "rgb_color": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "RGB color as [R, G, B] values 0-255 each"
                },
                "effect": {
                    "type": "string",
                    "description": "Light effect name (for lights that support effects like WLED)"
                }
            },
            "required": ["entity_id", "action"]
        }

    async def execute(
        self,
        user_id: str,
        entity_id: str,
        action: str,
        brightness: Optional[int] = None,
        brightness_percent: Optional[int] = None,
        rgb_color: Optional[List[int]] = None,
        effect: Optional[str] = None
    ) -> ToolResult:
        try:
            # Convert percentage to 0-255 if provided
            if brightness_percent is not None and brightness is None:
                brightness = int(brightness_percent * 255 / 100)

            if action == "on":
                result = await ha_control.turn_on_light(
                    entity_id,
                    brightness=brightness,
                    rgb_color=rgb_color,
                    effect=effect
                )
                action_desc = "turned on"
                if brightness:
                    action_desc += f" at {int(brightness/255*100)}% brightness"
            elif action == "off":
                result = await ha_control.turn_off_light(entity_id)
                action_desc = "turned off"
            elif action == "toggle":
                result = await ha_control.toggle_light(entity_id)
                action_desc = "toggled"
            else:
                return ToolResult(success=False, message=f"Unknown action: {action}")

            # Get friendly name for response
            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"{name} {action_desc}",
                data=result
            )
        except Exception as e:
            logger.error(f"Failed to control light {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to control light: {e}")


class HomeSwitchControlTool(BaseTool):
    """Control switches - turn on, off, or toggle."""

    @property
    def name(self) -> str:
        return "home_switch_control"

    @property
    def description(self) -> str:
        return (
            "Control smart switches - turn on, turn off, or toggle. "
            "Use for outlets, smart plugs, and other switch-type devices."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The switch entity ID (e.g., 'switch.office_fan')"
                },
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "toggle"],
                    "description": "Action to perform"
                }
            },
            "required": ["entity_id", "action"]
        }

    async def execute(self, user_id: str, entity_id: str, action: str) -> ToolResult:
        try:
            if action == "on":
                result = await ha_control.turn_on_switch(entity_id)
            elif action == "off":
                result = await ha_control.turn_off_switch(entity_id)
            elif action == "toggle":
                result = await ha_control.toggle_switch(entity_id)
            else:
                return ToolResult(success=False, message=f"Unknown action: {action}")

            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"{name} {action}",
                data=result
            )
        except Exception as e:
            logger.error(f"Failed to control switch {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to control switch: {e}")


class HomeClimateControlTool(BaseTool):
    """Control climate/thermostat devices."""

    @property
    def name(self) -> str:
        return "home_climate_control"

    @property
    def description(self) -> str:
        return (
            "Control thermostat and climate devices - set temperature, change mode (heat/cool/auto/off). "
            "Temperature should be in the units configured in Home Assistant (usually Fahrenheit or Celsius)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The climate entity ID (e.g., 'climate.thermostat')"
                },
                "temperature": {
                    "type": "number",
                    "description": "Target temperature"
                },
                "hvac_mode": {
                    "type": "string",
                    "enum": ["heat", "cool", "heat_cool", "auto", "off"],
                    "description": "HVAC mode to set"
                }
            },
            "required": ["entity_id"]
        }

    async def execute(
        self,
        user_id: str,
        entity_id: str,
        temperature: Optional[float] = None,
        hvac_mode: Optional[str] = None
    ) -> ToolResult:
        try:
            results = []

            if temperature is not None:
                await ha_control.set_climate_temperature(entity_id, temperature, hvac_mode)
                results.append(f"temperature set to {temperature}")

            if hvac_mode is not None and temperature is None:
                await ha_control.set_climate_mode(entity_id, hvac_mode)
                results.append(f"mode set to {hvac_mode}")

            if not results:
                return ToolResult(success=False, message="Must specify temperature or hvac_mode")

            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"{name}: {', '.join(results)}",
                data={"entity_id": entity_id, "temperature": temperature, "hvac_mode": hvac_mode}
            )
        except Exception as e:
            logger.error(f"Failed to control climate {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to control climate: {e}")


class HomeCoverControlTool(BaseTool):
    """Control covers - blinds, garage doors, shades."""

    @property
    def name(self) -> str:
        return "home_cover_control"

    @property
    def description(self) -> str:
        return (
            "Control covers like blinds, shades, and garage doors - open, close, or set position."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The cover entity ID (e.g., 'cover.garage_door')"
                },
                "action": {
                    "type": "string",
                    "enum": ["open", "close"],
                    "description": "Action to perform"
                },
                "position": {
                    "type": "integer",
                    "description": "Position 0-100 (0=closed, 100=open)",
                    "minimum": 0,
                    "maximum": 100
                }
            },
            "required": ["entity_id"]
        }

    async def execute(
        self,
        user_id: str,
        entity_id: str,
        action: Optional[str] = None,
        position: Optional[int] = None
    ) -> ToolResult:
        try:
            if position is not None:
                result = await ha_control.set_cover_position(entity_id, position)
                action_desc = f"set to {position}%"
            elif action == "open":
                result = await ha_control.open_cover(entity_id)
                action_desc = "opened"
            elif action == "close":
                result = await ha_control.close_cover(entity_id)
                action_desc = "closed"
            else:
                return ToolResult(success=False, message="Must specify action or position")

            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"{name} {action_desc}",
                data=result
            )
        except Exception as e:
            logger.error(f"Failed to control cover {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to control cover: {e}")


class HomeLockControlTool(BaseTool):
    """Control smart locks."""

    @property
    def name(self) -> str:
        return "home_lock_control"

    @property
    def description(self) -> str:
        return "Control smart locks - lock or unlock."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The lock entity ID (e.g., 'lock.front_door')"
                },
                "action": {
                    "type": "string",
                    "enum": ["lock", "unlock"],
                    "description": "Action to perform"
                }
            },
            "required": ["entity_id", "action"]
        }

    async def execute(self, user_id: str, entity_id: str, action: str) -> ToolResult:
        try:
            if action == "lock":
                result = await ha_control.lock(entity_id)
            elif action == "unlock":
                result = await ha_control.unlock(entity_id)
            else:
                return ToolResult(success=False, message=f"Unknown action: {action}")

            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"{name} {action}ed",
                data=result
            )
        except Exception as e:
            logger.error(f"Failed to control lock {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to control lock: {e}")


class HomeSceneActivateTool(BaseTool):
    """Activate a scene."""

    @property
    def name(self) -> str:
        return "home_scene_activate"

    @property
    def description(self) -> str:
        return (
            "Activate a Home Assistant scene. Scenes set multiple devices to predefined states "
            "(e.g., 'Movie Night' dims lights and turns on TV)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The scene entity ID (e.g., 'scene.movie_night')"
                }
            },
            "required": ["entity_id"]
        }

    async def execute(self, user_id: str, entity_id: str) -> ToolResult:
        try:
            result = await ha_control.activate_scene(entity_id)

            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"Activated scene: {name}",
                data=result
            )
        except Exception as e:
            logger.error(f"Failed to activate scene {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to activate scene: {e}")


class HomeMediaControlTool(BaseTool):
    """Control media players."""

    @property
    def name(self) -> str:
        return "home_media_control"

    @property
    def description(self) -> str:
        return "Control media players - play, pause, stop, set volume."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The media player entity ID (e.g., 'media_player.living_room_tv')"
                },
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "stop"],
                    "description": "Playback action"
                },
                "volume": {
                    "type": "number",
                    "description": "Volume level 0.0 to 1.0 (or 0-100 as percentage)",
                    "minimum": 0,
                    "maximum": 100
                }
            },
            "required": ["entity_id"]
        }

    async def execute(
        self,
        user_id: str,
        entity_id: str,
        action: Optional[str] = None,
        volume: Optional[float] = None
    ) -> ToolResult:
        try:
            results = []

            if action == "play":
                await ha_control.media_play(entity_id)
                results.append("playing")
            elif action == "pause":
                await ha_control.media_pause(entity_id)
                results.append("paused")
            elif action == "stop":
                await ha_control.media_stop(entity_id)
                results.append("stopped")

            if volume is not None:
                # Convert percentage to 0-1 if needed
                vol = volume / 100 if volume > 1 else volume
                await ha_control.set_volume(entity_id, vol)
                results.append(f"volume set to {int(vol * 100)}%")

            if not results:
                return ToolResult(success=False, message="Must specify action or volume")

            try:
                state = await ha_control.get_state(entity_id)
                name = state.get("attributes", {}).get("friendly_name", entity_id)
            except:
                name = entity_id

            return ToolResult(
                success=True,
                message=f"{name}: {', '.join(results)}",
                data={"entity_id": entity_id, "action": action, "volume": volume}
            )
        except Exception as e:
            logger.error(f"Failed to control media {entity_id}: {e}")
            return ToolResult(success=False, message=f"Failed to control media: {e}")


class HomeAllLightsOffTool(BaseTool):
    """Turn off all lights."""

    @property
    def name(self) -> str:
        return "home_all_lights_off"

    @property
    def description(self) -> str:
        return (
            "Turn off all lights in the home. Useful for bedtime or leaving the house. "
            "Optionally exclude specific lights."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Entity IDs to exclude from turning off (e.g., ['light.nightlight'])"
                }
            }
        }

    async def execute(self, user_id: str, exclude: Optional[List[str]] = None) -> ToolResult:
        try:
            exclude = exclude or []
            lights = await ha_control.get_lights()

            # Filter to only lights that are on
            on_lights = [l for l in lights if l["state"] == "on" and l["entity_id"] not in exclude]

            turned_off = []
            failed = []

            for light in on_lights:
                try:
                    await ha_control.turn_off_light(light["entity_id"])
                    turned_off.append(light.get("friendly_name", light["entity_id"]))
                except Exception as e:
                    failed.append(light["entity_id"])
                    logger.error(f"Failed to turn off {light['entity_id']}: {e}")

            if failed:
                return ToolResult(
                    success=True,
                    message=f"Turned off {len(turned_off)} lights, {len(failed)} failed",
                    data={"turned_off": turned_off, "failed": failed}
                )

            return ToolResult(
                success=True,
                message=f"Turned off {len(turned_off)} lights" if turned_off else "All lights were already off",
                data={"turned_off": turned_off}
            )
        except Exception as e:
            logger.error(f"Failed to turn off all lights: {e}")
            return ToolResult(success=False, message=f"Failed to turn off lights: {e}")


class HomeScheduleActionTool(BaseTool):
    """Schedule a home action for a specific time."""

    @property
    def name(self) -> str:
        return "home_schedule_action"

    @property
    def description(self) -> str:
        return (
            "Schedule a home automation action to execute at a specific time. "
            "Use this when the user wants something to happen later (e.g., 'turn off lights at 11pm', "
            "'turn on the heater in 30 minutes'). Supports one-time and recurring schedules. "
            "The action will be executed automatically at the scheduled time."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID to control (e.g., 'light.living_room', 'switch.heater')"
                },
                "domain": {
                    "type": "string",
                    "enum": ["light", "switch", "climate", "cover", "lock", "scene", "media_player"],
                    "description": "The type of device"
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform: 'on', 'off', 'toggle' for lights/switches; 'open', 'close' for covers; 'lock', 'unlock' for locks; 'activate' for scenes; 'play', 'pause', 'stop' for media"
                },
                "parameters": {
                    "type": "object",
                    "description": "Additional parameters like brightness (0-255), temperature, volume, etc."
                },
                "scheduled_time": {
                    "type": "string",
                    "description": "When to execute. Format: ISO datetime (2025-12-13T23:00:00), relative time ('in 30 minutes', 'in 2 hours'), or time today ('at 11pm', 'at 23:00')"
                },
                "description": {
                    "type": "string",
                    "description": "Human readable description of the scheduled action"
                },
                "recurring": {
                    "type": "boolean",
                    "description": "Whether this should repeat"
                },
                "recurrence_pattern": {
                    "type": "string",
                    "enum": ["daily", "weekdays", "weekends", "weekly"],
                    "description": "How often to repeat (only if recurring=true)"
                }
            },
            "required": ["entity_id", "domain", "action", "scheduled_time"]
        }

    def _parse_scheduled_time(self, time_str: str) -> datetime:
        """Parse various time formats into a datetime object."""
        tz = USER_TIMEZONE  # User's timezone
        now = datetime.now(tz)
        time_str_lower = time_str.lower().strip()

        # Handle ISO format
        if 'T' in time_str or '-' in time_str[:10]:
            try:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                return dt
            except ValueError:
                pass

        # Handle relative time: "in X minutes/hours"
        if time_str_lower.startswith('in '):
            parts = time_str_lower[3:].split()
            if len(parts) >= 2:
                try:
                    amount = int(parts[0])
                    unit = parts[1].rstrip('s')  # Remove plural 's'
                    if unit == 'minute':
                        return now + timedelta(minutes=amount)
                    elif unit == 'hour':
                        return now + timedelta(hours=amount)
                    elif unit == 'day':
                        return now + timedelta(days=amount)
                except ValueError:
                    pass

        # Handle "at X" time formats
        if time_str_lower.startswith('at '):
            time_str_lower = time_str_lower[3:]

        # Handle 12-hour format: "11pm", "11:30pm", "11 pm"
        import re
        match = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            ampm = match.group(3)

            if ampm == 'pm' and hour < 12:
                hour += 12
            elif ampm == 'am' and hour == 12:
                hour = 0

            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If the time is in the past, schedule for tomorrow
            if scheduled <= now:
                scheduled += timedelta(days=1)

            return scheduled

        # Handle 24-hour format: "23:00"
        match = re.match(r'(\d{1,2}):(\d{2})', time_str_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if scheduled <= now:
                scheduled += timedelta(days=1)

            return scheduled

        raise ValueError(f"Could not parse time: {time_str}")

    async def execute(
        self,
        user_id: str,
        entity_id: str,
        domain: str,
        action: str,
        scheduled_time: str,
        parameters: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        recurring: bool = False,
        recurrence_pattern: Optional[str] = None
    ) -> ToolResult:
        try:
            # Parse the scheduled time
            scheduled_dt = self._parse_scheduled_time(scheduled_time)

            # Generate description if not provided
            if not description:
                try:
                    state = await ha_control.get_state(entity_id)
                    name = state.get("attributes", {}).get("friendly_name", entity_id)
                except:
                    name = entity_id
                description = f"{action.capitalize()} {name}"

            # Insert into database
            async_session_maker, engine = _get_async_session_maker()

            async with async_session_maker() as session:
                result = await session.execute(
                    text("""
                        INSERT INTO scheduled_home_action
                        (user_id, entity_id, domain, action, parameters, scheduled_at,
                         description, recurring, recurrence_pattern, status)
                        VALUES (:user_id, :entity_id, :domain, :action, :parameters::jsonb,
                                :scheduled_at, :description, :recurring, :recurrence_pattern, 'pending')
                        RETURNING id
                    """),
                    {
                        "user_id": user_id,
                        "entity_id": entity_id,
                        "domain": domain,
                        "action": action,
                        "parameters": str(parameters) if parameters else None,
                        "scheduled_at": scheduled_dt,
                        "description": description,
                        "recurring": recurring,
                        "recurrence_pattern": recurrence_pattern
                    }
                )
                action_id = result.scalar()
                await session.commit()
            await engine.dispose()

            # Format time for response
            time_str = scheduled_dt.strftime("%I:%M %p on %B %d")
            if scheduled_dt.date() == datetime.now(USER_TIMEZONE).date():
                time_str = scheduled_dt.strftime("%I:%M %p today")
            elif scheduled_dt.date() == (datetime.now(USER_TIMEZONE) + timedelta(days=1)).date():
                time_str = scheduled_dt.strftime("%I:%M %p tomorrow")

            msg = f"Scheduled: {description} at {time_str}"
            if recurring:
                msg += f" ({recurrence_pattern})"

            return ToolResult(
                success=True,
                message=msg,
                data={
                    "id": action_id,
                    "entity_id": entity_id,
                    "action": action,
                    "scheduled_at": scheduled_dt.isoformat(),
                    "recurring": recurring
                }
            )
        except ValueError as e:
            return ToolResult(success=False, message=str(e))
        except Exception as e:
            logger.error(f"Failed to schedule home action: {e}")
            return ToolResult(success=False, message=f"Failed to schedule action: {e}")


class HomeListScheduledActionsTool(BaseTool):
    """List scheduled home actions."""

    @property
    def name(self) -> str:
        return "home_list_scheduled"

    @property
    def description(self) -> str:
        return (
            "List all scheduled home automation actions that are pending execution. "
            "Shows what actions are scheduled and when they will run."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_executed": {
                    "type": "boolean",
                    "description": "Include already executed actions (default: false)"
                }
            }
        }

    async def execute(self, user_id: str, include_executed: bool = False) -> ToolResult:
        try:
            async_session_maker, engine = _get_async_session_maker()

            async with async_session_maker() as session:
                if include_executed:
                    query = text("""
                        SELECT id, entity_id, domain, action, parameters, scheduled_at,
                               status, description, recurring, recurrence_pattern, executed_at
                        FROM scheduled_home_action
                        WHERE user_id = :user_id
                        ORDER BY scheduled_at DESC
                        LIMIT 50
                    """)
                else:
                    query = text("""
                        SELECT id, entity_id, domain, action, parameters, scheduled_at,
                               status, description, recurring, recurrence_pattern, executed_at
                        FROM scheduled_home_action
                        WHERE user_id = :user_id AND status = 'pending'
                        ORDER BY scheduled_at ASC
                    """)

                result = await session.execute(query, {"user_id": user_id})
                rows = result.fetchall()
            await engine.dispose()

            if not rows:
                return ToolResult(
                    success=True,
                    message="No scheduled home actions found",
                    data={"actions": []}
                )

            actions = []
            tz = USER_TIMEZONE
            now = datetime.now(tz)

            for row in rows:
                scheduled_at = row.scheduled_at
                if scheduled_at.tzinfo is None:
                    scheduled_at = scheduled_at.replace(tzinfo=tz)

                # Format time nicely
                if scheduled_at.date() == now.date():
                    time_str = scheduled_at.strftime("%I:%M %p today")
                elif scheduled_at.date() == (now + timedelta(days=1)).date():
                    time_str = scheduled_at.strftime("%I:%M %p tomorrow")
                else:
                    time_str = scheduled_at.strftime("%I:%M %p on %b %d")

                actions.append({
                    "id": row.id,
                    "description": row.description or f"{row.action} {row.entity_id}",
                    "scheduled_for": time_str,
                    "status": row.status,
                    "recurring": row.recurring,
                    "recurrence_pattern": row.recurrence_pattern
                })

            return ToolResult(
                success=True,
                message=f"Found {len(actions)} scheduled actions",
                data={"actions": actions}
            )
        except Exception as e:
            logger.error(f"Failed to list scheduled actions: {e}")
            return ToolResult(success=False, message=f"Failed to list scheduled actions: {e}")


class HomeCancelScheduledActionTool(BaseTool):
    """Cancel a scheduled home action."""

    @property
    def name(self) -> str:
        return "home_cancel_scheduled"

    @property
    def description(self) -> str:
        return (
            "Cancel a scheduled home automation action before it executes. "
            "Use home_list_scheduled first to find the action ID."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "integer",
                    "description": "The ID of the scheduled action to cancel"
                }
            },
            "required": ["action_id"]
        }

    async def execute(self, user_id: str, action_id: int) -> ToolResult:
        try:
            async_session_maker, engine = _get_async_session_maker()

            async with async_session_maker() as session:
                # Check if action exists and belongs to user
                result = await session.execute(
                    text("""
                        SELECT description, status FROM scheduled_home_action
                        WHERE id = :id AND user_id = :user_id
                    """),
                    {"id": action_id, "user_id": user_id}
                )
                row = result.fetchone()

                if not row:
                    await engine.dispose()
                    return ToolResult(success=False, message="Scheduled action not found")

                if row.status != 'pending':
                    await engine.dispose()
                    return ToolResult(success=False, message=f"Action already {row.status}")

                # Cancel it
                await session.execute(
                    text("""
                        UPDATE scheduled_home_action
                        SET status = 'cancelled', updated_at = now()
                        WHERE id = :id
                    """),
                    {"id": action_id}
                )
                await session.commit()
            await engine.dispose()

            return ToolResult(
                success=True,
                message=f"Cancelled: {row.description}",
                data={"id": action_id}
            )
        except Exception as e:
            logger.error(f"Failed to cancel scheduled action: {e}")
            return ToolResult(success=False, message=f"Failed to cancel: {e}")


class HomeStatusTool(BaseTool):
    """Get a complete snapshot of the home status."""

    @property
    def name(self) -> str:
        return "home_status"

    @property
    def description(self) -> str:
        return (
            "Get a complete snapshot of the current home status. "
            "Shows all lights that are on, switches that are on, lock states, "
            "thermostat status, open covers, and recent activity. "
            "Use this as the FIRST tool when the user asks about home/house status."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_recent_activity": {
                    "type": "boolean",
                    "description": "Include last 10 state changes (default: true)"
                }
            }
        }

    async def execute(self, user_id: str, include_recent_activity: bool = True) -> ToolResult:
        try:
            status = {
                "lights_on": [],
                "switches_on": [],
                "locks": [],
                "climate": [],
                "covers_open": [],
                "media_playing": [],
                "recent_activity": []
            }

            # Get all states from HA
            all_states = await ha_control.get_states()

            for entity in all_states:
                entity_id = entity["entity_id"]
                state = entity["state"]
                name = entity.get("attributes", {}).get("friendly_name", entity_id)
                domain = entity_id.split(".")[0]

                # Lights that are on
                if domain == "light" and state == "on":
                    brightness = entity.get("attributes", {}).get("brightness")
                    brightness_pct = int(brightness / 255 * 100) if brightness else None
                    status["lights_on"].append({
                        "name": name,
                        "entity_id": entity_id,
                        "brightness": f"{brightness_pct}%" if brightness_pct else "on"
                    })

                # Switches that are on
                elif domain == "switch" and state == "on":
                    status["switches_on"].append({
                        "name": name,
                        "entity_id": entity_id
                    })

                # All locks with their state
                elif domain == "lock":
                    status["locks"].append({
                        "name": name,
                        "entity_id": entity_id,
                        "state": state  # locked/unlocked
                    })

                # Climate/thermostat (skip unavailable entities — removed devices)
                elif domain == "climate" and state not in ("unavailable", "unknown"):
                    attrs = entity.get("attributes", {})
                    status["climate"].append({
                        "name": name,
                        "entity_id": entity_id,
                        "state": state,  # heat, cool, off, etc.
                        "current_temp": attrs.get("current_temperature"),
                        "target_temp": attrs.get("temperature"),
                        "hvac_action": attrs.get("hvac_action")  # heating, cooling, idle
                    })

                # Covers that are open
                elif domain == "cover" and state == "open":
                    position = entity.get("attributes", {}).get("current_position")
                    status["covers_open"].append({
                        "name": name,
                        "entity_id": entity_id,
                        "position": f"{position}%" if position is not None else "open"
                    })

                # Media players that are playing
                elif domain == "media_player" and state == "playing":
                    attrs = entity.get("attributes", {})
                    status["media_playing"].append({
                        "name": name,
                        "entity_id": entity_id,
                        "media_title": attrs.get("media_title"),
                        "volume": f"{int(attrs.get('volume_level', 0) * 100)}%" if attrs.get("volume_level") else None
                    })

            # Get recent activity from activity log
            if include_recent_activity:
                try:
                    from sqlalchemy import create_engine
                    from sqlalchemy.orm import sessionmaker
                    from app.core.config import settings

                    engine = create_engine(settings.database_url)
                    Session = sessionmaker(bind=engine)
                    db = Session()
                    try:
                        result = db.execute(
                            text("""
                                SELECT friendly_name, from_state, to_state, changed_at
                                FROM home_activity_log
                                ORDER BY changed_at DESC
                                LIMIT 10
                            """)
                        )
                        for row in result.fetchall():
                            changed_at = row.changed_at
                            if changed_at.tzinfo is None:
                                changed_at = changed_at.replace(tzinfo=ZoneInfo("UTC"))
                            # Convert to local time
                            local_time = changed_at.astimezone(USER_TIMEZONE)
                            status["recent_activity"].append({
                                "device": row.friendly_name,
                                "change": f"{row.from_state} → {row.to_state}",
                                "time": local_time.strftime("%I:%M %p")
                            })
                    finally:
                        db.close()
                except Exception as e:
                    logger.warning(f"Could not fetch recent activity: {e}")

            # Build summary message
            summary_parts = []
            if status["lights_on"]:
                summary_parts.append(f"{len(status['lights_on'])} lights on")
            else:
                summary_parts.append("all lights off")

            if status["switches_on"]:
                summary_parts.append(f"{len(status['switches_on'])} switches on")

            locked_count = sum(1 for l in status["locks"] if l["state"] == "locked")
            unlocked_count = sum(1 for l in status["locks"] if l["state"] == "unlocked")
            if unlocked_count > 0:
                summary_parts.append(f"{unlocked_count} locks UNLOCKED")
            elif locked_count > 0:
                summary_parts.append(f"all {locked_count} locks secured")

            if status["climate"]:
                for c in status["climate"]:
                    if c["state"] != "off":
                        summary_parts.append(f"thermostat {c['state']} at {c['target_temp']}°")

            if status["covers_open"]:
                summary_parts.append(f"{len(status['covers_open'])} covers open")

            if status["media_playing"]:
                summary_parts.append(f"{len(status['media_playing'])} media playing")

            return ToolResult(
                success=True,
                message=", ".join(summary_parts) if summary_parts else "Home status retrieved",
                data=status
            )
        except Exception as e:
            logger.error(f"Failed to get home status: {e}")
            return ToolResult(success=False, message=f"Failed to get home status: {e}")


# Export all home tools
HOME_TOOLS = [
    HomeStatusTool(),  # Put status first - most commonly needed
    HomeGetDevicesTool(),
    HomeLightControlTool(),
    HomeSwitchControlTool(),
    HomeClimateControlTool(),
    HomeCoverControlTool(),
    HomeLockControlTool(),
    HomeSceneActivateTool(),
    HomeMediaControlTool(),
    HomeAllLightsOffTool(),
    HomeScheduleActionTool(),
    HomeListScheduledActionsTool(),
    HomeCancelScheduledActionTool(),
]
