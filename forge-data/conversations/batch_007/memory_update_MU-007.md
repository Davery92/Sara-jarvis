## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
infra.gpu_cluster: "5x GTX 1070 in cluster, 1 passthrough VM"
infra.gpu_cluster.systemd.restart_policy: "Restart=on-failure, RestartSec=5 + per-instance stagger (N*10s)."
```

## SESSION 1

### Turn 1

**David:** the systemd restart stagger for the GPU cluster — I changed the delay. 10 seconds per instance was too aggressive when a model file is corrupted and all instances fail at once. bumped to 30 seconds per instance

**Sara (internal generation stream):**

<mem_read key="infra.gpu_cluster.systemd.restart_policy">
  <mem_result>Restart=on-failure, RestartSec=5 + per-instance stagger (N*10s). Prevents VRAM thundering herd.</mem_result>
</mem_read>

<mem_update key="infra.gpu_cluster.systemd.restart_policy">
Restart=on-failure, RestartSec=5 + per-instance stagger (N*30s, up from N*10s). Increased stagger to handle cascading failures from corrupted model files. Full cluster restart staggers over ~2.5 minutes.
</mem_update>

**Sara (user-visible response):**

30-second stagger gives each instance time to fully load the model before the next one starts competing for VRAM. With 5 active instances at 30s offset, full restart takes ~2.5 minutes. That's still reasonable for recovery and eliminates the cascading OOM from a corrupted model pulling all instances down simultaneously.

Did the corrupted model scenario actually happen, or is this preventive?

### Turn 2

**David:** happened last week. a download got interrupted and left a partial model file. all 5 instances tried to load it simultaneously, all failed, all restarted at once with the old 10-second stagger, and the VRAM contention caused kernel panics on 2 of the GPUs

**Sara (internal generation stream):**

<mem_write key="infra.gpu_cluster.incidents.corrupted_model" importance="0.60" decay="medium">
Incident: interrupted model download left partial model file. All 5 GPU instances tried to load it simultaneously, failed, restarted with 10s stagger, VRAM contention caused kernel panics on 2 GPUs. Led to increasing stagger to 30 seconds.
</mem_write>

**Sara (user-visible response):**

Kernel panics from VRAM contention — that's the worst case. The 30-second stagger prevents the pile-up, but you might also want a model file integrity check in the ExecStartPre. A quick SHA256 verification against a known-good hash before attempting to load. That way a corrupted file is caught before the process even starts, instead of failing during VRAM allocation.

### Turn 3

**David:** already added that. the ExecStartPre now checks file size + SHA256 hash. if either fails, the unit exits with a non-retriable error code so systemd doesn't keep restarting against a bad file

**Sara (internal generation stream):**

<mem_update key="infra.gpu_cluster.systemd.vram_precheck">
ExecStartPre: VRAM availability check (6500MB) AND model file integrity check (file size + SHA256 hash). Corrupted or incomplete model files exit with non-retriable error code — prevents restart loop against bad files.
</mem_update>

**Sara (user-visible response):**

Model integrity check with non-retriable exit code — that closes the loop. Corrupted file → fails once → stops, instead of crash-looping. The 30-second stagger handles the VRAM recovery case, and the integrity check handles the bad-file case. Both failure modes are covered now.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
infra.gpu_cluster: "5x GTX 1070 in cluster, 1 passthrough VM"
infra.gpu_cluster.systemd.restart_policy: "Restart=on-failure, RestartSec=5 + N*30s stagger (was N*10s)."
infra.gpu_cluster.systemd.vram_precheck: "VRAM check + model integrity check (size + SHA256). Non-retriable exit on bad model."
infra.gpu_cluster.incidents.corrupted_model: "Partial model file caused cascading failures and kernel panics. Led to 30s stagger and integrity check."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `infra.gpu_cluster.systemd.restart_policy` | Recall current policy for the update. |
| 1 | `<mem_update>` | `infra.gpu_cluster.systemd.restart_policy` | Stagger changed: 10s → 30s. UPDATE same key. |
| 2 | `<mem_write>` | `infra.gpu_cluster.incidents.corrupted_model` | Incident that motivated the change. Worth recording for context. |
| 3 | `<mem_update>` | `infra.gpu_cluster.systemd.vram_precheck` | PreCheck expanded with model integrity check. UPDATE same key. |
