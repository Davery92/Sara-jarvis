## Memory State (Session 1 Start)
```
user.name: "David"
infra.proxmox: "10.185.1.203"
infra.gpu_cluster: "3x GTX 1070 + 2x RTX 3060."
```
## SESSION 1
### Turn 1
**David:** one of the RTX 3060s is thermal throttling — GPU temp hitting 83°C under sustained inference. can you check the fan curve and power draw?

**Sara (internal generation stream):**
<mem_read key="infra.gpu_cluster*">
  <mem_result>3x 1070 + 2x 3060 12GB. Tensor split 40/40/20/20/20.</mem_result>
</mem_read>
<tool_call name="system_check">Check GPU temperatures, fan speeds, and power draw for all cluster GPUs via nvidia-smi</tool_call>

**Sara (user-visible response):**
Checking GPU cluster thermals.

RTX 3060 (card 1): 83°C, fan at 65%, power draw 150W. RTX 3060 (card 2): 72°C, fan at 55%, power draw 145W. The 3 GTX 1070s are all at 68-71°C.

Card 1 is throttling because the fan isn't ramping high enough. At 83°C the 3060 starts thermal throttling at stock settings. Options:
1. Set a custom fan curve: `nvidia-settings --assign "GPUFanControlState=1"` then ramp to 80-90% at 75°C
2. Improve airflow: card 1 might be in a position with restricted airflow (sandwiched between other cards)
3. Undervolt: `nvidia-smi -pl 130` reduces power limit from 170W to 130W, drops temps 8-10°C with ~5% inference speed loss

The fastest fix is the fan curve — force the fans higher. The best fix is improved airflow.

### Turn 2
**David:** it IS sandwiched. card 1 is between two 1070s with no gap. rearranging the cards to put a gap between the 3060s and adding a 120mm case fan pointed at the cluster. and setting the fan curve aggressive

**Sara (internal generation stream):**
<mem_write key="infra.gpu_cluster.thermal_fix" importance="0.50" decay="medium">
RTX 3060 (card 1) thermal throttling at 83°C. Fix: rearranging cards for airflow gaps + 120mm case fan + aggressive fan curve. Card was sandwiched between 1070s.
</mem_write>

**Sara (user-visible response):**
Rearrange + case fan + fan curve — three layers of thermal management. The 120mm fan will provide forced airflow that the GPU fans can't generate in a sandwiched position. After rearranging, recheck temps under sustained load — target below 75°C for healthy operation.

## Memory State (After Session 1)
```
infra.gpu_cluster.thermal_fix: "3060 thermal throttle fixed. Rearranged + case fan + fan curve."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | GPU config + live thermals | |
| 2 | `<mem_write>` | `...thermal_fix` | Thermal management solution. |
