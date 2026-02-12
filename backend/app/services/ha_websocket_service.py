"""Home Assistant Websocket Service

Maintains persistent connection to HA, subscribes to state_changed events,
and logs activity to the database for pattern detection.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Set
import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class HAWebsocketService:
    """Manages persistent websocket connection to Home Assistant."""

    # Default domains to track
    DEFAULT_INCLUDE_DOMAINS = {
        'light', 'switch', 'lock', 'cover', 'climate',
        'binary_sensor', 'input_boolean', 'fan', 'media_player'
    }

    # Entities to always exclude (noisy sensors)
    DEFAULT_EXCLUDE_PATTERNS = {
        'sensor.cpu', 'sensor.memory', 'sensor.disk',
        'sensor.battery', 'sensor.uptime', 'sensor.last_boot',
        'update.', 'sensor.sun_', 'weather.'
    }

    def __init__(
        self,
        ha_host: str,
        ha_token: str,
        database_url: str,
        ha_port: int = 8123,
        include_domains: Optional[Set[str]] = None,
        exclude_patterns: Optional[Set[str]] = None,
        require_state_change: bool = True
    ):
        self.ha_host = ha_host
        self.ha_port = ha_port
        self.ha_token = ha_token
        self.ws_url = f"ws://{ha_host}:{ha_port}/api/websocket"

        # Convert psycopg URL to asyncpg for async operations
        if 'psycopg' in database_url:
            database_url = database_url.replace('psycopg', 'asyncpg').replace('+asyncpg', '+asyncpg')
        elif 'postgresql://' in database_url and 'asyncpg' not in database_url:
            database_url = database_url.replace('postgresql://', 'postgresql+asyncpg://')

        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        self.include_domains = include_domains or self.DEFAULT_INCLUDE_DOMAINS
        self.exclude_patterns = exclude_patterns or self.DEFAULT_EXCLUDE_PATTERNS
        self.require_state_change = require_state_change

        self._message_id = 0
        self._running = False
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None

    def _next_message_id(self) -> int:
        self._message_id += 1
        return self._message_id

    def _should_log_entity(self, entity_id: str) -> bool:
        """Check if entity should be logged based on filters."""
        domain = entity_id.split('.')[0]

        # Check domain inclusion
        if domain not in self.include_domains:
            return False

        # Check exclusion patterns
        for pattern in self.exclude_patterns:
            if entity_id.startswith(pattern) or pattern in entity_id:
                return False

        return True

    async def _authenticate(self) -> bool:
        """Authenticate with Home Assistant."""
        if not self._ws:
            return False

        # Wait for auth_required message
        msg = await self._ws.receive_json()
        if msg.get('type') != 'auth_required':
            logger.error(f"Expected auth_required, got: {msg.get('type')}")
            return False

        # Send authentication
        await self._ws.send_json({
            'type': 'auth',
            'access_token': self.ha_token
        })

        # Wait for auth response
        msg = await self._ws.receive_json()
        if msg.get('type') == 'auth_ok':
            logger.info("Successfully authenticated with Home Assistant")
            return True
        else:
            logger.error(f"Authentication failed: {msg}")
            return False

    async def _subscribe_events(self) -> bool:
        """Subscribe to state_changed events."""
        if not self._ws:
            return False

        msg_id = self._next_message_id()
        await self._ws.send_json({
            'id': msg_id,
            'type': 'subscribe_events',
            'event_type': 'state_changed'
        })

        msg = await self._ws.receive_json()
        if msg.get('success'):
            logger.info("Subscribed to state_changed events")
            return True
        else:
            logger.error(f"Failed to subscribe: {msg}")
            return False

    async def _handle_state_change(self, event_data: dict):
        """Process and log a state change event."""
        data = event_data.get('data', {})
        entity_id = data.get('entity_id', '')

        if not self._should_log_entity(entity_id):
            return

        old_state = data.get('old_state', {})
        new_state = data.get('new_state', {})

        if not new_state:
            return  # Entity removed

        from_state = old_state.get('state') if old_state else None
        to_state = new_state.get('state')

        # Skip if state didn't actually change (just attribute update)
        if self.require_state_change and from_state == to_state:
            return

        # Extract metadata
        domain = entity_id.split('.')[0]
        friendly_name = new_state.get('attributes', {}).get('friendly_name', entity_id)
        changed_at = datetime.fromisoformat(
            new_state.get('last_changed', datetime.utcnow().isoformat()).replace('Z', '+00:00')
        )

        # Build context
        context = {
            'day_of_week': changed_at.strftime('%A'),
            'hour': changed_at.hour,
            'minute': changed_at.minute,
            'is_weekend': changed_at.weekday() >= 5
        }

        # Get relevant attributes (skip bloated ones)
        attributes = {}
        skip_attrs = {'entity_picture', 'icon', 'supported_features', 'attribution'}
        for k, v in new_state.get('attributes', {}).items():
            if k not in skip_attrs and not k.startswith('_'):
                attributes[k] = v

        await self._log_activity(
            entity_id=entity_id,
            friendly_name=friendly_name,
            domain=domain,
            from_state=from_state,
            to_state=to_state,
            changed_at=changed_at,
            context=context,
            attributes=attributes
        )

        # Bridge to cognitive raw buffer for Phase 1+ architecture
        try:
            from app.tasks.input_processing import process_environmental
            process_environmental.delay(
                entity_id=entity_id,
                old_state=from_state,
                new_state=to_state,
                attributes=attributes
            )
        except Exception as e:
            logger.debug(f"Could not send to raw buffer: {e}")

        # Bridge to reactive engine (event bus + activity state machine)
        try:
            from app.services.ha_reactive_bridge import bridge_ha_event
            await bridge_ha_event(
                entity_id=entity_id,
                domain=domain,
                from_state=from_state,
                to_state=to_state,
                attributes=attributes,
                changed_at=changed_at,
            )
        except Exception as e:
            logger.debug(f"Reactive bridge failed: {e}")

        logger.debug(f"Logged: {entity_id} {from_state} -> {to_state}")

    async def _log_activity(
        self,
        entity_id: str,
        friendly_name: str,
        domain: str,
        from_state: Optional[str],
        to_state: str,
        changed_at: datetime,
        context: dict,
        attributes: dict
    ):
        """Write activity to database."""
        async with self.async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO home_activity_log
                    (entity_id, friendly_name, domain, from_state, to_state, changed_at, context, attributes)
                    VALUES (:entity_id, :friendly_name, :domain, :from_state, :to_state, :changed_at, :context, :attributes)
                """),
                {
                    'entity_id': entity_id,
                    'friendly_name': friendly_name,
                    'domain': domain,
                    'from_state': from_state,
                    'to_state': to_state,
                    'changed_at': changed_at,
                    'context': json.dumps(context),
                    'attributes': json.dumps(attributes)
                }
            )
            await session.commit()

    async def _connection_loop(self):
        """Main connection loop with reconnection logic."""
        backoff = 1
        max_backoff = 60

        while self._running:
            try:
                logger.info(f"Connecting to {self.ws_url}")

                self._session = aiohttp.ClientSession()
                self._ws = await self._session.ws_connect(
                    self.ws_url,
                    heartbeat=30,
                    receive_timeout=60
                )

                if not await self._authenticate():
                    raise Exception("Authentication failed")

                if not await self._subscribe_events():
                    raise Exception("Subscription failed")

                backoff = 1  # Reset backoff on successful connection
                logger.info("Connected and listening for events")

                # Event loop
                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get('type') == 'event':
                            event = data.get('event', {})
                            if event.get('event_type') == 'state_changed':
                                await self._handle_state_change(event)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"Websocket error: {self._ws.exception()}")
                        break
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.warning("Websocket closed")
                        break

            except asyncio.CancelledError:
                logger.info("Connection loop cancelled")
                break
            except Exception as e:
                logger.error(f"Connection error: {e}")
            finally:
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                if self._session:
                    await self._session.close()
                self._ws = None
                self._session = None

            if self._running:
                logger.info(f"Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def start(self):
        """Start the websocket listener."""
        self._running = True
        await self._connection_loop()

    async def stop(self):
        """Stop the websocket listener."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
        await self.engine.dispose()
        logger.info("HA Websocket service stopped")
