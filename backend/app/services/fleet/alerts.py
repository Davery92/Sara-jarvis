"""
Fleet alert engine — edge-triggered, anti-nag by construction (FLEET_DESIGN.md §6.4).

A rule fires on the false→true edge and resolves when it clears. State lives on
``ManagedHost.agent_alert_state`` (per-rule) plus an open ``HostAlert`` ledger row.
On the firing edge we emit an interoception event onto the event bus — the same
``SYSTEM_HEALTH_DEGRADED`` / ``SYSTEM_HEALTH_RECOVERED`` path body_sense uses — so
fleet health flows through salience → deliberation → the attention economy. This
module **never** pushes to David directly.

Thresholds come from tunables (``fleet.disk_warning_pct`` etc.) with sane defaults,
so they can be tuned without a deploy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.host_alert import HostAlert
from app.services.tunables import get_tunable_float, get_tunable_int

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# rule → severity. host_offline + *_critical are "high" (they actually push, per the
# attention-queue gotcha); warnings are normal (inbox/digest); informational are low.
_SEVERITY = {
    "host_offline": "high",
    "disk_critical": "high",
    "mem_pressure": "high",
    "temp_high": "high",
    "disk_warning": "normal",
    "load_high": "normal",
    "unit_failed": "normal",
    "reboot_required": "low",
    "updates_pending": "low",
}


class Transition:
    """A rule crossing an edge on one host, ready to be turned into an event."""

    def __init__(self, host_id: str, host_name: str, rule: str, fired: bool,
                 severity: str, detail: Dict[str, Any], message: str):
        self.host_id = host_id
        self.host_name = host_name
        self.rule = rule
        self.fired = fired          # True = firing edge, False = resolved edge
        self.severity = severity
        self.detail = detail
        self.message = message


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def _thresholds() -> Dict[str, float]:
    return {
        "disk_warning": get_tunable_float("fleet.disk_warning_pct", 85.0),
        "disk_critical": get_tunable_float("fleet.disk_critical_pct", 95.0),
        "disk_hysteresis": get_tunable_float("fleet.disk_hysteresis_pct", 3.0),
        "mem_pressure": get_tunable_float("fleet.mem_pressure_pct", 92.0),
        "mem_clear": get_tunable_float("fleet.mem_clear_pct", 85.0),
        "load_mult": get_tunable_float("fleet.load_high_mult", 2.0),
        "temp_high": get_tunable_float("fleet.temp_high_c", 85.0),
        "temp_clear": get_tunable_float("fleet.temp_clear_c", 78.0),
        "updates": get_tunable_float("fleet.updates_pending_count", 25.0),
    }


def _eval_rules(snapshot: Dict[str, Any], prev_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Compute the current firing state for each rule from a telemetry snapshot.

    ``prev_state`` carries the last-known firing booleans so hysteresis / sustain
    logic can look back. Returns ``{rule: {"firing": bool, "detail": {...}}}``.
    Only rules present in the snapshot are evaluated; absent data → rule skipped.
    """
    t = _thresholds()
    out: Dict[str, Dict[str, Any]] = {}

    # --- disk (warning + critical, with hysteresis) ---
    disks = snapshot.get("disks") or []
    worst = None
    for d in disks:
        pct = d.get("used_pct")
        if pct is None:
            continue
        if worst is None or pct > worst.get("used_pct", -1):
            worst = d
    if worst is not None:
        pct = worst["used_pct"]
        for rule, thresh in (("disk_warning", t["disk_warning"]), ("disk_critical", t["disk_critical"])):
            was = prev_state.get(rule, {}).get("firing", False)
            clear_at = thresh - t["disk_hysteresis"]
            firing = pct >= thresh if not was else pct >= clear_at
            out[rule] = {"firing": firing, "detail": {"mount": worst.get("mount"), "pct": pct, "threshold": thresh}}

    # --- memory pressure (sustained via a small counter in state) ---
    mem = snapshot.get("mem") or {}
    mem_pct = mem.get("used_pct")
    if mem_pct is not None:
        was = prev_state.get("mem_pressure", {}).get("firing", False)
        firing = mem_pct >= t["mem_pressure"] if not was else mem_pct >= t["mem_clear"]
        out["mem_pressure"] = {"firing": firing, "detail": {"pct": mem_pct, "threshold": t["mem_pressure"]}}

    # --- load high (relative to cores) ---
    load1 = snapshot.get("load1")
    cores = snapshot.get("cpu_count") or 1
    if load1 is not None and cores:
        was = prev_state.get("load_high", {}).get("firing", False)
        high_at = t["load_mult"] * cores
        clear_at = 1.0 * cores
        firing = load1 > high_at if not was else load1 > clear_at
        out["load_high"] = {"firing": firing, "detail": {"load1": load1, "cores": cores, "threshold": high_at}}

    # --- temperature ---
    temp = snapshot.get("temp_max_c")
    if temp is not None:
        was = prev_state.get("temp_high", {}).get("firing", False)
        firing = temp >= t["temp_high"] if not was else temp >= t["temp_clear"]
        out["temp_high"] = {"firing": firing, "detail": {"temp_c": temp, "threshold": t["temp_high"]}}

    # --- failed systemd units ---
    failed = snapshot.get("failed_units")
    if failed is not None:
        names = snapshot.get("failed_unit_names") or []
        out["unit_failed"] = {"firing": bool(failed), "detail": {"count": failed, "units": names[:10]}}

    # --- reboot required (informational) ---
    if "reboot_required" in snapshot:
        out["reboot_required"] = {"firing": bool(snapshot.get("reboot_required")), "detail": {}}

    # --- pending updates (digest-only material) ---
    updates = snapshot.get("updates_pending")
    if updates is not None:
        out["updates_pending"] = {"firing": updates > t["updates"], "detail": {"count": updates}}

    return out


