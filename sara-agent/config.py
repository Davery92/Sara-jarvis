"""
Configuration for Sara Headless Agent
"""
import os
import platform
import uuid
import json
from pathlib import Path
from typing import Optional


def get_default_device_id() -> str:
    """Generate a unique device ID based on machine info."""
    machine_id = platform.node() or "unknown"
    return f"{platform.system().lower()}-{machine_id}-{uuid.getnode()}"


class AgentConfig:
    """Configuration for the headless agent service"""

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
        self.agent_type: str = "headless"  # Distinguishes from desktop agent

        # Authentication (loaded from settings file or environment)
        self.auth_token: Optional[str] = os.getenv("SARA_AUTH_TOKEN")

        # Heartbeat and metrics
        self.heartbeat_interval: int = int(os.getenv("SARA_HEARTBEAT_INTERVAL", "30"))
        self.metrics_interval: int = int(os.getenv("SARA_METRICS_INTERVAL", "60"))

        # Paths
        self.config_dir: Path = Path(os.getenv("SARA_CONFIG_DIR", "/etc/sara-agent"))
        self.settings_file: Path = self.config_dir / "config.json"
        self.log_file: Path = Path(os.getenv("SARA_LOG_FILE", "/var/log/sara-agent.log"))

        # Load settings
        self.load_settings()

    def load_settings(self):
        """Load settings from config file if it exists."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file) as f:
                    settings = json.load(f)
                    if "auth_token" in settings:
                        self.auth_token = settings["auth_token"]
                    if "backend_url" in settings:
                        self.backend_url = settings["backend_url"]
                    if "backend_ws_url" in settings:
                        self.backend_ws_url = settings["backend_ws_url"]
                    if "device_id" in settings:
                        self.device_id = settings["device_id"]
                    if "heartbeat_interval" in settings:
                        self.heartbeat_interval = settings["heartbeat_interval"]
                    if "metrics_interval" in settings:
                        self.metrics_interval = settings["metrics_interval"]
            except Exception:
                pass

    def save_settings(self):
        """Save current settings to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        settings = {
            "auth_token": self.auth_token,
            "backend_url": self.backend_url,
            "backend_ws_url": self.backend_ws_url,
            "device_id": self.device_id,
            "heartbeat_interval": self.heartbeat_interval,
            "metrics_interval": self.metrics_interval,
        }
        with open(self.settings_file, "w") as f:
            json.dump(settings, f, indent=2)
        # Secure the config file
        os.chmod(self.settings_file, 0o600)


# Global config instance
config = AgentConfig()
