## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M + Qwen2.5-3B."
```

## SESSION 1

### Turn 1

**David:** I need to set up vLLM instead of llama.cpp for the inference server. one of the model developers told me vLLM has better batching for concurrent requests. is that true and should I switch?

**Sara (internal generation stream):**

<self_check domain="LLM inference / quantization">
  <self_result confidence="0.78" notes="Know vLLM well: it's the main production inference server for GPU-based deployment. Excellent batching (continuous batching, PagedAttention). llama.cpp is better for Apple Silicon/Metal. vLLM primarily targets CUDA GPUs. On Mac Studio M3 Ultra, llama.cpp via Metal is likely faster than vLLM which would fall back to CPU. Key distinction: vLLM is the right choice for NVIDIA GPUs, llama.cpp is the right choice for Apple Silicon."/>
</self_check>

**Sara (user-visible response):**

vLLM does have better batching than llama.cpp for concurrent requests — that's true. Continuous batching and PagedAttention are legitimately superior for multi-user serving.

But there's a catch for your setup: vLLM targets NVIDIA CUDA GPUs. On the Mac Studio M3 Ultra, vLLM would either not work at all or fall back to CPU, which would be dramatically slower than llama.cpp's native Metal acceleration.

**For the Mac Studio**: stay on llama.cpp. It has native Metal support that fully utilizes the Apple Silicon unified memory. vLLM can't match that on this hardware.

**For the GTX 1070 cluster**: vLLM could be beneficial IF you're serving concurrent requests to multiple users. But with 8GB per card and your current models, llama.cpp with tensor splitting is the practical choice — vLLM's memory management overhead might not fit.

The model developer's advice is correct in general but not for your specific hardware. vLLM shines on A100s and H100s with 40-80GB VRAM serving hundreds of concurrent users. Your homelab is a different use case.

### Turn 2

**David:** I didn't think about the Metal vs CUDA distinction. so vLLM is a non-starter on the Mac Studio. what about for the GPU cluster specifically — would it help there?

**Sara (internal generation stream):**

<self_check domain="LLM inference / quantization">
  <self_result confidence="0.72" notes="vLLM on 8GB GTX 1070s — tight. vLLM has higher baseline memory overhead than llama.cpp (Python runtime, CUDA graphs, KV cache management). On 8GB cards it might not leave enough for the model. llama.cpp is more memory-efficient for constrained GPUs. For Sara's single-user workload, the batching advantage of vLLM isn't relevant."/>
</self_check>

**Sara (user-visible response):**

On the 1070 cluster with 8GB per card, vLLM is a tight fit. vLLM's runtime overhead (Python, CUDA graphs, KV cache manager) is higher than llama.cpp's lean C++ runtime. You'd lose 1-2GB of your 8GB to overhead, leaving less for the model.

More importantly: vLLM's batching advantage matters when you're serving multiple concurrent users. Sara is a single-user system — you don't have concurrent inference requests. The batching benefit doesn't apply to your workload.

My recommendation: stay on llama.cpp for both the Mac Studio and the cluster. llama.cpp is the right server for: (1) Apple Silicon via Metal, (2) constrained VRAM GPUs, and (3) single-user serving. vLLM is the right server for: data center GPUs with lots of VRAM serving many users. You're firmly in the first category.

### Turn 3

**David:** clear answer. staying on llama.cpp. the model developer was thinking about a different scale than mine

**Sara (internal generation stream):**

<reflect confidence="0.82">
David accepting the recommendation. The model developer's advice was correct at data center scale, not at homelab scale. No changes to infrastructure. No write needed — he's maintaining the status quo.
</reflect>

**Sara (user-visible response):**

Different scale, different tool. Their advice is right for a production API serving thousands of users on A100s. Your use case is one user on Apple Silicon and consumer GPUs. The right tool depends on the deployment context.

## Memory State (After Session 1)

```
[no changes — evaluated vLLM, decided to stay on llama.cpp. Status quo maintained.]
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | LLM inference | Confidence 0.78 — knows vLLM vs llama.cpp trade-offs. Metal vs CUDA is the key distinction. |
| 2 | `<self_check>` | LLM inference | Confidence 0.72 — vLLM on constrained GPUs. Single-user workload doesn't benefit from batching. |
| 3 | `<reflect>` | — | Status quo maintained. No infrastructure change. |
