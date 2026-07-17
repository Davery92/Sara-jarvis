## Memory State (Session 1 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203. Single-node."
infra.proxmox.backups: "Nightly vzdump to TrueNAS."
infra.proxmox.backups.retention: "7-day ZFS snapshot rotation. ~700GB."
infra.proxmox.vm_sizes: "Sara VM ~40GB, Jarvis VM ~60GB."
infra.gpu_passthrough_vm: "10.185.1.210, GTX 1070, Gemma 4."
```

## SESSION 1

### Turn 1

**David:** we talked about Proxmox VM provisioning a while back. I'm setting up a new VM for a dedicated Redis instance. remind me of the current VM layout

**Sara (internal generation stream):**

<mem_read key="infra.proxmox*">
  <mem_result>10.185.1.203. Sara VM at 10.185.1.176 (~40GB). Jarvis orchestrator at 10.185.1.180 (~60GB). GPU passthrough VM at 10.185.1.210. Backups: nightly vzdump, 7-day retention.</mem_result>
</mem_read>

**Sara (user-visible response):**

Current Proxmox VM layout on 10.185.1.203:

- **Sara VM**: 10.185.1.176, ~40GB
- **Jarvis orchestrator**: 10.185.1.180, ~60GB (runs FastAPI, PostgreSQL, Redis, Neo4j)
- **GPU passthrough VM**: 10.185.1.210, dedicated GTX 1070, Gemma 4 for voice pipeline

Backups: nightly vzdump to TrueNAS, 7-day retention, ~700GB total footprint.

The Redis that's currently in the Jarvis VM — are you splitting it out for isolation, or is this a separate Redis for a different purpose?

### Turn 2

**David:** splitting it out. the Jarvis VM is getting heavy — PostgreSQL, Redis, Neo4j, and the FastAPI app all on one VM. I want to give Redis its own lightweight VM so the working memory cache isn't competing with database I/O

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.vms.redis" importance="0.65" decay="medium">
New dedicated Redis VM being provisioned on Proxmox. Split from Jarvis VM to eliminate I/O competition between Redis working memory cache and PostgreSQL/Neo4j database operations.
</mem_write>

**Sara (user-visible response):**

Splitting Redis out eliminates the I/O contention — Redis is all memory-resident with periodic RDB snapshots, while PostgreSQL is disk-heavy. On a shared VM, the PG WAL writes and vacuum operations compete with Redis's AOF/RDB writes.

For the Redis VM: 2GB RAM is plenty (Redis dataset is probably under 500MB), 1-2 vCPUs, minimal disk (10GB). Alpine or Debian minimal. What IP are you assigning?

### Turn 3

**David:** 10.185.1.181. keeping it adjacent to Jarvis (.180). 2GB RAM, 2 vCPUs, Debian 12 minimal, 10GB disk. I'll update the Celery broker URL and the working memory config to point to the new IP

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.vms.redis.config" importance="0.60" decay="slow">
Dedicated Redis VM: 10.185.1.181. 2GB RAM, 2 vCPUs, Debian 12 minimal, 10GB disk. Hosts Redis for Sara working memory and Celery broker. Celery broker URL and working memory config updated to .181.
</mem_write>

**Sara (user-visible response):**

.181 for Redis, .180 for Jarvis — clean adjacency. After provisioning, update:
- `celery_app.py`: broker_url → `redis://10.185.1.181:6379/0`
- `celery_app.py`: result_backend → `redis://10.185.1.181:6379/1`
- Working memory config: point to `10.185.1.181:6379`

Test the Celery connection first — if the broker URL is wrong, all task processing stops.

## Memory State (After Session 1)

```
infra.proxmox: "10.185.1.203. Single-node."
infra.proxmox.vms.redis: "10.185.1.181. Dedicated Redis VM. 2GB, 2 vCPU, Debian 12."
infra.proxmox.vms.redis.config: "Hosts working memory + Celery broker. Split from Jarvis VM."
infra.proxmox.vm_sizes: "Sara ~40GB, Jarvis ~60GB, Redis ~10GB, GPU passthrough VM."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `infra.proxmox*` | Full VM layout recall. All from memory. |
| 2 | `<mem_write>` | `...vms.redis` | New VM being provisioned. Architecture decision. |
| 3 | `<mem_write>` | `...redis.config` | VM specs and IP. Slow decay — infrastructure. |
