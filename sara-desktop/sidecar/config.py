"""
Configuration for Sara Desktop Sidecar
"""
import os
import platform
import sys
import uuid
from pathlib import Path
from typing import Optional


def get_default_device_id() -> str:
    """Generate a unique device ID based on machine info."""
    machine_id = platform.node() or "unknown"
    return f"{platform.system().lower()}-{machine_id}-{uuid.getnode()}"


class SidecarConfig:
    """Configuration for the sidecar service"""

    def __init__(self):
        # Backend connection
        self.backend_url: str = os.getenv("SARA_BACKEND_URL", "https://sara-api.avery.cloud")
        self.backend_ws_url: str = os.getenv(
            "SARA_BACKEND_WS",
            "wss://sara-api.avery.cloud/api/devices/ws"
        )

        # Device identification
        self.device_id: str = get_default_device_id()
        self.hostname: str = platform.node()
        self.platform_name: str = platform.system().lower()
        self.os_version: str = platform.version()

        # Authentication (loaded from settings file or environment)
        self.auth_token: Optional[str] = os.getenv("SARA_AUTH_TOKEN")

        # Electron bridge
        self.electron_ws_port: int = int(os.getenv("SARA_ELECTRON_WS_PORT", "9876"))
        self.electron_ws_host: str = "127.0.0.1"

        # Screenshot
        self.screenshot_interval: int = int(os.getenv("SARA_SCREENSHOT_INTERVAL", "300"))  # 5 minutes
        self.screenshot_enabled: bool = True

        # Activity monitoring
        self.activity_report_interval: int = 5  # seconds
        self.idle_threshold: int = 60  # seconds without input = idle

        # Heartbeat
        self.heartbeat_interval: int = 10  # seconds

        # Voice (SPEAK command / local TTS playback — A3/A6)
        self.tts_url: str = os.getenv("SARA_TTS_URL", "http://10.185.1.9:8880")
        self.tts_voice: str = os.getenv("SARA_TTS_VOICE", "af_heart")
        self.tts_speed: float = float(os.getenv("SARA_TTS_SPEED", "1.0"))
        self.tts_output_device: Optional[str] = os.getenv("SARA_TTS_OUTPUT_DEVICE")  # substring match, None = system default

        # Jetson bridge — only connects when set (home network); empty disables it.
        # Default matches david-jetson (Orin Nano) at 10.185.1.84 — only takes
        # effect when running the sidecar standalone outside Electron, which
        # always passes SARA_JETSON_HOST explicitly (see main.ts).
        self.jetson_host: str = os.getenv("SARA_JETSON_HOST", "10.185.1.84")
        self.jetson_port: int = int(os.getenv("SARA_JETSON_PORT", "8765"))

        # Paths
        self.settings_file: Path = Path.home() / ".sara" / "sidecar-settings.json"

    def load_settings(self):
        """Load settings from settings file if it exists."""
        import json
        if self.settings_file.exists():
            try:
                with open(self.settings_file) as f:
                    settings = json.load(f)
                    if "auth_token" in settings:
                        self.auth_token = settings["auth_token"]
                    if "backend_url" in settings:
                        self.backend_url = settings["backend_url"]
                    if "screenshot_interval" in settings:
                        self.screenshot_interval = settings["screenshot_interval"]
            except Exception:
                pass

    def save_settings(self):
        """Save current settings to file."""
        import json
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings = {
            "auth_token": self.auth_token,
            "backend_url": self.backend_url,
            "screenshot_interval": self.screenshot_interval,
        }
        with open(self.settings_file, "w") as f:
            json.dump(settings, f, indent=2)


# Global config instance
config = SidecarConfig()
config.load_settings()
