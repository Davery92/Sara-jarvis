## Memory State (Session 1 Start)

```
user.name: "David"
infra.gpu_cluster: "5x GTX 1070, 1 passthrough VM"
infra.gpu_cluster.systemd.restart_policy: "Restart=on-failure, RestartSec=5 + N*30s stagger"
infra.gpu_cluster.vram_per_instance: "~6GB VRAM each. 6500MB threshold."
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M + Phi-3.5 Mini"
```

## SESSION 1

### Turn 1

**David:** how much VRAM does each 1070 instance use? I'm trying to figure out if I can squeeze a second small model onto one of the cluster GPUs

**Sara (internal generation stream):**

<mem_read key="infra.gpu_cluster.vram_per_instance">
  <mem_result>~6GB VRAM each. 6500MB threshold for ExecStartPre check.</mem_result>
</mem_read>

**Sara (user-visible response):**

Each 1070 instance uses ~6GB VRAM. The 1070s have 8GB total, so you've got roughly 2GB free per card. The ExecStartPre checks for 6500MB free before starting, which accounts for ~500MB driver overhead.

2GB free isn't enough for any meaningful model — even a tiny 1B model at fp16 would be ~2GB. You'd need to either reduce the primary model's VRAM footprint or run the second model on the CPU portion of the card.

### Turn 2

**David:** what about the Mac Studio — what's the VRAM situation there? I know we set it up with both models recently

**Sara (internal generation stream):**

<mem_read key="infra.mac_studio">
  <mem_result>M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M (~55GB) + Phi-3.5 Mini (~7.5GB). ~62.5GB used.</mem_result>
</mem_read>

**Sara (user-visible response):**

Mac Studio: Qwen3.5-MoE-A22B at ~55GB + Phi-3.5 Mini at ~7.5GB = ~62.5GB used out of 96GB. You've got 33.5GB of headroom. If you want a third model on the Mac Studio, you've got plenty of room — a 7B at Q8 (~7.5GB) or even a 13B at Q4 (~7GB) would fit easily.

### Turn 3

**David:** that's what I thought. the Mac Studio is the right place for additional models, not the 1070 cluster. thanks for the quick numbers

**Sara (internal generation stream):**

<reflect confidence="0.85">
David confirmed the conclusion: Mac Studio for additional models, not the 1070 cluster. All answers came from memory — no tool calls needed. The VRAM figures were stored facts, not live data. Correct tool restraint.
</reflect>

**Sara (user-visible response):**

The 1070 cluster is maxed per-card. The Mac Studio has the headroom. If you ever need more than 3 models simultaneously, the Mac Studio's unified memory architecture is the scalable path.

## Memory State (After Session 1)

```
[no changes — pure memory retrieval session]
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `infra.gpu_cluster.vram_per_instance` | David asks for stored VRAM data. Memory has it. NO tool call. |
| 2 | `<mem_read>` | `infra.mac_studio` | Mac Studio config from memory. NO tool call — these are stored facts, not live data. |
| 3 | `<reflect>` | — | All answers from memory. No new facts. Correct tool restraint — no live data needed. |
