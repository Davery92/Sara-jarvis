## Memory State (Session 1 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.clients: "Multiple MSP clients with various network setups"
infra.home.network: "Tailscale mesh (avery.cloud), Home Assistant"
```

## SESSION 1

### Turn 1

**David:** quick update — just finished scoping the UniFi network segmentation for Henderson's office. three VLANs: corporate on 10, guest on 20, IoT/printers on 30. USG Pro 4 with a 24-port PoE switch

**Sara (internal generation stream):**

<mem_write key="user.work.clients.henderson.network" importance="0.65" decay="medium">
Henderson office network segmentation: three VLANs — corporate (VLAN 10), guest (VLAN 20), IoT/printers (VLAN 30). Hardware: USG Pro 4 + 24-port PoE switch.
</mem_write>

**Sara (user-visible response):**

Clean three-tier segmentation. Are you doing inter-VLAN routing on the USG or keeping them fully isolated? The IoT VLAN especially — printers need to be reachable from corporate but you don't want IoT chatting back.

### Turn 2

**David:** corporate can reach IoT/printers for print jobs, everything else is isolated. guest has internet only, no LAN access. firewall rules on the USG handle it. also setting up a separate SSID per VLAN on the APs — they have 3 U6 Lites

**Sara (internal generation stream):**

<mem_write key="user.work.clients.henderson.network.firewall" importance="0.60" decay="medium">
Henderson network firewall: corporate can reach IoT/printers VLAN for printing, all others isolated. Guest has internet only, no LAN. Rules enforced on USG. Three U6 Lite APs with per-VLAN SSIDs.
</mem_write>

**Sara (user-visible response):**

Three U6 Lites for three SSIDs is fine — the U6 Lite handles multi-SSID well without significant throughput loss. One thing to watch: make sure the IoT VLAN SSID is WPA2-only if any of their printers are older. Some HP LaserJets choke on WPA3 transition mode.

### Turn 3

**David:** good call, they do have an older LaserJet. I'll set that SSID to WPA2. deploying it next Thursday

**Sara (internal generation stream):**

<mem_write key="user.work.clients.henderson.network.deployment" importance="0.55" decay="fast">
Henderson network deployment scheduled for Thursday April 10, 2026. IoT SSID set to WPA2 for older HP LaserJet compatibility.
</mem_write>

**Sara (user-visible response):**

Thursday gives you time to pre-stage the config in the UniFi controller. If you template the VLAN/firewall setup, it's reusable for other clients — this three-tier pattern works for most small offices.

---

*Time gap: 3 days later*

---

## Memory State (Session 2 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.clients: "Multiple MSP clients with various network setups"
user.work.clients.henderson.network: "Three VLANs: corporate (10), guest (20), IoT/printers (30). USG Pro 4 + 24-port PoE switch."
user.work.clients.henderson.network.firewall: "Corporate → IoT for printing, guest internet-only. Three U6 Lite APs, per-VLAN SSIDs."
user.work.clients.henderson.network.deployment: "Scheduled Thursday April 10. IoT SSID WPA2 for older LaserJet."
infra.home.network: "Tailscale mesh (avery.cloud), Home Assistant"
```

## SESSION 2

### Turn 1

**David:** henderson deployment went smooth actually. only snag was the USG needed a firmware update before it would do the VLAN trunking properly. burned like 20 minutes on that

**Sara (internal generation stream):**

<mem_write key="user.work.clients.henderson.network.deployment_result" importance="0.55" decay="fast">
Henderson network deployment completed successfully. Only issue: USG required firmware update for proper VLAN trunking, added ~20 minutes to the deployment.
</mem_write>

<reflect confidence="0.78">
The firmware issue is a minor operational detail — fast decay. But worth noting in case David hits the same issue on another USG deployment. The broader fact that the deployment succeeded is the key update.
</reflect>

**Sara (user-visible response):**

20 minutes for a firmware snag on a full VLAN deployment is nothing. Worth noting the firmware version that fixed it — if you have other clients on USG Pro 4s, you can pre-update before you're on-site.

### Turn 2

**David:** yeah it was 6.0.14 that fixed it. their unit was on 5.12 something. I'm adding USG firmware check to my deployment checklist

**Sara (internal generation stream):**

<mem_write key="tech.unifi.usg_pro4.vlan_trunking_firmware" importance="0.60" decay="slow">
USG Pro 4 needs firmware 6.0.14+ for reliable VLAN trunking. Versions around 5.12.x have issues. David adding firmware pre-check to deployment checklist.
</mem_write>

**Sara (user-visible response):**

5.12 to 6.0.14 is a big jump — there were some VLAN-related fixes in the 6.x line. Smart to add the pre-check. If you template your deployment checklist, that's one less thing to debug in the field.

## Memory State (After Session 2)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.clients: "Multiple MSP clients with various network setups"
user.work.clients.henderson.network: "Three VLANs: corporate (10), guest (20), IoT/printers (30). USG Pro 4 + 24-port PoE switch."
user.work.clients.henderson.network.firewall: "Corporate → IoT for printing, guest internet-only. Three U6 Lite APs, per-VLAN SSIDs."
user.work.clients.henderson.network.deployment: "Completed successfully. USG firmware update from 5.12.x to 6.0.14 needed for VLAN trunking."
user.work.clients.henderson.network.deployment_result: "Deployment completed, only snag was USG firmware. ~20 min extra."
tech.unifi.usg_pro4.vlan_trunking_firmware: "Needs firmware 6.0.14+ for reliable VLAN trunking. 5.12.x has issues."
infra.home.network: "Tailscale mesh (avery.cloud), Home Assistant"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `user.work.clients.henderson.network` | New client project with specific hardware and VLAN config. Worth storing for future reference. |
| S1T2 | `<mem_write>` | `user.work.clients.henderson.network.firewall` | Firewall rules and AP details. Extends the network picture. |
| S1T3 | `<mem_write>` | `user.work.clients.henderson.network.deployment` | Deployment date and WPA2 compatibility note. Fast decay — event-specific. |
| S2T1 | `<mem_write>` | `user.work.clients.henderson.network.deployment_result` | Deployment outcome. Fast decay but closes the loop. |
| S2T1 | `<reflect>` | — | Firmware snag is minor but noting it for potential reuse across USG deployments. |
| S2T2 | `<mem_write>` | `tech.unifi.usg_pro4.vlan_trunking_firmware` | Technical knowledge: specific firmware version requirement. Slow decay — reusable across clients. |
