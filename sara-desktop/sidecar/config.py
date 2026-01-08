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


def get_models_dir() -> Path:
    """Get the models directory, handling PyInstaller bundles."""
    # Check for PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        exe_dir = Path(sys.executable).parent

        # Check various locations
        candidates = [
            exe_dir / "models",  # Same dir as executable
            exe_dir.parent / "models",  # Parent dir (for app bundles)
            exe_dir.parent / "Resources" / "models",  # macOS app bundle
            Path.home() / ".sara" / "models",  # User's home directory
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Default to home directory (will be created)
        return Path.home() / ".sara" / "models"
    else:
        # Running as script
        return Path(__file__).parent.parent / "models"


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

        # Wake word
        self.wake_word_model: str = os.getenv("SARA_WAKE_WORD_MODEL", "hey_sara.onnx")
        self.wake_word_threshold: float = float(os.getenv("SARA_WAKE_WORD_THRESHOLD", "0.7"))

        # Screenshot
        self.screenshot_interval: int = int(os.getenv("SARA_SCREENSHOT_INTERVAL", "30"))
        self.screenshot_enabled: bool = True

        # Activity monitoring
        self.activity_report_interval: int = 5  # seconds
        self.idle_threshold: int = 60  # seconds without input = idle

        # Heartbeat
        self.heartbeat_interval: int = 10  # seconds

        # Paths
        self.models_dir: Path = get_models_dir()
        self.settings_file: Path = Path.home() / ".sara" / "sidecar-settings.json"

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
                    if "wake_word_threshold" in settings:
                        self.wake_word_threshold = float(settings["wake_word_threshold"])
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
