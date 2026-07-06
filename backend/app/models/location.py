"""Location awareness models: known places, location-triggered reminders, event log."""
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, Float, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class KnownPlace(Base):
    """A place David has saved (home, work, gym, a client site, ...)."""
    __tablename__ = "known_place"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    place_type = Column(String(50), default="other")  # home, work, gym, client_site, store, other
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_m = Column(Integer, default=150)
    source = Column(String(20), default="user")  # user, chat, learned
    visit_count = Column(Integer, default=0)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(String(20), default="active")  # active, suggested, dismissed
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<KnownPlace(name='{self.name}', type='{self.place_type}')>"


class LocationTrigger(Base):
    """A location-triggered reminder: fire a reminder on enter/exit of a place."""
    __tablename__ = "location_trigger"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    trigger_on = Column(String(10), nullable=False)  # 'enter' | 'exit'
    place_id = Column(String, ForeignKey("known_place.id", ondelete="CASCADE"), nullable=True)

    # Ad-hoc geofence (used when there's no saved place, e.g. "this client site")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    radius_m = Column(Integer, nullable=True)

    label = Column(String, nullable=False)  # place name snapshot, for display
    reminder_title = Column(String, nullable=False)
    reminder_description = Column(Text, nullable=True)
    recurring = Column(Boolean, default=False)
    cooldown_minutes = Column(Integer, default=60)
    status = Column(String(20), default="armed")  # armed, fired, cancelled, expired
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<LocationTrigger(trigger_on='{self.trigger_on}', label='{self.label}', status='{self.status}')>"


class LocationEvent(Base):
    """Raw location report/transition log, used for classification history and future place discovery."""
    __tablename__ = "location_event"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)
    place_id = Column(String, ForeignKey("known_place.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(10), nullable=False)  # 'report' | 'enter' | 'exit'
    source = Column(String(30), nullable=False)  # ios_significant, ios_geofence, manual
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<LocationEvent(type='{self.event_type}', source='{self.source}')>"
