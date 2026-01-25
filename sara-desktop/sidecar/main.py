"""
Sara Desktop Sidecar - Main Entry Point

Background service that provides:
- Activity monitoring (keyboard, mouse, active window)
- Screenshot capture (interval + on-demand)
- System metrics collection (CPU, RAM, disk, network, GPU)
- WebSocket connection to backend for commands
- Local WebSocket bridge to Electron app
"""
import asyncio
import logging
import signal
import sys
from typing import Optional

from config import config

# Try to import metrics collector
try:
    from metrics import metrics_collector, PSUTIL_AVAILABLE
except ImportError:
    metrics_collector = None
    PSUTIL_AVAILABLE = False

# Try to import voice bridge
try:
    from voice_bridge import VoiceBridge, VoiceState, is_available as voice_bridge_available
    VOICE_BRIDGE_AVAILABLE = voice_bridge_available()
except ImportError:
    VoiceBridge = None
    VoiceState = None
    VOICE_BRIDGE_AVAILABLE = False

# Try to import audio playback detector
try:
    from audio_playback import AudioPlaybackDetector, is_available as audio_playback_available
    AUDIO_PLAYBACK_AVAILABLE = audio_playback_available()
except ImportError:
    AudioPlaybackDetector = None
    AUDIO_PLAYBACK_AVAILABLE = False

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
        self._activity_monitor = None
        self._screenshot_service = None
        self._backend_client = None
        self._electron_bridge = None
        self._metrics_collector = metrics_collector if PSUTIL_AVAILABLE else None
        self._voice_bridge = None
        self._voice_state = "disconnected"
        self._audio_playback_detector = None
        self._last_playback_state = False

    async def start(self):
        """Start all sidecar services."""
        logger.info("Starting Sara Desktop Sidecar...")
        logger.info(f"Device ID: {config.device_id}")
        logger.info(f"Backend: {config.backend_url}")

        self.running = True

        # Import and initialize components
        try:
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

            # Start electron bridge FIRST so clients can connect
            logger.info("Starting Electron bridge first...")
            self._tasks = [asyncio.create_task(self._electron_bridge.start())]
            await asyncio.sleep(0.5)  # Give it time to start listening

            # Then start other services
            self._tasks.extend([
                asyncio.create_task(self._backend_client.connect()),
                asyncio.create_task(self._activity_monitor.start()),
                asyncio.create_task(self._screenshot_service.start()),
                asyncio.create_task(self._heartbeat_loop()),
            ])

            # Add metrics loop if psutil is available
            if self._metrics_collector:
                self._tasks.append(asyncio.create_task(self._metrics_loop()))
                logger.info("System metrics collection enabled")
            else:
                logger.warning("psutil not available - system metrics disabled")

            # Start voice bridge if available and enabled
            if VOICE_BRIDGE_AVAILABLE and config.voice_bridge_enabled:
                self._voice_bridge = VoiceBridge(
                    host=config.voice_bridge_host,
                    port=config.voice_bridge_port,
                    on_state_change=self._on_voice_state_change,
                    on_transcript=self._on_voice_transcript,
                )
                self._tasks.append(asyncio.create_task(self._voice_bridge.start()))
                logger.info(f"Voice bridge enabled: {config.voice_bridge_host}:{config.voice_bridge_port}")
            elif not VOICE_BRIDGE_AVAILABLE:
                logger.warning("Voice bridge not available - missing dependencies (sounddevice)")
            else:
                logger.info("Voice bridge disabled by configuration")

            # Start audio playback detector if available
            if AUDIO_PLAYBACK_AVAILABLE:
                self._audio_playback_detector = AudioPlaybackDetector(
                    on_state_change=self._on_audio_playback_change
                )
                self._tasks.append(asyncio.create_task(self._audio_playback_detector.start()))
                self._tasks.append(asyncio.create_task(self._audio_playback_report_loop()))
                logger.info("Audio playback detection enabled")
            else:
                logger.warning("Audio playback detection not available - missing pulsectl")

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
        if self._activity_monitor:
            await self._activity_monitor.stop()
        if self._screenshot_service:
            await self._screenshot_service.stop()
        if self._backend_client:
            await self._backend_client.disconnect()
        if self._electron_bridge:
            await self._electron_bridge.stop()
        if self._voice_bridge:
            await self._voice_bridge.stop()

        logger.info("Sidecar stopped")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to backend."""
        while self.running:
            try:
                if self._backend_client and self._activity_monitor:
                    activity = self._activity_monitor.get_activity_summary()

                    # Add quick metrics to heartbeat if available
                    if self._metrics_collector:
                        try:
                            metrics = self._metrics_collector.collect()
                            if metrics:
                                activity["cpu_percent"] = metrics.cpu.usage_percent
                                activity["memory_percent"] = metrics.memory.percent_used
                        except Exception:
                            pass

                    await self._backend_client.send_heartbeat(activity)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

            await asyncio.sleep(config.heartbeat_interval)

    async def _metrics_loop(self):
        """Send periodic full metrics to backend and Electron."""
        # Wait for initial connection
        await asyncio.sleep(15)

        while self.running:
            try:
                if self._metrics_collector:
                    metrics = self._metrics_collector.collect()
                    if metrics:
                        metrics_dict = metrics.to_dict()

                        # Send to Electron for UI display
                        if self._electron_bridge:
                            await self._electron_bridge.send_message({
                                "type": "system_metrics",
                                "metrics": {
                                    "cpu_percent": metrics.cpu.usage_percent,
                                    "memory_percent": metrics.memory.percent_used,
                                    "memory_used_gb": metrics.memory.used_gb,
                                    "memory_total_gb": metrics.memory.total_gb,
                                    "disks": [
                                        {
                                            "mount": d.mount_point,
                                            "percent": d.percent_used,
                                            "free_gb": d.free_gb
                                        }
                                        for d in metrics.disks[:3]  # Top 3 disks
                                    ],
                                    "gpus": [
                                        {
                                            "name": g.name,
                                            "utilization": g.utilization_percent,
                                            "memory_percent": round(g.memory_used_mb / g.memory_total_mb * 100, 1) if g.memory_total_mb > 0 else 0,
                                            "temp": g.temperature_c
                                        }
                                        for g in (metrics.gpus or [])
                                    ] if metrics.gpus else None
                                }
                            })

                        # Send full metrics to backend (less frequently)
                        if self._backend_client and self._backend_client.is_connected:
                            await self._backend_client.send_event("metrics", metrics_dict)

            except Exception as e:
                logger.error(f"Metrics error: {e}")

            await asyncio.sleep(60)  # Full metrics every 60 seconds

    async def _on_activity_update(self, activity: dict):
        """Called when activity metrics are updated."""
        # Forward to Electron for UI updates
        if self._electron_bridge:
            await self._electron_bridge.send_message({
                "type": "activity_update",
                "activity": activity
            })

    def _on_voice_state_change(self, state: str):
        """Called when voice bridge state changes."""
        self._voice_state = state
        # Forward to Electron for tray icon updates
        if self._electron_bridge:
            asyncio.create_task(self._electron_bridge.send_message({
                "type": "voice_state",
                "state": state
            }))

    def _on_voice_transcript(self, user_text: str, sara_text: str):
        """Called when voice transcript is received."""
        # Forward to Electron for display
        if self._electron_bridge:
            asyncio.create_task(self._electron_bridge.send_message({
                "type": "voice_transcript",
                "user": user_text,
                "sara": sara_text
            }))

    def _on_audio_playback_change(self, state):
        """Called when audio playback state changes."""
        self._last_playback_state = state.is_playing
        logger.info(f"Audio playback {'started' if state.is_playing else 'stopped'}: {state.applications}")

        # Forward to Electron for UI
        if self._electron_bridge:
            asyncio.create_task(self._electron_bridge.send_message({
                "type": "audio_playback",
                "is_playing": state.is_playing,
                "applications": state.applications
            }))

    async def _audio_playback_report_loop(self):
        """Periodically report audio playback state to backend."""
        import httpx

        await asyncio.sleep(5)  # Wait for startup

        while self.running:
            try:
                if self._audio_playback_detector:
                    state = self._audio_playback_detector.state

                    # Send to backend
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        apps = ",".join(state.applications) if state.applications else ""
                        await client.post(
                            f"{config.backend_url}/api/sensory/audio-playback",
                            params={
                                "is_playing": state.is_playing,
                                "volume_level": state.volume_level,
                                "applications": apps
                            }
                        )

            except Exception as e:
                logger.debug(f"Audio playback report error: {e}")

            await asyncio.sleep(5)  # Report every 5 seconds

    async def _handle_electron_message(self, data: dict):
        """Handle messages from Electron via the bridge."""
        msg_type = data.get("type")
        logger.info(f"Received Electron message: {msg_type}")

        if msg_type == "auth_token_update":
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
        cmd_type = command.get("command_type") or command.get("command")  # Support both keys
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

        elif cmd_type == "open_workspace":
            # Open the workbench-canvas workspace in browser
            url = payload.get("url", "http://10.185.1.180:3002")
            import webbrowser
            webbrowser.open(url)
            logger.info(f"Opened workspace: {url}")

        elif cmd_type == "get_metrics":
            # Return current system metrics
            command_id = command.get("command_id", "unknown")
            if self._metrics_collector:
                try:
                    metrics = self._metrics_collector.collect()
                    if metrics:
                        await self._backend_client.send_command_result(
                            command_id,
                            success=True,
                            result={"metrics": metrics.to_dict()}
                        )
                    else:
                        await self._backend_client.send_command_result(
                            command_id,
                            success=False,
                            error="Failed to collect metrics"
                        )
                except Exception as e:
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error=str(e)
                    )
            else:
                await self._backend_client.send_command_result(
                    command_id,
                    success=False,
                    error="Metrics collector not available (psutil not installed)"
                )

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
