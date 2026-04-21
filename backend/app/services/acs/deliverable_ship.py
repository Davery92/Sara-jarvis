"""Ship a built UI from the sandbox VM to a fresh LXC container for review.

The ACS tool `ship_to_lxc` dispatches here. Flow:

1. Provision a fresh LXC (dev preset) via the existing ContainerProvisioner.
2. rsync source_dir from VM into the LXC at /home/sara/app/.
3. Install runtime deps + start the service per `kind` (static | node).
4. Probe the port until it responds (or give up after a short window).
5. Insert an acs_deliverable row with status='pending_review' and
   auto_destroy_at = now + 7 days.
6. Return a summary dict that gets surfaced to Sara as the tool result.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import uuid
from datetime import timedelta

from sqlalchemy import text

from app.core.timezone import now as local_now
from app.db.session import get_async_session_factory
from app.services.container_provisioner import ContainerProvisioner, ProvisioningError
from app.services.vm_bridge import VMBridge

logger = logging.getLogger(__name__)

# On the VM, the key was installed as id_ed25519 and matches sara_agent.pub
# that the provisioner injects into every LXC's authorized_keys.
VM_SSH_KEY = "~/.ssh/id_ed25519"

# Same options we use elsewhere to skip host-key prompts against ephemeral LXCs.
SSH_OPTS = (
    "-o StrictHostKeyChecking=no "
    "-o UserKnownHostsFile=/dev/null "
    "-o ConnectTimeout=10 "
    "-o BatchMode=yes"
)

LXC_APP_DIR = "/home/sara/app"

SUPPORTED_KINDS = {"static", "node"}

DEFAULT_AUTO_DESTROY_DAYS = 7


def _build_start_command(kind: str, port: int, custom: str | None) -> str:
    """Return the shell command (run inside the LXC) to start the service.

    Wrapped in nohup + backgrounded so the SSH session can return.
    """
    if custom:
        inner = custom
    elif kind == "static":
        inner = f"python3 -m http.server {port} --bind 0.0.0.0"
    elif kind == "node":
        # Respects package.json "start" script; expects the app to honor $PORT.
        inner = f"PORT={port} npm start"
    else:
        raise ValueError(f"unsupported kind: {kind}")

    # setsid detaches the process from SSH's session so the shell returns
    # immediately once it spawns — otherwise SSH waits on the child's fds
    # even though we've redirected them.
    return (
        f"cd {LXC_APP_DIR} && "
        f"setsid nohup sh -c {shlex.quote(inner)} "
        f"> /tmp/app.log 2>&1 < /dev/null & "
        f"echo started pid=$!"
    )


def _install_script(kind: str) -> str | None:
    """Return the install/bootstrap command for the given kind, or None."""
    if kind == "static":
        return None
    if kind == "node":
        # 'research' preset doesn't ship Node; install it before npm install.
        return (
            "if ! command -v npm >/dev/null 2>&1; then "
            "  sudo apt-get -o DPkg::Lock::Timeout=900 install -y -qq nodejs npm; "
            "fi && "
            "if [ -f package.json ]; then "
            "  npm install --omit=dev --no-audit --no-fund; "
            "fi"
        )
    return None


async def _run_on_vm(bridge: VMBridge, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    result = await bridge.execute_command(cmd, timeout=timeout)
    return result.exit_code, result.stdout, result.stderr


async def _ssh_lxc(bridge: VMBridge, ip: str, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a command inside the LXC by SSHing from the VM."""
    ssh_cmd = (
        f"ssh -i {VM_SSH_KEY} {SSH_OPTS} sara@{ip} {shlex.quote(cmd)}"
    )
    return await _run_on_vm(bridge, ssh_cmd, timeout=timeout)


async def _probe_port(bridge: VMBridge, ip: str, port: int, attempts: int = 10, delay: float = 1.5) -> bool:
    """Hit http://ip:port from the VM until it responds or we give up."""
    url = f"http://{ip}:{port}"
    for i in range(attempts):
        rc, _, _ = await _run_on_vm(
            bridge,
            f"curl -sS -o /dev/null -m 3 -w '%{{http_code}}' {url} | grep -qE '^(2|3|4)'",
            timeout=10,
        )
        if rc == 0:
            return True
        await asyncio.sleep(delay)
    return False


