"""
Sara Fleet API — telemetry ingest, read-only diagnostics, and the machines view.

Two auth regimes (FLEET_DESIGN.md §6.3):
  * Agent-facing routes (enroll / report / commands / result) authenticate with a
    per-host bearer token — never a cookie. The token grants exactly: post
    telemetry + receive & answer diag commands for that one host.
  * User-facing routes (overview / hosts / diag / audit / revoke / enroll-command)
    use the normal cookie/JWT auth — David only.

The installer script itself (``GET /install.sh``) is public and contains no secrets;
the enroll secret is only ever handed out through the auth-gated
``GET /enroll-command``.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.managed_host import ManagedHost
from app.models.host_metric import HostMetric
from app.models.host_alert import HostAlert
from app.models import host_diag_command as hdc
from app.models.host_diag_command import HostDiagCommand
from app.services.fleet import alerts as fleet_alerts
from app.services.fleet import whitelist as fleet_whitelist

logger = logging.getLogger(__name__)
router = APIRouter()

_OUTPUT_CAP = 64 * 1024  # 64 KB cap on captured stdout/stderr


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _owner_id() -> str:
    return getattr(settings, "acs_owner_user_id", "") or ""


# ---------------------------------------------------------------------------
# Agent auth — per-host bearer token
# ---------------------------------------------------------------------------

def agent_host(authorization: Optional[str] = Header(None),
               db: Session = Depends(get_db)) -> ManagedHost:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    token_hash = _hash_token(token)
    # Indexed lookup by hash; confirm with constant-time compare to be safe.
    host = (db.query(ManagedHost)
            .filter(ManagedHost.agent_token_hash == token_hash,
                    ManagedHost.active == True)  # noqa: E712
            .first())
    if not host or not hmac.compare_digest(host.agent_token_hash or "", token_hash):
        raise HTTPException(status_code=401, detail="invalid host token")
    return host


# ---------------------------------------------------------------------------
# Freshness / snapshot helpers
# ---------------------------------------------------------------------------

def _interval() -> int:
    return int(getattr(settings, "fleet_report_interval", 300) or 300)


def _is_online(host: ManagedHost) -> bool:
    last = host.agent_last_report_at
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_now() - last).total_seconds() < 3 * _interval()


def _seconds_ago(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((_now() - dt).total_seconds())


def _metric_row(host_id: str, snap: Dict[str, Any]) -> HostMetric:
    """Extract the compact numeric row from a full snapshot."""
    mem = snap.get("mem") or {}
    disks = snap.get("disks") or []
    disk_max = None
    for d in disks:
        p = d.get("used_pct")
        if p is not None and (disk_max is None or p > disk_max):
            disk_max = p
    return HostMetric(
        host_id=host_id,
        cpu_pct=snap.get("cpu_pct"),
        load1=snap.get("load1"),
        mem_pct=mem.get("used_pct"),
        swap_pct=mem.get("swap_pct"),
        disk_max_pct=disk_max,
        temp_max_c=snap.get("temp_max_c"),
        net_rx_bps=snap.get("net_rx_bps"),
        net_tx_bps=snap.get("net_tx_bps"),
        failed_units=snap.get("failed_units"),
        extras=None,
    )


def _open_alerts(db: Session, host_id: str) -> List[HostAlert]:
    return (db.query(HostAlert)
            .filter(HostAlert.host_id == host_id, HostAlert.state == "firing")
            .order_by(HostAlert.fired_at.desc())
            .all())


def _headline(snap: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    snap = snap or {}
    mem = snap.get("mem") or {}
    disks = snap.get("disks") or []
    disk_max = max((d.get("used_pct") or 0 for d in disks), default=None)
    return {
        "cpu_pct": snap.get("cpu_pct"),
        "mem_pct": mem.get("used_pct"),
        "disk_max_pct": disk_max,
        "load1": snap.get("load1"),
        "cpu_count": snap.get("cpu_count"),
        "temp_max_c": snap.get("temp_max_c"),
        "uptime_seconds": snap.get("uptime_seconds"),
        "os": snap.get("os"),
        "arch": snap.get("arch"),
    }


# ===========================================================================
# Agent-facing routes
# ===========================================================================

class EnrollBody(BaseModel):
    enroll_secret: str
    machine_id: str
    hostname: str
    name: Optional[str] = None


@router.post("/enroll")
async def enroll(body: EnrollBody, db: Session = Depends(get_db)):
    expected = getattr(settings, "fleet_enroll_secret", "") or ""
    if not expected or not hmac.compare_digest(body.enroll_secret, expected):
        raise HTTPException(status_code=403, detail="invalid enroll secret")

    owner = _owner_id()
    if not owner:
        raise HTTPException(status_code=500, detail="fleet owner not configured")

    machine_id = body.machine_id.strip()
    name = (body.name or body.hostname).strip().lower()[:64]

    # Match by machine_id first (re-enroll of the same box). Otherwise fall back to
    # the name — names are unique per user, so a same-name enroll updates that row
    # (upgrading an SSH-only host, or re-pointing a re-imaged box that got a fresh
    # machine_id) rather than creating a duplicate.
    host = (db.query(ManagedHost)
            .filter(ManagedHost.machine_id == machine_id, ManagedHost.user_id == owner)
            .first())
    if host is None:
        host = (db.query(ManagedHost)
                .filter(ManagedHost.user_id == owner, ManagedHost.name == name)
                .first())

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)

    if host is None:
        host = ManagedHost(
            user_id=owner, name=name, hostname=body.hostname, username="sara-agent",
            transport="agent", machine_id=machine_id, agent_token_hash=token_hash,
            agent_enrolled_at=_now(), active=True, tags=[],
        )
        db.add(host)
    else:
        # Existing row — attach/refresh the agent transport.
        host.machine_id = machine_id
        host.agent_token_hash = token_hash
        host.agent_enrolled_at = _now()
        host.active = True
        host.transport = "both" if host.transport == "ssh" else "agent"
        if not host.hostname:
            host.hostname = body.hostname

    db.commit()
    db.refresh(host)
    logger.info(f"[fleet] enrolled host name={host.name} machine_id={machine_id} transport={host.transport}")
    return {"host_id": host.id, "name": host.name, "token": token,
            "report_interval": _interval()}


class ReportBody(BaseModel):
    snapshot: Dict[str, Any]
    spool: Optional[List[Dict[str, Any]]] = None  # backfill of missed reports


@router.post("/report")
async def report(body: ReportBody, host: ManagedHost = Depends(agent_host),
                 db: Session = Depends(get_db)):
    snapshots = list(body.spool or []) + [body.snapshot]
    alert_count = 0
    all_transitions = []

    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        db.add(_metric_row(host.id, snap))

    # Latest snapshot is authoritative for state + alerts.
    latest = body.snapshot if isinstance(body.snapshot, dict) else {}
    host.agent_snapshot = latest
    host.agent_last_report_at = _now()
    if latest.get("agent_version"):
        host.agent_version = str(latest["agent_version"])[:16]
    db.commit()

    try:
        transitions = fleet_alerts.evaluate_snapshot(db, host, latest)
        all_transitions.extend(transitions)
        alert_count = len(transitions)
    except Exception as e:
        logger.warning(f"[fleet] alert eval failed for {host.name}: {e}")

    if all_transitions:
        await fleet_alerts.emit_transitions(host.user_id, all_transitions)

    return {"ok": True, "alerts": alert_count, "report_interval": _interval()}


@router.get("/commands")
async def poll_commands(wait: int = Query(25, ge=0, le=55),
                        host: ManagedHost = Depends(agent_host),
                        db: Session = Depends(get_db)):
    """Long-poll pending diag commands for this host, dispatch them (mark running)."""
    deadline = _now() + timedelta(seconds=min(wait, 55))
    while True:
        pending = (db.query(HostDiagCommand)
                   .filter(HostDiagCommand.host_id == host.id,
                           HostDiagCommand.status == hdc.PENDING)
                   .order_by(HostDiagCommand.created_at.asc())
                   .all())
        if pending:
            out = []
            for cmd in pending:
                cmd.status = hdc.RUNNING
                cmd.started_at = _now()
                out.append({"id": cmd.id, "argv": cmd.argv})
            db.commit()
            return out
        if _now() >= deadline:
            return []
        await asyncio.sleep(0.5)
        db.expire_all()


class DiagResultBody(BaseModel):
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    denied: bool = False
    denied_reason: Optional[str] = None


@router.post("/commands/{cmd_id}/result")
async def command_result(cmd_id: int, body: DiagResultBody,
                         host: ManagedHost = Depends(agent_host),
                         db: Session = Depends(get_db)):
    cmd = (db.query(HostDiagCommand)
           .filter(HostDiagCommand.id == cmd_id, HostDiagCommand.host_id == host.id)
           .first())
    if not cmd:
        raise HTTPException(status_code=404, detail="command not found")
    if body.denied:
        cmd.status = hdc.DENIED_AGENT
        cmd.denied_reason = body.denied_reason or "denied by agent whitelist"
    else:
        cmd.status = hdc.DONE
        cmd.exit_code = body.exit_code
        cmd.stdout = (body.stdout or "")[:_OUTPUT_CAP]
        cmd.stderr = (body.stderr or "")[:_OUTPUT_CAP]
    cmd.finished_at = _now()
    db.commit()
    return {"ok": True}


# ===========================================================================
# User-facing routes (cookie auth)
# ===========================================================================

def _resolve_host(db: Session, user_id: str, name: str) -> ManagedHost:
    host = (db.query(ManagedHost)
            .filter(ManagedHost.user_id == user_id,
                    ManagedHost.name == (name or "").strip().lower(),
                    ManagedHost.active == True)  # noqa: E712
            .first())
    if not host:
        raise HTTPException(status_code=404, detail="host not found")
    return host


@router.get("/overview")
async def overview(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    hosts = (db.query(ManagedHost)
             .filter(ManagedHost.user_id == current_user.id, ManagedHost.active == True)  # noqa: E712
             .order_by(ManagedHost.name)
             .all())
    cards = []
    online = 0
    total_alerts = 0
    for h in hosts:
        has_agent = h.transport in ("agent", "both")
        is_online = has_agent and _is_online(h)
        if is_online:
            online += 1
        open_alerts = _open_alerts(db, h.id) if has_agent else []
        total_alerts += len(open_alerts)
        cards.append({
            "id": h.id,
            "name": h.name,
            "hostname": h.hostname,
            "transport": h.transport,
            "has_agent": has_agent,
            "online": is_online,
            "last_report_seconds_ago": _seconds_ago(h.agent_last_report_at),
            "agent_version": h.agent_version,
            "headline": _headline(h.agent_snapshot) if has_agent else None,
            "alerts": [{"rule": a.rule, "severity": a.severity, "detail": a.detail,
                        "fired_at": a.fired_at.isoformat() if a.fired_at else None}
                       for a in open_alerts],
        })
    return {
        "hosts": cards,
        "summary": {"total": len(hosts), "online": online, "alerts": total_alerts},
    }


@router.get("/hosts/{name}")
async def host_detail(name: str, current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    h = _resolve_host(db, current_user.id, name)
    open_alerts = _open_alerts(db, h.id)
    recent = (db.query(HostAlert)
              .filter(HostAlert.host_id == h.id)
              .order_by(HostAlert.fired_at.desc())
              .limit(20).all())
    return {
        "id": h.id,
        "name": h.name,
        "hostname": h.hostname,
        "transport": h.transport,
        "online": _is_online(h),
        "last_report_seconds_ago": _seconds_ago(h.agent_last_report_at),
        "agent_version": h.agent_version,
        "snapshot": h.agent_snapshot,
        "ssh_inspection": h.last_inspection,
        "open_alerts": [{"rule": a.rule, "severity": a.severity, "detail": a.detail,
                         "fired_at": a.fired_at.isoformat() if a.fired_at else None}
                        for a in open_alerts],
        "recent_alerts": [{"rule": a.rule, "severity": a.severity, "state": a.state,
                           "detail": a.detail,
                           "fired_at": a.fired_at.isoformat() if a.fired_at else None,
                           "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None}
                          for a in recent],
    }


@router.get("/hosts/{name}/metrics")
async def host_metrics(name: str, hours: int = Query(24, ge=1, le=720),
                       current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    h = _resolve_host(db, current_user.id, name)
    since = _now() - timedelta(hours=hours)
    rows = (db.query(HostMetric)
            .filter(HostMetric.host_id == h.id, HostMetric.ts >= since)
            .order_by(HostMetric.ts.asc())
            .all())
    return {
        "host": h.name,
        "hours": hours,
        "points": [{
            "ts": r.ts.isoformat() if r.ts else None,
            "cpu_pct": r.cpu_pct, "load1": r.load1, "mem_pct": r.mem_pct,
            "disk_max_pct": r.disk_max_pct, "temp_max_c": r.temp_max_c,
            "net_rx_bps": r.net_rx_bps, "net_tx_bps": r.net_tx_bps,
            "failed_units": r.failed_units,
        } for r in rows],
    }


class DiagBody(BaseModel):
    command: str
    requested_by: str = "web"
    request_context: Optional[str] = None


@router.post("/hosts/{name}/diag")
async def run_diag(name: str, body: DiagBody, current_user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    h = _resolve_host(db, current_user.id, name)
    if h.transport not in ("agent", "both"):
        raise HTTPException(status_code=400, detail="host has no fleet agent (SSH-only)")

    # Layer 1: server-side whitelist.
    ok, reason, argv = fleet_whitelist.validate_command(body.command)
    if not ok:
        cmd = HostDiagCommand(host_id=h.id, user_id=current_user.id,
                              requested_by=body.requested_by,
                              request_context=body.request_context,
                              argv=[body.command], status=hdc.DENIED_SERVER,
                              denied_reason=reason, finished_at=_now())
        db.add(cmd)
        db.commit()
        return {"status": hdc.DENIED_SERVER, "id": cmd.id, "reason": reason}

    cmd = HostDiagCommand(host_id=h.id, user_id=current_user.id,
                          requested_by=body.requested_by,
                          request_context=body.request_context,
                          argv=argv, status=hdc.PENDING)
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    cmd_id = cmd.id

    # Wait up to 35s for the agent to long-poll, run, and post the result.
    deadline = _now() + timedelta(seconds=35)
    while _now() < deadline:
        await asyncio.sleep(0.5)
        db.expire_all()
        cmd = db.query(HostDiagCommand).filter(HostDiagCommand.id == cmd_id).first()
        if cmd and cmd.status in (hdc.DONE, hdc.DENIED_AGENT, hdc.TIMEOUT, hdc.LOST):
            return _diag_out(cmd)

    return {"status": "pending", "id": cmd_id,
            "message": "command queued; agent has not answered yet (offline?)"}


def _diag_out(cmd: HostDiagCommand) -> Dict[str, Any]:
    return {
        "id": cmd.id,
        "status": cmd.status,
        "argv": cmd.argv,
        "exit_code": cmd.exit_code,
        "stdout": cmd.stdout,
        "stderr": cmd.stderr,
        "denied_reason": cmd.denied_reason,
    }


@router.get("/audit")
async def audit(name: Optional[str] = None, limit: int = Query(50, ge=1, le=500),
                current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    q = (db.query(HostDiagCommand, ManagedHost)
         .join(ManagedHost, HostDiagCommand.host_id == ManagedHost.id)
         .filter(ManagedHost.user_id == current_user.id))
    if name:
        q = q.filter(ManagedHost.name == name.strip().lower())
    rows = q.order_by(HostDiagCommand.created_at.desc()).limit(limit).all()
    return {"commands": [{
        "id": c.id, "host": h.name, "argv": c.argv, "status": c.status,
        "requested_by": c.requested_by, "denied_reason": c.denied_reason,
        "exit_code": c.exit_code,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "finished_at": c.finished_at.isoformat() if c.finished_at else None,
    } for c, h in rows]}


@router.post("/hosts/{name}/revoke")
async def revoke(name: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    h = _resolve_host(db, current_user.id, name)
    h.agent_token_hash = None
    h.transport = "ssh" if h.transport == "both" else "agent"
    db.commit()
    return {"ok": True, "message": f"{h.name} agent token revoked; re-enroll to restore"}


def _install_base_url() -> str:
    return (getattr(settings, "fleet_public_url", "") or "https://sara.avery.cloud").rstrip("/")


@router.get("/enroll-command")
async def enroll_command(current_user=Depends(get_current_user)):
    """The ready-to-paste installer one-liner, including the enroll secret.

    Auth-gated (David only) — this is what the dashboard's "Add machine" button
    shows so the command is always findable in the app (§7.3).
    """
    secret = getattr(settings, "fleet_enroll_secret", "") or ""
    base = _install_base_url()
    configured = bool(secret)
    if not configured:
        secret = "<set FLEET_ENROLL_SECRET in .env>"
    tmp = "/tmp/sara-fleet-install.sh"
    # Download-then-run (single line): works on password-sudo hosts too, because
    # sudo can read the password from the terminal (stdin isn't the curl pipe).
    return {
        "configured": configured,
        "url": base,
        "command": (f"curl -fsSL {base}/api/fleet/install.sh -o {tmp} && "
                    f"sudo bash {tmp} --enroll {secret} --url {base}"),
        "variants": {
            "named": "add --name <handle> before/after --enroll to override the auto-detected hostname",
            "uninstall": (f"curl -fsSL {base}/api/fleet/install.sh -o {tmp} && sudo bash {tmp} --uninstall"),
            "pipe": (f"passwordless-sudo hosts can pipe it: "
                     f"curl -fsSL {base}/api/fleet/install.sh | sudo bash -s -- --enroll {secret} --url {base}"),
            "note": "run it as a SINGLE line — if it wraps in your terminal the shell splits it and the secret is lost",
        },
    }


# --- public installer (no secrets) -----------------------------------------

def _deploy_dir() -> Path:
    """Locate deploy/fleet-agent across container and dev layouts.

    In the container the backend is mounted at ``/app`` and ``deploy/`` is mounted
    at ``/app/deploy`` (docker-compose), so parents[2] wins. In a bare checkout the
    backend lives at ``repo/backend`` so parents[3] (repo root) wins.
    """
    override = os.environ.get("FLEET_DEPLOY_DIR")
    candidates = []
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "deploy" / "fleet-agent")   # /app/deploy/fleet-agent
    candidates.append(here.parents[3] / "deploy" / "fleet-agent")   # repo/deploy/fleet-agent
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


@router.get("/install.sh", response_class=PlainTextResponse)
async def install_sh():
    path = _deploy_dir() / "install.sh"
    if not path.exists():
        raise HTTPException(status_code=404, detail="installer not found")
    return PlainTextResponse(path.read_text(), media_type="text/x-shellscript")


@router.get("/agent.py", response_class=PlainTextResponse)
async def agent_py():
    """The agent source, served so install.sh can fetch it (no secrets inside)."""
    path = _deploy_dir() / "sara_fleet_agent.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail="agent not found")
    return PlainTextResponse(path.read_text(), media_type="text/x-python")


@router.get("/agent.service", response_class=PlainTextResponse)
async def agent_service():
    path = _deploy_dir() / "sara-fleet-agent.service"
    if not path.exists():
        raise HTTPException(status_code=404, detail="unit not found")
    return PlainTextResponse(path.read_text(), media_type="text/plain")
