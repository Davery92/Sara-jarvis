"""
Screenshot Capture Service

Captures screenshots at regular intervals and on-demand.
Uploads to backend for storage and optional vision analysis.
"""
import asyncio
import base64
import hashlib
import io
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend_client import BackendClient

logger = logging.getLogger(__name__)


class ScreenshotService:
    """
    Captures and uploads screenshots.

    Features:
    - Interval-based capture (default 30 seconds)
    - Mode-aware capture rates (10s active, 60s ambient)
    - On-demand capture
    - Perceptual hashing to skip unchanged screens
    - Optional vision analysis
    """

    # Mode-aware intervals
    ACTIVE_INTERVAL = 10   # High frequency during active engagement
    AMBIENT_INTERVAL = 60  # Low frequency during ambient monitoring

    def __init__(
        self,
        backend_client: "BackendClient",
        interval: int = 30,
        enabled: bool = True,
        mode_aware: bool = True
    ):
        self.backend_client = backend_client
        self.interval = interval
        self.enabled = enabled
        self.mode_aware = mode_aware

        self._running = False
        self._last_hash: Optional[str] = None
        self._skip_unchanged = True
        self._current_mode: str = "ambient"

    def set_enabled(self, enabled: bool) -> None:
        """Toggle ambient screenshot capture on/off (Settings > Privacy).

        On-demand capture (capture_and_upload, called directly from a
        hotkey/click) is intentionally NOT gated by this — only the
        periodic ambient loop is.
        """
        self.enabled = enabled
        logger.info(f"Screenshot capture {'enabled' if enabled else 'disabled'}")

    async def start(self):
        """Start periodic screenshot capture."""
        logger.info(f"Starting screenshot service (interval: {self.interval}s, mode_aware: {self.mode_aware})")
        self._running = True

        try:
            import mss
            from PIL import Image

            with mss.mss() as sct:
                while self._running:
                    if not self.enabled:
                        await asyncio.sleep(5)
                        continue

                    try:
                        await self._capture_and_upload(sct)
                    except Exception as e:
                        logger.error(f"Screenshot capture error: {e}")

                    # Get mode-aware interval
                    interval = await self._get_capture_interval()
                    await asyncio.sleep(interval)

        except ImportError as e:
            logger.error(f"Screenshot dependencies not installed: {e}")
            logger.error("Install with: pip install mss Pillow")
        except Exception as e:
            logger.exception(f"Screenshot service error: {e}")

    async def stop(self):
        """Stop screenshot capture."""
        logger.info("Stopping screenshot service")
        self._running = False

    async def capture_and_upload(
        self,
        analyze: bool = False,
        analyze_prompt: Optional[str] = None
    ) -> Optional[dict]:
        """Capture and upload a screenshot on-demand.

        Returns {"screenshot_id", "analysis"} (or None on failure) so callers
        that need it in-turn — e.g. the take_screenshot command handler,
        which reports it back via command_result for DeviceTakeScreenshotTool
        to answer in the same chat turn (A5) — can use it directly instead
        of polling. `analysis` is the VLM's answer when analyze=True was
        passed (upload_screenshot runs it synchronously server-side).
        """
        try:
            import mss

            with mss.mss() as sct:
                return await self._capture_and_upload(
                    sct,
                    force=True,
                    analyze=analyze,
                    analyze_prompt=analyze_prompt
                )

        except Exception as e:
            logger.error(f"On-demand screenshot error: {e}")
            return None

    def _select_monitor(self, sct, window_rect: Optional[tuple]):
        """Pick the monitor containing the foreground window's center point,
        falling back to the primary monitor when we don't have a rect
        (macOS/Linux today) or it doesn't land on any known monitor."""
        monitors = sct.monitors[1:]  # index 0 is the "all monitors" virtual bbox
        if not window_rect or not monitors:
            return sct.monitors[1]

        left, top, right, bottom = window_rect
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2

        for m in monitors:
            if m["left"] <= center_x < m["left"] + m["width"] and m["top"] <= center_y < m["top"] + m["height"]:
                return m
        return sct.monitors[1]

    async def _capture_and_upload(
        self,
        sct,
        force: bool = False,
        analyze: bool = False,
        analyze_prompt: Optional[str] = None
    ) -> Optional[dict]:
        """Internal capture and upload method."""
        from PIL import Image

        window_title, app_name, window_rect = self._get_active_window_info()
        monitor = self._select_monitor(sct, window_rect)
        screenshot = sct.grab(monitor)

        # Convert to PIL Image
        img = Image.frombytes(
            "RGB",
            (screenshot.width, screenshot.height),
            screenshot.rgb
        )

        # Calculate hash
        img_hash = self._calculate_hash(img)

        # Skip if unchanged (unless forced)
        if not force and self._skip_unchanged:
            if img_hash == self._last_hash:
                logger.debug("Screenshot unchanged, skipping upload")
                return None

        self._last_hash = img_hash

        # Compress to JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80, optimize=True)
        buffer.seek(0)
        image_data = buffer.read()

        # Upload to backend
        if self.backend_client:
            try:
                result = await self.backend_client.upload_screenshot(
                    image_data=image_data,
                    window_title=window_title,
                    app_name=app_name,
                    analyze=analyze,
                    analyze_prompt=analyze_prompt
                )
                screenshot_id = result.get('screenshot_id', 'unknown')
                logger.info(f"Screenshot uploaded: {screenshot_id}")

                # Send to raw buffer for cognitive architecture
                await self._send_to_raw_buffer(
                    active_app=app_name,
                    window_title=window_title,
                    screenshot_ref=screenshot_id
                )
                return {"screenshot_id": screenshot_id, "analysis": result.get("analysis")}

            except Exception as e:
                logger.error(f"Screenshot upload failed: {e}")
                return None
        return None

    def _calculate_hash(self, img) -> str:
        """Calculate a perceptual hash of the image."""
        # Simple approach: resize to small size and hash
        small = img.resize((16, 16)).convert("L")
        pixels = list(small.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p > avg else "0" for p in pixels)
        return hashlib.md5(bits.encode()).hexdigest()

    def _get_active_window_info(self) -> tuple:
        """Get current active window title, app name, and screen rect
        (left, top, right, bottom) when available — the rect is what lets
        _select_monitor() capture the display the user is actually looking
        at instead of always the primary one."""
        import platform

        window_title = None
        app_name = None
        window_rect = None

        try:
            system = platform.system()

            if system == "Windows":
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                length = user32.GetWindowTextLengthW(hwnd) + 1
                buffer = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(hwnd, buffer, length)
                window_title = buffer.value

                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    window_rect = (rect.left, rect.top, rect.right, rect.bottom)

            elif system == "Darwin":
                import subprocess
                result = subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to get name of first application process whose frontmost is true'],
                    capture_output=True, text=True, timeout=1
                )
                if result.returncode == 0:
                    app_name = result.stdout.strip()

            elif system == "Linux":
                import subprocess
                result = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=1
                )
                if result.returncode == 0:
                    window_title = result.stdout.strip()

        except Exception as e:
            logger.debug(f"Could not get window info: {e}")

        return window_title, app_name, window_rect

    def set_interval(self, interval: int):
        """Update screenshot interval."""
        self.interval = interval
        logger.info(f"Screenshot interval updated to {interval}s")

    async def _get_capture_interval(self) -> int:
        """
        Get the capture interval based on current mode.

        Queries the backend for the current mode and returns
        appropriate interval (10s active, 60s ambient).
        Falls back to default interval if mode query fails.
        """
        if not self.mode_aware:
            return self.interval

        if not self.backend_client or not self.backend_client.config:
            return self.interval

        config = self.backend_client.config
        if not config.auth_token:
            return self.interval

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{config.backend_url}/api/cognitive/mode",
                    headers={"Authorization": f"Bearer {config.auth_token}"}
                )
                response.raise_for_status()
                data = response.json()
                mode = data.get("mode", "ambient")

                # Log mode changes
                if mode != self._current_mode:
                    logger.info(f"Mode changed: {self._current_mode} -> {mode}")
                    self._current_mode = mode

                # Return interval based on mode
                if mode == "active":
                    return self.ACTIVE_INTERVAL
                else:
                    return self.AMBIENT_INTERVAL

        except ImportError:
            return self.interval
        except Exception as e:
            logger.debug(f"Could not query mode, using default interval: {e}")
            return self.interval

    async def _send_to_raw_buffer(
        self,
        active_app: str = None,
        window_title: str = None,
        screenshot_ref: str = None
    ):
        """
        Send screen capture metadata to Sara's cognitive raw buffer.

        This bridges screen captures to the Phase 1+ cognitive architecture
        so Sara can maintain awareness of screen context.
        """
        if not self.backend_client or not self.backend_client.config:
            return

        config = self.backend_client.config
        if not config.auth_token:
            return

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{config.backend_url}/api/cognitive/raw-buffer/screen",
                    json={
                        "active_app": active_app,
                        "window_title": window_title,
                        "screenshot_ref": screenshot_ref,
                        "source": "screenshot_service"
                    },
                    headers={"Authorization": f"Bearer {config.auth_token}"}
                )
                response.raise_for_status()
                logger.debug("Screen capture metadata sent to raw buffer")

        except ImportError:
            logger.debug("httpx not available for raw buffer bridge")
        except Exception as e:
            # Don't fail screenshot service if raw buffer is unavailable
            logger.debug(f"Could not send screen capture to raw buffer: {e}")
