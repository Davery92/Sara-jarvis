## Memory State (Session 1 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Intune, Entra ID, M365"
user.work.security: "BitLocker deployed across managed fleet"
```

## SESSION 1

### Turn 1

**David:** need to set up BitLocker recovery key rotation for the managed fleet. right now keys are escrowed to Entra ID but they never rotate after initial setup

**Sara (internal generation stream):**

<mem_write key="user.work.bitlocker.current_state" importance="0.65" decay="medium">
BitLocker recovery keys escrowed to Entra ID but not rotating after initial setup. David planning to implement key rotation for managed fleet.
</mem_write>

**Sara (user-visible response):**

Key rotation after escrow is important — if a key is used for recovery, it should rotate immediately so the old key can't be reused. Intune has a device action for this: "Rotate BitLocker keys" which triggers a new recovery key and escrows it to Entra ID.

Are you looking for automatic rotation on a schedule, or rotation triggered by recovery events?

### Turn 2

**David:** both. automatic rotation every 90 days plus immediate rotation after any recovery event. the 90-day rotation is the compliance requirement, the recovery-triggered rotation is just good hygiene

**Sara (internal generation stream):**

<mem_write key="user.work.bitlocker.rotation_policy" importance="0.70" decay="medium">
BitLocker key rotation policy: 90-day automatic rotation (compliance requirement) plus immediate rotation after any recovery event. Dual-trigger approach.
</mem_write>

**Sara (user-visible response):**

For the 90-day rotation, you'll need a compliance policy in Intune that enforces `KeyRotationEnabled` with a 90-day interval. The Intune CSP for BitLocker supports `ConfigureRecoveryPasswordRotation` — set it to 1 for Azure AD-joined devices or 2 for hybrid-joined.

The recovery-triggered rotation is simpler — Intune automatically rotates the key when a recovery event is detected, as long as the rotation policy is enabled. You don't need a separate trigger for that.

### Turn 3

**David:** ok so the CSP handles both. what about the devices that are already escrowed with old keys? do they rotate on the next sync or do I need to push it manually?

**Sara (internal generation stream):**

<reflect confidence="0.78">
Good question. Existing devices with the policy newly applied should rotate on their next check-in, but there's a known gotcha with devices that haven't synced recently. I should answer and flag the edge case.
</reflect>

**Sara (user-visible response):**

When you deploy the rotation policy, existing devices should rotate on their next Intune sync. But there's a gotcha: devices that haven't synced in a while (powered off, out of network) won't pick it up until they check in. For those, you can push a manual "Rotate BitLocker keys" action from the Intune portal on a per-device basis.

For the initial rollout, I'd deploy the policy and then after a week, pull a report of devices that haven't rotated. Those are your stragglers — hit them with the manual action.

### Turn 4

**David:** makes sense. I'll deploy the CSP policy tomorrow and do the straggler sweep next week. thanks

**Sara (internal generation stream):**

<mem_write key="user.work.bitlocker.rotation_plan" importance="0.55" decay="fast">
BitLocker rotation plan: deploy CSP policy tomorrow (ConfigureRecoveryPasswordRotation), straggler sweep one week later for devices that haven't rotated. Manual rotation push for non-compliant devices.
</mem_write>

**Sara (user-visible response):**

When you pull the straggler report, filter by `lastSyncDateTime` in Intune — devices that haven't synced since the policy deployment are the ones to target. Saves you from manually checking each one.

## Memory State (After Session 1)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Intune, Entra ID, M365"
user.work.security: "BitLocker deployed across managed fleet"
user.work.bitlocker.current_state: "Keys escrowed to Entra ID, no rotation until now."
user.work.bitlocker.rotation_policy: "90-day auto rotation + recovery-event rotation. CSP: ConfigureRecoveryPasswordRotation."
user.work.bitlocker.rotation_plan: "Deploy CSP policy tomorrow, straggler sweep one week later."
```

---

*Time gap: same day, 3 hours later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** actually one more thing on the BitLocker rotation — do I need to worry about MBAM compatibility? some of our older clients still have MBAM server for key management

**Sara (internal generation stream):**

<mem_read key="user.work.bitlocker.*">
  <mem_result>Key rotation via Intune CSP. 90-day auto + recovery-event rotation. Deploying tomorrow.</mem_result>
</mem_read>

<self_check domain="Intune/Entra ID/M365">
  <self_result confidence="0.74" notes="MBAM (Microsoft BitLocker Administration and Monitoring) is the legacy SCCM-based key management tool. It's being deprecated in favor of Intune. I know the general compatibility story but not every edge case."/>
</self_check>

**Sara (user-visible response):**

MBAM and Intune BitLocker management are separate escrow paths. If a device is managed by both MBAM (via SCCM) and Intune, the key rotation from Intune will escrow the new key to Entra ID, but MBAM won't see it — it only tracks keys escrowed to its own database.

For clients still on MBAM: if you're rotating keys via Intune, you need to either migrate those clients off MBAM to Intune-only management, or skip Intune rotation for MBAM-managed devices and handle rotation through SCCM task sequences instead.

The clean path is migrating them to Intune key management. MBAM is end of mainstream support. But that's a per-client decision.

### Turn 2

**David:** yeah we're in the middle of migrating those clients to Intune-only anyway. I'll exclude the MBAM clients from the rotation policy for now and add them once they're migrated

**Sara (internal generation stream):**

<mem_write key="user.work.bitlocker.mbam_exclusion" importance="0.55" decay="fast">
MBAM-managed clients excluded from Intune BitLocker rotation policy until MBAM-to-Intune migration complete. Migration in progress.
</mem_write>

**Sara (user-visible response):**

