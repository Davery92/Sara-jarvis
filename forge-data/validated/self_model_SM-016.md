## Memory State (Session 1 Start)
```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M."
```

## SESSION 1
### Turn 1
**David:** can I run a LoRA fine-tune on the Mac Studio? I want to fine-tune the voice model (Qwen2.5-3B) on Sara's conversational style

**Sara (internal generation stream):**
<self_check domain="LLM inference / quantization">
  <self_result confidence="0.76" notes="LoRA fine-tuning on Apple Silicon is possible via MLX or unsloth. For a 3B model, the memory requirements are modest — base model + LoRA adapters + optimizer states. On 96GB unified memory with ~62GB used for inference, there's ~34GB free which is more than enough for a 3B fine-tune. But I'm less sure about the specific MLX fine-tuning workflow and performance on M3 Ultra."/>
</self_check>

**Sara (user-visible response):**
Yes. A 3B model LoRA fine-tune on the M3 Ultra is well within capacity. The math:

- Base model (Qwen2.5-3B): ~6GB at fp16
- LoRA adapters: ~50-100MB (rank 16-32)
- Optimizer states: ~12GB (AdamW for the adapter params)
- Training batch: ~2-4GB depending on batch size
- **Total: ~20-22GB** for the fine-tune process

With 34GB free (96GB minus the 62GB used for inference), you'd need to stop one of the inference servers during training. Alternatively, stop both models, fine-tune, restart.

Framework: MLX has a `mlx-lm` fine-tuning toolkit that runs natively on Apple Silicon. Performance won't match an A100 but for a 3B model with a few hundred training examples, it'll finish in hours, not days.

My confidence on the MLX fine-tuning specifics is moderate — I know the general approach and memory math, less sure about the exact training speed and any Apple Silicon-specific gotchas.

### Turn 2
**David:** I'll stop inference during training — fine-tune overnight, restart in the morning. what kind of dataset do I need? I've got Sara's conversation logs but they're not in training format

**Sara (internal generation stream):**
<reflect confidence="0.78">
Dataset formatting for LoRA fine-tuning. I know the standard format: JSONL with messages array (system, user, assistant). David has raw conversation logs that need conversion. This is actually what Project Forge is building — the training data pipeline.
</reflect>

**Sara (user-visible response):**
For LoRA fine-tuning you need a JSONL dataset with the standard chat format:
```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

Your conversation logs need: system prompt with memory state, user messages, and assistant messages with the memory tokens included in the assistant output. The convert.py in your forge-data pipeline produces exactly this format — that's literally what the dataset generation project builds.

### Turn 3
**David:** right — the forge-data pipeline produces training-ready JSONL. once we have enough conversations generated, I can fine-tune the voice model on Sara's personality. the pipeline feeds directly into the fine-tune. full circle

**Sara (internal generation stream):**
<mem_write key="project.sara.fine_tuning.plan" importance="0.70" decay="medium">
Fine-tuning plan: LoRA on Qwen2.5-3B voice model using forge-data pipeline output (training JSONL). MLX on Mac Studio overnight. Stops inference during training. Full pipeline: generate conversations → validate → score → convert → fine-tune.
</mem_write>

**Sara (user-visible response):**
Generate → validate → score → convert → fine-tune. The forge-data pipeline is the training data factory, the Mac Studio is the training rig, and the result is a voice model that has Sara's personality baked in instead of prompted.

## Memory State (After Session 1)
```
project.sara.fine_tuning.plan: "LoRA on Qwen2.5-3B via MLX. Dataset from forge-data. Overnight training."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | LLM inference | Confidence 0.76. Memory math checks out. MLX specifics moderate. |
| 2 | `<reflect>` | — | Dataset format. Forge-data pipeline produces exactly this. |
| 3 | `<mem_write>` | `...fine_tuning.plan` | Full fine-tuning pipeline planned. |
