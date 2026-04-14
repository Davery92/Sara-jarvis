## Memory State (Session 1 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.jarvis: "10.185.1.180 — orchestrator, FastAPI backend"
```

## SESSION 1

### Turn 1

**David:** so I'm not doing a Proxmox cluster after all. looked into the quorum requirements and with only one node it doesn't make sense — you need at least 3 for proper quorum. I'll just keep running single-node Proxmox and manage it directly

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.cluster_decision" importance="0.65" decay="slow">
David decided against Proxmox clustering. Single node (10.185.1.203) doesn't meet the 3-node quorum requirement. Staying with single-node Proxmox, direct management.
</mem_write>

**Sara (user-visible response):**

Single-node Proxmox is the right call with one box. Cluster overhead without quorum buys you nothing — you'd need two more nodes plus a quorum device (like a Raspberry Pi running corosync) to make it worthwhile. And at that point you're managing cluster state for no HA benefit since your workloads can't fail over anywhere.

If you ever add a second Proxmox node, it changes the calculus. But for now, single-node with direct management keeps things simple.

### Turn 2

**David:** yeah that's my thinking. also realized the cluster setup would have complicated my backup strategy — right now I do nightly Proxmox backups to the TrueNAS share via vzdump and it's straightforward. clustering adds PBS into the mix which is more infrastructure to manage

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.backups" importance="0.70" decay="slow">
Proxmox backups: nightly vzdump to TrueNAS share. Chose to stay with this simple approach rather than adding Proxmox Backup Server (PBS) which would be needed for cluster-aware backups.
</mem_write>

**Sara (user-visible response):**

vzdump to TrueNAS nightly is clean and auditable. PBS adds deduplication and incremental backups which are nice, but for a single node with a handful of VMs, it's unnecessary complexity. Your TrueNAS has ZFS snapshots underneath anyway — you're getting some of that dedup benefit at the storage layer.

### Turn 3

**David:** exactly. keep it simple. the VMs are small anyway — Sara's VM is like 40GB, the Jarvis VM is maybe 60GB. the whole nightly backup takes 15 minutes

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.vm_sizes" importance="0.55" decay="slow">
VM sizes on Proxmox: Sara VM ~40GB, Jarvis VM ~60GB. Total nightly backup takes ~15 minutes via vzdump to TrueNAS.
</mem_write>

**Sara (user-visible response):**

15 minutes for the full backup set is fast. At those VM sizes, even a daily rotation with 7-day retention is only ~700GB on TrueNAS. Plenty of headroom unless you're tight on the share.

## Memory State (After Session 1)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176. Single-node, no cluster."
infra.proxmox.cluster_decision: "No clustering — single node doesn't meet 3-node quorum. Direct management."
infra.proxmox.backups: "Nightly vzdump to TrueNAS. Simple, ~15 min. No PBS."
infra.proxmox.vm_sizes: "Sara VM ~40GB, Jarvis VM ~60GB."
infra.jarvis: "10.185.1.180 — orchestrator, FastAPI backend"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `infra.proxmox.cluster_decision` | Concrete decision against clustering with reasoning. Slow decay — architecture. |
| 2 | `<mem_write>` | `infra.proxmox.backups` | Backup strategy detail. Infrastructure fact. |
| 3 | `<mem_write>` | `infra.proxmox.vm_sizes` | Specific VM sizes and backup timing. Useful context for future capacity discussions. |
