## Memory State (Session 1 Start)
```
user.name: "David"
infra.home.network.hardware: "UniFi UDM Pro + US-8-60W. IDS/IPS enabled."
infra.home.network.iot_vlan: "VLAN 30 for IoT."
```

## SESSION 1
### Turn 1
**David:** the UDM Pro IDS is flagging traffic from one of the smart plugs. it's making DNS requests to a Chinese IP every 30 minutes. is that normal for cheap IoT devices?

**Sara (internal generation stream):**
<mem_write key="infra.home.network.security.smart_plug_alert" importance="0.65" decay="fast">
UDM Pro IDS flagging smart plug making DNS requests to Chinese IP every 30 minutes. Potential data exfiltration or telemetry from cheap IoT hardware.
</mem_write>

**Sara (user-visible response):**
Common but not "normal" in the good sense. Cheap IoT devices (especially Tuya-based smart plugs) frequently phone home to cloud servers in China for telemetry and firmware checks. It's not necessarily malicious — it's the manufacturer's cloud service. But it's data about your home network leaving the country.

Options: block the DNS requests in the UDM Pro firewall (the plug may stop working if it depends on cloud), replace with a local-only plug (Zigbee via HA), or accept it since the IoT VLAN isolates it from your servers.

### Turn 2
**David:** the IoT VLAN isolation means it can't reach anything important. I'll add a DNS block for that IP and see if the plug still works locally. if it breaks, I'll replace it with a Zigbee one

**Sara (internal generation stream):**
<mem_write key="infra.home.network.security.smart_plug_fix" importance="0.50" decay="fast">
Smart plug DNS exfiltration: blocking Chinese IP at UDM Pro firewall level. Testing if plug still works with cloud blocked. Fallback: replace with Zigbee plug (local-only via HA).
</mem_write>

**Sara (user-visible response):**
DNS block + test is the right diagnostic approach. If the plug works locally without cloud, you've got the best outcome: functional device with no data leaving your network. If it breaks, the Zigbee replacement through HA gives you better integration anyway.

## Memory State (After Session 1)
```
infra.home.network.security.smart_plug_alert: "Cheap plug phoning home to Chinese IP."
infra.home.network.security.smart_plug_fix: "DNS block testing. Zigbee fallback."
```

---

*Time gap: next day*

---
## Memory State (Session 2 Start)
```
[same as After Session 1]
```

## SESSION 2
### Turn 1
**David:** the DNS block worked — the smart plug still functions locally without cloud access. HA controls it fine over the local network. blocking that IP on all IoT VLAN traffic now, not just that one plug

**Sara (internal generation stream):**
<mem_read key="infra.home.network.security.smart_plug*">
  <mem_result>DNS block testing on Chinese IP. Plug phoning home every 30 min.</mem_result>
</mem_read>
<mem_update key="infra.home.network.security.smart_plug_fix">
DNS block successful. Smart plug works locally without cloud. Expanding block to all IoT VLAN traffic to Chinese IP. Plug controlled via HA over local network.
</mem_update>

**Sara (user-visible response):**
Local-only operation confirmed — expanding the block to the whole IoT VLAN is the right call. Any other Tuya-based devices will benefit from the same block. The IDS just earned its keep: it caught telemetry you wouldn't have noticed without it.

## Memory State (After Session 2)
```
infra.home.network.security.smart_plug_fix: "RESOLVED. DNS block, local operation. Applied to all IoT VLAN."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| S1T1 | `<mem_write>` | `...smart_plug_alert` | IDS finding. |
| S1T2 | `<mem_write>` | `...smart_plug_fix` | Diagnostic approach. |
| S2T1 | `<mem_read>` + `<mem_update>` | `...smart_plug_fix` | Fix confirmed, expanded. |
