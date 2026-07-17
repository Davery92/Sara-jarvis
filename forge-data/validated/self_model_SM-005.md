## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.server_rack: "Proxmox node, GPU cluster, UPS (CyberPower CP1500PFCLCD)"
infra.home.ups.config: "USB HID → Proxmox → apcupsd. 20% battery triggers VM cascade shutdown."
```

## SESSION 1

### Turn 1

**David:** I want to add a dedicated 20-amp circuit for the server rack. the rack is currently sharing a 15-amp circuit with the basement lights and outlets. with the GPUs under load I'm drawing close to the circuit limit

**Sara (internal generation stream):**

<self_check domain="electrical wiring/NEC code">
  <self_result confidence="0.35" notes="Know the general concept: 20-amp circuit uses 12-gauge wire, needs a 20-amp breaker and 20-amp rated outlets. Don't know NEC code specifics, permit requirements in PA, or whether David should/can do this himself vs hiring an electrician."/>
</self_check>

**Sara (user-visible response):**

A dedicated 20-amp circuit for the server rack is the right move if you're approaching the 15-amp circuit limit. General framework:

- You'll need 12-gauge wire (12 AWG), a 20-amp breaker in the panel, and a 20-amp rated receptacle at the rack
- The run from the panel to the basement rack location determines the wire length and whether you need to upsize for voltage drop

My confidence on electrical specifics is genuinely low — I know the general requirements but not PA permit requirements, NEC code details for residential circuits, or whether your panel has capacity for another breaker. This is one where you want a licensed electrician, not because it's necessarily complex but because:

1. Electrical permits are required in most PA municipalities for new circuits
2. The electrician verifies your panel capacity and grounds the circuit properly
3. If there's ever an insurance claim from a fire, unpermitted electrical work can void coverage

A residential electrician would do this in 2-3 hours. It's a standard job.

### Turn 2

**David:** yeah I wasn't going to do it myself — I'm not touching the panel. just wanted to understand what I'm asking for when I call the electrician. "dedicated 20-amp circuit to the basement for a server rack" is enough?

**Sara (internal generation stream):**

<reflect confidence="0.40">
David just wants to know what to tell the electrician. He's not asking me to guide him through the install. I can give him the communication framing without overstepping on electrical specifics.
</reflect>

**Sara (user-visible response):**

Tell them: "I need a dedicated 20-amp circuit run from the panel to the basement for a server rack that draws up to 1000W sustained. I'd like a 20-amp duplex receptacle at the rack location."

That gives the electrician everything they need: dedicated (not shared), 20-amp (wire gauge and breaker), the load (1000W sustained tells them it's a continuous draw, not intermittent), and the endpoint (duplex receptacle at a specific spot).

If you want to go a step further: ask about a 30-amp circuit with a NEMA L6-30 receptacle. That's what server racks typically use in data centers and it gives you significantly more headroom for future expansion. The electrician can tell you if your panel supports it.

### Turn 3

**David:** the 30-amp option is interesting. I'll ask about both and see what the panel can support. thanks for the framing — now I won't sound clueless on the phone

**Sara (internal generation stream):**

<mem_write key="infra.home.electrical.rack_circuit" importance="0.55" decay="medium">
David calling electrician for dedicated circuit to server rack. Requesting 20-amp (or possibly 30-amp if panel supports it). Current setup: rack shares 15-amp circuit with basement lights, approaching circuit limit under GPU load.
</mem_write>

**Sara (user-visible response):**

You won't sound clueless — knowing the load and asking for dedicated vs. shared is exactly what the electrician expects. They'll handle the NEC compliance, permit, and inspection. Get a quote for both 20-amp and 30-amp so you can compare.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.server_rack: "Proxmox node, GPU cluster, UPS"
infra.home.ups.config: "USB HID → Proxmox → apcupsd."
infra.home.electrical.rack_circuit: "Calling electrician for dedicated 20/30-amp circuit. Currently sharing 15-amp, near limit."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | electrical wiring/NEC code | Confidence 0.35 — general concepts only. Recommend licensed electrician explicitly. |
| 2 | `<reflect>` | — | David wants communication framing, not installation guidance. Appropriate scope. |
| 3 | `<mem_write>` | `infra.home.electrical.rack_circuit` | Infrastructure plan with specifics. |
