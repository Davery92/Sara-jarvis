"""
Sara Desktop Sidecar - Main Entry Point

Background service that provides:
- Wake word detection using OpenWakeWord
- Activity monitoring (keyboard, mouse, active window)
- Screenshot capture (interval + on-demand)
- WebSocket connection to backend for commands
- Local WebSocket bridge to Electron app
"""
import asyncio
import logging
import signal
import sys
from typing import Optional

from config import config

# Ensure log directory exists
log_dir = config.settings_file.parent
log_dir.mkdir(parents=True, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "sidecar.log", mode="a")
    ]
)
logger = logging.getLogger("sidecar")


class SidecarService:
    """Main service that coordinates all sidecar components."""

    def __init__(self):
        self.running = False
        self._tasks = []

        # Component instances (lazy loaded)
        self._wake_word = None
        self._activity_monitor = None
        self._screenshot_service = None
        self._backend_client = None
        self._electron_bridge = None

    async def start(self):
        """Start all sidecar services."""
        logger.info("Starting Sara Desktop Sidecar...")
        logger.info(f"Device ID: {config.device_id}")
        logger.info(f"Backend: {config.backend_url}")

        self.running = True

        # Import and initialize components
        try:
            from wake_word import WakeWordDetector
            from activity_monitor import ActivityMonitor
            from screenshot import ScreenshotService
            from backend_client import BackendClient
            from electron_bridge import ElectronBridge

            # Create instances
            self._electron_bridge = ElectronBridge(
                host=config.electron_ws_host,
                port=config.electron_ws_port,
                on_message=self._handle_electron_message
            )

            self._backend_client = BackendClient(
                config=config,
                on_command=self._handle_command
            )

            self._activity_monitor = ActivityMonitor(
                on_activity_update=self._on_activity_update
            )

            self._screenshot_service = ScreenshotService(
                backend_client=self._backend_client,
                interval=config.screenshot_interval
            )

            self._wake_word = WakeWordDetector(
                model_path=config.get_wake_word_model_path(),
                threshold=config.wake_word_threshold,
                on_wake_word=self._on_wake_word
            )

            # Start electron bridge FIRST so clients can connect while wake word loads
            logger.info("Starting Electron bridge first...")
            self._tasks = [asyncio.create_task(self._electron_bridge.start())]
            await asyncio.sleep(0.5)  # Give it time to start listening

            # Then start other services
            self._tasks.extend([
                asyncio.create_task(self._backend_client.connect()),
                asyncio.create_task(self._activity_monitor.start()),
                asyncio.create_task(self._screenshot_service.start()),
                asyncio.create_task(self._wake_word.start()),
                asyncio.create_task(self._heartbeat_loop()),
            ])

            logger.info("All services started successfully")

            # Wait for all tasks
            await asyncio.gather(*self._tasks, return_exceptions=True)

        except ImportError as e:
            logger.error(f"Failed to import component: {e}")
            logger.error("Make sure all dependencies are installed: pip install -r requirements.txt")
            raise
        except Exception as e:
            logger.exception(f"Error starting sidecar: {e}")
            raise

    async def stop(self):
        """Stop all sidecar services."""
        logger.info("Stopping Sara Desktop Sidecar...")
        self.running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Stop components
        if self._wake_word:
            await self._wake_word.stop()
        if self._activity_monitor:
            await self._activity_monitor.stop()
        if self._screenshot_service:
            await self._screenshot_service.stop()
        if self._backend_client:
            await self._backend_client.disconnect()
        if self._electron_bridge:
            await self._electron_bridge.stop()

        logger.info("Sidecar stopped")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to backend."""
        while self.running:
            try:
                if self._backend_client and self._activity_monitor:
                    activity = self._activity_monitor.get_activity_summary()
                    await self._backend_client.send_heartbeat(activity)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

            await asyncio.sleep(config.heartbeat_interval)

    async def _on_wake_word(self):
        """Called when wake word is detected."""
        logger.info("Wake word detected!")

        # Notify Electron to start listening
        if self._electron_bridge:
            await self._electron_bridge.send_message({
                "type": "wake_word_detected",
                "timestamp": asyncio.get_event_loop().time()
            })

        # Also tell backend (which may route to other devices)
        if self._backend_client:
            await self._backend_client.send_event("wake_word_detected", {})

    async def _on_activity_update(self, activity: dict):
        """Called when activity metrics are updated."""
        # Forward to Electron for UI updates
        if self._electron_bridge:
            await self._electron_bridge.send_message({
                "type": "activity_update",
                "activity": activity
            })

    async def _handle_electron_message(self, data: dict):
        """Handle messages from Electron via the bridge."""
        msg_type = data.get("type")
        logger.info(f"Received Electron message: {msg_type}")

        if msg_type == "get_audio_devices_request":
            # Get list of audio devices and send back
            websocket = data.get("websocket")
            if self._wake_word and websocket:
                devices = self._wake_word.get_audio_devices()
                current = self._wake_word.get_current_device()
                await self._electron_bridge.send_audio_devices(websocket, devices, current)

        elif msg_type == "set_audio_device_request":
            # Set preferred audio device
            device_index = data.get("device_index")
            device_name = data.get("device_name")
            if self._wake_word:
                self._wake_word.set_preferred_device(device_index, device_name)
                # Notify Electron of the change
                await self._electron_bridge.send_message({
                    "type": "audio_device_changed",
                    "device_index": device_index,
                    "device_name": device_name
                })

        elif msg_type == "auth_token_update":
            # Update auth token
            token = data.get("token")
            if token:
                config.auth_token = token
                config.save_settings()
                if self._backend_client:
                    self._backend_client.config.auth_token = token

        elif msg_type == "screenshot_request":
            # Take screenshot on demand
            if self._screenshot_service:
                await self._screenshot_service.capture_and_upload(
                    analyze=data.get("analyze", False),
                    analyze_prompt=data.get("analyze_prompt")
                )

    async def _handle_command(self, command: dict):
        """Handle a command received from backend."""
        cmd_type = command.get("command")
        payload = command.get("payload", {})

        logger.info(f"Received command: {cmd_type}")

        if cmd_type == "take_screenshot":
            # Capture screenshot
            if self._screenshot_service:
                analyze = payload.get("analyze", False)
                prompt = payload.get("analyze_prompt")
                await self._screenshot_service.capture_and_upload(
                    analyze=analyze,
                    analyze_prompt=prompt
                )

        elif cmd_type == "open_url":
            url = payload.get("url")
            if url:
                import webbrowser
                webbrowser.open(url)
                logger.info(f"Opened URL: {url}")

        elif cmd_type == "show_note":
            # Forward to Electron
            if self._electron_bridge:
                await self._electron_bridge.send_message({
                    "type": "show_note",
                    "note_id": payload.get("note_id"),
                    "title": payload.get("title"),
                    "content": payload.get("content")
                })

        elif cmd_type == "show_timer":
            # Forward to Electron
            if self._electron_bridge:
                await self._electron_bridge.send_message({
                    "type": "show_timer",
                    "timer_id": payload.get("timer_id"),
                    "label": payload.get("label"),
                    "remaining_seconds": payload.get("remaining_seconds")
                })

        elif cmd_type == "speak":
            # Forward to Electron for TTS
            if self._electron_bridge:
                await self._electron_bridge.send_message({
                    "type": "speak",
                    "text": payload.get("text")
                })

        elif cmd_type == "show_notification":
            # Forward to Electron
            if self._electron_bridge:
                await self._electron_bridge.send_message({
                    "type": "show_notification",
                    "title": payload.get("title"),
                    "message": payload.get("message")
                })

        elif cmd_type == "start_listening":
            # Wake word triggered from another device
            if self._electron_bridge:
                await self._electron_bridge.send_message({
                    "type": "start_listening"
                })

        else:
            logger.warning(f"Unknown command type: {cmd_type}")


async def main():
    """Main entry point."""
    service = SidecarService()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(service.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        await service.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
