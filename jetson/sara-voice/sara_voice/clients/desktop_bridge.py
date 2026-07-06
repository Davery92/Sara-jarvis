"""WebSocket server for desktop audio bridge.

Serves as the communication hub between the Jetson voice agent and
the desktop sidecar. Handles:
- Sending TTS audio chunks to desktop for playback
- Receiving playback state (echo state) from desktop
- Sending conversation events (start/end/barge-in)
- Receiving stop_playback commands for barge-in
"""

import asyncio
import json
import logging
import time

import numpy as np

logger = logging.getLogger(__name__)


class DesktopBridge:
    """WebSocket server bridging Jetson to desktop sidecar."""

    def __init__(self, config: dict):
        bridge_cfg = config.get("desktop_bridge", {})
        self._host = bridge_cfg.get("host", "0.0.0.0")
        self._port = bridge_cfg.get("port", 8765)
        self._reconnect_interval = bridge_cfg.get("reconnect_interval_seconds", 5)

        audio_cfg = bridge_cfg.get("audio_format", {})
        self._sample_rate = audio_cfg.get("sample_rate", 24000)
        self._channels = audio_cfg.get("channels", 1)
        self._dtype = audio_cfg.get("dtype", "int16")

        self._server = None
        self._clients: set = set()
        self._running = False

        # State
        self._desktop_playing = False
        self._last_echo_report: float = 0
        self._listening_enabled = True

        # Callbacks
        self._on_playback_complete: list[asyncio.Future] = []
        self._on_barge_in_callback = None
        self._on_echo_state_callback = None
        self._on_listening_change_callback = None
        self._on_request_stop_callback = None
        self._on_media_state_callback = None
        self._on_speak_proactive_callback = None

    async def start(self):
        """Start the WebSocket server."""
        import websockets

        self._running = True
        self._server = await websockets.serve(
            self._handle_client,
            self._host,
            self._port,
        )
        logger.info("Desktop bridge WebSocket server started on %s:%d", self._host, self._port)

    async def _handle_client(self, websocket, path=None):
        """Handle a connected desktop client."""
        self._clients.add(websocket)
        client_addr = websocket.remote_address
        logger.info("Desktop client connected: %s", client_addr)
        await self._send_listening_status(websocket)

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except Exception as e:
            logger.debug("Desktop client disconnected: %s (%s)", client_addr, e)
        finally:
            self._clients.discard(websocket)
            logger.info("Desktop client removed: %s", client_addr)

    async def _handle_message(self, websocket, message: str | bytes):
        """Process incoming message from desktop."""
        if isinstance(message, bytes):
            return  # Ignore binary messages from desktop

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Invalid JSON from desktop: %s", message[:100])
            return

        event_type = data.get("event", data.get("type", ""))

        if event_type == "playback_complete":
            logger.debug("Desktop: playback complete")
            self._desktop_playing = False
            # Resolve waiting futures
            for fut in self._on_playback_complete:
                if not fut.done():
                    fut.set_result(True)
            self._on_playback_complete.clear()
            if self._on_echo_state_callback:
                await self._on_echo_state_callback(False)

        elif event_type == "echo_state":
            is_playing = data.get("is_playing", False)
            self._desktop_playing = is_playing
            if self._on_echo_state_callback:
                await self._on_echo_state_callback(is_playing)

        elif event_type == "stop_confirmed":
            logger.debug("Desktop: stop confirmed")
            self._desktop_playing = False

        elif event_type == "set_listening":
            enabled = bool(data.get("enabled", True))
            if enabled != self._listening_enabled:
                self._listening_enabled = enabled
                logger.info("Desktop listening set to %s", enabled)
                if self._on_listening_change_callback:
                    await self._on_listening_change_callback(enabled)
            await self._broadcast_listening_status()

        elif event_type == "get_status":
            await self._send_listening_status(websocket)

        elif event_type == "request_stop":
            # Backend-relayed CANCEL_SPEECH (A1 desktop hotkey / webapp+iOS
            # mute — Desktop Jarvis Overhaul B2.6). Distinct from
            # "stop_confirmed" (Jetson->desktop ack) — this is inbound.
            logger.info("Remote stop requested")
            if self._on_request_stop_callback:
                await self._on_request_stop_callback()

        elif event_type == "media_state":
            # Backend-relayed desktop media_state (B2.4).
            playing = bool(data.get("playing", False))
            if self._on_media_state_callback:
                await self._on_media_state_callback(playing)

        elif event_type == "speak_proactive":
            # Backend-relayed proactive delivery (Desktop Jarvis Overhaul D)
            # — a spoken one-liner David didn't ask for. Only actually
            # speaks if the Jetson is idle; service.py's callback is
            # responsible for declining while mid-conversation so this
            # never talks over David or Sara.
            text = data.get("text", "")
            if text and self._on_speak_proactive_callback:
                await self._on_speak_proactive_callback(text)

        else:
            logger.debug("Desktop event: %s", event_type)

    async def send_audio(self, audio: np.ndarray):
        """Send PCM audio chunk to desktop for playback."""
        if not self._clients:
            logger.debug("No desktop clients connected, dropping audio")
            return

        # Send as binary (int16 PCM bytes)
        audio_bytes = audio.astype(np.int16).tobytes()

        # Send bare PCM bytes for compatibility with desktop sidecar voice_bridge.py
        disconnected = set()
        for ws in self._clients:
            try:
                await ws.send(audio_bytes)
            except Exception:
                disconnected.add(ws)

        self._clients -= disconnected
        self._desktop_playing = True

    async def _send_listening_status(self, websocket):
        """Reply to a client with current listening status."""
        try:
            await websocket.send(json.dumps({
                "type": "listening_status",
                "enabled": self._listening_enabled,
            }))
        except Exception:
            pass

    async def _broadcast_listening_status(self):
        """Broadcast listening status to all connected clients."""
        disconnected = set()
        message = json.dumps({
            "type": "listening_status",
            "enabled": self._listening_enabled,
        })
        for ws in self._clients:
            try:
                await ws.send(message)
            except Exception:
                disconnected.add(ws)
        self._clients -= disconnected

    async def send_event(self, event: dict):
        """Send a JSON event to all connected desktop clients."""
        message = json.dumps(event)
        disconnected = set()
        for ws in self._clients:
            try:
                await ws.send(message)
            except Exception:
                disconnected.add(ws)
        self._clients -= disconnected

    async def send_conversation_start(self):
        """Notify desktop that a voice conversation has started."""
        await self.send_event({"event": "conversation_start", "timestamp": time.time()})

    async def send_conversation_end(self, summary: str = ""):
        """Notify desktop that a voice conversation has ended."""
        await self.send_event({
            "event": "conversation_end",
            "summary": summary,
            "timestamp": time.time(),
        })

    async def send_stop_playback(self):
        """Tell desktop to immediately stop audio playback (barge-in)."""
        await self.send_event({"event": "stop_playback"})
        self._desktop_playing = False

    async def wait_for_playback_complete(self, timeout: float = 60.0) -> bool:
        """Wait for desktop to report playback complete."""
        if not self._clients:
            return True  # No clients, nothing to wait for
        if not self._desktop_playing:
            # Playback already completed before we started waiting.
            return True

        fut = asyncio.get_event_loop().create_future()
        self._on_playback_complete.append(fut)
        try:
            await asyncio.wait_for(fut, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("Playback complete timeout after %.1fs", timeout)
            return False

    def set_echo_state_callback(self, callback):
        """Set callback for echo state changes: async def callback(is_playing: bool)."""
        self._on_echo_state_callback = callback

    def set_barge_in_callback(self, callback):
        """Set callback for barge-in events."""
        self._on_barge_in_callback = callback

    def set_request_stop_callback(self, callback):
        """Set callback for a backend-relayed CANCEL_SPEECH request: async def callback()."""
        self._on_request_stop_callback = callback

    def set_media_state_callback(self, callback):
        """Set callback for a backend-relayed media_state change: async def callback(playing: bool)."""
        self._on_media_state_callback = callback

    def set_speak_proactive_callback(self, callback):
        """Set callback for a backend-relayed proactive speak request: async def callback(text: str)."""
        self._on_speak_proactive_callback = callback

    def set_listening_change_callback(self, callback):
        """Set callback for listening on/off changes from desktop controls."""
        self._on_listening_change_callback = callback

    async def stop(self):
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Close all client connections
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        logger.info("Desktop bridge stopped")

    @property
    def is_connected(self) -> bool:
        return len(self._clients) > 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def is_desktop_playing(self) -> bool:
        return self._desktop_playing

    @property
    def is_listening_enabled(self) -> bool:
        return self._listening_enabled
