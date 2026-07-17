## Memory State (Session 1 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd, running Gemma 4 26B-A4B"
```

## SESSION 1

### Turn 1

**David:** I want to set up GPU passthrough on the Proxmox node for one of the 1070s. dedicated card for a specific inference container instead of sharing the cluster

**Sara (internal generation stream):**

<mem_write key="project.infra.gpu_passthrough.plan" importance="0.70" decay="medium">
David planning to set up GPU passthrough on Proxmox node (10.185.1.203) for a dedicated GTX 1070 card. Goal: isolated inference container instead of sharing the cluster.
</mem_write>

**Sara (user-visible response):**

For PCI passthrough on Proxmox you'll need IOMMU enabled in BIOS, the `vfio-pci` module loaded, and the GPU's PCI ID added to the passthrough config. Which card are you isolating — one of the cluster nodes, or a separate card?

### Turn 2

**David:** one of the cluster cards. pulling GPU 5 out of the cluster rotation and passing it through to a dedicated VM. the VM will run a single llama.cpp instance for Sara's voice pipeline — needs guaranteed latency, can't share

**Sara (internal generation stream):**

<mem_write key="project.infra.gpu_passthrough.details" importance="0.75" decay="medium">
GPU passthrough plan: GPU 5 (GTX 1070) removed from cluster rotation, passed through to a dedicated Proxmox VM. VM runs a single llama.cpp instance for Sara's voice pipeline. Reason: guaranteed latency requirement, can't share with cluster.
</mem_write>

**Sara (user-visible response):**

Makes sense — voice pipeline latency is non-negotiable for a decent UX. GPU 5 as a dedicated passthrough means the cluster drops to 5 cards but the voice path gets a guaranteed ~8GB VRAM allocation.

For the passthrough config: you'll need the PCI address of GPU 5. Run `lspci -nn | grep -i nvidia` on the Proxmox host to get the bus:device.function and vendor:device IDs. Then add it to `/etc/modprobe.d/vfio.conf` and blacklist it from the nvidia driver.

### Turn 3

**David:** yeah I've done passthrough before, just not on this specific box. the tricky part is going to be the IOMMU groups — these 1070s are all in the same x16 slots and I'm not sure they're in separate groups

**Sara (internal generation stream):**

<mem_write key="project.infra.gpu_passthrough.iommu_concern" importance="0.60" decay="fast">
IOMMU group concern: all 6 GTX 1070s may be in the same IOMMU group due to x16 slot layout. If so, passing through one card may require passing through all or using ACS override patch.
</mem_write>

**Sara (user-visible response):**

Check with `find /sys/kernel/iommu_groups/ -type l | sort -V`. If multiple 1070s share a group, your options are:

1. **ACS override patch** — forces separate groups per device. Works but it's a kernel patch, meaning you need to rebuild or use a patched kernel.
2. **Move the card** — if there's a slot on a different IOMMU group boundary.
3. **Pass through the whole group** — but that defeats the purpose if you want the other cards in the cluster.

On most consumer/prosumer boards, x16 slots from the same PCIe controller end up in the same group. Server boards with proper ACS support separate them natively.

## Memory State (After Session 1)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd, running Gemma 4 26B-A4B"
project.infra.gpu_passthrough.plan: "Dedicated GTX 1070 passthrough on Proxmox for isolated inference container."
project.infra.gpu_passthrough.details: "GPU 5 removed from cluster, passed to dedicated VM for Sara voice pipeline. Guaranteed latency."
project.infra.gpu_passthrough.iommu_concern: "1070s may share IOMMU groups. May need ACS override or slot move."
```

---

*Time gap: same day, 4 hours later*

---