def _message(host_name: str, rule: str, detail: Dict[str, Any], firing: bool) -> str:
    if not firing:
        return f"{host_name}: {rule.replace('_', ' ')} cleared"
    if rule in ("disk_warning", "disk_critical"):
        return f"{host_name}: {detail.get('mount', 'disk')} at {detail.get('pct')}%"
    if rule == "mem_pressure":
        return f"{host_name}: memory at {detail.get('pct')}%"
    if rule == "load_high":
        return f"{host_name}: load {detail.get('load1')} on {detail.get('cores')} cores"
    if rule == "temp_high":
        return f"{host_name}: {detail.get('temp_c')}°C"
    if rule == "unit_failed":
        units = ", ".join(detail.get("units", [])) or f"{detail.get('count')} unit(s)"
        return f"{host_name}: failed units — {units}"
    if rule == "reboot_required":
        return f"{host_name}: reboot required"
    if rule == "updates_pending":
        return f"{host_name}: {detail.get('count')} package updates pending"
    if rule == "host_offline":
        return f"{host_name}: offline (no report in {detail.get('minutes', '?')} min)"
    return f"{host_name}: {rule}"


def evaluate_snapshot(db: Session, host, snapshot: Dict[str, Any]) -> List[Transition]:
    """Run all rules for a host's fresh snapshot; persist edges; return transitions.

    Mutates ``host.agent_alert_state`` and writes/closes ``HostAlert`` rows, but
    does *not* emit events — the async caller does that via :func:`emit_transitions`
    so this stays usable from sync (Celery) contexts too.
    """
    prev_state = dict(host.agent_alert_state or {})
    current = _eval_rules(snapshot, prev_state)
    return _apply(db, host, current, prev_state)


def _apply(db: Session, host, current: Dict[str, Dict[str, Any]],
           prev_state: Dict[str, Any]) -> List[Transition]:
    transitions: List[Transition] = []
    new_state = dict(prev_state)

    for rule, cur in current.items():
        firing = cur["firing"]
        detail = cur["detail"]
        was = prev_state.get(rule, {}).get("firing", False)
        new_state[rule] = {"firing": firing}

        if firing and not was:
            severity = _SEVERITY.get(rule, "normal")
            db.add(HostAlert(host_id=host.id, rule=rule, severity=severity,
                             state="firing", detail=detail, notified=True))
            transitions.append(Transition(host.id, host.name, rule, True, severity,
                                          detail, _message(host.name, rule, detail, True)))
        elif not firing and was:
            _resolve_open(db, host.id, rule)
            transitions.append(Transition(host.id, host.name, rule, False,
                                          _SEVERITY.get(rule, "normal"), detail,
                                          _message(host.name, rule, detail, False)))

    host.agent_alert_state = new_state
    db.commit()
    return transitions


def _resolve_open(db: Session, host_id: str, rule: str):
    open_rows = (db.query(HostAlert)
                 .filter(HostAlert.host_id == host_id, HostAlert.rule == rule,
                         HostAlert.state == "firing")
                 .all())
    for row in open_rows:
        row.state = "resolved"
        row.resolved_at = _now()


def evaluate_offline(db: Session, host, interval_seconds: int) -> List[Transition]:
    """Offline detection: fires host_offline after 3× the report interval."""
    prev_state = dict(host.agent_alert_state or {})
    was = prev_state.get("host_offline", {}).get("firing", False)
    last = host.agent_last_report_at
    if last is None:
        return []
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    gap = (_now() - last).total_seconds()
    offline = gap > 3 * max(interval_seconds, 60)
    if offline == was:
        return []
    detail = {"minutes": round(gap / 60)}
    current = {"host_offline": {"firing": offline, "detail": detail}}
    return _apply(db, host, current, prev_state)


async def emit_transitions(user_id: str, transitions: List[Transition]) -> None:
    """Publish each transition onto the event bus (interoception path)."""
    if not transitions:
        return
    try:
        from app.services.event_bus import event_bus, Event, EventType
    except Exception as e:  # pragma: no cover
        logger.warning(f"[fleet.alerts] event bus unavailable: {e}")
        return

    for tr in transitions:
        etype = EventType.SYSTEM_HEALTH_DEGRADED if tr.fired else EventType.SYSTEM_HEALTH_RECOVERED
        try:
            await event_bus.publish(Event(
                event_type=etype,
                user_id=user_id,
                source="fleet",
                payload={
                    "fleet": True,
                    "host": tr.host_name,
                    "rule": tr.rule,
                    "severity": tr.severity,
                    "summary": tr.message,
                    "impact": tr.message,
                    "detail": tr.detail,
                    "confidence": 1.0,
                    "provenance": "fleet_agent",
                },
            ))
        except Exception as e:
            logger.warning(f"[fleet.alerts] failed to publish {tr.rule} for {tr.host_name}: {e}")
