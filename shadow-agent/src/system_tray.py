"""
System Tray UI for Voice Agent
Cross-platform system tray with mode switching and controls
"""
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Always import PIL (required for this module to work)
from PIL import Image, ImageDraw

# Try to import platform-specific tray library
try:
    import pystray
    TRAY_AVAILABLE = True
except ImportError:
    logger.warning("pystray not available - system tray will be disabled")
    TRAY_AVAILABLE = False

from typing import Optional
from audio_session import VoiceAgent, VoiceMode, VoiceAgentState


class SystemTrayUI:
    """System tray icon and menu for voice agent"""

    def __init__(self, voice_agent: VoiceAgent):
        """
        Initialize system tray

        Args:
            voice_agent: VoiceAgent instance to control
        """
        if not TRAY_AVAILABLE:
            raise ImportError("pystray not available. Install with: pip install pystray pillow")

        self.voice_agent = voice_agent
        self.icon: Optional["pystray.Icon"] = None

        # Status tracking
        self.current_state = VoiceAgentState.IDLE
        self.current_mode = voice_agent.voice_mode

        # Register state change callback
        voice_agent.on_state_change = self._on_state_change

    def create_icon_image(self, state: VoiceAgentState) -> "Image.Image":
        """
        Create icon image based on agent state

        Args:
            state: Current voice agent state

        Returns:
            PIL Image for tray icon
        """
        # Create 64x64 icon
        image = Image.new('RGB', (64, 64), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)

        # Draw based on state
        if state == VoiceAgentState.IDLE:
            # Gray circle
            draw.ellipse([8, 8, 56, 56], fill=(128, 128, 128), outline=(64, 64, 64), width=3)
        elif state == VoiceAgentState.LISTENING_FOR_WAKE:
            # Green circle (listening)
            draw.ellipse([8, 8, 56, 56], fill=(76, 175, 80), outline=(56, 142, 60), width=3)
        elif state == VoiceAgentState.RECORDING:
            # Red circle (recording)
            draw.ellipse([8, 8, 56, 56], fill=(244, 67, 54), outline=(198, 40, 40), width=3)
            # Add inner dot
            draw.ellipse([24, 24, 40, 40], fill=(255, 255, 255))
        elif state == VoiceAgentState.PROCESSING:
            # Yellow circle (processing)
            draw.ellipse([8, 8, 56, 56], fill=(255, 193, 7), outline=(245, 127, 23), width=3)
        elif state == VoiceAgentState.SPEAKING:
            # Blue circle (speaking)
            draw.ellipse([8, 8, 56, 56], fill=(33, 150, 243), outline=(25, 118, 210), width=3)
            # Add sound waves
            draw.arc([16, 16, 48, 48], start=180, end=360, fill=(255, 255, 255), width=2)
        elif state == VoiceAgentState.ERROR:
            # Red X
            draw.ellipse([8, 8, 56, 56], fill=(244, 67, 54), outline=(198, 40, 40), width=3)
            draw.line([20, 20, 44, 44], fill=(255, 255, 255), width=4)
            draw.line([20, 44, 44, 20], fill=(255, 255, 255), width=4)

        return image

    def _on_state_change(self, new_state: VoiceAgentState):
        """Callback when voice agent state changes"""
        self.current_state = new_state

        # Update icon
        if self.icon:
            self.icon.icon = self.create_icon_image(new_state)
            self.icon.title = f"Sara Voice - {new_state.value.title()}"

    def _create_menu(self):
        """Create system tray menu"""
        return pystray.Menu(
            # Status display
            pystray.MenuItem(
                lambda item: f"Status: {self.current_state.value.title()}",
                lambda item: None,
                enabled=False
            ),
            pystray.Menu.SEPARATOR,

            # Mode selection
            pystray.MenuItem(
                "Voice Mode",
                pystray.Menu(
                    pystray.MenuItem(
                        "Always-On",
                        lambda item: self._set_mode(VoiceMode.ALWAYS_ON),
                        checked=lambda item: self.current_mode == VoiceMode.ALWAYS_ON,
                        radio=True
                    ),
                    pystray.MenuItem(
                        "Shadow-Only",
                        lambda item: self._set_mode(VoiceMode.SHADOW_ONLY),
                        checked=lambda item: self.current_mode == VoiceMode.SHADOW_ONLY,
                        radio=True
                    ),
                    pystray.MenuItem(
                        "Push-to-Talk",
                        lambda item: self._set_mode(VoiceMode.PUSH_TO_TALK),
                        checked=lambda item: self.current_mode == VoiceMode.PUSH_TO_TALK,
                        radio=True
                    )
                )
            ),
            pystray.Menu.SEPARATOR,

            # Actions
            pystray.MenuItem(
                "Test Voice",
                lambda item: self._test_voice(),
                enabled=lambda item: self.current_mode == VoiceMode.PUSH_TO_TALK
            ),
            pystray.MenuItem("Settings", lambda item: self._open_settings()),
            pystray.MenuItem("View Logs", lambda item: self._view_logs()),
            pystray.Menu.SEPARATOR,

            # Exit
            pystray.MenuItem("Restart Agent", lambda item: self._restart_agent()),
            pystray.MenuItem("Quit", lambda item: self._quit())
        )

    def _set_mode(self, mode: VoiceMode):
        """Change voice mode"""
        self.current_mode = mode
        self.voice_agent.set_voice_mode(mode)
        logger.info(f"Voice mode changed to: {mode.value}")

    def _test_voice(self):
        """Trigger manual voice activation (PTT)"""
        self.voice_agent.trigger_manual_listen()

    def _open_settings(self):
        """Open settings (placeholder)"""
        logger.info("Settings clicked (not implemented)")
        # TODO: Open settings window

    def _view_logs(self):
        """Open log file"""
        log_file = Path.home() / ".sara" / "shadow-agent.log"
        if log_file.exists():
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(["notepad", str(log_file)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(log_file)])
            else:
                subprocess.Popen(["xdg-open", str(log_file)])

    def _restart_agent(self):
        """Restart voice agent"""
        logger.info("Restarting voice agent...")
        self.voice_agent.stop()
        self.voice_agent.start()

    def _quit(self):
        """Quit application"""
        logger.info("Quit requested")
        self.voice_agent.stop()
        if self.icon:
            self.icon.stop()

    def run(self):
        """Start system tray (blocking)"""
        # Create icon
        initial_image = self.create_icon_image(self.current_state)
        self.icon = pystray.Icon(
            "sara_voice",
            initial_image,
            "Sara Voice Agent",
            self._create_menu()
        )

        logger.info("Starting system tray...")

        # Run (blocking)
        self.icon.run()
