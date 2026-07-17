## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.network: "Tailscale mesh (avery.cloud), Home Assistant"
infra.home.power: "Standard residential power setup"
infra.proxmox: "10.185.1.203"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd"
infra.mac_studio: "M3 Ultra 96GB"
```

## SESSION 1

### Turn 1

**David:** just installed a CyberPower CP1500PFCLCD for the server rack. 1500VA/1000W sine wave. got tired of losing inference jobs every time the power flickered

**Sara (internal generation stream):**

<mem_write key="infra.home.ups" importance="0.80" decay="slow">
UPS installed: CyberPower CP1500PFCLCD. 1500VA/1000W, pure sine wave output. Protects server rack. Installed due to power flicker interrupting inference jobs.
</mem_write>

**Sara (user-visible response):**

1500VA sine wave is the right pick for the rack — the 1070s and Proxmox box combined probably draw 600-800W under load, so you've got decent headroom. Does it have a USB/NUT interface for automated shutdown?

### Turn 2

**David:** yeah USB HID. I've got it connected to the Proxmox host and configured apcupsd — when battery hits 20% it triggers a clean shutdown of all VMs first, then the host. the Mac Studio is on a separate circuit so it's not on this UPS

**Sara (internal generation stream):**

<mem_write key="infra.home.ups.config" importance="0.75" decay="slow">
UPS config: USB HID connected to Proxmox host. Running apcupsd. At 20% battery: clean VM shutdown first, then host shutdown. Mac Studio on separate circuit, not protected by this UPS.
</mem_write>

<mem_write key="infra.mac_studio.power" importance="0.55" decay="slow">
Mac Studio is on a separate electrical circuit from the server rack. Not on the CyberPower UPS.
</mem_write>

**Sara (user-visible response):**

apcupsd with the VM cascade shutdown is solid. 20% threshold gives you maybe 3-4 minutes of runtime at full load to get everything down cleanly.

The Mac Studio being on a separate circuit is a gap though. If that circuit flickers during a long inference job on Qwen, you lose the same way. Worth putting a smaller UPS on that circuit — even a 600VA would cover the Mac Studio's ~75W idle draw for 30+ minutes.

### Turn 3

**David:** yeah I know, it's on the list. might grab a CP600E for the studio. for now I at least have the rack covered — that's where the production workloads run. Mac Studio can deal with the occasional blip, launchd restarts the server automatically

**Sara (internal generation stream):**

<mem_write key="infra.home.ups.mac_studio_plan" importance="0.50" decay="fast">
David considering CyberPower CP600E for Mac Studio circuit. Not purchased yet — lower priority since launchd auto-restarts llama-server. Rack UPS covers production workloads.
</mem_write>

**Sara (user-visible response):**

Fair prioritization. The rack is the critical path — Sara's VM, the GPU cluster, Proxmox itself. Mac Studio has launchd as its safety net and it's not running anything stateful beyond the inference server. The CP600E would be nice-to-have but not urgent.

### Turn 4

**David:** also set up a Home Assistant automation — the UPS reports runtime remaining via NUT-to-MQTT. if runtime drops below 10 minutes I get a push notification. gives me a heads-up before the auto-shutdown triggers

**Sara (internal generation stream):**

<mem_write key="infra.home.ups.monitoring" importance="0.65" decay="slow">
UPS monitoring: NUT → MQTT → Home Assistant automation. Push notification when runtime remaining drops below 10 minutes. Provides early warning before apcupsd triggers shutdown at 20%.
</mem_write>

**Sara (user-visible response):**

NUT to MQTT to HA push — that's a clean monitoring chain. The 10-minute warning before the 20% auto-shutdown gives you time to intervene if it's just a brief outage. You could extend that to have Sara log a power event too — useful for correlating with any inference failures after the fact.

### Turn 5

**David:** ooh good idea. I'll add a webhook from HA to Sara's event endpoint when the UPS triggers. then the consolidation can pick it up and note the power event

**Sara (internal generation stream):**

<mem_write key="project.sara.events.power_integration" importance="0.60" decay="medium">
Planned: Home Assistant webhook to Sara's event endpoint on UPS power events. Consolidation engine can then log and correlate power events with system behavior.
</mem_write>

**Sara (user-visible response):**

That closes the observability loop — power event hits Sara's event pipeline, gets salience-scored, shows up in consolidation. If you ever see a pattern of flickers at certain times, Sara would surface that. The webhook from HA is a single HTTP POST to `/events/external` with a type and payload.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.network: "Tailscale mesh (avery.cloud), Home Assistant"
infra.home.ups: "CyberPower CP1500PFCLCD, 1500VA/1000W sine wave. Protects server rack."
infra.home.ups.config: "USB HID → Proxmox → apcupsd. 20% battery triggers VM cascade shutdown then host."
infra.home.ups.monitoring: "NUT → MQTT → HA. Push notification at <10 min runtime."
infra.home.ups.mac_studio_plan: "Considering CP600E for Mac Studio circuit. Not purchased yet."
infra.mac_studio: "M3 Ultra 96GB"
infra.mac_studio.power: "Separate circuit from rack. Not on UPS. Launchd auto-restarts llama-server."
infra.proxmox: "10.185.1.203"
infra.gpu_cluster: "6x GTX 1070, llama.cpp with systemd"
project.sara.events.power_integration: "Planned: HA webhook → Sara event endpoint for UPS power events."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `infra.home.ups` | New hardware addition. Specific model, specs, and motivation. Slow decay — infrastructure. |
| 2 | `<mem_write>` | `infra.home.ups.config` | Shutdown automation config. Critical infrastructure detail. |
| 2 | `<mem_write>` | `infra.mac_studio.power` | Mac Studio on separate circuit is a relevant infrastructure fact. |
| 3 | `<mem_write>` | `infra.home.ups.mac_studio_plan` | Tentative plan with a specific product mention. Fast decay — may not happen soon. |
| 4 | `<mem_write>` | `infra.home.ups.monitoring` | Monitoring chain details. Slow decay — deployed infrastructure. |
| 5 | `<mem_write>` | `project.sara.events.power_integration` | Planned integration. Medium decay — concrete idea with a specific endpoint. |