## Memory State (Session 2 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd, running Gemma 4 26B-A4B"
project.infra.gpu_passthrough.plan: "Dedicated GTX 1070 passthrough on Proxmox for isolated inference container."
project.infra.gpu_passthrough.details: "GPU 5 removed from cluster, passed to dedicated VM for Sara voice pipeline. Guaranteed latency."
project.infra.gpu_passthrough.iommu_concern: "1070s may share IOMMU groups. May need ACS override or slot move."
```

## SESSION 2

### Turn 1

**David:** checked the IOMMU groups — GPU 5 is in its own group. got lucky, it's on a separate PCIe controller

**Sara (internal generation stream):**

<mem_read key="project.infra.gpu_passthrough.*">
  <mem_result>GPU 5 passthrough planned for Sara voice pipeline VM. IOMMU group concern flagged — may share groups with other 1070s.</mem_result>
</mem_read>

<mem_update key="project.infra.gpu_passthrough.iommu_concern">
IOMMU resolved: GPU 5 is in its own IOMMU group on a separate PCIe controller. No ACS override needed.
</mem_update>

**Sara (user-visible response):**

Clean. Separate controller means no ACS patching, no group conflicts. You can pass through GPU 5 without touching the other cards. Have you added it to vfio.conf yet?

### Turn 2

**David:** yeah, added the PCI ID to vfio.conf and blacklisted it from nvidia. rebooted and the card shows up as vfio-pci. now I need to create the VM and attach it

**Sara (internal generation stream):**

<mem_write key="project.infra.gpu_passthrough.status" importance="0.65" decay="fast">
GPU passthrough progress: GPU 5 bound to vfio-pci driver after reboot. Next step: create VM and attach the card.
</mem_write>

**Sara (user-visible response):**

In the Proxmox VM config, add the PCI device under Hardware → Add → PCI Device. Select the GPU by its bus address. Enable "All Functions" if you want to pass through both the GPU and its audio controller. Set "Primary GPU" if this VM won't have a virtual display.

For the VM itself — keep it minimal. A lightweight Debian or Alpine with just llama.cpp, CUDA toolkit, and the nvidia driver. No desktop environment.

### Turn 3

**David:** going with Debian 12 minimal. same as the other inference VMs. should have this up by tonight

**Sara (internal generation stream):**

<mem_write key="project.infra.gpu_passthrough.vm_config" importance="0.60" decay="medium">
GPU passthrough VM: Debian 12 minimal. Running single llama.cpp instance for Sara voice pipeline. GPU 5 (GTX 1070) attached via PCI passthrough.
</mem_write>

**Sara (user-visible response):**

Debian 12 minimal is the right base. Once the nvidia driver is installed and `nvidia-smi` sees the card, llama.cpp should just work. Match the CUDA toolkit version to whatever you're running on the other cluster nodes for consistency.

## Memory State (After Session 2)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.gpu_cluster: "5x GTX 1070 in cluster (GPU 5 removed for passthrough), llama.cpp with systemd, running Gemma 4 26B-A4B"
project.infra.gpu_passthrough.plan: "Dedicated GTX 1070 passthrough on Proxmox for isolated inference container."
project.infra.gpu_passthrough.details: "GPU 5 removed from cluster, passed to dedicated VM for Sara voice pipeline."
project.infra.gpu_passthrough.iommu_concern: "RESOLVED: GPU 5 in its own IOMMU group on separate PCIe controller."
project.infra.gpu_passthrough.status: "GPU 5 bound to vfio-pci. VM creation in progress."
project.infra.gpu_passthrough.vm_config: "Debian 12 minimal. Single llama.cpp instance. GPU 5 via PCI passthrough."
```

---

*Time gap: same day, evening*

---

## Memory State (Session 3 Start)

```
[same as After Session 2]
```

## SESSION 3

### Turn 1

**David:** passthrough VM is up. llama.cpp running, nvidia-smi sees the card, getting ~35 tok/s on Gemma 4 which is about right for a single 1070

**Sara (internal generation stream):**

<mem_read key="project.infra.gpu_passthrough.*">
  <mem_result>GPU 5 passthrough for Sara voice pipeline. Debian 12 VM. Card bound to vfio-pci, VM creation was in progress.</mem_result>
</mem_read>

<mem_update key="project.infra.gpu_passthrough.status">
GPU passthrough VM operational. llama.cpp running, nvidia-smi confirms GPU 5. Performance: ~35 tok/s on Gemma 4 26B-A4B (expected for single GTX 1070).
</mem_update>

