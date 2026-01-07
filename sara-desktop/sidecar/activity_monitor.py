"""
Activity Monitor

Tracks keyboard, mouse, and active window to determine user activity level.
Reports activity metrics for determining the "active device".
"""
import asyncio
import logging
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ActivityMetrics:
    """Current activity metrics."""
    keyboard_events: int = 0
    mouse_events: int = 0
    mouse_distance: float = 0.0
    active_window: Optional[str] = None
    active_app: Optional[str] = None
    last_activity_at: float = field(default_factory=time.time)

    def reset_counts(self):
        """Reset event counts (called after reporting)."""
        self.keyboard_events = 0
        self.mouse_events = 0
        self.mouse_distance = 0.0


class ActivityMonitor:
    """
    Monitors user activity (keyboard, mouse, active window).

    Uses pynput for input monitoring and platform-specific
    APIs for active window detection.
    """

    def __init__(
        self,
        on_activity_update: Optional[Callable] = None,
        report_interval: float = 5.0,
        idle_threshold: float = 60.0
    ):
        self.on_activity_update = on_activity_update
        self.report_interval = report_interval
        self.idle_threshold = idle_threshold

        self._running = False
        self._metrics = ActivityMetrics()
        self._keyboard_listener = None
        self._mouse_listener = None
        self._last_mouse_pos = None

    async def start(self):
        """Start activity monitoring."""
        logger.info("Starting activity monitor...")
        self._running = True

        try:
            from pynput import keyboard, mouse

            # Keyboard listener
            def on_key_press(key):
                self._metrics.keyboard_events += 1
                self._metrics.last_activity_at = time.time()

            self._keyboard_listener = keyboard.Listener(on_press=on_key_press)
            self._keyboard_listener.start()

            # Mouse listener
            def on_mouse_move(x, y):
                self._metrics.mouse_events += 1
                self._metrics.last_activity_at = time.time()

                if self._last_mouse_pos:
                    dx = x - self._last_mouse_pos[0]
                    dy = y - self._last_mouse_pos[1]
                    self._metrics.mouse_distance += (dx**2 + dy**2) ** 0.5
                self._last_mouse_pos = (x, y)

            def on_mouse_click(x, y, button, pressed):
                if pressed:
                    self._metrics.mouse_events += 1
                    self._metrics.last_activity_at = time.time()

            self._mouse_listener = mouse.Listener(
                on_move=on_mouse_move,
                on_click=on_mouse_click
            )
            self._mouse_listener.start()

            logger.info("Input listeners started")

            # Periodic reporting loop
            await self._report_loop()

        except ImportError as e:
            logger.error(f"pynput not installed: {e}")
            logger.error("Install with: pip install pynput")
        except Exception as e:
            logger.exception(f"Error starting activity monitor: {e}")

    async def stop(self):
        """Stop activity monitoring."""
        logger.info("Stopping activity monitor...")
        self._running = False

        if self._keyboard_listener:
            self._keyboard_listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()

    async def _report_loop(self):
        """Periodically report activity metrics."""
        while self._running:
            try:
                # Update active window
                self._update_active_window()

                # Get activity summary
                activity = self.get_activity_summary()

                # Call callback
                if self.on_activity_update:
                    if asyncio.iscoroutinefunction(self.on_activity_update):
                        await self.on_activity_update(activity)
                    else:
                        self.on_activity_update(activity)

                # Reset counts for next interval
                self._metrics.reset_counts()

            except Exception as e:
                logger.error(f"Activity report error: {e}")

            await asyncio.sleep(self.report_interval)

    def _update_active_window(self):
        """Get the currently active window title and app name."""
        try:
            system = platform.system()

            if system == "Windows":
                self._update_active_window_windows()
            elif system == "Darwin":
                self._update_active_window_macos()
            elif system == "Linux":
                self._update_active_window_linux()

        except Exception as e:
            logger.debug(f"Could not get active window: {e}")

    def _update_active_window_windows(self):
        """Get active window on Windows."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # Get foreground window
            hwnd = user32.GetForegroundWindow()

            # Get window title
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buffer = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buffer, length)
            self._metrics.active_window = buffer.value

            # Get process name
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # Get process name from PID
            import psutil
            try:
                process = psutil.Process(pid.value)
                self._metrics.active_app = process.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        except Exception as e:
            logger.debug(f"Windows active window error: {e}")

    def _update_active_window_macos(self):
        """Get active window on macOS."""
        try:
            import subprocess

            # Get frontmost application
            script = '''
            tell application "System Events"
                set frontApp to name of first application process whose frontmost is true
            end tell
            return frontApp
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                self._metrics.active_app = result.stdout.strip()

            # Get window title
            script = '''
            tell application "System Events"
                tell (first application process whose frontmost is true)
                    if exists window 1 then
                        return name of window 1
                    end if
                end tell
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                self._metrics.active_window = result.stdout.strip()

        except Exception as e:
            logger.debug(f"macOS active window error: {e}")

    def _update_active_window_linux(self):
        """Get active window on Linux (X11)."""
        try:
            import subprocess

            # Get active window ID
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                self._metrics.active_window = result.stdout.strip()

            # Get window class (app name)
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowclassname"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                self._metrics.active_app = result.stdout.strip()

        except Exception as e:
            logger.debug(f"Linux active window error: {e}")

    def get_activity_level(self) -> str:
        """
        Determine activity level based on recent metrics.

        Returns: "idle", "low", "medium", or "high"
        """
        idle_seconds = time.time() - self._metrics.last_activity_at

        if idle_seconds > self.idle_threshold:
            return "idle"

        # Activity based on events per report interval
        total_events = self._metrics.keyboard_events + self._metrics.mouse_events

        if total_events == 0:
            return "idle"
        elif total_events < 10:
            return "low"
        elif total_events < 50:
            return "medium"
        else:
            return "high"

    def get_activity_summary(self) -> dict:
        """Get current activity summary for reporting."""
        return {
            "activity_level": self.get_activity_level(),
            "keyboard_events": self._metrics.keyboard_events,
            "mouse_events": self._metrics.mouse_events,
            "mouse_distance": round(self._metrics.mouse_distance, 2),
            "active_window": self._metrics.active_window,
            "active_app": self._metrics.active_app,
            "idle_seconds": round(time.time() - self._metrics.last_activity_at, 1),
            "timestamp": datetime.utcnow().isoformat()
        }
