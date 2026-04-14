## Memory State (Session 1 Start)

```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M (~55GB) + Phi-3.5 Mini (~7.5GB)."
infra.mac_studio.performance: "25 tok/s, 400ms first token."
```

## SESSION 1

### Turn 1

**David:** swapped Phi-3.5 Mini for Qwen2.5-3B on the Mac Studio for voice. the Qwen 3B is faster and the response quality is better for short conversational turns

**Sara (internal generation stream):**

<mem_read key="infra.mac_studio">
  <mem_result>M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M + Phi-3.5 Mini.</mem_result>
</mem_read>

<mem_update key="infra.mac_studio">
M3 Ultra 96GB. Primary: Qwen3.5-MoE-A22B Q5_K_M (~55GB). Voice: Qwen2.5-3B (replaced Phi-3.5 Mini). Total ~62GB used.
</mem_update>

**Sara (user-visible response):**

Qwen2.5-3B over Phi-3.5 — same model family as the primary makes the response style more consistent between text and voice. What's the tok/s improvement?

### Turn 2

**David:** 220 tok/s on the 3B via MLX. Phi was doing 150. first token latency is 50ms vs 100ms on Phi. the voice pipeline total is now under 1 second end-to-end

**Sara (internal generation stream):**

<mem_write key="infra.mac_studio.voice_model" importance="0.65" decay="slow">
Voice model: Qwen2.5-3B via MLX on Mac Studio. 220 tok/s (was 150 on Phi-3.5). First token 50ms (was 100ms). Voice pipeline: under 1 second end-to-end.
</mem_write>

<mem_update key="project.sara.voice.latency.current">
Voice pipeline: under 1 second end-to-end (down from 1.4s). Improvement from Qwen2.5-3B voice model (50ms first token) replacing Phi-3.5 (100ms).
</mem_update>

**Sara (user-visible response):**

Sub-1-second voice pipeline. From 4.5 seconds at the start to under 1 second now — that's a 4.5x improvement across the optimization journey. 50ms first token means Sara starts responding almost instantly after you stop speaking. At that latency, the conversation feels completely natural.

### Turn 3

**David:** it really does. this is the milestone I was chasing. sub-1-second feels like talking to a person, not waiting for a computer

**Sara (internal generation stream):**

<reflect confidence="0.85">
David celebrating hitting the sub-1-second milestone. "The milestone I was chasing" — this was a specific goal. The technical facts are captured. His satisfaction is emotional, not storable.
</reflect>

**Sara (user-visible response):**

4.5s → 2.1s → 1.4s → sub-1s. Each step was a different optimization: streaming STT, VAD tuning, dedicated GPU, and now the faster voice model. The pipeline is at human conversation latency. Anything further is diminishing returns.

## Memory State (After Session 1)

```
infra.mac_studio: "M3 Ultra 96GB. Primary: Qwen3.5-MoE-A22B Q5_K_M. Voice: Qwen2.5-3B via MLX."
infra.mac_studio.voice_model: "Qwen2.5-3B, 220 tok/s, 50ms first token."
project.sara.voice.latency.current: "Sub-1 second E2E."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` + `<mem_update>` | `infra.mac_studio` | Voice model changed. UPDATE same key. |
| 2 | `<mem_write>` | `...voice_model` | New model specs. |
| 2 | `<mem_update>` | `...latency.current` | Major milestone: sub-1-second. |
| 3 | `<reflect>` | — | David celebrating. Emotional, not storable. |
