## Memory State (Session 1 Start)
```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Intune, Entra ID P2, M365"
```

## SESSION 1
### Turn 1
**David:** a client wants to implement Conditional Access policies that block sign-in from countries outside the US. they're worried about credential stuffing from overseas IPs. is that something Intune CA can handle, or do I need a third-party tool?

**Sara (internal generation stream):**
<self_check domain="Intune / Entra ID / M365">
  <self_result confidence="0.78" notes="Location-based Conditional Access is a core Entra ID feature. Named Locations define trusted/blocked geographies, CA policies enforce them. No third-party needed. Confident on this — it's a standard MSP deployment."/>
</self_check>

**Sara (user-visible response):**
Native Entra ID Conditional Access handles this directly — no third-party tool needed.

Steps:
1. **Entra ID > Security > Named Locations**: create a named location for "Allowed Countries" → select US (and any other countries the client travels to)
2. **Conditional Access > New Policy**: target all users, all cloud apps
3. **Conditions > Locations**: include "Any location", exclude "Allowed Countries"
4. **Grant**: Block access

That blocks all sign-ins from outside the US. If the client has employees who travel, add those countries to the allowed list or use a "trusted network" named location for their VPN.

One caveat: location-based CA uses IP geolocation which isn't 100% accurate. VPN/proxy users might trigger false blocks. The client should have a break-glass process for legitimate blocked sign-ins.

### Turn 2
**David:** clean. I'll deploy this today. the client doesn't have travelers so US-only is fine. thanks for confirming it's native — I wasn't sure if named locations supported country-level blocking

**Sara (internal generation stream):**
<mem_write key="user.work.clients.geo_blocking" importance="0.50" decay="fast">
Client requesting geo-blocking via Entra ID Conditional Access. US-only named location policy. No travelers, straightforward deployment.
</mem_write>

**Sara (user-visible response):**
Named Locations support country-level, IP range, and GPS-based (for compliant devices). Country-level is the simplest for blanket geo-blocking. Deploy and check the CA sign-in logs after 24 hours — you'll see any blocked attempts and can verify the policy is working.

## Memory State (After Session 1)
```
user.work.clients.geo_blocking: "Client US-only Conditional Access. Named Locations."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Intune/Entra ID | Confidence 0.78. Standard CA deployment. |
| 2 | `<mem_write>` | `...geo_blocking` | Client deployment. Fast decay. |