Use a device filter on the Intune policy to exclude the MBAM clients — filter by `managementAgent` or better, tag them with a device category. That way as each client migrates, you just update their category and they automatically pick up the rotation policy.

### Turn 3

**David:** device category tag is cleaner. I'll use "MBAM-legacy" as the tag and exclude it from the policy scope

**Sara (internal generation stream):**

<mem_write key="user.work.bitlocker.mbam_tag" importance="0.50" decay="fast">
Using device category "MBAM-legacy" to tag and exclude MBAM-managed devices from Intune BitLocker rotation policy.
</mem_write>

**Sara (user-visible response):**

Clean. As clients migrate, remove the tag and they flow into the rotation policy automatically. No per-device manual work.

## Memory State (After Session 2)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Intune, Entra ID, M365"
user.work.security: "BitLocker deployed across managed fleet"
user.work.bitlocker.current_state: "Keys escrowed to Entra ID, rotation being implemented."
user.work.bitlocker.rotation_policy: "90-day auto + recovery-event. CSP: ConfigureRecoveryPasswordRotation."
user.work.bitlocker.rotation_plan: "Deploy CSP tomorrow, straggler sweep one week later."
user.work.bitlocker.mbam_exclusion: "MBAM clients excluded until migration. 'MBAM-legacy' device category tag."
user.work.bitlocker.mbam_tag: "Device category 'MBAM-legacy' for policy exclusion."
```

---

*Time gap: same day, evening*

---

## Memory State (Session 3 Start)

```
[same as After Session 2]
```

## SESSION 3

### Turn 1

**David:** deployed the BitLocker rotation policy. 247 devices picked it up on the first sync cycle. 18 stragglers haven't synced yet — I'll hit those next week as planned

**Sara (internal generation stream):**

<mem_read key="user.work.bitlocker.*">
  <mem_result>90-day rotation + recovery-event. Deploy today, straggler sweep next week. MBAM clients excluded with 'MBAM-legacy' tag.</mem_result>
</mem_read>

<mem_update key="user.work.bitlocker.rotation_plan">
BitLocker rotation policy deployed. 247 devices applied on first sync. 18 stragglers to be addressed next week via manual rotation push.
</mem_update>

**Sara (user-visible response):**

247 out of 265 on the first sync is a 93% uptake. 18 stragglers is expected — those are probably the devices that are off-network or powered down. Next week's sweep will catch most of them. Any that still haven't synced after the sweep are likely decommissioned devices that should be cleaned up in Intune anyway.

### Turn 2

**David:** yeah good point — I should audit the stale devices while I'm at it. two birds

**Sara (internal generation stream):**

<mem_write key="user.work.intune.stale_device_audit" importance="0.50" decay="fast">
David planning to audit stale Intune devices during the BitLocker straggler sweep next week. Combining device hygiene with rotation compliance.
</mem_write>

**Sara (user-visible response):**

Filter by `lastSyncDateTime` older than 30 days. Anything that hasn't checked in for a month is either retired, lost, or needs attention. Cross-reference with your PSA's asset inventory and you'll have a clean fleet list.

### Turn 3

**David:** perfect. thanks for walking through all of this across the day

**Sara (internal generation stream):**

<reflect confidence="0.85">
David wrapping up after three sessions in one day on the same topic. Conversational close — no new facts.
</reflect>

**Sara (user-visible response):**

Solid rollout. The rotation, the MBAM exclusion, and the stale device cleanup — you're getting three compliance wins out of one project.

## Memory State (After Session 3)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Intune, Entra ID, M365"
user.work.security: "BitLocker deployed across managed fleet, key rotation active"
user.work.bitlocker.current_state: "Keys escrowed + rotating."
user.work.bitlocker.rotation_policy: "90-day auto + recovery-event. CSP: ConfigureRecoveryPasswordRotation. Deployed."
user.work.bitlocker.rotation_plan: "DEPLOYED. 247/265 applied. 18 stragglers for next week."
user.work.bitlocker.mbam_exclusion: "MBAM clients excluded. 'MBAM-legacy' device category tag."
user.work.intune.stale_device_audit: "Planned during straggler sweep. Filter lastSyncDateTime >30 days."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `user.work.bitlocker.current_state` | Baseline: keys escrowed but no rotation. Starting point for the project. |
| S1T2 | `<mem_write>` | `user.work.bitlocker.rotation_policy` | Policy decision: 90-day + recovery-event. Concrete spec. |
| S1T3 | `<reflect>` | — | Known gotcha about stale devices. Engage with the edge case. |
| S1T4 | `<mem_write>` | `user.work.bitlocker.rotation_plan` | Deployment timeline: tomorrow deploy, next week sweep. |
| S2T1 | `<mem_read>` | `user.work.bitlocker.*` | Recall context for MBAM compatibility question. |
| S2T1 | `<self_check>` | Intune/M365 | MBAM compatibility — moderate confidence (0.74). Know the general story. |
| S2T2 | `<mem_write>` | `user.work.bitlocker.mbam_exclusion` | Decision: exclude MBAM clients until migration. |
| S2T3 | `<mem_write>` | `user.work.bitlocker.mbam_tag` | Implementation detail: device category tag name. |
| S3T1 | `<mem_read>` | `user.work.bitlocker.*` | Session 3 recall of full BitLocker context. |
| S3T1 | `<mem_update>` | `user.work.bitlocker.rotation_plan` | Deployment results: 247/265. Update plan with actual numbers. |
| S3T2 | `<mem_write>` | `user.work.intune.stale_device_audit` | New planned action emerging from the straggler sweep. |
| S3T3 | `<reflect>` | — | Session close. No new facts. |
