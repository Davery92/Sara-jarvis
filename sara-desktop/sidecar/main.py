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
        self._loop = None

        # Component instances (lazy loaded)
        self._activity_monitor = None
        self._screenshot_service = None
        self._backend_client = None
        self._electron_bridge = None
        self._metrics_collector = metrics_collector if PSUTIL_AVAILABLE else None
        self._focus_tracker = None

        # Latest browser-extension context: {url, domain, title, received_at}.
        # Used to enrich focus_span payloads when active_app is a browser.
        self._browser_context: dict = {}

    async def start(self):
        """Start all sidecar services."""
        logger.info("Starting Sara Desktop Sidecar...")
        logger.info(f"Device ID: {config.device_id}")
        logger.info(f"Backend: {config.backend_url}")
        logger.info(f"Python executable: {sys.executable}")
        logger.info(f"Python version: {sys.version.split()[0]}")

        self.running = True
        self._loop = asyncio.get_running_loop()

        # Import and initialize components
        try:
            from activity_monitor import ActivityMonitor
            from screenshot import ScreenshotService
            from backend_client import BackendClient
            from electron_bridge import ElectronBridge
            from focus_tracker import FocusTracker

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

            self._focus_tracker = FocusTracker(
                on_focus_span=self._on_focus_span,
                on_state_change=self._on_activity_state,
                browser_context_provider=self._get_browser_context,
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
            bridge_task = asyncio.create_task(self._electron_bridge.start())
            self._tasks = [bridge_task]
            await asyncio.sleep(0.5)  # Give it time to start listening
            if bridge_task.done():
                exc = bridge_task.exception()
                if exc:
                    raise RuntimeError(f"Electron bridge failed to start: {exc}")
                raise RuntimeError(
                    "Electron bridge exited during startup (port in use). "
                    "Another sidecar instance is likely already running."
                )

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

        # Stop components — flush any in-flight span before activity_monitor
        # quits so we don't lose the last span on graceful shutdown.
        if self._focus_tracker:
            try:
                await self._focus_tracker.flush()
            except Exception as e:
                logger.error(f"focus_tracker flush failed: {e}")
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
        # Feed the focus tracker so it can detect span boundaries and state
        # transitions. The tracker invokes _on_focus_span / _on_activity_state
        # when relevant.
        if self._focus_tracker:
            try:
                await self._focus_tracker.on_tick(activity)
            except Exception as e:
                logger.error(f"focus_tracker tick failed: {e}")

        # Forward to Electron for UI updates
        if self._electron_bridge:
            await self._electron_bridge.send_message({
                "type": "activity_update",
                "activity": activity
            })

    async def _on_focus_span(self, span: dict) -> None:
        """Forward a completed focus span to the backend over the device WS."""
        if self._backend_client:
            try:
                await self._backend_client.send_focus_span(span)
            except Exception as e:
                logger.error(f"send_focus_span failed: {e}")

    async def _on_activity_state(self, state: dict) -> None:
        """Forward a desktop activity-state transition to the backend."""
        if self._backend_client:
            try:
                await self._backend_client.send_activity_state(state)
            except Exception as e:
                logger.error(f"send_activity_state failed: {e}")

    def _get_browser_context(self) -> Optional[dict]:
        """Return the most-recent browser tab context if it's still fresh.

        We treat anything older than 60s as stale — if the extension has
        stopped reporting (browser closed, extension disabled) we'd rather
        drop the URL from focus spans than report whatever was last there.
        """
        ctx = self._browser_context
        if not ctx:
            return None
        import time as _time
        if _time.time() - ctx.get("received_at", 0) > 60:
            return None
        return {k: v for k, v in ctx.items() if k != "received_at"}

    # ── Desktop actuators (invoked by chat-originated tool calls) ────────────

    def _write_clipboard(self, text: str) -> None:
        try:
            import pyperclip
        except ImportError:
            logger.error("write_clipboard: pyperclip not installed")
            return
        try:
            pyperclip.copy(text)
            logger.info(f"Clipboard set ({len(text)} chars)")
        except Exception as e:
            logger.error(f"write_clipboard failed: {e}")

    def _focus_window(self, title_match: str) -> None:
        try:
            import pygetwindow as gw
        except ImportError:
            logger.error("focus_window: pygetwindow not installed")
            return
        try:
            needle = title_match.lower()
            matches = [w for w in gw.getAllWindows() if needle in (w.title or "").lower()]
            if not matches:
                logger.info(f"focus_window: no window matched '{title_match}'")
                return
            target = matches[0]
            try:
                if hasattr(target, "isMinimized") and target.isMinimized:
                    target.restore()
            except Exception:
                pass
            try:
                target.activate()
            except Exception as e:
                # pygetwindow wraps Win32 calls and raises Win32Exception even
                # when GetLastError() == ERROR_SUCCESS (0). Swallow that one
                # false positive but re-raise any real failure.
                if "operation completed successfully" not in str(e).lower():
                    raise
            logger.info(f"Focused window: {target.title}")
        except Exception as e:
            logger.error(f"focus_window failed: {e}")

    def _type_keystrokes(self, text: str) -> bool:
        """Inject keystrokes into whatever currently has focus. Returns True on success."""
        try:
            from pynput.keyboard import Controller, Key
        except ImportError:
            logger.error("type_keystrokes: pynput not installed")
            return False
        try:
            kb = Controller()
            for ch in text:
                if ch == "\n":
                    kb.press(Key.enter)
                    kb.release(Key.enter)
                else:
                    kb.type(ch)
            return True
        except Exception as e:
            logger.error(f"type_keystrokes failed: {e}")
            return False

    def _type_into_window(self, title_match: str, text: str) -> None:
        """Atomically focus a window matching `title_match` and type `text` into it.

        On Windows uses ctypes to do the AttachThreadInput / SetForegroundWindow
        dance that defeats anti-focus-stealing restrictions, then verifies the
        target window actually has foreground before injecting keystrokes.

        On other platforms falls back to a best-effort focus + sleep + type.
        """
        import sys
        if sys.platform == "win32":
            self._type_into_window_windows(title_match, text)
        else:
            self._type_into_window_fallback(title_match, text)

    def _type_into_window_windows(self, title_match: str, text: str) -> None:
        import ctypes
        from ctypes import wintypes
        import time

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Find a top-level visible window whose title contains the needle.
        needle = title_match.lower()
        target_hwnd = ctypes.c_void_p(None)
        target_title = [""]

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if needle in buf.value.lower():
                target_hwnd.value = hwnd
                target_title[0] = buf.value
                return False  # stop enumerating
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)

        if not target_hwnd.value:
            logger.error(f"type_into_window: no window matched '{title_match}'")
            return

        # The classic Windows focus-stealing dance: attach our thread's input
        # queue to the current foreground window's queue, then SetForegroundWindow
        # succeeds. Without this, Windows often returns 0 (success) without
        # actually transferring focus.
        SW_RESTORE = 9
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        our_tid = kernel32.GetCurrentThreadId()

        attached = False
        try:
            if fg_tid and fg_tid != our_tid:
                attached = bool(user32.AttachThreadInput(our_tid, fg_tid, True))

            if user32.IsIconic(target_hwnd.value):
                user32.ShowWindow(target_hwnd.value, SW_RESTORE)
            user32.BringWindowToTop(target_hwnd.value)
            user32.SetForegroundWindow(target_hwnd.value)
        finally:
            if attached:
                user32.AttachThreadInput(our_tid, fg_tid, False)

        # Brief settle so the window manager can finish the transition before
        # we verify foreground and start injecting input.
        time.sleep(0.15)

        new_fg = user32.GetForegroundWindow()
        if new_fg != target_hwnd.value:
            logger.error(
                f"type_into_window: focus transfer to '{target_title[0]}' "
                f"failed (foreground hwnd={new_fg}, target hwnd={target_hwnd.value}); "
                f"refusing to type to avoid leaking keys to the wrong window"
            )
            return

        ok = self._type_keystrokes(text)
        if ok:
            logger.info(f"Typed {len(text)} chars into '{target_title[0]}'")

    def _type_into_window_fallback(self, title_match: str, text: str) -> None:
        import time
        try:
            import pygetwindow as gw
        except ImportError:
            logger.error("type_into_window: pygetwindow not installed")
            return
        try:
            needle = title_match.lower()
            matches = [w for w in gw.getAllWindows() if needle in (w.title or "").lower()]
            if not matches:
                logger.error(f"type_into_window: no window matched '{title_match}'")
                return
            target = matches[0]
            try:
                if hasattr(target, "isMinimized") and target.isMinimized:
                    target.restore()
            except Exception:
                pass
            try:
                target.activate()
            except Exception as e:
                if "operation completed successfully" not in str(e).lower():
                    raise
            time.sleep(0.15)
            ok = self._type_keystrokes(text)
            if ok:
                logger.info(f"Typed {len(text)} chars into '{target.title}'")
        except Exception as e:
            logger.error(f"type_into_window failed: {e}")

    def _schedule_electron_message(self, payload: dict):
        """Send an Electron bridge message from any thread context."""
        bridge = self._electron_bridge
        if not bridge:
            return

        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(bridge.send_message(payload))
            )
            return

        try:
            asyncio.create_task(bridge.send_message(payload))
        except RuntimeError as e:
            logger.debug("Dropping electron message without running loop: %s", e)

    async def _handle_electron_message(self, data: dict):
        """Handle messages from Electron via the bridge."""
        msg_type = data.get("type")
        logger.info(f"Received Electron message: {msg_type}")

        if msg_type == "auth_token_update":
            # Update auth token and force reconnect
            token = data.get("token")
            if token:
                config.auth_token = token
                config.save_settings()
                if self._backend_client:
                    self._backend_client.config.auth_token = token
                    # Force disconnect so the reconnect loop picks up the new token
                    await self._backend_client.disconnect()
                    logger.info("Auth token updated, forcing backend reconnect")

        elif msg_type == "screenshot_request":
            # Take screenshot on demand
            if self._screenshot_service:
                await self._screenshot_service.capture_and_upload(
                    analyze=data.get("analyze", False),
                    analyze_prompt=data.get("analyze_prompt")
                )

        elif msg_type == "browser_context":
            # From the browser extension. Cache the latest active tab so
            # focus_tracker can stitch it into focus_span payloads.
            url = data.get("url")
            if url:
                import time as _time
                self._browser_context = {
                    "url": url,
                    "domain": data.get("domain") or "",
                    "title": data.get("title") or "",
                    "received_at": _time.time(),
                }
                logger.debug(
                    "browser_context: %s — %s",
                    self._browser_context.get("domain"),
                    (self._browser_context.get("title") or "")[:60],
                )

        elif msg_type == "shutdown_sidecar":
            logger.warning("Shutdown requested by Electron, stopping sidecar")
            asyncio.create_task(self.stop())

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
            url = payload.get("url", "https://canvas.avery.cloud")
            import webbrowser
            webbrowser.open(url)
            logger.info(f"Opened workspace: {url}")

        elif cmd_type == "write_clipboard":
            text = payload.get("text")
            if text is None:
                logger.warning("write_clipboard: missing 'text' payload")
            else:
                self._write_clipboard(text)

        elif cmd_type == "focus_window":
            title_match = payload.get("title_match", "")
            if not title_match:
                logger.warning("focus_window: missing 'title_match' payload")
            else:
                self._focus_window(title_match)

        elif cmd_type == "type_into_window":
            title_match = payload.get("title_match", "")
            text = payload.get("text")
            if not title_match or not text:
                logger.warning("type_into_window: missing 'title_match' or 'text'")
            else:
                self._type_into_window(title_match, text)

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
