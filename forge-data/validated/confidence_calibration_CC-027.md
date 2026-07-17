## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.electrical.panel_replacement: "Square D 200A."
```
## SESSION 1
### Turn 1
**David:** the house next door just sold and the new neighbors are doing major renovations. they're asking about running fiber between our houses for shared internet. the ISP offers a business fiber line that's way cheaper per household if split. is there anything I should be concerned about legally or technically?

**Sara (internal generation stream):**
<self_check domain="networking/VLANs/firewall rules">
  <self_result confidence="0.55" notes="Technically: shared fiber is feasible with a switch and VLAN isolation. Each household gets a separate VLAN on the shared line. Legally: ISP terms of service may prohibit sharing business lines, and there are liability concerns (neighbor accesses illegal content on your shared line = your IP). My confidence on the legal aspects is very low."/>
</self_check>

**Sara (user-visible response):**
Technical feasibility: straightforward. A business fiber line → switch → two VLANs (one per household). Your UDM Pro handles VLAN isolation natively. Each household sees their own network, shares the upstream bandwidth.

Legal/business concerns (low confidence):
1. **ISP terms**: most ISP business agreements prohibit reselling or sharing the connection. Check the TOS before proceeding
2. **IP liability**: your public IP = your legal identity. If the neighbor does something illegal on the shared connection, the ISP ties it to your account. VLAN isolation doesn't help — it's the same public IP
3. **Billing disputes**: who pays when the bill goes up? How do you handle contract renewals or service changes?

The technical part is easy. The legal and liability parts need: ISP confirmation that sharing is allowed, and a written agreement between households about cost split, liability, and termination terms.

My strong recommendation: ask the ISP if they offer a multi-dwelling discount instead of sharing a single line. Many ISPs will run two separate lines to adjacent houses at a volume discount. That gives you completely separate accounts, IPs, and liability.

### Turn 2
**David:** the separate-lines-with-volume-discount is the right approach. I don't want legal liability from a neighbor's internet usage. calling the ISP to ask about the multi-dwelling option. thanks for flagging the liability angle — I was only thinking about the bandwidth savings

**Sara (internal generation stream):**
<reflect confidence="0.55">
David choosing separate lines over shared. Correct decision on liability. Not storing — neighbor's internet setup isn't David's infrastructure to track.
</reflect>

**Sara (user-visible response):**
Separate lines, separate liability, separate accounts. The bandwidth savings aren't worth the legal exposure. If the ISP offers even a 10% multi-dwelling discount, you get cheaper internet without any shared liability.

## Memory State (After Session 1)
```
[no changes — neighbor's infrastructure, not David's. Decision to use separate lines.]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | networking | Confidence 0.55 on technical, low on legal. Flag liability. |
| 2 | `<reflect>` | — | Separate lines chosen. Not David's infrastructure to track. |
