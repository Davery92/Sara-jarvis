#!/usr/bin/env python3
"""Background worker to execute scheduled home automation actions.

Runs every minute checking for pending actions that are due for execution.

Usage:
    python -m app.workers.scheduled_home_worker

Or as systemd service (see sara-scheduled-home.service)
"""
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.services.ha_control_service import HAControlService
from app.core.timezone import USER_TIMEZONE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/david/jarvis/logs/scheduled_home_worker.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration from environment
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub')
HA_HOST = os.getenv('HA_HOST', '10.185.1.61')
HA_PORT = int(os.getenv('HA_PORT', '8123'))
HA_TOKEN = os.getenv('HA_TOKEN', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODhkZGQ0ZWVlOWI0ODNjOTIwMTU1YTA0ZTM3YTk0NCIsImlhdCI6MTc2NTU2OTczNiwiZXhwIjoyMDgwOTI5NzM2fQ.oLO_hR-RzJFP-TsrKWEteDZbUReVEUdtENIeMAE5Teg')


class ScheduledHomeWorker:
    """Worker that executes scheduled home automation actions."""

    def __init__(self, database_url: str, ha_host: str, ha_port: int, ha_token: str):
        self.running = False
        self.tz = USER_TIMEZONE

        # Create database engine
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        # Create HA control service
        self.ha_control = HAControlService(
            ha_host=ha_host,
            ha_port=ha_port,
            ha_token=ha_token
        )

    async def execute_action(self, action: dict) -> tuple[bool, str]:
        """Execute a scheduled home action."""
        entity_id = action["entity_id"]
        domain = action["domain"]
        action_type = action["action"]
        parameters = action.get("parameters") or {}

        try:
            if domain == "light":
                if action_type == "on":
                    await self.ha_control.turn_on_light(entity_id, **parameters)
                elif action_type == "off":
                    await self.ha_control.turn_off_light(entity_id)
                elif action_type == "toggle":
                    await self.ha_control.toggle_light(entity_id)
                else:
                    return False, f"Unknown light action: {action_type}"

            elif domain == "switch":
                if action_type == "on":
                    await self.ha_control.turn_on_switch(entity_id)
                elif action_type == "off":
                    await self.ha_control.turn_off_switch(entity_id)
                elif action_type == "toggle":
                    await self.ha_control.toggle_switch(entity_id)
                else:
                    return False, f"Unknown switch action: {action_type}"

            elif domain == "climate":
                temp = parameters.get("temperature")
                mode = parameters.get("hvac_mode")
                if temp:
                    await self.ha_control.set_climate_temperature(entity_id, temp, mode)
                elif mode:
                    await self.ha_control.set_climate_mode(entity_id, mode)
                else:
                    return False, "Climate action requires temperature or hvac_mode"

            elif domain == "cover":
                if action_type == "open":
                    await self.ha_control.open_cover(entity_id)
                elif action_type == "close":
                    await self.ha_control.close_cover(entity_id)
                elif "position" in parameters:
                    await self.ha_control.set_cover_position(entity_id, parameters["position"])
                else:
                    return False, f"Unknown cover action: {action_type}"

            elif domain == "lock":
                if action_type == "lock":
                    await self.ha_control.lock(entity_id)
                elif action_type == "unlock":
                    await self.ha_control.unlock(entity_id)
                else:
                    return False, f"Unknown lock action: {action_type}"

            elif domain == "scene":
                await self.ha_control.activate_scene(entity_id)

            elif domain == "media_player":
                if action_type == "play":
                    await self.ha_control.media_play(entity_id)
                elif action_type == "pause":
                    await self.ha_control.media_pause(entity_id)
                elif action_type == "stop":
                    await self.ha_control.media_stop(entity_id)
                elif "volume" in parameters:
                    await self.ha_control.set_volume(entity_id, parameters["volume"])
                else:
                    return False, f"Unknown media action: {action_type}"

            else:
                return False, f"Unknown domain: {domain}"

            return True, "Success"

        except Exception as e:
            logger.error(f"Failed to execute action {action['id']}: {e}")
            return False, str(e)

    async def handle_recurring(self, action: dict):
        """Create next occurrence for recurring actions."""
        pattern = action.get("recurrence_pattern")
        if not pattern:
            return

        scheduled_at = action["scheduled_at"]
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=self.tz)

        # Calculate next occurrence
        if pattern == "daily":
            next_time = scheduled_at + timedelta(days=1)
        elif pattern == "weekly":
            next_time = scheduled_at + timedelta(weeks=1)
        elif pattern == "weekdays":
            next_time = scheduled_at + timedelta(days=1)
            while next_time.weekday() >= 5:  # Skip weekends
                next_time += timedelta(days=1)
        elif pattern == "weekends":
            next_time = scheduled_at + timedelta(days=1)
            while next_time.weekday() < 5:  # Skip weekdays
                next_time += timedelta(days=1)
        else:
            logger.warning(f"Unknown recurrence pattern: {pattern}")
            return

        # Insert next occurrence
        async with self.async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO scheduled_home_action
                    (user_id, entity_id, domain, action, parameters, scheduled_at,
                     description, recurring, recurrence_pattern, status)
                    VALUES (:user_id, :entity_id, :domain, :action, :parameters::jsonb,
                            :scheduled_at, :description, true, :recurrence_pattern, 'pending')
                """),
                {
                    "user_id": action["user_id"],
                    "entity_id": action["entity_id"],
                    "domain": action["domain"],
                    "action": action["action"],
                    "parameters": str(action.get("parameters")) if action.get("parameters") else None,
                    "scheduled_at": next_time,
                    "description": action.get("description"),
                    "recurrence_pattern": pattern
                }
            )
            await session.commit()
            logger.info(f"Created next recurring action for {next_time}")

    async def process_due_actions(self):
        """Find and execute all actions that are due."""
        now = datetime.now(self.tz)

        async with self.async_session() as session:
            # Find pending actions that are due (scheduled time <= now)
            result = await session.execute(
                text("""
                    SELECT id, user_id, entity_id, domain, action, parameters,
                           scheduled_at, description, recurring, recurrence_pattern
                    FROM scheduled_home_action
                    WHERE status = 'pending' AND scheduled_at <= :now
                    ORDER BY scheduled_at ASC
                    LIMIT 10
                """),
                {"now": now}
            )
            actions = result.fetchall()

        if not actions:
            return

        logger.info(f"Found {len(actions)} actions to execute")

        for action in actions:
            action_dict = {
                "id": action.id,
                "user_id": action.user_id,
                "entity_id": action.entity_id,
                "domain": action.domain,
                "action": action.action,
                "parameters": action.parameters,
                "scheduled_at": action.scheduled_at,
                "description": action.description,
                "recurring": action.recurring,
                "recurrence_pattern": action.recurrence_pattern
            }

            logger.info(f"Executing action {action.id}: {action.description or action.entity_id}")

            success, error_msg = await self.execute_action(action_dict)

            # Update the action status
            async with self.async_session() as session:
                if success:
                    await session.execute(
                        text("""
                            UPDATE scheduled_home_action
                            SET status = 'executed', executed_at = :now, updated_at = :now
                            WHERE id = :id
                        """),
                        {"id": action.id, "now": datetime.now(self.tz)}
                    )
                    logger.info(f"Action {action.id} executed successfully")

                    # Handle recurring actions
                    if action.recurring:
                        await self.handle_recurring(action_dict)
                else:
                    await session.execute(
                        text("""
                            UPDATE scheduled_home_action
                            SET status = 'failed', error_message = :error, updated_at = :now
                            WHERE id = :id
                        """),
                        {"id": action.id, "error": error_msg, "now": datetime.now(self.tz)}
                    )
                    logger.error(f"Action {action.id} failed: {error_msg}")

                await session.commit()

    async def run(self):
        """Main loop - check for due actions every minute."""
        self.running = True
        logger.info("Scheduled home worker started")

        while self.running:
            try:
                await self.process_due_actions()
            except Exception as e:
                logger.error(f"Error processing scheduled actions: {e}")

            # Wait 60 seconds before next check
            await asyncio.sleep(60)

        logger.info("Scheduled home worker stopped")

    def stop(self):
        """Stop the worker gracefully."""
        logger.info("Stopping scheduled home worker...")
        self.running = False


async def main():
    """Main entry point."""
    logger.info("Starting scheduled home actions worker")

    worker = ScheduledHomeWorker(
        database_url=DATABASE_URL,
        ha_host=HA_HOST,
        ha_port=HA_PORT,
        ha_token=HA_TOKEN
    )

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
        worker.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Run worker with shutdown handling
    worker_task = asyncio.create_task(worker.run())

    try:
        await shutdown_event.wait()
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    logger.info("Scheduled home actions worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
