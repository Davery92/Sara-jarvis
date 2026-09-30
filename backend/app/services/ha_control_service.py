"""Home Assistant Control Service

Provides methods to control Home Assistant entities via REST API.
"""
import asyncio

import aiohttp
import logging
from typing import Dict, Any, List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class HAControlService:
    """Service to control Home Assistant entities."""

    def __init__(
        self,
        ha_host: Optional[str] = None,
        ha_port: Optional[int] = None,
        ha_token: Optional[str] = None
    ):
        self.ha_host = ha_host or settings.ha_host
        self.ha_port = ha_port or settings.ha_port
        self.ha_token = ha_token or settings.ha_token
        self.base_url = f"http://{self.ha_host}:{self.ha_port}/api"
        self.headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json"
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make a request to Home Assistant API."""
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    headers=self.headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                        raise Exception("Authentication failed - check HA token")
                    elif response.status == 404:
                        raise Exception(f"Entity or service not found")
                    else:
                        text = await response.text()
                        raise Exception(f"HA API error {response.status}: {text}")
        except aiohttp.ClientError as e:
            raise Exception(f"Connection to Home Assistant failed: {e}")

    async def get_states(self) -> List[Dict[str, Any]]:
        """Get all entity states."""
        return await self._request("GET", "/states")

    async def get_state(self, entity_id: str) -> Dict[str, Any]:
        """Get state of a specific entity."""
        return await self._request("GET", f"/states/{entity_id}")

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Call a Home Assistant service."""
        data = kwargs.copy()
        if entity_id:
            data["entity_id"] = entity_id

        return await self._request("POST", f"/services/{domain}/{service}", data)


    # ── Accepted is not confirmed (reliable-assistant plan Phase F) ─────────
    #
    # "Verify actual device outcome where observable; distinguish accepted
    # command from confirmed state."
    #
    # Finding 21 (`M02_STALE_LOCK_FALSE_SUCCESS_CLAIM`): a lock command
    # reported success — "Locked... the unavailable state seems to have
    # cleared" — against a device the adapter's own response explicitly marked
    # `device_unavailable_no_state_change`. Source-confirmed at the time: every
    # method here returned `{"success": True}` on the strength of the HTTP call
    # alone, never reading the entity state back. That applies to any device on
    # this path, not just locks.
    #
    # So an observable command now reads the state back and says which of the
    # three things happened:
    #
    #   accepted=True,  confirmed=True   -> it is in the expected state
    #   accepted=True,  confirmed=False  -> Home Assistant took the command and
    #                                       the device did not move. `success`
    #                                       is False, because telling David
    #                                       "locked" here is the finding.
    #   accepted=False                   -> the call itself failed
    #
    # Eventual consistency is real: HA's state machine can lag a service call
    # by a moment, so the readback is retried a bounded number of times before
    # concluding the device did not move. Bounded, not a wait loop.

    _CONFIRM_ATTEMPTS = 3
    _CONFIRM_DELAY_S = 0.4

    async def _confirm_state(
        self, entity_id: str, expected: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Read the entity back and report whether it actually moved."""
        observed = None
        for attempt in range(self._CONFIRM_ATTEMPTS):
            try:
                state_obj = await self.get_state(entity_id)
            except Exception as exc:
                return {
                    "confirmed": False, "observable": False,
                    "state": None,
                    "detail": f"could not read {entity_id} back: {exc}",
                }
            observed = (state_obj or {}).get("state")
            if expected is None:
                return {"confirmed": False, "observable": False, "state": observed,
                        "detail": "this command has no single observable end state"}
            if observed in expected:
                return {"confirmed": True, "observable": True, "state": observed,
                        "detail": ""}
            if observed in ("unavailable", "unknown", None):
                # No point retrying a device that is not reporting at all.
                break
            if attempt < self._CONFIRM_ATTEMPTS - 1:
                await asyncio.sleep(self._CONFIRM_DELAY_S)
        return {
            "confirmed": False, "observable": True, "state": observed,
            "detail": (
                f"{entity_id} is {observed!r}, not {'/'.join(expected or [])} — "
                "Home Assistant accepted the command but the device did not move"
            ),
        }

    async def _call_and_confirm(
        self, domain: str, service: str, entity_id: str,
        expected: Optional[List[str]], action: str, **kwargs,
    ) -> Dict[str, Any]:
        await self.call_service(domain, service, entity_id, **kwargs)
        confirmation = await self._confirm_state(entity_id, expected)
        result = {
            # `success` now means "accepted AND, where observable, confirmed".
            # Callers that only read `success` therefore stop reporting an
            # unmoved device as done, which is the whole point.
            "success": bool(confirmation["confirmed"]) or not confirmation["observable"],
            "accepted": True,
            "confirmed": confirmation["confirmed"],
            "observed_state": confirmation["state"],
            "entity_id": entity_id,
            "action": action,
        }
        if kwargs:
            result["params"] = kwargs
        if confirmation["detail"]:
            result["detail"] = confirmation["detail"]
        if not result["success"]:
            logger.warning(
                "🏠 %s %s accepted but NOT confirmed: %s",
                action, entity_id, confirmation["detail"],
            )
        else:
            logger.info("🏠 %s %s -> state %r", action, entity_id, confirmation["state"])
        return result

    # Light controls
    async def turn_on_light(
        self,
        entity_id: str,
        brightness: Optional[int] = None,
        color_temp: Optional[int] = None,
        rgb_color: Optional[List[int]] = None,
        effect: Optional[str] = None
    ) -> Dict[str, Any]:
        """Turn on a light with optional parameters."""
        kwargs = {}
        if brightness is not None:
            kwargs["brightness"] = min(255, max(0, brightness))
        if color_temp is not None:
            kwargs["color_temp"] = color_temp
        if rgb_color is not None:
            kwargs["rgb_color"] = rgb_color
        if effect is not None:
            kwargs["effect"] = effect

        return await self._call_and_confirm(
            "light", "turn_on", entity_id, ["on"], "turn_on", **kwargs)

    async def turn_off_light(self, entity_id: str) -> Dict[str, Any]:
        """Turn off a light."""
        return await self._call_and_confirm(
            "light", "turn_off", entity_id, ["off"], "turn_off")

    async def toggle_light(self, entity_id: str) -> Dict[str, Any]:
        """Toggle a light."""
        await self.call_service("light", "toggle", entity_id)
        logger.info(f"Toggled {entity_id}")
        return {"success": True, "entity_id": entity_id, "action": "toggle"}

    # Switch controls
    async def turn_on_switch(self, entity_id: str) -> Dict[str, Any]:
        """Turn on a switch."""
        return await self._call_and_confirm(
            "switch", "turn_on", entity_id, ["on"], "turn_on")

    async def turn_off_switch(self, entity_id: str) -> Dict[str, Any]:
        """Turn off a switch."""
        return await self._call_and_confirm(
            "switch", "turn_off", entity_id, ["off"], "turn_off")

    async def toggle_switch(self, entity_id: str) -> Dict[str, Any]:
        """Toggle a switch."""
        await self.call_service("switch", "toggle", entity_id)
        logger.info(f"Toggled switch {entity_id}")
        return {"success": True, "entity_id": entity_id, "action": "toggle"}

    # Climate controls
    async def set_climate_temperature(
        self,
        entity_id: str,
        temperature: float,
        hvac_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set climate/thermostat temperature."""
        kwargs = {"temperature": temperature}
        if hvac_mode:
            kwargs["hvac_mode"] = hvac_mode

        await self.call_service("climate", "set_temperature", entity_id, **kwargs)
        logger.info(f"Set {entity_id} temperature to {temperature}")
        return {"success": True, "entity_id": entity_id, "temperature": temperature}

    async def set_climate_mode(self, entity_id: str, hvac_mode: str) -> Dict[str, Any]:
        """Set climate/thermostat mode (heat, cool, auto, off)."""
        await self.call_service("climate", "set_hvac_mode", entity_id, hvac_mode=hvac_mode)
        logger.info(f"Set {entity_id} mode to {hvac_mode}")
        return {"success": True, "entity_id": entity_id, "hvac_mode": hvac_mode}

    # Cover/blinds controls
    async def open_cover(self, entity_id: str) -> Dict[str, Any]:
        """Open a cover (blinds, garage door, etc)."""
        return await self._call_and_confirm(
            "cover", "open_cover", entity_id, ["open", "opening"], "open")

    async def close_cover(self, entity_id: str) -> Dict[str, Any]:
        """Close a cover."""
        return await self._call_and_confirm(
            "cover", "close_cover", entity_id, ["closed", "closing"], "close")

    async def set_cover_position(self, entity_id: str, position: int) -> Dict[str, Any]:
        """Set cover position (0-100)."""
        await self.call_service("cover", "set_cover_position", entity_id, position=position)
        logger.info(f"Set cover {entity_id} to position {position}")
        return {"success": True, "entity_id": entity_id, "position": position}

    # Lock controls
    async def lock(self, entity_id: str) -> Dict[str, Any]:
        """Lock a lock."""
        return await self._call_and_confirm(
            "lock", "lock", entity_id, ["locked"], "lock")

    async def unlock(self, entity_id: str) -> Dict[str, Any]:
        """Unlock a lock."""
        return await self._call_and_confirm(
            "lock", "unlock", entity_id, ["unlocked"], "unlock")

    # Fan controls
    async def turn_on_fan(
        self,
        entity_id: str,
        speed: Optional[str] = None,
        percentage: Optional[int] = None
    ) -> Dict[str, Any]:
        """Turn on a fan."""
        kwargs = {}
        if speed:
            kwargs["speed"] = speed
        if percentage is not None:
            kwargs["percentage"] = percentage

        await self.call_service("fan", "turn_on", entity_id, **kwargs)
        logger.info(f"Turned on fan {entity_id}")
        return {"success": True, "entity_id": entity_id, "action": "turn_on", "params": kwargs}

    async def turn_off_fan(self, entity_id: str) -> Dict[str, Any]:
        """Turn off a fan."""
        await self.call_service("fan", "turn_off", entity_id)
        logger.info(f"Turned off fan {entity_id}")
        return {"success": True, "entity_id": entity_id, "action": "turn_off"}

    # Media player controls
    async def media_play(self, entity_id: str) -> Dict[str, Any]:
        """Play media."""
        await self.call_service("media_player", "media_play", entity_id)
        return {"success": True, "entity_id": entity_id, "action": "play"}

    async def media_pause(self, entity_id: str) -> Dict[str, Any]:
        """Pause media."""
        await self.call_service("media_player", "media_pause", entity_id)
        return {"success": True, "entity_id": entity_id, "action": "pause"}

    async def media_stop(self, entity_id: str) -> Dict[str, Any]:
        """Stop media."""
        await self.call_service("media_player", "media_stop", entity_id)
        return {"success": True, "entity_id": entity_id, "action": "stop"}

    async def set_volume(self, entity_id: str, volume_level: float) -> Dict[str, Any]:
        """Set volume (0.0 to 1.0)."""
        await self.call_service(
            "media_player", "volume_set", entity_id,
            volume_level=max(0.0, min(1.0, volume_level))
        )
        return {"success": True, "entity_id": entity_id, "volume": volume_level}

    # Scene activation
    async def activate_scene(self, entity_id: str) -> Dict[str, Any]:
        """Activate a scene."""
        await self.call_service("scene", "turn_on", entity_id)
        logger.info(f"Activated scene {entity_id}")
        return {"success": True, "entity_id": entity_id, "action": "activate"}

    # Script execution
    async def run_script(self, entity_id: str) -> Dict[str, Any]:
        """Run a script."""
        # Scripts use just the script name without domain prefix in service call
        script_name = entity_id.replace("script.", "")
        await self.call_service("script", script_name)
        logger.info(f"Ran script {entity_id}")
        return {"success": True, "entity_id": entity_id, "action": "run"}

    # Query helpers
    async def get_entities_by_domain(self, domain: str) -> List[Dict[str, Any]]:
        """Get all entities for a specific domain."""
        states = await self.get_states()
        return [
            {
                "entity_id": s["entity_id"],
                "state": s["state"],
                "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                "attributes": s.get("attributes", {})
            }
            for s in states
            if s["entity_id"].startswith(f"{domain}.")
        ]

    async def get_lights(self) -> List[Dict[str, Any]]:
        """Get all lights with their current states."""
        return await self.get_entities_by_domain("light")

    async def get_switches(self) -> List[Dict[str, Any]]:
        """Get all switches with their current states."""
        return await self.get_entities_by_domain("switch")

    async def get_climate(self) -> List[Dict[str, Any]]:
        """Get all climate entities."""
        return await self.get_entities_by_domain("climate")

    async def find_entity(self, search_term: str) -> List[Dict[str, Any]]:
        """Find entities matching a search term in entity_id or friendly_name."""
        states = await self.get_states()
        search_lower = search_term.lower()
        matches = []

        for s in states:
            entity_id = s["entity_id"].lower()
            friendly_name = s.get("attributes", {}).get("friendly_name", "").lower()

            if search_lower in entity_id or search_lower in friendly_name:
                matches.append({
                    "entity_id": s["entity_id"],
                    "state": s["state"],
                    "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                    "domain": s["entity_id"].split(".")[0]
                })

        return matches


# Singleton instance
ha_control = HAControlService()
