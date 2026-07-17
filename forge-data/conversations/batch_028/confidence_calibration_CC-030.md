## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.electrical.panel_replacement: "Square D 200A."
```
## SESSION 1
### Turn 1
**David:** there's a water stain on the basement ceiling that wasn't there yesterday. it's under the upstairs bathroom. plumbing leak?

**Sara (internal generation stream):**
<self_check domain="plumbing/HVAC systems">
  <self_result confidence="0.35" notes="Water stain on basement ceiling under a bathroom — most likely a plumbing leak from the bathroom above. Could be: toilet wax seal, shower drain, supply line, or condensation from the HVAC system. Can't diagnose remotely but the location (directly under bathroom) strongly suggests plumbing."/>
</self_check>

<mem_write key="user.personal.home.plumbing.water_stain" importance="0.60" decay="fast">
Water stain on basement ceiling directly under upstairs bathroom. Appeared overnight. Probable plumbing leak from bathroom above.
</mem_write>

**Sara (user-visible response):**
Water stain directly under the bathroom — high probability it's a plumbing leak from above. Common sources:

1. **Toilet wax seal**: most common. If the toilet was rocked or shifted, the wax seal breaks and water seeps on each flush
2. **Shower/tub drain**: leaking drain connection. Usually shows after showers
3. **Supply line**: pressurized leak from hot/cold water line. Would drip continuously

Quick diagnostic: flush the toilet upstairs and watch the stain. If it gets wet, it's the toilet seal. Then run the shower for 5 minutes and check. This narrows the source before calling a plumber.

My confidence on plumbing is low — I'm going through the common causes. If the diagnostic doesn't pinpoint it, a plumber can scope the pipes with a camera.

### Turn 2
**David:** flushed the toilet — the stain got wetter. it's the wax seal. calling the plumber tomorrow. $150 fix. thanks for the flush test — saved me a diagnostic visit

**Sara (internal generation stream):**
<mem_update key="user.personal.home.plumbing.water_stain">
Water stain diagnosed: toilet wax seal leak. Confirmed by flush test. Plumber scheduled. ~$150 fix.
</mem_update>

**Sara (user-visible response):**
Wax seal replacement is a quick fix — plumber pulls the toilet, replaces the seal, resets the toilet. $150 and done in an hour. Good catch on the stain — undetected toilet seal leaks can cause subfloor rot if they run for months. Caught early.

## Memory State (After Session 1)
```
user.personal.home.plumbing.water_stain: "Toilet wax seal leak. Plumber scheduled. $150."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` + `<mem_write>` | plumbing + concern | Confidence 0.35. Common sources listed. Diagnostic approach. |
| 2 | `<mem_update>` | `...water_stain` | Diagnosed and scheduled fix. |
