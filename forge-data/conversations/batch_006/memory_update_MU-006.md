## Memory State (Session 1 Start)

```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB, Qwen3.5-122B-A10B IQ4_XS"
infra.mac_studio.management: "launchd managed with health watchdog"
project.sara.voice.stt_model: "distil-whisper-large-v3 on Jetson, streaming"
```

## SESSION 1

### Turn 1

**David:** switched the Mac Studio from Qwen3.5-122B to Qwen3.5-MoE-A22B. the new MoE variant with 22B active parameters. smaller active set means faster inference and it fits better with the Phi-3.5 voice model running alongside

**Sara (internal generation stream):**

<mem_read key="infra.mac_studio">
  <mem_result>M3 Ultra 96GB, Qwen3.5-122B-A10B IQ4_XS</mem_result>
</mem_read>

<mem_update key="infra.mac_studio">
M3 Ultra 96GB. Primary model: Qwen3.5-MoE-A22B (switched from Qwen3.5-122B-A10B). 22B active parameters. Better fit for dual-model operation with Phi-3.5 voice model.
</mem_update>

**Sara (user-visible response):**

22B active is a big jump from 10B active on the old MoE. More active parameters should improve response quality noticeably, especially on complex multi-step reasoning. What quantization level on the new model?

### Turn 2

**David:** Q5_K_M. it's about 55GB at that quant. with Phi-3.5 at 7.5GB I'm using about 62.5GB of the 96GB — plenty of headroom

**Sara (internal generation stream):**

<mem_update key="infra.mac_studio">
M3 Ultra 96GB. Primary: Qwen3.5-MoE-A22B at Q5_K_M (~55GB). Voice: Phi-3.5 Mini fp16 (~7.5GB). Total: ~62.5GB, 33.5GB headroom.
</mem_update>

**Sara (user-visible response):**

Q5_K_M at 55GB with 33.5GB headroom — much more comfortable than the old setup where Qwen was eating 75GB alone. The higher quant level (Q5 vs IQ4_XS) gives you better output quality too. How's the inference speed compare?

### Turn 3

**David:** faster. 22B active at Q5 is doing about 25 tok/s vs the old 122B-A10B at ~18 tok/s. first token latency dropped from ~800ms to ~400ms. noticeable improvement in conversation flow

**Sara (internal generation stream):**

<mem_write key="infra.mac_studio.performance" importance="0.65" decay="medium">
Mac Studio inference performance with Qwen3.5-MoE-A22B Q5_K_M: ~25 tok/s (up from ~18 tok/s), first token latency ~400ms (down from ~800ms). Significant improvement in conversation flow.
</mem_write>

**Sara (user-visible response):**

25 tok/s and 400ms first token — that's a real conversation-quality improvement. The 400ms first token means Sara's text responses start in under half a second. Combined with the 1.4s voice pipeline, the whole system feels significantly snappier.

Good model swap.

## Memory State (After Session 1)

```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB. Primary: Qwen3.5-MoE-A22B Q5_K_M (~55GB). Voice: Phi-3.5 Mini (~7.5GB). ~62.5GB used."
infra.mac_studio.management: "launchd managed with health watchdog"
infra.mac_studio.performance: "25 tok/s, 400ms first token (up from 18 tok/s, 800ms with old model)."
project.sara.voice.stt_model: "distil-whisper-large-v3 on Jetson, streaming"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `infra.mac_studio` | Recall current model to register the change. |
| 1 | `<mem_update>` | `infra.mac_studio` | Model swapped. UPDATE same key — don't duplicate. "Got it" style, no apology for old info. |
| 2 | `<mem_update>` | `infra.mac_studio` | Quantization and VRAM details. Same key, refined value. |
| 3 | `<mem_write>` | `infra.mac_studio.performance` | New performance baseline with the new model. Worth tracking. |
