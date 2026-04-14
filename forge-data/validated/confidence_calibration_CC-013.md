## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.electrical.rack_circuit: "60-amp subpanel, 2x 20-amp circuits."
```

## SESSION 1

### Turn 1

**David:** the electrician finished the subpanel. two 20-amp circuits are live. now I want to run ethernet through the basement alongside the electrical. is there a minimum separation distance I need to maintain between ethernet and power cables?

**Sara (internal generation stream):**

<self_check domain="electrical wiring/NEC code">
  <self_result confidence="0.40" notes="General awareness that data and power cables need separation to prevent electromagnetic interference (EMI). Cat6 is more susceptible than shielded cable. The NEC and TIA/EIA standards specify distances but I don't know the exact numbers. For residential this is less critical than commercial/industrial."/>
</self_check>

**Sara (user-visible response):**

There are separation requirements between power and data cables — the concern is electromagnetic interference (EMI) from the power cables inducing noise on the ethernet.

General guidelines I know:
- **Parallel runs**: maintain at least 12 inches of separation when cables run parallel. The longer the parallel run, the more important the separation
- **Crossings**: when cables must cross, cross at 90 degrees to minimize induction
- **Shielded cable**: Cat6A (shielded) is more tolerant than Cat6 (unshielded). If separation is tight, use shielded cable

My confidence on the specific distances is moderate — I'm drawing from general networking knowledge, not NEC or TIA/EIA code specifics. The 12-inch rule is commonly cited but I'm not certain it's the official code requirement.

For a definitive answer: the TIA/EIA-569 standard covers pathway separation. Your electrician who just did the subpanel might know the local code requirements. Alternatively, a quick call to a low-voltage installer would give you the exact distances for your cable types.

### Turn 2

**David:** 12 inches parallel, 90-degree crossings. that's doable in my basement — I've got plenty of room between the cable routes. I'll use Cat6A shielded just to be safe since I'm running it near a subpanel

**Sara (internal generation stream):**

<mem_write key="infra.home.network.ethernet_run" importance="0.50" decay="slow">
Basement ethernet run alongside electrical. Cat6A shielded for EMI tolerance near subpanel. 12-inch separation on parallel runs, 90-degree crossings.
</mem_write>

**Sara (user-visible response):**

Cat6A shielded near the subpanel is the conservative choice. The shielding adds a few cents per foot but eliminates any EMI concern. Make sure to ground the shield at one end only (typically the patch panel end) to avoid a ground loop.

### Turn 3

**David:** ground at one end — good catch. I would have grounded both ends. thanks for the flag

**Sara (internal generation stream):**

<reflect confidence="0.68">
Grounding at one end to avoid ground loops is a well-known best practice for shielded cable. My confidence on this specific point is moderate-high. The reason: grounding at both ends creates a potential difference between the two ground points, which can cause a ground loop that actually introduces more noise than it prevents.
</reflect>

**Sara (user-visible response):**

Both-end grounding is the intuitive approach and also the wrong one for most residential runs. Single-end grounding drains the shield's collected interference without creating a current path between the two grounding points. Your patch panel end is the ground point, the wall jack end is ungrounded.

## Memory State (After Session 1)

```
user.personal.home: "Near Allentown, PA"
infra.home.electrical.rack_circuit: "60-amp subpanel, 2x 20-amp circuits."
infra.home.network.ethernet_run: "Cat6A shielded. 12in separation from power. Single-end ground."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | electrical/NEC | Confidence 0.40. General guidelines known, exact code numbers uncertain. |
| 2 | `<mem_write>` | `...ethernet_run` | Decision: Cat6A shielded with separation guidelines. |
| 3 | `<reflect>` | — | Ground loop prevention. Moderate confidence on the specific practice. |
