"""
Configuration for Sara Desktop Sidecar
"""
import os
import platform
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def get_default_device_id() -> str:
    """Generate a unique device ID based on machine info."""
    machine_id = platform.node() or "unknown"
    return f"{platform.system().lower()}-{machine_id}-{uuid.getnode()}"


@dataclass
class SidecarConfig:
    """Configuration for the sidecar service"""

    # Backend connection
    backend_url: str = field(
        default_factory=lambda: os.getenv("SARA_BACKEND_URL", "https://sara-api.avery.cloud")
    )
    backend_ws_url: str = field(
        default_factory=lambda: os.getenv(
            "SARA_BACKEND_WS",
            "wss://sara-api.avery.cloud/api/devices/ws"
        )
    )

    # Device identification
    device_id: str = field(default_factory=get_default_device_id)
    hostname: str = field(default_factory=platform.node)
    platform: str = field(default_factory=lambda: platform.system().lower())
    os_version: str = field(default_factory=platform.version)

    # Authentication (loaded from settings file or environment)
    auth_token: Optional[str] = field(
        default_factory=lambda: os.getenv("SARA_AUTH_TOKEN")
    )

    # Electron bridge
    electron_ws_port: int = field(
        default_factory=lambda: int(os.getenv("SARA_ELECTRON_WS_PORT", "9876"))
    )
    electron_ws_host: str = "127.0.0.1"

    # Wake word
    wake_word_model: str = field(
        default_factory=lambda: os.getenv("SARA_WAKE_WORD_MODEL", "hey_sara.onnx")
    )
    wake_word_threshold: float = 0.5

    # Screenshot
    screenshot_interval: int = field(
        default_factory=lambda: int(os.getenv("SARA_SCREENSHOT_INTERVAL", "30"))
    )
    screenshot_enabled: bool = True

    # Activity monitoring
    activity_report_interval: int = 5  # seconds
    idle_threshold: int = 60  # seconds without input = idle

    # Heartbeat
    heartbeat_interval: int = 10  # seconds

    # Paths
    models_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "models")
    settings_file: Path = field(
        default_factory=lambda: Path.home() / ".sara" / "sidecar-settings.json"
    )

    def get_wake_word_model_path(self) -> Path:
        """Get the full path to the wake word model."""
        return self.models_dir / self.wake_word_model

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
            "screenshot_interval": self.screenshot_interval
        }
        with open(self.settings_file, "w") as f:
            json.dump(settings, f, indent=2)


# Global config instance
config = SidecarConfig()
config.load_settings()
