"""
Fleet context provider — a compact digest of every machine's health.

Produces a short, ContextBudget-friendly string ("6 hosts · all reporting · open
alerts: jetson disk 91% (firing 2h)") for injection into chat context when the
conversation touches servers/infra, and always available to deliberation and the
morning brief. Read-only; no side effects.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.managed_host import ManagedHost
from app.models.host_alert import HostAlert

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh(host: ManagedHost, interval: int = 300) -> bool:
    last = host.agent_last_report_at
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_now() - last).total_seconds() < 3 * interval


def _age_str(dt: Optional[datetime]) -> str:
    if dt is None:
        return "?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (_now() - dt).total_seconds()
    if secs < 3600:
        return f"{round(secs / 60)}m"
    if secs < 86400:
        return f"{round(secs / 3600)}h"
    return f"{round(secs / 86400)}d"


def fleet_digest(db: Session, user_id: str, max_chars: int = 1600) -> str:
    """One-paragraph fleet health digest. Empty string if no agent hosts."""
    hosts = (db.query(ManagedHost)
             .filter(ManagedHost.user_id == user_id, ManagedHost.active == True,  # noqa: E712
                     ManagedHost.transport.in_(("agent", "both")))
             .order_by(ManagedHost.name)
             .all())
    if not hosts:
        return ""

    online = [h for h in hosts if _fresh(h)]
    offline = [h for h in hosts if not _fresh(h)]

    open_alerts = (db.query(HostAlert)
                   .join(ManagedHost, HostAlert.host_id == ManagedHost.id)
                   .filter(ManagedHost.user_id == user_id, HostAlert.state == "firing")
                   .all())

    parts = [f"{len(hosts)} machine(s)"]
    if offline:
        parts.append(f"{len(online)} online, {len(offline)} offline ({', '.join(h.name for h in offline)})")
    else:
        parts.append("all reporting")

    if open_alerts:
        alert_bits = []
        # index host names for alert rendering
        name_by_id = {h.id: h.name for h in hosts}
        for a in open_alerts[:8]:
            hn = name_by_id.get(a.host_id, "host")
            d = a.detail or {}
            if a.rule in ("disk_warning", "disk_critical"):
                alert_bits.append(f"{hn} {d.get('mount', 'disk')} {d.get('pct')}% (firing {_age_str(a.fired_at)})")
            elif a.rule == "mem_pressure":
                alert_bits.append(f"{hn} memory {d.get('pct')}%")
            elif a.rule == "load_high":
                alert_bits.append(f"{hn} load {d.get('load1')}")
            elif a.rule == "temp_high":
                alert_bits.append(f"{hn} {d.get('temp_c')}°C")
            elif a.rule == "unit_failed":
                alert_bits.append(f"{hn} failed unit(s)")
            elif a.rule == "host_offline":
                alert_bits.append(f"{hn} offline")
            else:
                alert_bits.append(f"{hn} {a.rule}")
        parts.append("open alerts: " + "; ".join(alert_bits))
    else:
        parts.append("no open alerts")

    digest = "Fleet: " + " · ".join(parts) + "."
    return digest[:max_chars]


def fleet_brief_line(db: Session, user_id: str) -> str:
    """One line for the morning brief — only non-empty when something is open."""
    open_alerts = (db.query(HostAlert)
                   .join(ManagedHost, HostAlert.host_id == ManagedHost.id)
                   .filter(ManagedHost.user_id == user_id, HostAlert.state == "firing")
                   .all())
    if not open_alerts:
        return ""
    return fleet_digest(db, user_id)
