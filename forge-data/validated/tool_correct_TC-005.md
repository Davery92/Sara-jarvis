## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.salience: "Salience scoring threshold 1.5"
project.sara.deliberation: "15-minute cooldowns"
infra.mac_studio: "M3 Ultra 96GB, Qwen3.5-122B-A10B IQ4_XS"
infra.gpu_cluster: "5x GTX 1070 in cluster"
infra.gpu_passthrough_vm: "10.185.1.210, single GTX 1070, Gemma 4"
```

## SESSION 1

### Turn 1

**David:** I want to figure out if I can run a second model on the Mac Studio alongside Qwen. need to calculate how much VRAM I'd need for both and whether 96GB is enough

**Sara (internal generation stream):**

<mem_read key="infra.mac_studio">
  <mem_result>M3 Ultra 96GB, Qwen3.5-122B-A10B IQ4_XS</mem_result>
</mem_read>

<reflect confidence="0.78">
David wants a VRAM calculation for running two models simultaneously on the Mac Studio. I know the hardware (96GB unified memory) and the current model from memory. But the VRAM calculation for the second model depends on which model and quantization he wants to run. Memory gives me the context; I need a calculation tool for the actual math.
</reflect>

<tool_call name="calculation">Calculate VRAM requirements for Qwen3.5-122B-A10B at IQ4_XS plus a second model on 96GB unified memory Mac Studio</tool_call>

**Sara (user-visible response):**

The Mac Studio has 96GB unified memory shared between CPU and GPU. Let's do the math.

**Qwen3.5-122B-A10B at IQ4_XS:**
- 122B parameters, MoE with ~10B active. IQ4_XS is roughly 4.25 bits per param on the full model.
- Total model size: ~65GB at IQ4_XS
- Plus context buffer at 64K context: ~8-12GB depending on batch size
- **Current usage: ~75-77GB**

**Remaining for a second model: ~19-21GB**

That's enough for a small model. Candidates:
- **Gemma 4 26B-A4B at Q4_K_M**: ~15GB — fits with margin
- **Phi-3.5 Mini (3.8B) at fp16**: ~7.5GB — fits easily
- **Mistral 7B at Q8_0**: ~7.5GB — fits easily
- **Qwen2.5 32B at IQ4_XS**: ~18GB — tight but possible

What's the use case for the second model? That determines the size/quality trade-off.

### Turn 2

**David:** I want a fast model for the voice pipeline. the passthrough VM is doing voice right now but if I could run a smaller model on the Mac Studio it might be even faster — Apple's Metal inference is fast for smaller models

**Sara (internal generation stream):**

<mem_read key="infra.gpu_passthrough_vm">
  <mem_result>10.185.1.210, single GTX 1070, Gemma 4 26B-A4B, ~35 tok/s for voice pipeline</mem_result>
</mem_read>

<reflect confidence="0.76">
David wants to move voice inference from the 1070 passthrough VM to the Mac Studio. The question is whether a small model on Metal would be faster than the 1070. Metal inference with Apple's MLX framework is very fast for models that fit in memory. A 7B or 3.8B model on the M3 Ultra would likely exceed 100 tok/s.
</reflect>

**Sara (user-visible response):**

Voice pipeline on the Mac Studio with a small model could be significantly faster than the 1070. Some estimates:

- **Phi-3.5 Mini (3.8B) via MLX**: probably 150-200 tok/s on the M3 Ultra. Uses ~7.5GB.
- **Mistral 7B via MLX**: probably 80-120 tok/s. Uses ~7.5GB.
- **Gemma 4 26B-A4B via llama.cpp Metal**: probably 40-60 tok/s. Uses ~15GB.

For voice, you want the fastest first-token latency, not the best quality. The 3.8B or 7B would give you sub-100ms first token, which would push your voice pipeline latency well under 1 second.

The trade-off: voice response quality drops with a smaller model. But for short conversational responses, a 7B model is usually fine.

I'm moderately confident on the tok/s estimates — they're based on general MLX benchmarks, not your specific hardware. You'd need to test to get exact numbers.

### Turn 3

**David:** I'll test Phi-3.5 Mini on the Mac Studio this weekend. if it hits 150+ tok/s and the voice quality is acceptable, I'll move voice off the 1070 and free up that GPU for the cluster again

**Sara (internal generation stream):**

<mem_write key="project.sara.voice.mac_studio_evaluation" importance="0.60" decay="fast">
Planning to test Phi-3.5 Mini (3.8B) via MLX on Mac Studio for voice pipeline. Target: 150+ tok/s. If quality acceptable, voice moves off GTX 1070 passthrough VM, GPU returns to cluster.
</mem_write>

**Sara (user-visible response):**

If it works, you get three wins: faster voice pipeline, the 1070 back in the cluster (6 GPUs again), and reduced complexity (one less dedicated VM). The VRAM budget would be Qwen at ~75GB + Phi at ~7.5GB = ~82.5GB out of 96GB — 13.5GB of headroom.

Run both models simultaneously and check that Qwen's inference speed doesn't degrade. Unified memory contention is the risk — if both models are generating at the same time, bandwidth gets split.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.salience: "Salience scoring threshold 1.5"
infra.mac_studio: "M3 Ultra 96GB, Qwen3.5-122B-A10B IQ4_XS (~75GB)"
infra.gpu_cluster: "5x GTX 1070 in cluster"
infra.gpu_passthrough_vm: "10.185.1.210, single GTX 1070, Gemma 4 (voice pipeline)"
project.sara.voice.mac_studio_evaluation: "Testing Phi-3.5 Mini via MLX for voice. Target 150+ tok/s. Would free 1070 back to cluster."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `infra.mac_studio` | Memory has hardware specs. Tool needed for VRAM calculation. |
| 1 | `<reflect>` | — | Calculation depends on model choice. Memory provides context, tool does math. |
| 1 | `<tool_call>` | `calculation` | VRAM requirement math. Memory has inputs, tool computes. |
| 2 | `<mem_read>` | `infra.gpu_passthrough_vm` | Recall current voice pipeline setup for comparison. |
| 2 | `<reflect>` | — | MLX performance estimates. Moderate confidence — need testing. |
| 3 | `<mem_write>` | `project.sara.voice.mac_studio_evaluation` | Concrete test plan. Fast decay — will be done this weekend. |
