"""
Body-capability registry (SINGULAR_SARA_MASTER_PLAN §4.4/§C7).

"Distinguish VM workshop, `acs-tool-runner`, managed hosts, and Proxmox
sandboxes in body capability records." Read-mostly service over the new
`body_capability` table — a durable record of what execution bodies exist
and what they can do, separate from any single body's identity/prompt (the
plan is explicit that the VM must stop being a second brain, not stop being
a workshop).

Populated today only by the VM workshop's heartbeat (see the additive
`capabilities` field on `/api/acs/v2/heartbeat`'s `HeartbeatIn`). Managed
hosts and Proxmox sandboxes already report status elsewhere
(`managed_host.last_status`, Proxmox provisioning records) and get folded in
as a later, deliberate step — not invented here without a real source.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_capability(
    db: AsyncSession,
    name: str,
    kind: str,
    version: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record/refresh one body's capability row. Caller commits."""
    import json

    await db.execute(text("""
        INSERT INTO body_capability (name, kind, version, capabilities, capability_metadata, last_seen_at, updated_at)
        VALUES (:name, :kind, :version, CAST(:capabilities AS jsonb), CAST(:metadata AS jsonb), NOW(), NOW())
        ON CONFLICT (name) DO UPDATE SET
            kind = EXCLUDED.kind,
            version = EXCLUDED.version,
            capabilities = EXCLUDED.capabilities,
            capability_metadata = EXCLUDED.capability_metadata,
            last_seen_at = NOW(),
            updated_at = NOW()
    """), {
        "name": name,
        "kind": kind,
        "version": version,
        "capabilities": json.dumps(capabilities or []),
        "metadata": json.dumps(metadata or {}),
    })


async def list_capabilities(db: AsyncSession, stale_after_seconds: int = 900) -> List[Dict[str, Any]]:
    """Every known body, with a computed `alive` flag (seen within
    `stale_after_seconds` — default 15 min, matching the daemon's own
    silence threshold in `body_sense._DAEMON_SILENT_SECONDS`)."""
    rows = (await db.execute(text("""
        SELECT name, kind, version, capabilities, capability_metadata, last_seen_at,
               EXTRACT(EPOCH FROM (NOW() - last_seen_at)) AS age_seconds
        FROM body_capability
        ORDER BY kind, name
    """))).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        age = d.pop("age_seconds", None)
        d["alive"] = age is not None and age <= stale_after_seconds
        out.append(d)
    return out
