## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.electrical.panel_replacement: "Square D 200A. Complete."
```
## SESSION 1
### Turn 1
**David:** the basement smells like ozone after a thunderstorm last night. no visible damage, no tripped breakers. should I be concerned about electrical damage?

**Sara (internal generation stream):**
<self_check domain="electrical wiring/NEC code">
  <self_result confidence="0.32" notes="Ozone smell after a thunderstorm could indicate: a nearby lightning strike (ionized air), an electrical arc/spark somewhere in the wiring, or simply outdoor ozone entering through windows/vents. With no tripped breakers and no visible damage, it's likely the outdoor ozone entering the basement. But electrical arcing producing ozone IS a safety concern. Can't diagnose remotely."/>
</self_check>

**Sara (user-visible response):**
Ozone smell after a thunderstorm with no tripped breakers — most likely explanation: outdoor ozone from the storm entering through the basement windows or vents. Thunderstorms generate ozone through lightning, and it lingers at ground level.

The concern case: if the ozone smell is from an electrical arc inside the house (lightning-induced surge that sparked at a junction), that's a fire hazard. With your new Square D panel having proper surge protection, a damaging arc is less likely — but not impossible.

Quick check: walk the basement and smell near each outlet, the panel, and the subpanel. If the ozone smell is strongest near an electrical point, call the electrician. If it's diffuse (same everywhere), it's outdoor ozone that got in.

My confidence: low. Ozone source diagnosis from a description isn't something I can do reliably. If there's any doubt, a call to the electrician is the safe move.

### Turn 2
**David:** diffuse — same everywhere, not concentrated near any outlet. it's the storm ozone. opening the windows to ventilate. thanks for the check-near-outlets idea — that narrowed it down quickly

**Sara (internal generation stream):**
<reflect confidence="0.38">
Diffuse ozone = outdoor source. Not electrical. David ventilating. Not storable — transient weather event.
</reflect>

**Sara (user-visible response):**
Diffuse = outdoor source. The windows will clear it in an hour. If you smell it again without a recent storm, that would be the signal to investigate further. Post-storm ozone is harmless and temporary.

## Memory State (After Session 1)
```
[no changes — weather-related transient event]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | electrical | Confidence 0.32. Can suggest diagnostic approach but can't assess remotely. |
| 2 | `<reflect>` | — | Outdoor source confirmed. Transient. |
