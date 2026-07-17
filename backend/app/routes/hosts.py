"""
Managed-hosts API — register / list / inspect Linux machines Sara can reach.

Backs the chat "check out <server>" capability with a programmatic surface for
the web/iOS clients (a "Machines" panel). All inspection is read-only over SSH.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.services import host_inspector

logger = logging.getLogger(__name__)
router = APIRouter()


class HostCreate(BaseModel):
    name: str
    hostname: str
    username: str = "sara"
    port: int = 22
    ssh_key_path: str = "~/.ssh/sara_agent"
    description: Optional[str] = None


class HostOut(BaseModel):
    id: str
    name: str
    hostname: str
    username: str
    port: int
    description: Optional[str] = None
    last_status: Optional[str] = None
    last_seen_at: Optional[str] = None
    last_inspection: Optional[dict] = None


def _to_out(h) -> HostOut:
    return HostOut(
        id=h.id, name=h.name, hostname=h.hostname, username=h.username,
        port=h.port, description=h.description, last_status=h.last_status,
        last_seen_at=h.last_seen_at.isoformat() if h.last_seen_at else None,
        last_inspection=h.last_inspection,
    )


@router.get("/hosts", response_model=List[HostOut])
async def list_hosts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return [_to_out(h) for h in host_inspector.list_hosts(db, current_user.id)]


@router.post("/hosts", response_model=HostOut)
async def create_host(body: HostCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    host = host_inspector.add_host(
        db, current_user.id, name=body.name, hostname=body.hostname,
        username=body.username, port=body.port, ssh_key_path=body.ssh_key_path,
        description=body.description,
    )
    return _to_out(host)


@router.delete("/hosts/{name}")
async def delete_host(name: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    if not host_inspector.remove_host(db, current_user.id, name):
        raise HTTPException(status_code=404, detail="Host not found")
    return {"ok": True}


@router.post("/hosts/{name}/inspect", response_model=HostOut)
async def inspect(name: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    host = host_inspector.get_host(db, current_user.id, name)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    spec = await host_inspector.inspect_host(db, host)
    db.refresh(host)
    out = _to_out(host)
    out.last_inspection = spec
    return out
