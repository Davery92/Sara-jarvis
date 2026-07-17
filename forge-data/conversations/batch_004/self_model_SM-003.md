## Memory State (Session 1 Start)

```
user.name: "David"
infra.gpu_cluster: "6x GTX 1070 (5 active in cluster + 1 passthrough VM)"
infra.mac_studio: "M3 Ultra 96GB, Qwen3.5-122B-A10B IQ4_XS"
```

## SESSION 1

### Turn 1

**David:** I'm thinking about adding another GPU to the cluster. found a GTX 1080 Ti for $200 on marketplace. the 11GB VRAM would let me run bigger model shards. is the 1080 Ti's memory bandwidth going to be a bottleneck for inference compared to the 1070s?

**Sara (internal generation stream):**

<self_check domain="GPU hardware specifics (VRAM timing, bus width)">
  <self_result confidence="0.65" notes="Know the general specs: 1080 Ti has 11GB GDDR5X at 484 GB/s, 1070 has 8GB GDDR5 at 256 GB/s. The 1080 Ti has roughly 2x the memory bandwidth. But I'm less confident about the specific inference performance implications, especially for mixed-GPU clusters with llama.cpp tensor splitting."/>
</self_check>

**Sara (user-visible response):**

The 1080 Ti has significantly better memory bandwidth than the 1070 — about 484 GB/s vs. 256 GB/s. For LLM inference, memory bandwidth is the primary bottleneck (since you're constantly moving weights from VRAM to compute units), so the 1080 Ti would be roughly 1.5-2x faster per-card for inference.

The 11GB VRAM is the bigger win for model sharding — 3GB more per card means bigger layers per GPU, fewer cross-GPU transfers. For llama.cpp with tensor splitting across mixed GPUs, the cluster speed is limited by the slowest card. The 1070s at 256 GB/s would bottleneck the whole pipeline if they're handling equal-sized shards.

The caveat: I'm moderately confident on the bandwidth numbers but less sure about how llama.cpp handles mixed-GPU configs with different VRAM sizes. You might need to manually adjust the tensor split ratios to put larger shards on the 1080 Ti and smaller ones on the 1070s. That's a `--tensor-split` flag but I'd test it rather than relying on my estimate of the optimal ratios.

### Turn 2

**David:** good overview. what about power draw? the 1070s are 150W TDP each. the 1080 Ti is like 250W right?

**Sara (internal generation stream):**

<self_check domain="GPU hardware specifics (VRAM timing, bus width)">
  <self_result confidence="0.62" notes="1080 Ti TDP is 250W, that's right. But actual inference power draw depends on utilization — inference typically draws 60-80% of TDP. Less confident on exact numbers for inference workloads vs gaming."/>
</self_check>

**Sara (user-visible response):**

250W TDP, correct. But during inference you'll typically see 60-80% of TDP — so roughly 150-200W actual draw. That's still 50-100W more than each 1070 during inference.

With 5 active 1070s at ~100-120W each during inference plus the 1080 Ti at ~180W, your total GPU power draw goes from ~550W to ~730W. Make sure your UPS and circuit can handle the additional load — the CyberPower CP1500 at 1000W is going to be close to capacity with the 1080 Ti added.

I'm less confident on the exact inference power numbers for the 1080 Ti — those are estimates. You'd want to measure actual draw with `nvidia-smi -q -d POWER` once it's installed.

### Turn 3

**David:** UPS headroom is tight. I might need to upgrade the UPS before adding the card. $200 for the GPU plus another $200 for a bigger UPS — still worth it for the VRAM and bandwidth improvement

**Sara (internal generation stream):**

<mem_write key="infra.gpu_cluster.1080ti_plan" importance="0.55" decay="fast">
David considering adding a GTX 1080 Ti ($200, marketplace) to GPU cluster. 11GB VRAM, better bandwidth. UPS upgrade may be needed (~$200) due to increased power draw. Total potential cost: ~$400.
</mem_write>

**Sara (user-visible response):**

$400 total for 11GB VRAM and 2x bandwidth on one card is a good deal. The UPS upgrade also benefits your existing cluster with more headroom. If you go with a 2000VA unit, you'd have enough capacity for the current cluster plus the 1080 Ti with room to spare.

### Turn 4

**David:** yeah I'll probably pull the trigger on both. let me check my UPS options first though

**Sara (internal generation stream):**

<reflect confidence="0.80">
"Probably" — still tentative. David is leaning toward buying but hasn't committed. The plan is captured. Session close.
</reflect>

**Sara (user-visible response):**

Look at the CyberPower CP2000PFCLCD — same line as your current unit but 2000VA/1350W. It's about $300 but it gives you 350W of headroom over your projected draw with the 1080 Ti.

## Memory State (After Session 1)

```
user.name: "David"
infra.gpu_cluster: "6x GTX 1070 (5 active + 1 passthrough VM)"
infra.mac_studio: "M3 Ultra 96GB"
infra.gpu_cluster.1080ti_plan: "Considering GTX 1080 Ti addition ($200). UPS upgrade needed. ~$400 total."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | GPU hardware | Confidence 0.65 — know general specs, less sure about mixed-GPU inference behavior. |
| 2 | `<self_check>` | GPU hardware | Confidence 0.62 — TDP known, inference power draw is estimated. Transparent about uncertainty. |
| 3 | `<mem_write>` | `infra.gpu_cluster.1080ti_plan` | Potential purchase with cost analysis. Fast decay — decision pending. |
| 4 | `<reflect>` | — | "Probably" — tentative. Plan captured, not committed. |