async def ship_to_lxc(
    *,
    user_id: str,
    session_id: str | None,
    title: str,
    source_dir: str,
    kind: str,
    port: int = 8080,
    description: str | None = None,
    start_command: str | None = None,
    auto_destroy_days: int = DEFAULT_AUTO_DESTROY_DAYS,
) -> dict:
    """Provision LXC, deploy source_dir, start service, record deliverable.

    Returns a dict the caller can serialize to the tool result.
    """
    if kind not in SUPPORTED_KINDS and not start_command:
        raise ValueError(
            f"kind must be one of {SUPPORTED_KINDS} or provide start_command"
        )

    bridge = VMBridge()

    # 1. Verify source_dir exists on VM
    rc, _, stderr = await _run_on_vm(
        bridge, f"test -d {shlex.quote(source_dir)}", timeout=15
    )
    if rc != 0:
        return {
            "success": False,
            "error": f"source_dir not found on VM: {source_dir}",
            "stderr": stderr[:300],
        }

    # 2. Provision LXC. 'research' preset (python3/git) is plenty for static
    # and for node once we've added Node to it; avoids the multi-minute
    # build-essential + docker install of 'dev'. If a future kind needs
    # build tools, bump this up per kind.
    provisioner = ContainerProvisioner()
    preset = "research"
    try:
        container = await provisioner.provision(
            user_id=user_id,
            session_id=session_id,
            preset=preset,
            persistent=True,
            purpose=f"deliverable: {title}",
        )
    except ProvisioningError as e:
        return {"success": False, "error": f"LXC provisioning failed: {e}"}

    lxc_ip = container.ip
    vmid = container.vmid
    logger.info(f"[ship_to_lxc] provisioned vmid={vmid} ip={lxc_ip} ssh_ready={container.ssh_ready}")

    if not container.ssh_ready:
        return {
            "success": False,
            "vmid": vmid,
            "ip": lxc_ip,
            "error": (
                "LXC provisioned but post-create setup failed — sara user / SSH key not configured. "
                "Check backend logs for _post_create_setup. Container left running for debugging."
            ),
        }

    # 3. Prepare app dir + rsync from VM → LXC
    rc, _, stderr = await _ssh_lxc(bridge, lxc_ip, f"mkdir -p {LXC_APP_DIR}", timeout=30)
    if rc != 0:
        return {
            "success": False,
            "vmid": vmid,
            "ip": lxc_ip,
            "error": f"could not mkdir app dir on LXC: {stderr[:300]}",
        }

    source_trailing = source_dir.rstrip("/") + "/"
    rsync_cmd = (
        f"rsync -az --delete "
        f"-e 'ssh -i {VM_SSH_KEY} {SSH_OPTS}' "
        f"{shlex.quote(source_trailing)} "
        f"sara@{lxc_ip}:{LXC_APP_DIR}/"
    )
    rc, _, stderr = await _run_on_vm(bridge, rsync_cmd, timeout=180)
    if rc != 0:
        return {
            "success": False,
            "vmid": vmid,
            "ip": lxc_ip,
            "error": f"rsync failed: {stderr[:500]}",
        }

    # 4. Install deps (kind-specific)
    install = _install_script(kind)
    if install:
        rc, _, stderr = await _ssh_lxc(
            bridge, lxc_ip, f"cd {LXC_APP_DIR} && {install}", timeout=300
        )
        if rc != 0:
            return {
                "success": False,
                "vmid": vmid,
                "ip": lxc_ip,
                "error": f"dep install failed: {stderr[:500]}",
            }

    # 5. Start service
    try:
        start_cmd = _build_start_command(kind, port, start_command)
    except ValueError as e:
        return {"success": False, "vmid": vmid, "ip": lxc_ip, "error": str(e)}

    # Fire-and-forget: SSH sessions don't reliably detach from backgrounded
    # children even with setsid + full fd redirection, so we use a short
    # timeout and treat a timeout as "probably launched, port probe will tell
    # us the truth". A real failure surfaces when _probe_port fails AND the
    # log tail shows the error.
    rc, _, stderr = await _ssh_lxc(bridge, lxc_ip, start_cmd, timeout=8)
    if rc != 0 and "timed out" not in stderr.lower():
        return {
            "success": False,
            "vmid": vmid,
            "ip": lxc_ip,
            "error": f"service start failed: {stderr[:500]}",
        }

    # 6. Probe port — this is the real health check.
    reachable = await _probe_port(bridge, lxc_ip, port)

    # Grab the tail of the app log regardless — useful either way
    _, log_tail, _ = await _ssh_lxc(
        bridge, lxc_ip, "tail -n 40 /tmp/app.log 2>/dev/null || true", timeout=10
    )

    # 7. Record deliverable
    deliverable_id = str(uuid.uuid4())
    auto_destroy_at = local_now() + timedelta(days=auto_destroy_days)
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO acs_deliverable
                    (id, user_id, session_id, vmid, title, description, kind, ip, port,
                     start_command, built_from, status, created_at, auto_destroy_at)
                VALUES
                    (:id, :uid, :sid, :vmid, :title, :desc, :kind, :ip, :port,
                     :start_cmd, :built_from, 'pending_review', NOW(), :auto_destroy_at)
                """
            ),
            {
                "id": deliverable_id,
                "uid": user_id,
                "sid": session_id,
                "vmid": vmid,
                "title": title,
                "desc": description,
                "kind": kind,
                "ip": lxc_ip,
                "port": port,
                "start_cmd": start_cmd,
                "built_from": source_dir,
                "auto_destroy_at": auto_destroy_at,
            },
        )
        await db.commit()

    url = f"http://{lxc_ip}:{port}"
    return {
        "success": True,
        "deliverable_id": deliverable_id,
        "vmid": vmid,
        "ip": lxc_ip,
        "port": port,
        "url": url,
        "reachable": reachable,
        "kind": kind,
        "title": title,
        "auto_destroy_at": auto_destroy_at.isoformat(),
        "log_tail": log_tail[-1500:] if log_tail else "",
        "message": (
            f"Shipped '{title}' to {url} (vmid={vmid}). "
            f"{'Service reachable.' if reachable else 'Service NOT reachable yet — check log_tail.'} "
            f"Auto-destroys {auto_destroy_at.strftime('%Y-%m-%d')} unless David keeps it."
        ),
    }
