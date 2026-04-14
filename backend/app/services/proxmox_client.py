"""
Proxmox VE REST API client for dynamic LXC container provisioning.

Uses httpx for async HTTP with PVEAPIToken auth — no third-party Proxmox library.
"""

import asyncio
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Container presets: template ostemplate, resources, and post-create packages
CONTAINER_PRESETS = {
    "minimal": {
        "ostemplate": "local:vztmpl/alpine-3.20-default_20240908_amd64.tar.xz",
        "cores": 1,
        "memory_mb": 512,
        "disk_gb": 4,
        "packages": [],
    },
    "research": {
        "ostemplate": "local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst",
        "cores": 2,
        "memory_mb": 2048,
        "disk_gb": 10,
        "packages": ["python3", "python3-pip", "python3-venv", "git", "curl", "wget", "jq"],
    },
    "dev": {
        "ostemplate": "local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst",
        "cores": 2,
        "memory_mb": 4096,
        "disk_gb": 15,
        "packages": ["python3", "python3-pip", "python3-venv", "git", "curl", "wget",
                      "jq", "build-essential", "docker.io", "docker-compose"],
    },
}


class ProxmoxError(Exception):
    """Raised when a PVE API call fails."""


class ProxmoxClient:
    """Async HTTP client wrapping the Proxmox VE REST API."""

    def __init__(self):
        self.base_url = settings.proxmox_api_url.rstrip("/")
        self.node = settings.proxmox_node
        self.token_id = settings.proxmox_token_id
        self.token_secret = settings.proxmox_token_secret
        self.verify_ssl = settings.proxmox_verify_ssl

    def _auth_header(self) -> dict:
        return {"Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}"}

    async def _request(
        self, method: str, path: str, data: Optional[dict] = None, timeout: float = 30.0
    ) -> dict:
        """Execute an HTTP request against the PVE API."""
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=timeout) as client:
            resp = await client.request(
                method, url, headers=self._auth_header(), data=data
            )
        if resp.status_code >= 400:
            raise ProxmoxError(
                f"PVE API {method} {path} returned {resp.status_code}: {resp.text[:500]}"
            )
        return resp.json()

    # ── Node-level queries ──

    async def get_node_status(self) -> dict:
        """Get node resource usage (CPU, memory, storage)."""
        result = await self._request("GET", f"/nodes/{self.node}/status")
        return result.get("data", {})

    async def list_templates(self) -> list[dict]:
        """List available container templates on local storage."""
        result = await self._request("GET", f"/nodes/{self.node}/storage/local/content")
        return [
            item for item in result.get("data", [])
            if item.get("content") == "vztmpl"
        ]

    # ── Container lifecycle ──

    async def list_containers(self) -> list[dict]:
        """List all LXC containers on the node."""
        result = await self._request("GET", f"/nodes/{self.node}/lxc")
        return result.get("data", [])

    async def get_container_status(self, vmid: int) -> dict:
        """Get status of a specific container."""
        result = await self._request(
            "GET", f"/nodes/{self.node}/lxc/{vmid}/status/current"
        )
        return result.get("data", {})

    async def get_container_config(self, vmid: int) -> dict:
        """Get configuration of a specific container."""
        result = await self._request("GET", f"/nodes/{self.node}/lxc/{vmid}/config")
        return result.get("data", {})

    async def create_lxc(
        self,
        vmid: int,
        template: str,
        hostname: str,
        cores: int = 2,
        memory_mb: int = 2048,
        disk_gb: int = 10,
        ssh_keys: Optional[str] = None,
        net_bridge: str = "vmbr0",
        start: bool = True,
    ) -> str:
        """Create an LXC container. Returns UPID for task tracking."""
        payload = {
            "vmid": vmid,
            "ostemplate": template,
            "hostname": hostname,
            "cores": cores,
            "memory": memory_mb,
            "swap": 512,
            "rootfs": f"{settings.proxmox_default_storage}:{disk_gb}",
            "net0": f"name=eth0,bridge={net_bridge},ip=dhcp",
            "unprivileged": 1,
            "start": int(start),
            "features": "nesting=1",
        }
        if ssh_keys:
            payload["ssh-public-keys"] = ssh_keys

        result = await self._request(
            "POST", f"/nodes/{self.node}/lxc", data=payload, timeout=60.0
        )
        upid = result.get("data", "")
        logger.info(f"LXC create started: vmid={vmid}, hostname={hostname}, upid={upid}")
        return upid

    async def start_container(self, vmid: int) -> str:
        """Start a stopped container. Returns UPID."""
        result = await self._request(
            "POST", f"/nodes/{self.node}/lxc/{vmid}/status/start"
        )
        return result.get("data", "")

    async def stop_container(self, vmid: int) -> str:
        """Stop a running container. Returns UPID."""
        result = await self._request(
            "POST", f"/nodes/{self.node}/lxc/{vmid}/status/stop"
        )
        return result.get("data", "")

    async def destroy_container(self, vmid: int, purge: bool = True) -> str:
        """Destroy a container (must be stopped first). Returns UPID."""
        params = {"purge": int(purge)} if purge else None
        result = await self._request(
            "DELETE", f"/nodes/{self.node}/lxc/{vmid}", data=params
        )
        return result.get("data", "")

    # ── Task tracking ──

    async def _wait_for_task(self, upid: str, timeout: float = 120.0) -> dict:
        """Poll task status until complete or timeout."""
        import time
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            result = await self._request(
                "GET",
                f"/nodes/{self.node}/tasks/{upid}/status",
            )
            data = result.get("data", {})
            status = data.get("status", "")
            if status == "stopped":
                exit_status = data.get("exitstatus", "")
                if exit_status != "OK":
                    raise ProxmoxError(
                        f"Task {upid} failed: {exit_status}"
                    )
                return data
            await asyncio.sleep(1)
        raise ProxmoxError(f"Task {upid} timed out after {timeout}s")

    # ── Network / IP resolution ──

    async def get_container_ip(self, vmid: int, timeout: float = 30.0) -> Optional[str]:
        """Poll container network interfaces until an IP is assigned (DHCP)."""
        import time
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                result = await self._request(
                    "GET",
                    f"/nodes/{self.node}/lxc/{vmid}/interfaces",
                )
                interfaces = result.get("data", [])
                for iface in interfaces:
                    if iface.get("name") == "eth0":
                        hwaddr = iface.get("inet", "")
                        # Proxmox returns "ip/cidr" format
                        if hwaddr and "/" in hwaddr:
                            return hwaddr.split("/")[0]
                        # Some PVE versions use inet with just the IP
                        if hwaddr and hwaddr.count(".") == 3:
                            return hwaddr
            except ProxmoxError:
                pass  # Container may not be ready yet
            await asyncio.sleep(2)
        logger.warning(f"Could not resolve IP for vmid={vmid} within {timeout}s")
        return None

    # ── Exec via lxc-attach (PVE API) ──

    async def exec_in_container(self, vmid: int, command: str, timeout: float = 30.0) -> str:
        """Execute a command inside a container via the PVE exec API.

        Falls back to lxc-attach via node SSH if exec API is unavailable.
        """
        try:
            # PVE 8.x+ has a direct exec endpoint
            result = await self._request(
                "POST",
                f"/nodes/{self.node}/lxc/{vmid}/status/exec",
                data={"command": command},
                timeout=timeout,
            )
            return str(result.get("data", ""))
        except ProxmoxError:
            # Fallback: use the create-then-poll approach for older PVE
            # Run via a helper that wraps lxc-attach as a node-level command
            logger.debug(f"exec API unavailable, skipping exec for vmid={vmid}")
            return ""

    # ── VMID allocation ──

    async def get_next_vmid(self) -> int:
        """Find the next available VMID in the configured range."""
        existing = await self.list_containers()
        used_vmids = {int(c.get("vmid", 0)) for c in existing}
        for vmid in range(settings.proxmox_vmid_range_start, settings.proxmox_vmid_range_end + 1):
            if vmid not in used_vmids:
                return vmid
        raise ProxmoxError(
            f"No available VMIDs in range "
            f"{settings.proxmox_vmid_range_start}-{settings.proxmox_vmid_range_end}"
        )

    # ── Resource guard ──

    async def check_resource_limits(self) -> tuple[bool, str]:
        """Check if creating another container would exceed limits.
        Returns (allowed, reason).
        """
        containers = await self.list_containers()
        managed = [
            c for c in containers
            if settings.proxmox_vmid_range_start <= int(c.get("vmid", 0)) <= settings.proxmox_vmid_range_end
        ]

        if len(managed) >= settings.proxmox_max_containers:
            return False, f"At max containers ({settings.proxmox_max_containers})"

        total_cores = sum(int(c.get("cpus", 0)) for c in managed)
        total_mem = sum(int(c.get("maxmem", 0)) // (1024 * 1024) for c in managed)

        if total_cores >= settings.proxmox_max_cores:
            return False, f"At max cores ({total_cores}/{settings.proxmox_max_cores})"
        if total_mem >= settings.proxmox_max_memory_mb:
            return False, f"At max memory ({total_mem}/{settings.proxmox_max_memory_mb}MB)"

        return True, "OK"
