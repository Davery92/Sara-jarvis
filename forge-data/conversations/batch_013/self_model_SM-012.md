## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
user.occupation: "Network & IT Support Technician at Marvel IT"
infra.proxmox: "10.185.1.203"
```

## SESSION 1

### Turn 1

**David:** I want to set up a VLAN for IoT devices on my home network. the smart plugs, the HA sensors, the thermostat — I want them on their own network segment so they can't reach the server rack if compromised. what's the best approach?

**Sara (internal generation stream):**

<self_check domain="networking/VLANs/firewall rules">
  <self_result confidence="0.74" notes="Know VLAN segmentation well — David does this for clients (Henderson network had VLANs 10/20/30). Home IoT VLAN is the same pattern. Know the general approach: create VLAN, assign IoT devices, firewall rules to isolate. Less confident on specific consumer router VLAN support — depends on David's hardware."/>
</self_check>

**Sara (user-visible response):**

Same pattern you used for Henderson's network — create an IoT VLAN, assign smart devices to it, firewall rules to allow IoT → internet but block IoT → LAN.

The approach depends on your home router/switch. If you're running a managed switch and a router that supports VLANs (UniFi, pfSense, OPNsense), it's straightforward:

1. Create VLAN 30 (or whatever ID) for IoT
2. Assign IoT device ports/WiFi SSID to VLAN 30
3. Firewall rules:
   - IoT VLAN → Internet: allow (devices need cloud connectivity)
   - IoT VLAN → LAN/Server VLAN: block (prevents compromised IoT from reaching servers)
   - LAN → IoT VLAN: allow (you need to manage the devices from your main network)
   - HA exception: allow HA's IP on the main LAN to reach IoT VLAN for device control

What networking hardware are you using at home? That determines the specifics.

### Turn 2

**David:** I've got a UniFi USG and a US-8-60W switch. same ecosystem as the client deployments

**Sara (internal generation stream):**

<mem_write key="infra.home.network.hardware" importance="0.60" decay="slow">
Home network hardware: UniFi USG + US-8-60W switch. Same ecosystem as client deployments.
</mem_write>

**Sara (user-visible response):**

UniFi makes this easy — you already know the controller UI from the client work. In the UniFi controller:

1. **Settings > Networks > Create New**: name "IoT", VLAN ID 30, DHCP enabled
2. **Settings > WiFi > Create New SSID**: "HomeIoT", assign to the IoT network, WPA2 (some IoT devices don't support WPA3)
3. **Settings > Firewall > LAN In**: create a rule blocking traffic from IoT VLAN (10.x.30.0/24) to your main LAN (except HA's IP)

The switch port assignments: any wired IoT devices get their switch port tagged to VLAN 30. Wireless IoT connects to the HomeIoT SSID which is automatically on the VLAN.

My confidence on the UniFi-specific config is moderate — I know the general VLAN architecture but the exact menu paths in the controller UI might have changed in recent firmware versions. You know the UniFi controller well enough to navigate minor UI differences.

### Turn 3

**David:** yeah the menu paths are close enough. I'll set this up this weekend. it's basically the same config I did for Henderson but scaled down for home

**Sara (internal generation stream):**

<mem_write key="infra.home.network.iot_vlan" importance="0.60" decay="slow">
Planning IoT VLAN for home network. VLAN 30 on UniFi USG/US-8-60W. Isolates smart plugs, HA sensors, thermostat from server rack. HA exception for device control. Setup this weekend.
</mem_write>

**Sara (user-visible response):**

Same pattern, smaller scale. The Henderson config is your template — you even used VLAN 30 for IoT there. Once it's up, all your IoT devices are isolated and your server rack is protected from compromised smart plugs. The HA exception lets Sara still interact with the smart home layer through the integration.

## Memory State (After Session 1)

```
user.name: "David"
infra.proxmox: "10.185.1.203"
infra.home.network.hardware: "UniFi USG + US-8-60W switch."
infra.home.network.iot_vlan: "Planned: VLAN 30 for IoT. Isolates smart devices from servers."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | networking/VLANs | Confidence 0.74 — knows VLAN architecture well, less sure on David's specific hardware. |
| 2 | `<mem_write>` | `...network.hardware` | Home network hardware identified. Slow decay. |
| 3 | `<mem_write>` | `...iot_vlan` | IoT VLAN plan for home network. |
