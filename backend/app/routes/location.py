"""Location awareness routes: reports, geofence events, known places, location triggers."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.deps import get_current_user
from app.core.timezone import now as local_now
from app.db.session import get_db
from app.models.location import KnownPlace, LocationTrigger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/location", tags=["Location"])


# ── Reports ──

class LocationReport(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    source: str = "ios_significant"
    observed_at: Optional[datetime] = None


@router.post("/report")
async def report_location(
    data: LocationReport,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Periodic location report from the phone (significant-location-change tier)."""
    from app.services.location_service import process_report
    result = await process_report(
        db, current_user.id, data.latitude, data.longitude, data.accuracy, data.source,
        observed_at=data.observed_at,
    )
    return {"ok": True, **result}


class GeofenceEvent(BaseModel):
    region_id: str
    event: str  # 'enter' | 'exit'
    latitude: float
    longitude: float
    # Client timestamp (ISO8601). Present when the phone replays a geofence event it
    # queued while the backend was unreachable (Phase 10A-fix), so the backend can
    # process late events at their real time instead of arrival time.
    event_time: Optional[str] = None


@router.post("/geofence-event")
async def geofence_event(
    data: GeofenceEvent,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Trusted enter/exit signal from iOS native CLRegion monitoring."""
    if data.event not in ("enter", "exit"):
        raise HTTPException(status_code=400, detail="event must be 'enter' or 'exit'")
    from app.services.location_service import handle_geofence_event
    result = await handle_geofence_event(
        db, current_user.id, data.region_id, data.event, data.latitude, data.longitude,
        event_time=data.event_time,
    )
    return {"ok": True, **result}


@router.get("/geofences")
async def get_geofences(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Regions the phone should register for native geofencing."""
    from app.services.location_service import geofence_payload
    return {"regions": geofence_payload(db, current_user.id)}


# ── Known Places ──

class PlaceCreate(BaseModel):
    name: str
    place_type: str = "other"
    latitude: float
    longitude: float
    radius_m: int = 150


class PlaceUpdate(BaseModel):
    name: Optional[str] = None
    place_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_m: Optional[int] = None
    is_active: Optional[bool] = None


def _place_to_dict(p: KnownPlace) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "place_type": p.place_type,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "radius_m": p.radius_m,
        "source": p.source,
        "status": p.status,
        "visit_count": p.visit_count,
        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/places")
async def list_places(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    places = db.query(KnownPlace).filter(
        KnownPlace.user_id == current_user.id, KnownPlace.is_active == True
    ).order_by(KnownPlace.name).all()
    return {"places": [_place_to_dict(p) for p in places]}


@router.get("/places/suggestions")
async def list_suggested_places(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Places discovered from location history, awaiting confirm/dismiss."""
    places = db.query(KnownPlace).filter(
        KnownPlace.user_id == current_user.id, KnownPlace.status == "suggested"
    ).order_by(KnownPlace.visit_count.desc()).all()
    return {"suggestions": [_place_to_dict(p) for p in places]}


class SuggestionConfirm(BaseModel):
    name: Optional[str] = None
    place_type: str = "other"


@router.post("/places/{place_id}/confirm")
async def confirm_suggested_place(
    place_id: str,
    data: SuggestionConfirm,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    place = db.query(KnownPlace).filter(
        KnownPlace.id == place_id, KnownPlace.user_id == current_user.id, KnownPlace.status == "suggested"
    ).first()
    if not place:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if data.name:
        place.name = data.name
    place.place_type = data.place_type
    place.status = "active"
    place.is_active = True
    db.commit()
    db.refresh(place)

    try:
        from app.services.personal_knowledge_graph import personal_kg
        personal_kg.upsert_fact(
            fact_type="Place",
            properties={"name": place.name, "type": place.place_type, "address": "", "significance": ""},
            confidence=0.8,
            source="inferred",
        )
    except Exception as e:
        logger.debug(f"PKG place mirror failed: {e}")

    return _place_to_dict(place)


@router.post("/places/{place_id}/dismiss")
async def dismiss_suggested_place(
    place_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    place = db.query(KnownPlace).filter(
        KnownPlace.id == place_id, KnownPlace.user_id == current_user.id, KnownPlace.status == "suggested"
    ).first()
    if not place:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    place.status = "dismissed"
    db.commit()
    return {"ok": True}


class GeocodeRequest(BaseModel):
    address: str


@router.post("/geocode")
async def geocode_preview(
    data: GeocodeRequest,
    current_user=Depends(get_current_user),
):
    """Resolve a free-text address to coordinates, for the 'add place by address' form."""
    from app.services.travel_nudge import geocode_address
    result = await geocode_address(data.address)
    if not result:
        raise HTTPException(status_code=404, detail="Could not find that address")
    lat, lon = result
    return {"latitude": lat, "longitude": lon}


@router.post("/places")
async def create_place(
    data: PlaceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    place = KnownPlace(
        user_id=current_user.id,
        name=data.name,
        place_type=data.place_type,
        latitude=data.latitude,
        longitude=data.longitude,
        radius_m=data.radius_m,
        source="user",
    )
    db.add(place)
    db.commit()
    db.refresh(place)

    try:
        from app.services.personal_knowledge_graph import personal_kg
        personal_kg.upsert_fact(
            fact_type="Place",
            properties={"name": data.name, "type": data.place_type, "address": "", "significance": ""},
            confidence=0.9,
            source="explicit_statement",
        )
    except Exception as e:
        logger.debug(f"PKG place mirror failed: {e}")

    return _place_to_dict(place)


@router.patch("/places/{place_id}")
async def update_place(
    place_id: str,
    data: PlaceUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    place = db.query(KnownPlace).filter(
        KnownPlace.id == place_id, KnownPlace.user_id == current_user.id
    ).first()
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")

    for field in ("name", "place_type", "latitude", "longitude", "radius_m", "is_active"):
        val = getattr(data, field)
        if val is not None:
            setattr(place, field, val)

    db.commit()
    db.refresh(place)
    return _place_to_dict(place)


@router.delete("/places/{place_id}")
async def delete_place(
    place_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    place = db.query(KnownPlace).filter(
        KnownPlace.id == place_id, KnownPlace.user_id == current_user.id
    ).first()
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")

    place.is_active = False
    db.commit()
    return {"ok": True}


# ── Location Triggers ──

def _trigger_to_dict(t: LocationTrigger) -> dict:
    return {
        "id": t.id,
        "trigger_on": t.trigger_on,
        "place_id": t.place_id,
        "label": t.label,
        "reminder_title": t.reminder_title,
        "reminder_description": t.reminder_description,
        "recurring": t.recurring,
        "cooldown_minutes": t.cooldown_minutes,
        "status": t.status,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "last_fired_at": t.last_fired_at.isoformat() if t.last_fired_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/triggers")
async def list_triggers(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    triggers = db.query(LocationTrigger).filter(
        LocationTrigger.user_id == current_user.id, LocationTrigger.status == "armed"
    ).order_by(LocationTrigger.created_at.desc()).all()
    return {"triggers": [_trigger_to_dict(t) for t in triggers]}


@router.delete("/triggers/{trigger_id}")
async def cancel_trigger(
    trigger_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    trigger = db.query(LocationTrigger).filter(
        LocationTrigger.id == trigger_id, LocationTrigger.user_id == current_user.id
    ).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    trigger.status = "cancelled"
    db.commit()
    return {"ok": True}
