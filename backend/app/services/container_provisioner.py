"""
Container Provisioner — high-level service for dynamic LXC provisioning.

Combines ProxmoxClient + DB tracking + SSH setup for ACS sessions.
"""

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from app.core.config import settings
from app.services.proxmox_client import (
    ProxmoxClient,
    ProxmoxError,
    CONTAINER_PRESETS,
)

logger = logging.getLogger(__name__)


@dataclass
class ContainerInfo:
    vmid: int
    ip: str
    hostname: str
    preset: str
    ssh_ready: bool
    cores: int
    memory_mb: int
    disk_gb: int


class ProvisioningError(Exception):
    """Raised when container provisioning fails."""


class ContainerProvisioner:
    """High-level container lifecycle management."""

    def __init__(self):
        self.pve = ProxmoxClient()

    async def provision(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        preset: str = "research",
        persistent: bool = False,
        purpose: Optional[str] = None,
    ) -> ContainerInfo:
        """Provision a new LXC container with SSH access.

        1. Check resource limits
        2. Allocate VMID
        3. Create LXC via PVE API
        4. Wait for start + IP
        5. Post-create setup (sara user, SSH key)
        6. Insert DB record
        7. Return ContainerInfo
        """
        # Validate preset
        preset_config = CONTAINER_PRESETS.get(preset)
        if not preset_config:
            raise ProvisioningError(
                f"Unknown preset '{preset}'. Available: {list(CONTAINER_PRESETS.keys())}"
            )

        # Resource guard
        allowed, reason = await self.pve.check_resource_limits()
        if not allowed:
            raise ProvisioningError(f"Resource limit reached: {reason}")

        # Allocate VMID
        vmid = await self.pve.get_next_vmid()
        hostname = f"sara-{preset}-{vmid}"
        cores = preset_config["cores"]
        memory_mb = preset_config["memory_mb"]
        disk_gb = preset_config["disk_gb"]

        # Read SSH public key
        ssh_keys = None
        key_path = os.path.expanduser(settings.proxmox_ssh_public_key_path)
        if os.path.exists(key_path):
            with open(key_path) as f:
                ssh_keys = f.read().strip()

        # Create the container
        logger.info(f"Provisioning container: vmid={vmid}, preset={preset}, hostname={hostname}")
        try:
            upid = await self.pve.create_lxc(
                vmid=vmid,
                template=preset_config["ostemplate"],
                hostname=hostname,
                cores=cores,
                memory_mb=memory_mb,
                disk_gb=disk_gb,
                ssh_keys=ssh_keys,
                start=True,
            )
            await self.pve._wait_for_task(upid, timeout=120.0)
        except ProxmoxError as e:
            raise ProvisioningError(f"LXC creation failed: {e}")

        # Wait for IP assignment
        ip = await self.pve.get_container_ip(vmid, timeout=30.0)
        if not ip:
            logger.warning(f"Container {vmid} created but no IP assigned, attempting cleanup")
            try:
                await self._destroy_container(vmid)
            except Exception:
                pass
            raise ProvisioningError(f"Container {vmid} failed to get IP address")

        # Post-create setup: create sara user, inject SSH key
        ssh_ready = await self._post_create_setup(vmid, ssh_keys, preset_config)

        # Insert DB record
        container_id = str(uuid.uuid4())
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                INSERT INTO proxmox_container
                    (id, vmid, user_id, session_id, hostname, ip_address, preset,
                     cores, memory_mb, disk_gb, persistent, purpose, status, created_at, last_used_at)
                VALUES
                    (:id, :vmid, :uid, :sid, :hostname, :ip, :preset,
                     :cores, :mem, :disk, :persistent, :purpose, 'running', NOW(), NOW())
            """), {
                "id": container_id, "vmid": vmid, "uid": user_id, "sid": session_id,
                "hostname": hostname, "ip": ip, "preset": preset,
                "cores": cores, "mem": memory_mb, "disk": disk_gb,
                "persistent": persistent, "purpose": purpose,
            })
            await db.commit()

        logger.info(f"Container provisioned: vmid={vmid}, ip={ip}, ssh_ready={ssh_ready}")
        return ContainerInfo(
            vmid=vmid, ip=ip, hostname=hostname, preset=preset,
            ssh_ready=ssh_ready, cores=cores, memory_mb=memory_mb, disk_gb=disk_gb,
        )

    async def _post_create_setup(
        self, vmid: int, ssh_keys: Optional[str], preset_config: dict
    ) -> bool:
        """Run post-create setup inside the container via lxc-attach."""
        try:
            # Install packages if specified
            packages = preset_config.get("packages", [])
            if packages:
                pkg_str = " ".join(packages)
                # Give the container a moment to initialize networking
                import asyncio
                await asyncio.sleep(3)
                await self.pve.exec_in_container(
                    vmid,
                    f"apt-get update -qq && apt-get install -y -qq {pkg_str} openssh-client openssh-server",
                    timeout=120.0,
                )
            else:
                # Minimal preset (Alpine) — still needs SSH server
                import asyncio
                await asyncio.sleep(3)
                await self.pve.exec_in_container(
                    vmid,
                    "apk add --no-cache openssh-server openssh-client || "
                    "apt-get update -qq && apt-get install -y -qq openssh-server openssh-client",
                    timeout=120.0,
                )

            # Ensure SSH daemon is running
            await self.pve.exec_in_container(
                vmid,
                "mkdir -p /run/sshd && "
                "(ssh-keygen -A 2>/dev/null || true) && "
                "(service ssh start 2>/dev/null || /usr/sbin/sshd 2>/dev/null || true)",
                timeout=15.0,
            )

            # Create sara user with sudo access
            cmds = [
                "useradd -m -s /bin/bash sara 2>/dev/null || true",
                "mkdir -p /home/sara/.ssh",
                "chmod 700 /home/sara/.ssh",
            ]

            # Always try to read the public key if not passed
            if not ssh_keys:
                key_path = os.path.expanduser(settings.proxmox_ssh_public_key_path)
                if os.path.exists(key_path):
                    with open(key_path) as f:
                        ssh_keys = f.read().strip()

            if ssh_keys:
                # Escape the key for shell
                safe_key = ssh_keys.replace("'", "'\\''")
                cmds.append(f"echo '{safe_key}' > /home/sara/.ssh/authorized_keys")
                cmds.append("chmod 600 /home/sara/.ssh/authorized_keys")
            else:
                logger.error(f"No SSH public key available for container {vmid} — SSH access will fail")

            # Inject SSH private key so Sara can SSH out to GPU host and other servers
            private_key_path = os.path.expanduser(settings.gpu_host_ssh_key)
            if os.path.exists(private_key_path):
                with open(private_key_path) as f:
                    private_key = f.read().strip()
                safe_privkey = private_key.replace("'", "'\\''")
                cmds.append(f"echo '{safe_privkey}' > /home/sara/.ssh/id_ed25519")
                cmds.append("chmod 600 /home/sara/.ssh/id_ed25519")

            # Add SSH config for GPU host to avoid host key prompts
            gpu_host = settings.gpu_host
            gpu_user = settings.gpu_host_user
            ssh_config = (
                f"Host gpu\\n"
                f"  HostName {gpu_host}\\n"
                f"  User {gpu_user}\\n"
                f"  IdentityFile ~/.ssh/id_ed25519\\n"
                f"  StrictHostKeyChecking no\\n"
                f"  UserKnownHostsFile /dev/null\\n"
            )
            cmds.append(f"echo -e '{ssh_config}' > /home/sara/.ssh/config")
            cmds.append("chmod 600 /home/sara/.ssh/config")

            cmds.extend([
                "chown -R sara:sara /home/sara/.ssh",
                "echo 'sara ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/sara",
                "mkdir -p /home/sara/autonomous",
                "chown sara:sara /home/sara/autonomous",
            ])

            # Write environment hints so Sara knows about the GPU host
            env_lines = (
                f"GPU_HOST={gpu_host}\\n"
                f"GPU_USER={gpu_user}\\n"
                f"GPU_LLM_URL={settings.gpu_host_llm_url}\\n"
                f"GPU_LLM_MODEL={settings.gpu_host_llm_model}\\n"
            )
            cmds.append(f"echo -e '{env_lines}' > /home/sara/.gpu_env")
            cmds.append("chown sara:sara /home/sara/.gpu_env")
            cmds.append("echo 'source ~/.gpu_env' >> /home/sara/.bashrc")

            combined = " && ".join(cmds)
            await self.pve.exec_in_container(vmid, combined, timeout=30.0)
            return True
        except Exception as e:
            logger.warning(f"Post-create setup partially failed for vmid={vmid}: {e}")
            return False

    async def destroy(self, vmid: int) -> bool:
        """Stop and destroy a container, update DB."""
        try:
            await self._destroy_container(vmid)

            # Update DB
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE proxmox_container
                    SET status = 'destroyed', destroyed_at = NOW()
                    WHERE vmid = :vmid AND status != 'destroyed'
                """), {"vmid": vmid})
                await db.commit()

            logger.info(f"Container destroyed: vmid={vmid}")
            return True
        except Exception as e:
            logger.error(f"Failed to destroy container vmid={vmid}: {e}")
            return False

    async def _destroy_container(self, vmid: int):
        """Stop then destroy a container via PVE API."""
        try:
            status = await self.pve.get_container_status(vmid)
            if status.get("status") == "running":
                upid = await self.pve.stop_container(vmid)
                await self.pve._wait_for_task(upid, timeout=30.0)
        except ProxmoxError:
            pass  # May already be stopped

        upid = await self.pve.destroy_container(vmid)
        await self.pve._wait_for_task(upid, timeout=60.0)

    async def list_active(self, user_id: str) -> list[dict]:
        """List active containers for a user."""
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT vmid, hostname, ip_address, preset, cores, memory_mb,
                       disk_gb, persistent, purpose, status, created_at, last_used_at
                FROM proxmox_container
                WHERE user_id = :uid AND status IN ('creating', 'running')
                ORDER BY created_at DESC
            """), {"uid": user_id})
            rows = result.mappings().all()
            return [dict(r) for r in rows]

    async def cleanup_session(self, session_id: str, skip_vmids: set = None) -> int:
        """Destroy all ephemeral containers from a session. Returns count destroyed.

        Args:
            skip_vmids: Set of VMID strings to preserve (persistent containers).
        """
        from app.db.session import get_async_session_factory
        skip_vmids = skip_vmids or set()
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT vmid FROM proxmox_container
                WHERE session_id = :sid AND persistent = FALSE
                  AND status IN ('creating', 'running')
            """), {"sid": session_id})
            vmids = [row[0] for row in result.fetchall() if str(row[0]) not in skip_vmids]

        destroyed = 0
        for vmid in vmids:
            if await self.destroy(vmid):
                destroyed += 1
        if destroyed:
            logger.info(f"Session cleanup: destroyed {destroyed} containers for session {session_id}")
        return destroyed

    async def cleanup_stale(self, max_idle_hours: int = 24) -> int:
        """Destroy ephemeral containers idle for more than max_idle_hours.

        Also reconciles DB state with actual Proxmox state — marks containers
        as 'destroyed' if they no longer exist or are stopped on Proxmox.
        """
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        # Reconcile DB vs Proxmox state first
        await self._reconcile_container_state()

        async with async_session() as db:
            result = await db.execute(text("""
                SELECT vmid FROM proxmox_container
                WHERE persistent = FALSE
                  AND status IN ('creating', 'running')
                  AND last_used_at < NOW() - INTERVAL ':hours hours'
            """.replace(":hours", str(int(max_idle_hours)))))
            vmids = [row[0] for row in result.fetchall()]

        destroyed = 0
        for vmid in vmids:
            if await self.destroy(vmid):
                destroyed += 1
        if destroyed:
            logger.info(f"Stale cleanup: destroyed {destroyed} idle containers (>{max_idle_hours}h)")
        return destroyed

    async def _reconcile_container_state(self):
        """Check actual Proxmox container status and update DB for any that are stopped/gone."""
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            result = await db.execute(text("""
                SELECT vmid FROM proxmox_container
                WHERE status IN ('creating', 'running')
            """))
            db_vmids = [row[0] for row in result.fetchall()]

        if not db_vmids:
            return

        # Get actual state from Proxmox
        try:
            pve_containers = await self.pve.list_containers()
            pve_status = {c["vmid"]: c["status"] for c in pve_containers}
        except Exception as e:
            logger.debug(f"Reconciliation skipped — Proxmox API unavailable: {e}")
            return

        stale_vmids = []
        for vmid in db_vmids:
            actual = pve_status.get(vmid)
            if actual is None or actual == "stopped":
                stale_vmids.append(vmid)

        if stale_vmids:
            async with async_session() as db:
                for vmid in stale_vmids:
                    status = pve_status.get(vmid)
                    if status is None:
                        # Container doesn't exist on Proxmox at all
                        await db.execute(text("""
                            UPDATE proxmox_container
                            SET status = 'destroyed', destroyed_at = NOW()
                            WHERE vmid = :vmid AND status != 'destroyed'
                        """), {"vmid": vmid})
                    else:
                        # Container exists but is stopped
                        await db.execute(text("""
                            UPDATE proxmox_container
                            SET status = 'stopped'
                            WHERE vmid = :vmid AND status IN ('creating', 'running')
                        """), {"vmid": vmid})
                await db.commit()
            logger.info(f"Reconciled {len(stale_vmids)} containers: {stale_vmids}")

    async def touch(self, vmid: int):
        """Update last_used_at timestamp for a container."""
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                UPDATE proxmox_container SET last_used_at = NOW() WHERE vmid = :vmid
            """), {"vmid": vmid})
            await db.commit()
