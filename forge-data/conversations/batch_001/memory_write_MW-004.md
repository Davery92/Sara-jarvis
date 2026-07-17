## Memory State (Session 1 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.jarvis: "10.185.1.180 — orchestrator, FastAPI backend"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd, running Gemma 4 26B-A4B"
infra.mac_studio: "M3 Ultra 96GB, llama-server, Qwen3.5-122B-A10B IQ4_XS, launchd managed"
project.sara.celery: "Celery workers with Redis broker"
```

## SESSION 1

### Turn 1

**David:** been thinking about systemd restart policies for the inference services. right now if llama-server crashes on the 1070 cluster it just restarts immediately and sometimes that causes a cascade — all 6 instances try to grab VRAM at once and OOM the whole node

**Sara (internal generation stream):**

<reflect confidence="0.85">
David is describing a problem — systemd restart cascading causing OOM. He said "been thinking about" which suggests he hasn't decided yet. I'll engage with the problem but not store a decision until he commits.
</reflect>

**Sara (user-visible response):**

The thundering herd problem. All 6 competing for VRAM simultaneously after a restart is a guaranteed OOM. You need staggered restarts with backoff. `RestartSec=` with a randomized or instance-indexed delay is the simplest fix — have you looked at that yet?

### Turn 2

**David:** yeah that's basically where I landed. going with RestartSec=5 plus a per-instance offset. instance 0 gets 0s extra, instance 1 gets 10s, instance 2 gets 20s, etc. so worst case after a full cluster restart they come up over about a minute instead of all at once. also adding Restart=on-failure instead of Restart=always — if it exits cleanly I don't want it restarting

**Sara (internal generation stream):**

<mem_write key="infra.gpu_cluster.systemd.restart_policy" importance="0.75" decay="slow">
GPU cluster systemd restart policy: Restart=on-failure (not always), RestartSec=5 plus per-instance staggered offset (instance N gets N*10s additional delay). Full cluster restart staggers over ~60 seconds to prevent VRAM thundering herd OOM.
</mem_write>

**Sara (user-visible response):**

Clean design. The staggered offset prevents the cascade, and `on-failure` means you can still do controlled shutdowns for model swaps without systemd fighting you.

One thing — you might want `StartLimitIntervalSec` and `StartLimitBurst` too. If an instance is crash-looping (bad model file, corrupted weights), you don't want systemd hammering restarts every 5 seconds forever. Something like 3 attempts in 60 seconds, then stop and alert.

### Turn 3

**David:** good point. I'll add StartLimitBurst=3 and StartLimitIntervalSec=120. and for the alert I can just have the OnFailure= unit send a notification through Sara's push system

**Sara (internal generation stream):**

<mem_write key="infra.gpu_cluster.systemd.failure_limits" importance="0.65" decay="slow">
GPU cluster systemd failure limits: StartLimitBurst=3, StartLimitIntervalSec=120. OnFailure unit sends notification through Sara's push notification system.
</mem_write>

**Sara (user-visible response):**

That closes the loop — crash detection, bounded retries, and notification on persistent failure. The 120-second window with 3 bursts is conservative enough that transient VRAM allocation failures get retried but a broken model file doesn't burn cycles.

Want me to draft the unit file template with all of this?

### Turn 4

**David:** nah I've got it, pretty straightforward. just wanted to talk through the approach

**Sara (internal generation stream):**

<reflect confidence="0.88">
David declining the template offer — he's confident in implementation. No new facts to store. Just conversational close.
</reflect>

**Sara (user-visible response):**

Solid approach. The stagger pattern might be worth replicating for the Celery workers too if you ever see the same restart pile-up there.

---

*Time gap: next day*

---

## Memory State (Session 2 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.jarvis: "10.185.1.180 — orchestrator, FastAPI backend"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd, running Gemma 4 26B-A4B"
infra.gpu_cluster.systemd.restart_policy: "Restart=on-failure, RestartSec=5 + per-instance stagger (N*10s). Prevents VRAM thundering herd."
infra.gpu_cluster.systemd.failure_limits: "StartLimitBurst=3, StartLimitIntervalSec=120. OnFailure notifies via Sara push system."
infra.mac_studio: "M3 Ultra 96GB, llama-server, Qwen3.5-122B-A10B IQ4_XS, launchd managed"
project.sara.celery: "Celery workers with Redis broker"
```

