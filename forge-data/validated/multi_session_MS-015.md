## Memory State (Session 1 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203"
infra.gpu_cluster: "5x GTX 1070"
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B + Qwen2.5-3B."
project.sara.voice: "Sub-1 second E2E."
```

## SESSION 1

### Turn 1

**David:** Proxmox node rebooted overnight. not sure why. the VMs came back up automatically but Sara was down for what looks like 12 minutes based on the notification gap

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.incidents.unexpected_reboot" importance="0.65" decay="fast">
Proxmox node unexpected reboot overnight. VMs recovered automatically (onboot). Sara was down ~12 minutes (measured by notification gap). Root cause unknown.
</mem_write>

**Sara (user-visible response):**

12-minute outage from an unexpected reboot — the onboot configs saved you from manual recovery. For the root cause, check:

1. `journalctl --list-boots` — confirms the reboot and gives you the exact timestamp
2. `journalctl -b -1 --since "5 minutes before reboot"` — logs from the last boot, final minutes before the reboot
3. `dmesg` in the current boot — kernel messages that might explain the shutdown
4. Check if the UPS triggered a shutdown (check apcupsd logs)

The most common unplanned Proxmox reboots: kernel panic, OOM killer taking out a critical process, or a power event the UPS couldn't ride through.

### Turn 2

**David:** checking now. UPS logs show no power event. dmesg shows... an OOM kill on the Neo4j process. it consumed all available RAM and the kernel killed it, which cascaded into a Proxmox watchdog reboot

**Sara (internal generation stream):**

<mem_update key="infra.proxmox.incidents.unexpected_reboot">
Proxmox reboot root cause: OOM kill on Neo4j process. Neo4j consumed all available host RAM. Kernel OOM killed Neo4j, triggered Proxmox watchdog reboot. UPS not involved — not a power event.
</mem_update>

**Sara (user-visible response):**

Neo4j OOM causing a cascading Proxmox reboot — that's a memory limit problem. Neo4j's JVM heap is probably not capped, so it grew until it consumed all host memory. The fix:

1. Set a JVM heap limit in Neo4j's config: `NEO4J_server_memory_heap_max__size=2G` (or whatever's appropriate for your data size)
2. Set a container/VM memory limit so even if Neo4j leaks, it can't take down the host
3. Add memory usage monitoring to the Sara alert system — notify if any VM exceeds 80% of its allocated RAM

### Turn 3

**David:** the heap limit is the immediate fix. I'll cap it at 2G. the current PKG is small enough that 2G is plenty. the container limit is a good second layer

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.neo4j.memory_fix" importance="0.65" decay="medium">
Neo4j memory fix: JVM heap capped at 2G. Container memory limit added as second layer. Prevents OOM cascade that caused Proxmox reboot.
</mem_write>

**Sara (user-visible response):**

2G heap cap for Neo4j and a container limit. The two layers mean: if Neo4j hits 2G heap, it garbage collects. If somehow it leaks beyond the container limit, the container gets killed instead of the host. The Proxmox node stays up either way.

## Memory State (After Session 1)

```
infra.proxmox: "10.185.1.203"
infra.proxmox.incidents.unexpected_reboot: "OOM on Neo4j → Proxmox watchdog reboot. 12 min downtime."
infra.proxmox.neo4j.memory_fix: "JVM heap 2G cap + container memory limit."
```

---

*Time gap: a week*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** Neo4j has been stable all week with the 2G heap cap. no more memory growth. also added the container limit at 3G so there's a 1G buffer. the Proxmox node hasn't had any issues since

**Sara (internal generation stream):**

<mem_read key="infra.proxmox.neo4j.memory_fix">
  <mem_result>JVM heap 2G cap + container memory limit.</mem_result>
</mem_read>

<mem_update key="infra.proxmox.neo4j.memory_fix">
Neo4j stable for 1 week with 2G heap cap + 3G container limit (1G buffer). No memory growth. Proxmox reboot issue resolved.
</mem_update>

**Sara (user-visible response):**

One week stable with the heap cap confirms it was an unbounded memory issue, not a leak. The 2G heap with 3G container limit is the right setup — Neo4j gets room to operate and the container can't threaten the host. The Proxmox watchdog reboot won't happen again.

### Turn 2

**David:** good. one less thing to worry about. the 12-minute outage was a wake-up call about running critical services without memory limits. I'm auditing all the containers this weekend to make sure they all have caps

**Sara (internal generation stream):**

<mem_write key="infra.proxmox.memory_audit" importance="0.55" decay="fast">
David auditing all Proxmox containers/VMs for memory limits this weekend. Prompted by Neo4j OOM incident. Goal: no service can consume unbounded host memory.
</mem_write>

**Sara (user-visible response):**

The audit is the right response — if Neo4j was running without limits, others might be too. Check: PostgreSQL (`shared_buffers` + `work_mem`), Redis (already has a max memory setting if configured), and any JVM-based services. The Sara VM and Jarvis VM should both have Proxmox-level memory caps.

## Memory State (After Session 2)

```
infra.proxmox: "10.185.1.203"
infra.proxmox.neo4j.memory_fix: "RESOLVED. 2G heap, 3G container. Stable 1 week."
infra.proxmox.incidents.unexpected_reboot: "RESOLVED. OOM → heap cap."
infra.proxmox.memory_audit: "Auditing all containers for memory limits."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `...unexpected_reboot` | Incident: unexpected Proxmox reboot. |
| S1T2 | `<mem_update>` | `...unexpected_reboot` | Root cause: Neo4j OOM. |
| S1T3 | `<mem_write>` | `...memory_fix` | Fix: JVM heap cap + container limit. |
| S2T1 | `<mem_read>` + `<mem_update>` | `...memory_fix` | Fix validated after 1 week. |
| S2T2 | `<mem_write>` | `...memory_audit` | Broader audit prompted by incident. |
