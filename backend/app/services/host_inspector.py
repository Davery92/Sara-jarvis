"""
Host inspector — registry CRUD + remote spec inspection for ManagedHost.

"Sara, check out gpu-box" → resolve the registered host → SSH in (reusing the
VMBridge transport) → run a battery of read-only probes → parse into a
structured spec → persist + render a clean markdown report.

Everything here is read-only on the remote host. No state is mutated remotely;
the worst case is a connection attempt. Auth is SSH-key based (see ManagedHost).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.managed_host import ManagedHost
from app.services.vm_bridge import VMBridge, VMConfig, VMConnectionStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    return (name or "").strip().lower()


def list_hosts(db: Session, user_id: str) -> list[ManagedHost]:
    return (
        db.query(ManagedHost)
        .filter(ManagedHost.user_id == user_id, ManagedHost.active == True)  # noqa: E712
        .order_by(ManagedHost.name)
        .all()
    )


def get_host(db: Session, user_id: str, name: str) -> Optional[ManagedHost]:
    return (
        db.query(ManagedHost)
        .filter(
            ManagedHost.user_id == user_id,
            ManagedHost.name == _norm_name(name),
            ManagedHost.active == True,  # noqa: E712
        )
        .first()
    )


def add_host(
    db: Session,
    user_id: str,
    name: str,
    hostname: str,
    username: str = "sara",
    port: int = 22,
    ssh_key_path: str = "~/.ssh/sara_agent",
    description: Optional[str] = None,
) -> ManagedHost:
    """Create or update (upsert by name) a managed host."""
    name = _norm_name(name)
    existing = get_host(db, user_id, name)
    if existing:
        existing.hostname = hostname
        existing.username = username
        existing.port = port
        existing.ssh_key_path = ssh_key_path
        if description is not None:
            existing.description = description
        existing.active = True
        db.commit()
        db.refresh(existing)
        return existing

    host = ManagedHost(
        user_id=user_id,
        name=name,
        hostname=hostname,
        username=username,
        port=port,
        ssh_key_path=ssh_key_path,
        description=description,
        tags=[],
    )
    db.add(host)
    db.commit()
    db.refresh(host)
    return host


def remove_host(db: Session, user_id: str, name: str) -> bool:
    host = get_host(db, user_id, name)
    if not host:
        return False
    host.active = False
    db.commit()
    return True


def bridge_for(host: ManagedHost) -> VMBridge:
    """Build a VMBridge transport for an arbitrary managed host."""
    return VMBridge(VMConfig(
        host=host.hostname,
        username=host.username,
        ssh_key_path=host.ssh_key_path,
        connect_timeout=10,
    ))


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

# A single batched probe keeps it to one SSH round-trip. Each section is fenced
# with a marker so we can split the combined stdout deterministically.
_PROBE_SCRIPT = r"""
echo '@@HOSTNAME@@'; hostname 2>/dev/null
echo '@@OS@@'; (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -s
echo '@@KERNEL@@'; uname -r 2>/dev/null
echo '@@ARCH@@'; uname -m 2>/dev/null
echo '@@UPTIME@@'; uptime -p 2>/dev/null || uptime 2>/dev/null
echo '@@CPU_MODEL@@'; (lscpu 2>/dev/null | grep -m1 'Model name' | sed 's/Model name:[[:space:]]*//') || echo unknown
echo '@@CPU_COUNT@@'; nproc 2>/dev/null
echo '@@LOADAVG@@'; cat /proc/loadavg 2>/dev/null | awk '{print $1", "$2", "$3}'
echo '@@MEM@@'; free -b 2>/dev/null | awk '/^Mem:/ {print $2" "$3" "$7}'
echo '@@DISK@@'; df -B1 --output=target,size,used,avail -x tmpfs -x devtmpfs -x squashfs -x efivarfs -x overlay 2>/dev/null | tail -n +2
echo '@@DOCKER@@'; (command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}} ({{.Image}}) {{.Status}}' 2>/dev/null) || echo '__none__'
echo '@@GPU@@'; (command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader,nounits 2>/dev/null) || echo '__none__'
echo '@@TOPPROC@@'; ps -eo pcpu,pmem,comm --sort=-pcpu 2>/dev/null | head -n 6 | tail -n +2
echo '@@END@@'
"""


def _split_sections(stdout: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in stdout.splitlines():
        m = re.match(r"^@@([A-Z_]+)@@$", line.strip())
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1)
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None and current != "END":
        sections[current] = "\n".join(buf).strip()
    return sections


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} EB"


def _parse_spec(sections: dict[str, str]) -> dict:
    spec: dict = {}
    spec["hostname"] = sections.get("HOSTNAME") or None
    spec["os"] = sections.get("OS") or None
    spec["kernel"] = sections.get("KERNEL") or None
    spec["arch"] = sections.get("ARCH") or None
    spec["uptime"] = sections.get("UPTIME") or None
    spec["cpu_model"] = sections.get("CPU_MODEL") or None
    try:
        spec["cpu_count"] = int(sections.get("CPU_COUNT", "").strip())
    except (ValueError, TypeError):
        spec["cpu_count"] = None
    spec["loadavg"] = sections.get("LOADAVG") or None

    mem = (sections.get("MEM") or "").split()
    if len(mem) == 3:
        total, used, avail = (int(x) for x in mem)
        spec["mem"] = {
            "total": total, "used": used, "available": avail,
            "total_h": _human_bytes(total), "used_h": _human_bytes(used),
            "available_h": _human_bytes(avail),
            "used_pct": round(used / total * 100) if total else None,
        }
    else:
        spec["mem"] = None

    disks = []
    for line in (sections.get("DISK") or "").splitlines():
        parts = line.split()
        if len(parts) == 4:
            mount, size, used, avail = parts
            # Skip pseudo / firmware mounts that aren't real storage.
            if mount.startswith(("/sys", "/proc", "/run", "/dev")):
                continue
            try:
                size_i, used_i, avail_i = int(size), int(used), int(avail)
            except ValueError:
                continue
            disks.append({
                "mount": mount,
                "size_h": _human_bytes(size_i), "used_h": _human_bytes(used_i),
                "avail_h": _human_bytes(avail_i),
                "used_pct": round(used_i / size_i * 100) if size_i else None,
            })
    spec["disks"] = disks

    docker_raw = sections.get("DOCKER", "")
    spec["docker"] = (
        [] if docker_raw.strip() == "__none__"
        else [l for l in docker_raw.splitlines() if l.strip()]
    )
    spec["docker_available"] = docker_raw.strip() != "__none__"

    gpu_raw = sections.get("GPU", "")
    gpus = []
    if gpu_raw.strip() != "__none__":
        for line in gpu_raw.splitlines():
            cols = [c.strip() for c in line.split(",")]
            if len(cols) == 4:
                gpus.append({
                    "name": cols[0], "mem_total_mb": cols[1],
                    "mem_used_mb": cols[2], "util_pct": cols[3],
                })
    spec["gpus"] = gpus

    spec["top_processes"] = [
        l.strip() for l in (sections.get("TOPPROC") or "").splitlines() if l.strip()
    ]
    return spec


async def inspect_host(db: Session, host: ManagedHost) -> dict:
    """SSH into the host, gather specs, persist + return the structured spec.

    The returned dict always has a 'status' key. On failure, 'error' explains.
    """
    bridge = bridge_for(host)
    status = await bridge.test_connection()
    if status != VMConnectionStatus.CONNECTED:
        spec = {"status": status.value, "error": _status_hint(status, host)}
        _persist(db, host, status.value, None)
        return spec

    result = await bridge.execute_command(_PROBE_SCRIPT, timeout=45)
    if result.timed_out:
        _persist(db, host, "error", None)
        return {"status": "error", "error": "Inspection commands timed out after 45s."}

    sections = _split_sections(result.stdout)
    spec = _parse_spec(sections)
    spec["status"] = "connected"
    _persist(db, host, "connected", spec)
    return spec


def _persist(db: Session, host: ManagedHost, status: str, spec: Optional[dict]):
    host.last_status = status
    host.last_seen_at = datetime.now(timezone.utc)
    if spec is not None:
        host.last_inspection = spec
    db.commit()


def _status_hint(status: VMConnectionStatus, host: ManagedHost) -> str:
    if status == VMConnectionStatus.UNREACHABLE:
        return (
            f"Couldn't reach {host.hostname}:{host.port} — the host may be offline "
            f"or the address/port is wrong."
        )
    if status == VMConnectionStatus.AUTH_FAILED:
        return (
            f"Connected to {host.hostname} but SSH auth failed. Add Sara's public key "
            f"({host.ssh_key_path}.pub) to ~{host.username}/.ssh/authorized_keys on that host."
        )
    return f"SSH error connecting to {host.hostname}."


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_report(host: ManagedHost, spec: dict) -> str:
    """Deterministic markdown report — reliable, no LLM round-trip needed."""
    if spec.get("status") != "connected":
        return f"❌ **{host.name}** — {spec.get('error', 'inspection failed')}"

    lines = [f"### 🖥️ {host.name} — `{host.username}@{host.hostname}`"]
    if host.description:
        lines.append(f"_{host.description}_")
    lines.append("")

    osline = spec.get("os") or "unknown OS"
    if spec.get("arch"):
        osline += f" ({spec['arch']})"
    lines.append(f"- **OS:** {osline}")
    if spec.get("kernel"):
        lines.append(f"- **Kernel:** {spec['kernel']}")
    if spec.get("uptime"):
        lines.append(f"- **Uptime:** {spec['uptime']}")

    cpu = spec.get("cpu_model") or "CPU"
    if spec.get("cpu_count"):
        cpu += f" — {spec['cpu_count']} cores"
    if spec.get("loadavg"):
        cpu += f" (load {spec['loadavg']})"
    lines.append(f"- **CPU:** {cpu}")

    mem = spec.get("mem")
    if mem:
        lines.append(
            f"- **Memory:** {mem['used_h']} / {mem['total_h']} used "
            f"({mem['used_pct']}%), {mem['available_h']} available"
        )

    for d in spec.get("disks", []):
        lines.append(
            f"- **Disk {d['mount']}:** {d['used_h']} / {d['size_h']} used "
            f"({d['used_pct']}%), {d['avail_h']} free"
        )

    gpus = spec.get("gpus", [])
    for g in gpus:
        lines.append(
            f"- **GPU:** {g['name']} — {g['mem_used_mb']}/{g['mem_total_mb']} MB, "
            f"{g['util_pct']}% util"
        )

    docker = spec.get("docker", [])
    if spec.get("docker_available"):
        if docker:
            lines.append(f"- **Docker:** {len(docker)} running")
            for c in docker[:8]:
                lines.append(f"    - {c}")
        else:
            lines.append("- **Docker:** installed, no running containers")

    return "\n".join(lines)
