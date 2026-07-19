"""
Fleet tools — Sara's read-only window into every machine David owns.

  * ``fleet_status`` — the fleet digest, or one host's live snapshot + open alerts.
  * ``fleet_diag`` — run a single whitelisted, read-only diagnostic command on an
    agent-equipped host and return its output. The whitelist summary is embedded in
    the tool description so the model proposes only runnable commands.

Both are safe from chat *and* the ACS daemon: fleet_diag is read-only, audited
(every call is a ``host_diag_command`` row), and re-validated by the agent on the
box itself, so it needs no ``requires_user_origin`` gate.
"""

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from app.models.managed_host import ManagedHost
from app.models import host_diag_command as hdc
from app.models.host_diag_command import HostDiagCommand
from app.services.fleet import whitelist as fleet_whitelist
from app.services import fleet_context


def _resolve(db: Session, user_id: str, name: str):
    return (db.query(ManagedHost)
            .filter(ManagedHost.user_id == user_id,
                    ManagedHost.name == (name or "").strip().lower(),
                    ManagedHost.active == True)  # noqa: E712
            .first())


class FleetStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "fleet_status"

    @property
    def description(self) -> str:
        return (
            "Check the health of David's machines (his 'fleet'). Call with no host "
            "for a fleet-wide digest (how many are online, any open alerts like disk "
            "or memory pressure). Pass a host name for that machine's latest snapshot "
            "(CPU, memory, disks, load, temperature, uptime) and its open alerts. "
            "Read-only and instant — data comes from agents that push telemetry every "
            "few minutes."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string",
                         "description": "Optional machine name (e.g. 'jetson'). Omit for the whole fleet."},
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        host_name = (kwargs.get("host") or "").strip()
        db: Session = next(get_db())
        try:
            if not host_name:
                digest = fleet_context.fleet_digest(db, user_id)
                if not digest:
                    return ToolResult(success=True, data={"hosts": 0},
                                      message="No fleet agents are enrolled yet. "
                                              "Say 'add a machine' or open Machines → Add machine to enroll one.")
                return ToolResult(success=True, data={"digest": digest}, message=digest)

            host = _resolve(db, user_id, host_name)
            if not host:
                return ToolResult(success=False, message=f"No machine named '{host_name}' is registered.")
            if host.transport not in ("agent", "both"):
                return ToolResult(success=False,
                                  message=f"'{host.name}' is SSH-only (no fleet agent). Use host inspection instead.")

            snap = host.agent_snapshot or {}
            from app.models.host_alert import HostAlert
            alerts = (db.query(HostAlert)
                      .filter(HostAlert.host_id == host.id, HostAlert.state == "firing")
                      .all())
            data = {
                "host": host.name,
                "snapshot": snap,
                "open_alerts": [{"rule": a.rule, "severity": a.severity, "detail": a.detail} for a in alerts],
            }
            mem = (snap.get("mem") or {})
            summary = (f"{host.name}: cpu {snap.get('cpu_pct')}%, mem {mem.get('used_pct')}%, "
                       f"load {snap.get('load1')}, {len(alerts)} open alert(s)")
            return ToolResult(success=True, data=data, message=summary)
        finally:
            db.close()


class FleetDiagTool(BaseTool):
    @property
    def name(self) -> str:
        return "fleet_diag"

    @property
    def description(self) -> str:
        return (
            "Run ONE read-only diagnostic command on an agent-equipped machine and get "
            "its output. Use this to investigate ('why is the sara VM's disk filling "
            "up?' → df / du; 'why is it slow?' → top / ps; check a service → "
            "systemctl status / journalctl). " + fleet_whitelist.WHITELIST_SUMMARY +
            " If a command is denied, the reason is returned — pick a whitelisted "
            "alternative. Never attempts to change anything."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Machine name (e.g. 'sara-vm')."},
                "command": {"type": "string",
                            "description": "A single read-only command, e.g. 'df -h' or "
                                           "'journalctl -u nginx -n 100'. No pipes or redirection."},
            },
            "required": ["host", "command"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        host_name = (kwargs.get("host") or "").strip()
        command = (kwargs.get("command") or "").strip()
        origin = kwargs.get("_origin") or "chat"
        if not host_name or not command:
            return ToolResult(success=False, message="Both 'host' and 'command' are required.")

        db: Session = next(get_db())
        try:
            host = _resolve(db, user_id, host_name)
            if not host:
                return ToolResult(success=False, message=f"No machine named '{host_name}' is registered.")
            if host.transport not in ("agent", "both"):
                return ToolResult(success=False,
                                  message=f"'{host.name}' has no fleet agent (SSH-only).")

            # Layer 1: server-side whitelist.
            ok, reason, argv = fleet_whitelist.validate_command(command)
            if not ok:
                db.add(HostDiagCommand(host_id=host.id, user_id=user_id, requested_by=origin,
                                       argv=[command], status=hdc.DENIED_SERVER, denied_reason=reason))
                db.commit()
                return ToolResult(success=False,
                                  message=f"Command denied (read-only policy): {reason}")

            cmd = HostDiagCommand(host_id=host.id, user_id=user_id, requested_by=origin,
                                  argv=argv, status=hdc.PENDING)
            db.add(cmd)
            db.commit()
            db.refresh(cmd)
            cmd_id = cmd.id
        finally:
            db.close()

        # Wait for the agent to long-poll, run, and post the result.
        import asyncio
        from datetime import datetime, timezone, timedelta
        deadline = datetime.now(timezone.utc) + timedelta(seconds=35)
        while datetime.now(timezone.utc) < deadline:
            await asyncio.sleep(0.5)
            db = next(get_db())
            try:
                cmd = db.query(HostDiagCommand).filter(HostDiagCommand.id == cmd_id).first()
                if cmd and cmd.status in (hdc.DONE, hdc.DENIED_AGENT, hdc.TIMEOUT, hdc.LOST):
                    if cmd.status == hdc.DONE:
                        out = (cmd.stdout or "").strip() or "(no output)"
                        return ToolResult(success=True,
                                          data={"argv": cmd.argv, "exit_code": cmd.exit_code,
                                                "stdout": cmd.stdout, "stderr": cmd.stderr},
                                          message=out[:6000])
                    if cmd.status == hdc.DENIED_AGENT:
                        return ToolResult(success=False,
                                          message=f"The agent refused the command: {cmd.denied_reason}")
                    return ToolResult(success=False, message=f"Command {cmd.status}.")
            finally:
                db.close()

        return ToolResult(success=False,
                          message=f"'{host_name}' didn't answer in time — it may be offline.")
