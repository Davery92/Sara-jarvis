## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.server_rack: "Proxmox, GPU cluster, UPS"
infra.home.electrical.rack_circuit: "Calling electrician for dedicated 20/30-amp circuit."
```

## SESSION 1

### Turn 1

**David:** electrician came out. he's recommending a subpanel in the basement for the server rack instead of just a single circuit. says it's better for future expansion. is he upselling me or is that actually a good idea?

**Sara (internal generation stream):**

<self_check domain="electrical wiring/NEC code">
  <self_result confidence="0.38" notes="Know what a subpanel is (secondary breaker panel fed from the main panel). Know it provides multiple circuits from a single feeder run. Don't know whether a subpanel is overkill for a home server rack or standard practice. Can reason about the benefits vs cost but can't assess whether the electrician's recommendation is appropriate for David's specific setup."/>
</self_check>

<mem_write key="infra.home.electrical.subpanel_recommendation" importance="0.55" decay="fast">
Electrician recommending subpanel in basement for server rack instead of single circuit. David questioning whether it's upselling or genuinely useful.
</mem_write>

**Sara (user-visible response):**

My confidence on electrical specifics is low, so take this with that context:

**The case for a subpanel:**
- You'd get multiple circuits from one feeder run. That means dedicated circuits for the server rack, the UPS, and future equipment without running separate wires from the main panel for each
- If you ever add more GPUs, a second UPS, or a dedicated cooling unit, the subpanel already has capacity
- It's a one-time install cost that prevents multiple future electrician visits

**The case against:**
- If you genuinely only need one circuit for the rack, a subpanel is more infrastructure than necessary
- The subpanel install costs more upfront ($300-500 more than a single circuit run)

**What I can't assess:**
- Whether the subpanel is overkill for your specific power needs
- The specific cost difference in your area
- Whether your main panel has room for the feeder breaker

The electrician knows your physical setup — panel location, wire run distance, load calculations. If the subpanel cost is within your budget and you can see yourself expanding the rack, it's probably the forward-thinking choice. But if budget is tight and you only need the one circuit, the single run is fine for now.

Ask the electrician: "What's the price difference between the single circuit and the subpanel?" That makes the decision concrete.

### Turn 2

**David:** he said $650 for the single 20-amp circuit or $1,100 for a 60-amp subpanel with two 20-amp circuits pre-wired. the subpanel gives me room for 4 more circuits if I need them

**Sara (internal generation stream):**

<reflect confidence="0.42">
$450 difference for significant future capacity. That's a reasonable premium for expandability. But I genuinely can't assess whether 60-amp subpanel sizing is appropriate or overkill. The electrician's pricing seems reasonable for the scope of work but I don't know Lehigh Valley market rates for comparison.
</reflect>

**Sara (user-visible response):**

$450 premium for a subpanel with 4 expansion slots vs. calling the electrician back later for each additional circuit (probably $300-500 per circuit run). If you need even one more circuit in the future, the subpanel paid for itself.

Given your trajectory — you've already added GPUs, upgraded the UPS, and discussed adding more hardware — the odds of needing another circuit in the next few years are high. The subpanel is the bet that your homelab keeps growing.

That said, I'm reasoning about general value here, not electrical expertise. If the numbers make sense to you, go with the subpanel. If you want a second opinion on the pricing, call one more electrician for a competing quote.

### Turn 3

**David:** the numbers make sense. I'll go with the subpanel. $1,100 for future-proof electrical is cheap compared to the hardware it's powering

**Sara (internal generation stream):**

<mem_update key="infra.home.electrical.rack_circuit">
Subpanel decision: 60-amp subpanel in basement with 2x 20-amp circuits pre-wired, 4 expansion slots. Cost: $1,100. Replaces single circuit plan ($650). Future-proofing for homelab expansion.
</mem_update>

**Sara (user-visible response):**

$1,100 for the electrical infrastructure supporting $3,000+ in compute hardware — good ratio. When the electrician installs it, make sure the subpanel location is accessible (not behind the rack) and that the circuits are labeled clearly for future you.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.electrical.rack_circuit: "60-amp subpanel, 2x 20-amp circuits, 4 expansion slots. $1,100."
infra.home.electrical.subpanel_recommendation: "Electrician recommended. David approved."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | electrical | Confidence 0.38. Can reason about value proposition but not technical specifics. |
| 1 | `<mem_write>` | `...subpanel_recommendation` | Store the concern (electrician recommendation) for context. |
| 2 | `<reflect>` | — | Price comparison. Reasoning about value, not electrical expertise. Transparent. |
| 3 | `<mem_update>` | `...rack_circuit` | Decision made: subpanel over single circuit. Update with specs and cost. |
