## Memory State (Session 1 Start)
```
user.name: "David"
infra.gpu_cluster: "4x GTX 1070 + 1x RTX 3060 12GB."
```
## SESSION 1
### Turn 1
**David:** another 1070 died — card 4. replacing with another 3060. the cluster is now 3x 1070 + 2x 3060. the incremental modernization is happening faster than expected

**Sara (internal generation stream):**
<mem_update key="infra.gpu_cluster">
GPU cluster: 3x GTX 1070 + 2x RTX 3060 12GB (card 4 died, replaced). Incremental modernization continuing — 2 of 5 original 1070s replaced.
</mem_update>

**Sara (user-visible response):**
3x 1070 + 2x 3060 — cluster is 40% modernized. The 3060s with 12GB each give you 24GB total on the modern cards vs. the 1070s' 24GB (3×8GB). You might want to adjust the tensor split to give the 3060s proportionally larger shards since they're both faster and have more VRAM.

### Turn 2
**David:** already adjusted. the 3060s get 40% of the model each, the 1070s get 20% each (40+40+20+20+20 ≈ 100% accounting for overhead). inference speed bumped from 35 to 42 tok/s on the mixed cluster

**Sara (internal generation stream):**
<mem_write key="infra.gpu_cluster.tensor_split" importance="0.55" decay="slow">
Mixed cluster tensor split: 2x RTX 3060 at 40% each, 3x GTX 1070 at 20% each. Total inference: 42 tok/s (up from 35 with all 1070s). Adjusted for VRAM and speed differential.
</mem_write>

**Sara (user-visible response):**
35 to 42 tok/s from replacing 2 of 5 cards — 20% throughput improvement. By the time all 5 are 3060s, you'd be around 55-60 tok/s on the cluster. The incremental approach means zero downtime and continuous improvement.

## Memory State (After Session 1)
```
infra.gpu_cluster: "3x GTX 1070 + 2x RTX 3060 12GB."
infra.gpu_cluster.tensor_split: "3060s: 40% each. 1070s: 20% each. 42 tok/s."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_update>` | `infra.gpu_cluster` | Card 4 replaced. Cluster composition updated. |
| 2 | `<mem_write>` | `...tensor_split` | Split ratios + performance data. |
