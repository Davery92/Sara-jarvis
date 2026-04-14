## Memory State (Session 1 Start)
```
user.name: "David"
infra.truenas: "TrueNAS. ZFS. NVMe SLOG."
infra.truenas.zfs_pool.current: "RAIDZ1 3x2TB + RAIDZ1 3x4TB."
infra.proxmox.backups: "Nightly vzdump to TrueNAS."
```
## SESSION 1
### Turn 1
**David:** TrueNAS is reporting a degraded RAIDZ1 — one of the 2TB drives is showing SMART errors. can you check the drive health and whether I need to replace it urgently?

**Sara (internal generation stream):**
<mem_read key="infra.truenas*">
  <mem_result>TrueNAS. RAIDZ1 3x2TB + RAIDZ1 3x4TB. NVMe SLOG. Nightly vzdump backups.</mem_result>
</mem_read>
<tool_call name="system_check">Check TrueNAS SMART status for all drives, zpool status for degraded vdev, and identify the failing drive</tool_call>

**Sara (user-visible response):**
Checking TrueNAS drive health.

The degraded drive is `/dev/da1` in the 2TB RAIDZ1 vdev. SMART reports: 47 reallocated sectors (threshold: 0 for concern), 3 pending sectors, and a raw read error rate trending upward. The drive is failing — not dead yet, but the SMART data predicts failure.

RAIDZ1 tolerates one drive failure, so you're currently protected. But if a SECOND drive in the same vdev fails before you replace this one, you lose the vdev.

**Action: replace the drive ASAP.** Order a replacement 2TB (or upgrade to 4TB to match the other vdev). The replacement process:
1. `zpool offline tank da1` (take failing drive offline)
2. Physically swap the drive
3. `zpool replace tank da1 da_new` (resilver the new drive)
4. Resilvering takes a few hours for 2TB

Don't wait for the drive to fully die — SMART errors are the warning.

### Turn 2
**David:** ordering a 4TB to replace the 2TB. might as well upgrade while I'm swapping. the RAIDZ1 won't get the extra capacity until all 3 drives match, but it's one step toward a full upgrade

**Sara (internal generation stream):**
<mem_write key="infra.truenas.drive_replacement" importance="0.65" decay="fast">
TrueNAS: 2TB drive (da1) failing with SMART errors in first RAIDZ1 vdev. Replacing with 4TB drive. RAIDZ1 capacity stays at 2TB-per-drive until all 3 match, but incremental upgrade toward all-4TB.
</mem_write>

**Sara (user-visible response):**
4TB replacement is forward-thinking. The RAIDZ1 capacity is limited by the smallest drive, so you won't see extra space yet. But when the other two 2TB drives eventually fail (and they will — same age/batch), you replace them with 4TB too. Third replacement = instant 8TB usable on that vdev, matching the other vdev.

## Memory State (After Session 1)
```
infra.truenas.drive_replacement: "da1 failing. Replacing 2TB with 4TB. RAIDZ1 degraded but protected."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | TrueNAS config + live SMART data | |
| 2 | `<mem_write>` | `...drive_replacement` | Replacement plan. |
