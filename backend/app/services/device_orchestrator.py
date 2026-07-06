"""
Device Orchestrator Service

Intelligent content routing across David's devices. Decides which device
should receive what type of content based on:
- Device capabilities (desktop for long content, phone for alerts)
- Current activity state (focused work → don't buzz phone, use desktop)
- Device activity level (route to whichever device David is actively using)
- Content type (notification, long text, URL, voice, visual)

This sits on top of command_router (which handles delivery) — this service
handles the *decision* of where to send things.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """Types of content that can be routed to devices."""
    NOTIFICATION = "notification"      # Short alert/push
    LONG_TEXT = "long_text"            # Detailed response, article, briefing
    URL = "url"                        # Web link to open
    VOICE = "voice"                    # Spoken response (TTS)
    VISUAL = "visual"                  # Screenshot, image, visual data
    TIMER = "timer"                    # Timer display
    WORKSPACE = "workspace"            # Full workspace/canvas content


class DeviceClass(str, Enum):
    """Device classification for routing decisions."""
    DESKTOP = "desktop"    # Linux/macOS/Windows desktop
    MOBILE = "mobile"      # iOS/Android phone
    TABLET = "tablet"      # iPad/Android tablet
    VOICE = "voice"        # HomePod/Echo/voice-only device
    UNKNOWN = "unknown"


@dataclass
class DeviceProfile:
    """Profile of a specific device for routing decisions."""
    device_id: str
    device_class: DeviceClass
    platform: str
    friendly_name: str
    is_online: bool
    activity_level: str  # idle, low, medium, high
    last_activity_at: Optional[datetime] = None
    has_websocket: bool = False  # Can receive real-time commands
    has_push: bool = False       # Can receive push notifications
    capabilities: List[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.is_online and self.activity_level in ("medium", "high")


@dataclass
class RoutingDecision:
    """Result of a content routing decision."""
    target_device_id: Optional[str]
    target_device_class: DeviceClass
    delivery_method: str  # "websocket", "push", "defer", "broadcast"
    reason: str
    fallback_device_id: Optional[str] = None


# Content type → preferred device class (in priority order)
CONTENT_PREFERENCES: Dict[ContentType, List[DeviceClass]] = {
    ContentType.NOTIFICATION: [DeviceClass.MOBILE, DeviceClass.DESKTOP],
    ContentType.LONG_TEXT: [DeviceClass.DESKTOP, DeviceClass.TABLET, DeviceClass.MOBILE],
    ContentType.URL: [DeviceClass.DESKTOP, DeviceClass.TABLET, DeviceClass.MOBILE],
    ContentType.VOICE: [DeviceClass.VOICE, DeviceClass.DESKTOP, DeviceClass.MOBILE],
    ContentType.VISUAL: [DeviceClass.DESKTOP, DeviceClass.TABLET],
    ContentType.TIMER: [DeviceClass.MOBILE, DeviceClass.DESKTOP],
    ContentType.WORKSPACE: [DeviceClass.DESKTOP],
}

# Activity state overrides: when in these states, prefer these device classes
ACTIVITY_DEVICE_OVERRIDES: Dict[str, DeviceClass] = {
    "focused_work": DeviceClass.DESKTOP,   # Working at desk → desktop
    "in_meeting": DeviceClass.MOBILE,      # In meeting → phone only (quiet)
    "exercising": DeviceClass.MOBILE,      # Working out → phone
    "cooking": DeviceClass.VOICE,          # Cooking → voice device (hands busy)
    "away": DeviceClass.MOBILE,            # Away → phone
}


class DeviceOrchestrator:
    """
    Orchestrates content delivery across David's devices.

    Usage:
        decision = await orchestrator.route_content(
            db, user_id, ContentType.NOTIFICATION,
            activity_state="focused_work"
        )
    """

    def classify_device(self, platform: str) -> DeviceClass:
        """Classify a device based on its platform string."""
        platform_lower = (platform or "").lower()
        if platform_lower in ("ios", "android"):
            return DeviceClass.MOBILE
        if platform_lower in ("ipados",):
            return DeviceClass.TABLET
        if platform_lower in ("linux", "darwin", "windows", "macos"):
            return DeviceClass.DESKTOP
        if platform_lower in ("homepod", "echo", "voice"):
            return DeviceClass.VOICE
        return DeviceClass.UNKNOWN

    async def get_device_profiles(
        self,
        db,
        user_id: str,
    ) -> List[DeviceProfile]:
        """
        Build profiles for all of the user's devices by combining:
        - Machine registry (desktop agents)
        - Push tokens (mobile devices)
        - WebSocket connections (real-time capable)
        """
        from app.services.machine_registry import machine_registry_service
        from app.services.command_router import command_router
        from sqlalchemy import text

        profiles = []

        # Desktop/laptop machines from registry
        try:
            machines = await machine_registry_service.get_user_machines(db, user_id, include_offline=True)
            for m in machines:
                profiles.append(DeviceProfile(
                    device_id=m.device_id,
                    device_class=self.classify_device(m.platform),
                    platform=m.platform or "unknown",
                    friendly_name=m.friendly_name or m.hostname or m.device_id,
                    is_online=m.is_online,
                    activity_level=m.activity_level or "idle",
                    last_activity_at=m.last_activity_at,
                    has_websocket=command_router.is_device_connected(m.device_id),
                    capabilities=m.capabilities if isinstance(m.capabilities, list) else [],
                ))
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(f"Failed to get machine profiles: {e}")

        # Mobile devices from push tokens
        try:
            push_results = db.execute(text("""
                SELECT id, token, platform, device_name, is_active, created_at
                FROM push_token
                WHERE user_id = :user_id AND is_active = true
            """), {"user_id": user_id}).fetchall()

            for pt in push_results:
                device_id = f"push_{pt.id}"
                profiles.append(DeviceProfile(
                    device_id=device_id,
                    device_class=self.classify_device(pt.platform),
                    platform=pt.platform or "mobile",
                    friendly_name=pt.device_name or f"{pt.platform} phone",
                    is_online=True,  # Push devices are always "reachable"
                    activity_level="low",  # We don't track mobile activity levels
                    has_websocket=False,
                    has_push=True,
                ))
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(f"Failed to get push token profiles: {e}")

        return profiles

    async def route_content(
        self,
        db,
        user_id: str,
        content_type: ContentType,
        activity_state: Optional[str] = None,
        interruptibility: float = 0.5,
        preferred_device_id: Optional[str] = None,
    ) -> RoutingDecision:
        """
        Decide which device should receive this content.

        Priority:
        1. Explicit preference (user requested specific device)
        2. Activity state override (focused_work → desktop)
        3. Content type preference + most active matching device
        4. Any active device
        5. Defer if nothing available
        """
        profiles = await self.get_device_profiles(db, user_id)

        if not profiles:
            return RoutingDecision(
                target_device_id=None,
                target_device_class=DeviceClass.UNKNOWN,
                delivery_method="defer",
                reason="No devices registered"
            )

        # 1. Explicit preference
        if preferred_device_id:
            match = next((p for p in profiles if p.device_id == preferred_device_id), None)
            if match and match.is_online:
                method = "websocket" if match.has_websocket else ("push" if match.has_push else "defer")
                return RoutingDecision(
                    target_device_id=match.device_id,
                    target_device_class=match.device_class,
                    delivery_method=method,
                    reason=f"User-preferred device: {match.friendly_name}"
                )

        # 2. Activity state override
        if activity_state and activity_state in ACTIVITY_DEVICE_OVERRIDES:
            preferred_class = ACTIVITY_DEVICE_OVERRIDES[activity_state]
            candidates = [
                p for p in profiles
                if p.device_class == preferred_class and p.is_online
            ]
            if candidates:
                best = self._pick_most_active(candidates)
                method = "websocket" if best.has_websocket else ("push" if best.has_push else "defer")
                return RoutingDecision(
                    target_device_id=best.device_id,
                    target_device_class=best.device_class,
                    delivery_method=method,
                    reason=f"Activity override ({activity_state} → {preferred_class.value}): {best.friendly_name}"
                )

        # 3. Content type preference
        preferred_classes = CONTENT_PREFERENCES.get(content_type, [])
        for device_class in preferred_classes:
            candidates = [
                p for p in profiles
                if p.device_class == device_class and p.is_online
            ]
            if candidates:
                best = self._pick_most_active(candidates)
                method = "websocket" if best.has_websocket else ("push" if best.has_push else "defer")

                # Find fallback device of different class
                fallback = None
                other_online = [p for p in profiles if p.is_online and p.device_id != best.device_id]
                if other_online:
                    fallback = self._pick_most_active(other_online).device_id

                return RoutingDecision(
                    target_device_id=best.device_id,
                    target_device_class=best.device_class,
                    delivery_method=method,
                    reason=f"Content preference ({content_type.value} → {device_class.value}): {best.friendly_name}",
                    fallback_device_id=fallback,
                )

        # 4. Any active device
        active = [p for p in profiles if p.is_active]
        if active:
            best = self._pick_most_active(active)
            method = "websocket" if best.has_websocket else ("push" if best.has_push else "defer")
            return RoutingDecision(
                target_device_id=best.device_id,
                target_device_class=best.device_class,
                delivery_method=method,
                reason=f"Fallback to most active: {best.friendly_name}"
            )

        # 5. Any online device
        online = [p for p in profiles if p.is_online]
        if online:
            best = self._pick_most_active(online)
            method = "websocket" if best.has_websocket else ("push" if best.has_push else "defer")
            return RoutingDecision(
                target_device_id=best.device_id,
                target_device_class=best.device_class,
                delivery_method=method,
                reason=f"Fallback to any online: {best.friendly_name}"
            )

        # 6. Broadcast/defer — no devices available
        return RoutingDecision(
            target_device_id=None,
            target_device_class=DeviceClass.UNKNOWN,
            delivery_method="defer",
            reason="No online devices — content will be delivered when a device comes online"
        )

    def _pick_most_active(self, profiles: List[DeviceProfile]) -> DeviceProfile:
        """Pick the most active device from a list of candidates."""
        activity_rank = {"high": 4, "medium": 3, "low": 2, "idle": 1}

        return max(
            profiles,
            key=lambda p: (
                activity_rank.get(p.activity_level, 0),
                1 if p.has_websocket else 0,  # Prefer real-time capable
                p.last_activity_at or datetime.min,  # Most recently active
            )
        )

    async def get_device_context_for_chat(
        self,
        db,
        user_id: str,
    ) -> Optional[str]:
        """
        Build a device awareness context string for injection into the system prompt.
        Tells Sara which devices David has and which is active, plus (A7) the
        unified presence line — the same "where is David" answer every other
        consumer (overlay routing, voice-note device selection) uses.
        """
        presence_line = None
        try:
            from app.services.device_presence import resolve as resolve_presence, format_context_line
            presence_line = format_context_line(await resolve_presence(db, user_id))
        except Exception as e:
            logger.warning(f"device_presence context line failed: {e}")

        try:
            profiles = await self.get_device_profiles(db, user_id)
            online = [p for p in profiles if p.is_online]

            if not profiles or not online:
                return presence_line

            lines = ["[Device awareness — route content to the right device when relevant]"]
            if presence_line:
                lines.append(presence_line)
            lines.append(f"David has {len(profiles)} devices ({len(online)} online):")

            for p in sorted(profiles, key=lambda x: x.is_online, reverse=True):
                status = "online" if p.is_online else "offline"
                activity = f", {p.activity_level}" if p.is_online and p.activity_level != "idle" else ""
                ws = ", real-time" if p.has_websocket else ""
                push = ", push" if p.has_push else ""
                lines.append(f"  - {p.friendly_name} ({p.device_class.value}/{p.platform}) [{status}{activity}{ws}{push}]")

            # Identify the primary active device
            active = [p for p in profiles if p.is_active]
            if active:
                primary = self._pick_most_active(active)
                lines.append(f"Primary active device: {primary.friendly_name}")
            elif online:
                lines.append(f"No highly active device — {online[0].friendly_name} is reachable")

            lines.append("Use device tools to send content to the right device when relevant.")
            return "\n".join(lines)

        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(f"Device context generation failed: {e}")
            return presence_line
            return None


# Global singleton
device_orchestrator = DeviceOrchestrator()
