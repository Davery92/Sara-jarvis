## Memory State (Session 1 Start)

```
user.name: "David"
infra.home.ups: "CyberPower CP1500PFCLCD, 1500VA/1000W."
infra.home.ups.config: "USB HID → Proxmox → apcupsd. 20% triggers VM cascade shutdown."
infra.gpu_cluster: "5x GTX 1070 in cluster"
```

## SESSION 1

### Turn 1

**David:** upgraded the UPS to the CP2000PFCLCD. 2000VA/1350W. the 1500 was cutting it too close with the GPU cluster under full load

**Sara (internal generation stream):**

<mem_read key="infra.home.ups">
  <mem_result>CyberPower CP1500PFCLCD, 1500VA/1000W.</mem_result>
</mem_read>

<mem_update key="infra.home.ups">
CyberPower CP2000PFCLCD, 2000VA/1350W. Upgraded from CP1500PFCLCD (1500VA/1000W) due to GPU cluster load nearing old capacity.
</mem_update>

**Sara (user-visible response):**

1500 to 2000VA gives you 350W more headroom. With the GPU cluster at full load you were probably drawing 800-900W — the old UPS had maybe 100W of margin. The 2000VA puts you at ~450W headroom, which is comfortable. Did you keep the same shutdown config?

### Turn 2

**David:** same apcupsd config, just repointed to the new UPS USB interface. 20% battery still triggers the VM cascade shutdown. also upped the push notification threshold from 10 minutes runtime to 15 minutes since the bigger battery gives more runtime

**Sara (internal generation stream):**

<mem_update key="infra.home.ups.config">
USB HID → Proxmox → apcupsd. 20% triggers VM cascade shutdown. Push notification at 15 minutes remaining runtime (was 10 minutes, adjusted for larger battery).
</mem_update>

**Sara (user-visible response):**

Same shutdown logic, adjusted notification threshold for the bigger battery. At 2000VA with your load, you've got roughly 15-20 minutes of runtime on battery — the 15-minute alert gives you a 5-minute warning before the 20% auto-shutdown triggers. Clean transition.

## Memory State (After Session 1)

```
user.name: "David"
infra.home.ups: "CyberPower CP2000PFCLCD, 2000VA/1350W."
infra.home.ups.config: "apcupsd, 20% VM cascade shutdown, 15-min runtime notification."
infra.gpu_cluster: "5x GTX 1070 in cluster"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `infra.home.ups` | Recall current UPS for the update. |
| 1 | `<mem_update>` | `infra.home.ups` | UPS upgraded. UPDATE same key. |
| 2 | `<mem_update>` | `infra.home.ups.config` | Config adjusted for new UPS. Same key, updated values. |
