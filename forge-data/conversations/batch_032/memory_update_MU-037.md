## Memory State (Session 1 Start)
```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB. Primary inference."
infra.mac_studio.models: "Dual model: 22B primary + 7B fast."
```
## SESSION 1
### Turn 1
**David:** swapped the 7B fast model for a 14B. the 7B was too shallow for tool-use decisions. 14B fits in memory with the 22B and the quality jump on function calling is massive

**Sara (internal generation stream):**
<mem_update key="infra.mac_studio.models">
Dual model: 22B primary + 14B fast (upgraded from 7B). 14B chosen for better tool-use/function calling quality. Both fit in 96GB unified memory.
</mem_update>

**Sara (user-visible response):**
Updated. Dual model stack is now 22B + 14B. The 7B-to-14B jump makes sense for tool use — function calling needs enough capacity to reason about parameter selection, and 7B models consistently fumble multi-parameter tools. The 14B should handle that without eating too much of your memory budget. You're at roughly 22 + 14 = ~36GB for weights, leaving 60GB for context and KV cache. Plenty of headroom.

### Turn 2
**David:** exactly. KV cache was the concern but at 14B quantized it's fine. inference speed dropped from 45 tok/s to 38 tok/s on the fast model but the accuracy gain is worth it

**Sara (internal generation stream):**
<mem_update key="infra.mac_studio.models">
22B primary + 14B fast (was 7B). 14B quantized. 38 tok/s (was 45). Better tool-use accuracy. KV cache headroom OK.
</mem_update>

**Sara (user-visible response):**
38 tok/s on the fast model is still well within real-time for tool routing — the latency difference between 45 and 38 is imperceptible in practice. You traded ~15% speed for a quality jump that actually changes the reliability of the tool pipeline. Good trade.

## Memory State (After Session 1)
```
infra.mac_studio.models: "22B primary + 14B fast (was 7B). 38 tok/s. Better tool-use."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_update>` | `...models` | Model swap 7B → 14B. Same key updated. |
| 2 | `<mem_update>` | `...models` | Added speed benchmark. Same key refined. |
