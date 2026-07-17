#!/usr/bin/env python3
"""Home Assistant Websocket Listener

Standalone worker that maintains a persistent connection to Home Assistant
and logs state changes to the database.

Usage:
    python -m app.workers.ha_listener

Or as systemd service (see sara-ha-listener.service)
"""
import asyncio
import logging
import os
import signal
import sys

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.ha_websocket_service import HAWebsocketService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/david/jarvis/logs/ha_listener.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration from environment
HA_HOST = os.getenv('HA_HOST', '10.185.1.61')
HA_PORT = int(os.getenv('HA_PORT', '8123'))
HA_TOKEN = os.getenv('HA_TOKEN', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODhkZGQ0ZWVlOWI0ODNjOTIwMTU1YTA0ZTM3YTk0NCIsImlhdCI6MTc2NTU2OTczNiwiZXhwIjoyMDgwOTI5NzM2fQ.oLO_hR-RzJFP-TsrKWEteDZbUReVEUdtENIeMAE5Teg')
DATABASE_URL = os.getenv('DATABASE_URL')


async def main():
    """Main entry point."""
    logger.info(f"Starting Home Assistant listener for {HA_HOST}:{HA_PORT}")

    # Connect the event bus so HA events reach the reactive engine
    try:
        from app.services.event_bus import event_bus
        await event_bus.connect()
        logger.info("Event bus connected for HA event bridging")
    except Exception as e:
        logger.warning(f"Event bus connection failed (reactive features degraded): {e}")

    service = HAWebsocketService(
        ha_host=HA_HOST,
        ha_token=HA_TOKEN,
        ha_port=HA_PORT,
        database_url=DATABASE_URL
    )

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Run service with shutdown handling
    service_task = asyncio.create_task(service.start())

    try:
        await shutdown_event.wait()
    finally:
        await service.stop()
        # Disconnect event bus
        try:
            from app.services.event_bus import event_bus
            await event_bus.disconnect()
        except Exception:
            pass
        service_task.cancel()
        try:
            await service_task
        except asyncio.CancelledError:
            pass

    logger.info("Home Assistant listener stopped")


if __name__ == '__main__':
    asyncio.run(main())