## SESSION 2

### Turn 1

**David:** deployed the systemd changes to the cluster last night. had a bonus realization — I also added a ExecStartPre script that checks available VRAM before starting the instance. if there's not enough free VRAM it exits with a specific code that systemd treats as a retriable failure

**Sara (internal generation stream):**

<mem_write key="infra.gpu_cluster.systemd.vram_precheck" importance="0.70" decay="slow">
GPU cluster systemd units include ExecStartPre VRAM availability check. If insufficient free VRAM, exits with a retriable failure code so systemd backs off and retries after RestartSec delay. Deployed April 3, 2026.
</mem_write>

**Sara (user-visible response):**

That's a good addition — it means the stagger isn't just time-based but also resource-aware. An instance won't start until there's actually room for it. What are you using for the VRAM check — nvidia-smi query or something from the NVML bindings?

### Turn 2

**David:** nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits. simple but works. each instance needs about 6GB so the script checks for 6500MB free on its assigned GPU

**Sara (internal generation stream):**

<mem_write key="infra.gpu_cluster.vram_per_instance" importance="0.60" decay="slow">
Each llama.cpp instance on the 1070 cluster needs ~6GB VRAM. ExecStartPre checks for 6500MB free via nvidia-smi --query-gpu=memory.free.
</mem_write>

**Sara (user-visible response):**

6500MB threshold with 6GB requirement gives you a 500MB buffer for driver overhead. That's about right for the 1070's 8GB total. Clean solution — nvidia-smi is slower than NVML but for a startup check it doesn't matter.

## Memory State (After Session 2)

```
user.name: "David"
infra.proxmox: "10.185.1.203, Sara VM at 10.185.1.176"
infra.jarvis: "10.185.1.180 — orchestrator, FastAPI backend"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd, running Gemma 4 26B-A4B"
infra.gpu_cluster.systemd.restart_policy: "Restart=on-failure, RestartSec=5 + per-instance stagger (N*10s). Prevents VRAM thundering herd."
infra.gpu_cluster.systemd.failure_limits: "StartLimitBurst=3, StartLimitIntervalSec=120. OnFailure notifies via Sara push system."
infra.gpu_cluster.systemd.vram_precheck: "ExecStartPre VRAM check — 6500MB free required. nvidia-smi query. Exits with retriable code if insufficient. Deployed April 3, 2026."
infra.gpu_cluster.vram_per_instance: "Each instance needs ~6GB VRAM. 6500MB threshold (500MB buffer for driver overhead)."
infra.mac_studio: "M3 Ultra 96GB, llama-server, Qwen3.5-122B-A10B IQ4_XS, launchd managed"
project.sara.celery: "Celery workers with Redis broker"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<reflect>` | — | "Been thinking about" signals David hasn't decided yet. Engage, don't store until commitment. |
| S1T2 | `<mem_write>` | `infra.gpu_cluster.systemd.restart_policy` | David commits to specific approach: on-failure, staggered RestartSec. Concrete infra decision. |
| S1T3 | `<mem_write>` | `infra.gpu_cluster.systemd.failure_limits` | Additional detail: StartLimitBurst/Interval and OnFailure notification. Extends the policy. |
| S1T4 | `<reflect>` | — | David declining template offer is conversational, not factual. No write. |
| S2T1 | `<mem_write>` | `infra.gpu_cluster.systemd.vram_precheck` | New capability added to the deployment. Concrete implementation detail with deploy date. |
| S2T2 | `<mem_write>` | `infra.gpu_cluster.vram_per_instance` | Specific VRAM requirement per instance. Slow decay — hardware constraint won't change often. |
