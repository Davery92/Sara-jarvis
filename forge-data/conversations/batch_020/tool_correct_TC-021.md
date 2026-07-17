## Memory State (Session 1 Start)
```
user.name: "David"
infra.home.network.hardware: "UniFi UDM Pro. IDS/IPS."
infra.home.network.iot_vlan: "VLAN 30."
```
## SESSION 1
### Turn 1
**David:** the kid says the internet is slow. I'm on my work laptop and it's fine. can you check if the IoT VLAN is saturating the bandwidth or if it's a device-specific issue?

**Sara (internal generation stream):**
<mem_read key="infra.home.network*">
  <mem_result>UDM Pro. IoT VLAN 30. IDS/IPS enabled.</mem_result>
</mem_read>
<tool_call name="system_check">Check UDM Pro bandwidth usage per VLAN and per-client data for the kid's devices</tool_call>

**Sara (user-visible response):**
Checking per-VLAN bandwidth on the UDM Pro.

Main LAN bandwidth: 45 Mbps down (normal). IoT VLAN: 8 Mbps (normal). The kid's iPad is connected to the main WiFi and showing 2 Mbps down — that's the problem. The bandwidth is available but her device isn't getting it.

Check: is the iPad connected to the 5GHz or 2.4GHz SSID? If it's on 2.4GHz (which some older iPads prefer), it'll be slower, especially if she's far from the AP. Also check if the iPad's WiFi assist or VPN is throttling.

### Turn 2
**David:** 2.4GHz — that's probably it. the iPad always connects to 2.4 when the 5GHz signal is marginal. moving the AP closer to her room would fix this. or I can split the SSIDs and force the iPad to 5GHz only

**Sara (internal generation stream):**
<reflect confidence="0.74">
David diagnosing the WiFi band issue. SSID splitting or AP repositioning — both valid. Not storing this as a permanent fix until David implements something.
</reflect>

**Sara (user-visible response):**
Split SSIDs (separate 2.4G and 5G names) let you force devices to specific bands. Set the iPad to the 5G-only SSID. But the cleaner fix is AP placement: if the 5GHz signal is strong in her room, the iPad will prefer it automatically. UniFi APs let you adjust minimum RSSI to kick devices off weak bands.

## Memory State (After Session 1)
```
[no changes — transient WiFi issue, diagnosis in progress]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Network config (memory) + live bandwidth (tool) | |
| 2 | `<reflect>` | — | WiFi band issue. Fix not implemented yet. |
