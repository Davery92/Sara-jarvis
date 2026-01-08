"""
Electron Bridge

Local WebSocket server for communication between the Python sidecar
and the Electron app.
"""
import asyncio
import json
import logging
from typing import Set, Optional, Callable

logger = logging.getLogger(__name__)


class ElectronBridge:
    """
    Local WebSocket server for Electron communication.

    The Electron app connects to this server to receive:
    - Wake word detection events
    - Commands from other devices
    - Activity updates

    And can send:
    - Auth token updates
    - Configuration changes
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9876,
        on_message: Optional[Callable] = None
    ):
        self.host = host
        self.port = port
        self.on_message = on_message

        self._server = None
        self._clients: Set = set()
        self._running = False

    async def start(self):
        """Start the WebSocket server."""
        try:
            import websockets

            self._running = True

            self._server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port
            )

            logger.info(f"Electron bridge listening on ws://{self.host}:{self.port}")

            # Keep server running
            await asyncio.Future()  # Run forever

        except ImportError:
            logger.error("websockets not installed: pip install websockets")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"Port {self.port} already in use, another sidecar may be running")
            else:
                raise
        except Exception as e:
            logger.exception(f"Electron bridge error: {e}")

    async def stop(self):
        """Stop the WebSocket server."""
        logger.info("Stopping Electron bridge")
        self._running = False

        # Close all client connections
        for client in self._clients.copy():
            try:
                await client.close()
            except Exception:
                pass

        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, websocket):
        """Handle a client connection."""
        self._clients.add(websocket)
        logger.info(f"Electron client connected (total: {len(self._clients)})")

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)

        except Exception as e:
            logger.debug(f"Client disconnected: {e}")

        finally:
            self._clients.discard(websocket)
            logger.info(f"Electron client disconnected (total: {len(self._clients)})")

    async def _handle_message(self, websocket, message: str):
        """Handle a message from Electron."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            logger.debug(f"Received from Electron: {msg_type}")

            if msg_type == "auth_token":
                # Electron is providing auth token
                token = data.get("token")
                if token and self.on_message:
                    await self._call_handler({
                        "type": "auth_token_update",
                        "token": token
                    })

            elif msg_type == "config_update":
                # Configuration change from Electron
                if self.on_message:
                    await self._call_handler(data)

            elif msg_type == "take_screenshot":
                # Request screenshot from Electron UI
                if self.on_message:
                    await self._call_handler({
                        "type": "screenshot_request",
                        "analyze": data.get("analyze", False),
                        "analyze_prompt": data.get("analyze_prompt")
                    })

            elif msg_type == "ping":
                # Health check
                await websocket.send(json.dumps({"type": "pong"}))

            else:
                # Forward unknown messages to handler
                if self.on_message:
                    await self._call_handler(data)

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from Electron: {message[:100]}")
        except Exception as e:
            logger.error(f"Message handling error: {e}")

    async def _call_handler(self, data: dict):
        """Call the message handler."""
        if self.on_message:
            if asyncio.iscoroutinefunction(self.on_message):
                await self.on_message(data)
            else:
                self.on_message(data)

    async def send_message(self, message: dict):
        """Send a message to all connected Electron clients."""
        if not self._clients:
            logger.debug("No Electron clients connected")
            return

        message_str = json.dumps(message)
        disconnected = []

        for client in self._clients:
            try:
                await client.send(message_str)
            except Exception as e:
                logger.debug(f"Failed to send to client: {e}")
                disconnected.append(client)

        # Clean up disconnected clients
        for client in disconnected:
            self._clients.discard(client)

    async def broadcast_wake_word(self):
        """Send wake word detection event to Electron."""
        await self.send_message({
            "type": "wake_word_detected",
            "timestamp": asyncio.get_event_loop().time()
        })

    async def show_note(self, note_id: str, title: str, content: str):
        """Tell Electron to show a note overlay."""
        await self.send_message({
            "type": "show_note",
            "note_id": note_id,
            "title": title,
            "content": content
        })

    async def show_timer(self, timer_id: str, label: str, remaining_seconds: int):
        """Tell Electron to show a timer overlay."""
        await self.send_message({
            "type": "show_timer",
            "timer_id": timer_id,
            "label": label,
            "remaining_seconds": remaining_seconds
        })

    async def show_notification(self, title: str, message: str):
        """Tell Electron to show a notification."""
        await self.send_message({
            "type": "show_notification",
            "title": title,
            "message": message
        })

    async def start_listening(self):
        """Tell Electron to start voice recording."""
        await self.send_message({
            "type": "start_listening"
        })

    async def speak(self, text: str):
        """Tell Electron to speak text via TTS."""
        await self.send_message({
            "type": "speak",
            "text": text
        })

    @property
    def client_count(self) -> int:
        """Get number of connected clients."""
        return len(self._clients)

    @property
    def has_clients(self) -> bool:
        """Check if any clients are connected."""
        return len(self._clients) > 0
