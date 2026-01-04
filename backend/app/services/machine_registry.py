"""
Machine Registry Service
Manages registered machines for shadow agent with activity detection
"""
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, update, and_
from sqlalchemy.orm import Session
import uuid

from app.models.machine import Machine


class MachineRegistryService:
    """Service for managing registered shadow agent machines"""

    # Consider machine offline if no heartbeat for this long
    OFFLINE_THRESHOLD_SECONDS = 60

    async def register_machine(
        self,
        db: Session,
        user_id: str,
        device_id: str,
        hostname: str,
        platform: str,
        os_version: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        agent_version: Optional[str] = None
    ) -> Machine:
        """
        Register a new machine or update existing registration.
        Called when agent first connects.
        """
        # Check if machine already exists
        stmt = select(Machine).where(Machine.device_id == device_id)
        existing = db.execute(stmt).scalar_one_or_none()

        now = datetime.utcnow()

        if existing:
            # Update existing machine
            existing.user_id = user_id
            existing.hostname = hostname
            existing.platform = platform
            existing.os_version = os_version
            existing.capabilities = capabilities or []
            existing.agent_version = agent_version
            existing.last_heartbeat_at = now
            existing.is_online = True
            existing.updated_at = now
            db.commit()
            db.refresh(existing)
            return existing
        else:
            # Create new machine
            machine = Machine(
                id=str(uuid.uuid4()),
                user_id=user_id,
                device_id=device_id,
                hostname=hostname,
                platform=platform,
                os_version=os_version,
                capabilities=capabilities or [],
                agent_version=agent_version,
                last_heartbeat_at=now,
                is_online=True,
                activity_level="idle"
            )
            db.add(machine)
            db.commit()
            db.refresh(machine)
            return machine

    async def update_heartbeat(
        self,
        db: Session,
        device_id: str,
        activity_level: str,
        last_activity_at: Optional[datetime] = None
    ) -> Optional[Machine]:
        """
        Update machine heartbeat and activity level.
        Called every 10 seconds by the agent.
        """
        now = datetime.utcnow()

        stmt = select(Machine).where(Machine.device_id == device_id)
        machine = db.execute(stmt).scalar_one_or_none()

        if not machine:
            return None

        machine.last_heartbeat_at = now
        machine.activity_level = activity_level
        machine.is_online = True
        if last_activity_at:
            machine.last_activity_at = last_activity_at
        machine.updated_at = now

        db.commit()
        db.refresh(machine)
        return machine

    async def get_most_active_machine(
        self,
        db: Session,
        user_id: str
    ) -> Optional[Machine]:
        """
        Get the most recently active online machine for a user.
        Used for auto-detection when starting shadow session.
        """
        cutoff = datetime.utcnow() - timedelta(seconds=self.OFFLINE_THRESHOLD_SECONDS)

        stmt = (
            select(Machine)
            .where(
                and_(
                    Machine.user_id == user_id,
                    Machine.is_online == True,
                    Machine.last_heartbeat_at >= cutoff
                )
            )
            .order_by(Machine.last_activity_at.desc().nullslast())
            .limit(1)
        )

        return db.execute(stmt).scalar_one_or_none()

    async def get_user_machines(
        self,
        db: Session,
        user_id: str,
        include_offline: bool = False
    ) -> List[Machine]:
        """
        Get all machines registered for a user.
        """
        cutoff = datetime.utcnow() - timedelta(seconds=self.OFFLINE_THRESHOLD_SECONDS)

        if include_offline:
            stmt = (
                select(Machine)
                .where(Machine.user_id == user_id)
                .order_by(Machine.last_activity_at.desc().nullslast())
            )
        else:
            stmt = (
                select(Machine)
                .where(
                    and_(
                        Machine.user_id == user_id,
                        Machine.is_online == True,
                        Machine.last_heartbeat_at >= cutoff
                    )
                )
                .order_by(Machine.last_activity_at.desc().nullslast())
            )

        result = db.execute(stmt).scalars().all()
        return list(result)

    async def get_machine_by_device_id(
        self,
        db: Session,
        device_id: str
    ) -> Optional[Machine]:
        """
        Get a specific machine by device ID.
        """
        stmt = select(Machine).where(Machine.device_id == device_id)
        return db.execute(stmt).scalar_one_or_none()

    async def get_machine_by_id(
        self,
        db: Session,
        machine_id: str
    ) -> Optional[Machine]:
        """
        Get a specific machine by internal ID.
        """
        stmt = select(Machine).where(Machine.id == machine_id)
        return db.execute(stmt).scalar_one_or_none()

    async def mark_offline(
        self,
        db: Session,
        device_id: str
    ) -> bool:
        """
        Mark a machine as offline.
        Called when agent disconnects gracefully.
        """
        stmt = (
            update(Machine)
            .where(Machine.device_id == device_id)
            .values(is_online=False, updated_at=datetime.utcnow())
        )
        result = db.execute(stmt)
        db.commit()
        return result.rowcount > 0

    async def cleanup_stale_machines(
        self,
        db: Session,
        stale_threshold_hours: int = 24
    ) -> int:
        """
        Mark machines as offline if they haven't sent a heartbeat in a while.
        Should be called periodically (e.g., every minute).
        """
        cutoff = datetime.utcnow() - timedelta(hours=stale_threshold_hours)

        stmt = (
            update(Machine)
            .where(
                and_(
                    Machine.is_online == True,
                    Machine.last_heartbeat_at < cutoff
                )
            )
            .values(is_online=False, updated_at=datetime.utcnow())
        )

        result = db.execute(stmt)
        db.commit()
        return result.rowcount

    async def update_machine_config(
        self,
        db: Session,
        device_id: str,
        screenshot_enabled: Optional[bool] = None,
        screenshot_interval_seconds: Optional[int] = None,
        clipboard_enabled: Optional[bool] = None,
        terminal_enabled: Optional[bool] = None,
        file_access_enabled: Optional[bool] = None
    ) -> Optional[Machine]:
        """
        Update capture configuration for a machine.
        """
        stmt = select(Machine).where(Machine.device_id == device_id)
        machine = db.execute(stmt).scalar_one_or_none()

        if not machine:
            return None

        if screenshot_enabled is not None:
            machine.screenshot_enabled = screenshot_enabled
        if screenshot_interval_seconds is not None:
            machine.screenshot_interval_seconds = screenshot_interval_seconds
        if clipboard_enabled is not None:
            machine.clipboard_enabled = clipboard_enabled
        if terminal_enabled is not None:
            machine.terminal_enabled = terminal_enabled
        if file_access_enabled is not None:
            machine.file_access_enabled = file_access_enabled

        machine.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(machine)
        return machine


# Global service instance
machine_registry_service = MachineRegistryService()
