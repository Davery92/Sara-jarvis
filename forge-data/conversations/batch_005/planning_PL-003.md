## Memory State (Session 1 Start)

```
user.name: "David"
infra.truenas: "TrueNAS storage server. ZFS pools."
infra.proxmox.backups: "Nightly vzdump to TrueNAS share."
infra.proxmox.vm_sizes: "Sara VM ~40GB, Jarvis VM ~60GB."
```

## SESSION 1

### Turn 1

**David:** I need to expand the ZFS pool on TrueNAS. running low on space — the backup share for Proxmox is at 85% and I've got 3 new 4TB drives to add. help me plan this out, I want to make sure I don't lose data

**Sara (internal generation stream):**

<mem_write key="infra.truenas.zfs_expansion" importance="0.70" decay="medium">
ZFS pool expansion planned on TrueNAS. Current: backup share at 85% capacity. Adding 3x 4TB drives. Data safety is primary concern.
</mem_write>

<plan_start goal="Expand TrueNAS ZFS pool safely with 3x 4TB drives">
  <plan_step goal="Assess current pool topology and plan target configuration" status="active" depends_on="none"/>
  <plan_step goal="Pre-expansion backup of critical data" status="pending" depends_on="assessment"/>
  <plan_step goal="Physical drive installation" status="pending" depends_on="backup"/>
  <plan_step goal="ZFS pool expansion" status="pending" depends_on="install"/>
  <plan_step goal="Verification and monitoring" status="pending" depends_on="expansion"/>
</plan_start>

**Sara (user-visible response):**

Here's the plan, broken into phases. The key risk is data loss during expansion, so we front-load the safety steps.

**Phase 1 — Assessment (30 min)**
- Run `zpool status` to see current pool topology (mirror, RAIDZ1, RAIDZ2, stripe?)
- Run `zpool list` to see current capacity and fragmentation
- Decide the target configuration: you can add a new vdev (e.g., RAIDZ1 of 3 drives = ~8TB usable) or expand existing vdevs (only if current pool is mirrors)

The target config depends on your current topology. What does `zpool status` show?

### Turn 2

**David:** it's currently a single 3-drive RAIDZ1 with 3x 2TB drives. so 4TB usable, and 3.4TB used. I want to add the 3 new 4TB drives as a second RAIDZ1 vdev

**Sara (internal generation stream):**

<mem_write key="infra.truenas.zfs_pool.current" importance="0.65" decay="slow">
TrueNAS ZFS pool: single RAIDZ1 vdev with 3x 2TB drives. 4TB usable, 3.4TB used (85%). Plan: add second RAIDZ1 vdev with 3x 4TB drives.
</mem_write>

**Sara (user-visible response):**

Adding a second RAIDZ1 vdev is the correct approach — you can't add individual drives to an existing RAIDZ1. The new vdev gives you ~8TB additional usable space, bringing total pool capacity to ~12TB usable.

**Updated plan:**

**Phase 2 — Pre-expansion backup (2-4 hours)**
- Pause the nightly Proxmox vzdump job temporarily
- Snapshot the existing pool: `zfs snapshot -r poolname@pre-expansion`
- If you have ANY external storage, copy the most critical datasets off-box
- Risk: if something catastrophic happens during expansion (power loss, drive DOA), the snapshot protects you. External backup is belt-and-suspenders.

**Phase 3 — Physical install (30-60 min)**
- Power down TrueNAS (or hot-swap if your chassis supports it)
- Install 3x 4TB drives
- Boot and verify all 3 new drives appear in `diskinfo` or the TrueNAS UI
- Run SMART tests on all 3 new drives: `smartctl -t short /dev/daX`

**Phase 4 — Pool expansion (10 min)**
```bash
zpool add poolname raidz1 /dev/da3 /dev/da4 /dev/da5
```
Adjust device names to match. This is a non-destructive operation — it adds the new vdev alongside the existing one. Existing data is untouched.

**Phase 5 — Verification (30 min)**
- `zpool status` — verify both vdevs show ONLINE
- `zpool list` — confirm new capacity
- Resume the vzdump job and run a test backup
- Monitor for 24 hours — check `zpool scrub poolname` to verify data integrity

The riskiest step is Phase 3 (physical install). If your chassis doesn't support hot-swap, the power-down/boot cycle is where things could go wrong. The snapshot from Phase 2 is your safety net.

### Turn 3

**David:** chassis supports hot-swap so no shutdown needed. I'll skip the external backup since I have the snapshot and the existing data is all Proxmox backups — I can regenerate them if worst case happens. timeline: do this Saturday morning?

**Sara (internal generation stream):**

<mem_write key="infra.truenas.zfs_expansion.timeline" importance="0.55" decay="fast">
ZFS expansion scheduled for Saturday morning. Hot-swap capable chassis — no shutdown. Skipping external backup (data is regenerable Proxmox backups). Using ZFS snapshot as safety net.
</mem_write>

**Sara (user-visible response):**

Saturday morning with hot-swap — straightforward. Since the data is regenerable backups, skipping external copy is a reasonable risk decision. The ZFS snapshot still protects you during the vdev addition.

Sequence for Saturday:
1. Snapshot existing pool
2. Hot-swap the 3 drives (TrueNAS should detect them automatically)
3. SMART short test on all 3
4. `zpool add` the new RAIDZ1 vdev
5. Verify with `zpool status`
6. Run a test vzdump
7. Delete the pre-expansion snapshot once you're confident

Total time: about 90 minutes including SMART tests.

### Turn 4

**David:** perfect. 90 minutes and I've got 12TB of ZFS storage. thanks for the structured plan

**Sara (internal generation stream):**

<reflect confidence="0.85">
David is satisfied with the plan. All the key details are captured. Session close.
</reflect>

**Sara (user-visible response):**

One last thing: after the expansion, run a full scrub (`zpool scrub poolname`) overnight. It verifies every block on both vdevs. You'll sleep better knowing the pool is clean.

## Memory State (After Session 1)

```
user.name: "David"
infra.truenas: "TrueNAS storage server. ZFS pools."
infra.truenas.zfs_pool.current: "RAIDZ1 3x 2TB (4TB usable, 85% full). Adding second RAIDZ1 vdev with 3x 4TB (8TB additional)."
infra.truenas.zfs_expansion: "3x 4TB drives. New RAIDZ1 vdev. Total: ~12TB usable."
infra.truenas.zfs_expansion.timeline: "Saturday morning. Hot-swap, ~90 min total."
infra.proxmox.backups: "Nightly vzdump to TrueNAS share."
infra.proxmox.vm_sizes: "Sara VM ~40GB, Jarvis VM ~60GB."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `infra.truenas.zfs_expansion` | Expansion project initiated. |
| 1 | `<plan_start>` | ZFS pool expansion | 5-phase structured plan with dependencies. |
| 2 | `<mem_write>` | `infra.truenas.zfs_pool.current` | Current topology: RAIDZ1, 3x 2TB, 85% full. |
| 3 | `<mem_write>` | `infra.truenas.zfs_expansion.timeline` | Saturday morning, hot-swap. Concrete timeline. |
| 4 | `<reflect>` | — | Session close. Plan accepted. |