**Sara (user-visible response):**

35 tok/s on Gemma 4 from a single 1070 is in line with what the cluster nodes do individually. Voice pipeline should be comfortable with that — even at conversational turn lengths you're looking at sub-second generation for short responses.

Is the voice pipeline already pointed at this VM or still hitting the shared cluster?

### Turn 2

**David:** switching it over now. just need to update the endpoint URL in the voice service config. 10.185.1.210 is the new VM's IP

**Sara (internal generation stream):**

<mem_write key="infra.gpu_passthrough_vm" importance="0.75" decay="slow">
GPU passthrough VM for Sara voice pipeline: 10.185.1.210. Debian 12, single GTX 1070 (GPU 5), llama.cpp running Gemma 4 26B-A4B at ~35 tok/s.
</mem_write>

**Sara (user-visible response):**

Once the endpoint is swapped, test a few voice turns end-to-end to confirm the latency is where you want it. The passthrough should shave off any contention jitter you were seeing on the shared cluster. If the numbers look good, update the systemd service on the voice pipeline to point to 10.185.1.210 permanently.

### Turn 3

**David:** will do. nice to have the voice path on its own dedicated card finally

**Sara (internal generation stream):**

<reflect confidence="0.85">
David expressing satisfaction. Transient sentiment — no write needed. The key facts (VM IP, performance, configuration) are already captured.
</reflect>

**Sara (user-visible response):**

Dedicated inference for the voice path was the right call. One card for guaranteed latency is worth more than the marginal throughput of having it in the cluster pool.

## Memory State (After Session 3)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.gpu_cluster: "5x GTX 1070 in cluster, llama.cpp with systemd, running Gemma 4 26B-A4B"
infra.gpu_passthrough_vm: "10.185.1.210. Debian 12, single GTX 1070 (GPU 5). llama.cpp, Gemma 4 at ~35 tok/s. Dedicated to Sara voice pipeline."
project.infra.gpu_passthrough.plan: "COMPLETE. Dedicated GTX 1070 passthrough for voice pipeline."
project.infra.gpu_passthrough.details: "GPU 5 removed from cluster, passed to VM at 10.185.1.210."
project.infra.gpu_passthrough.iommu_concern: "RESOLVED: Separate PCIe controller."
project.infra.gpu_passthrough.status: "COMPLETE. VM operational, ~35 tok/s, voice pipeline being switched over."
project.infra.gpu_passthrough.vm_config: "Debian 12 minimal. Single llama.cpp instance."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.infra.gpu_passthrough.plan` | New project: GPU passthrough for inference. Initial plan captured. |
| S1T2 | `<mem_write>` | `project.infra.gpu_passthrough.details` | Specifics: GPU 5, voice pipeline, latency requirement. |
| S1T3 | `<mem_write>` | `project.infra.gpu_passthrough.iommu_concern` | Technical risk flagged. Fast decay — will be resolved or not. |
| S2T1 | `<mem_read>` | `project.infra.gpu_passthrough.*` | Retrieving passthrough context to respond naturally to David's update. |
| S2T1 | `<mem_update>` | `project.infra.gpu_passthrough.iommu_concern` | IOMMU resolved — GPU 5 in separate group. Update existing key. |
| S2T2 | `<mem_write>` | `project.infra.gpu_passthrough.status` | Progress update: card bound, VM next. |
| S2T3 | `<mem_write>` | `project.infra.gpu_passthrough.vm_config` | VM specs decided: Debian 12 minimal. |
| S3T1 | `<mem_read>` | `project.infra.gpu_passthrough.*` | Retrieving project context for session 3 continuity. |
| S3T1 | `<mem_update>` | `project.infra.gpu_passthrough.status` | VM operational, performance confirmed. |
| S3T2 | `<mem_write>` | `infra.gpu_passthrough_vm` | Permanent infra entry: VM IP, specs, role. Slow decay — infrastructure fact. |
| S3T3 | `<reflect>` | — | David's satisfaction is transient. Facts already captured. |
