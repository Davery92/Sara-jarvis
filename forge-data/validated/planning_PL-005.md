## Memory State (Session 1 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.tools: "Intune, Entra ID, M365"
user.work.fleet: "Dell device fleet, managed via Intune"
```

## SESSION 1

### Turn 1

**David:** need to build out Intune app protection policies for BYOD. we've got a few clients asking about letting employees use personal phones for work email and Teams without full MDM enrollment. I need a plan that balances security with user privacy

**Sara (internal generation stream):**

<mem_write key="user.work.intune.app_protection" importance="0.65" decay="medium">
Building Intune App Protection Policies (APP) for BYOD. Client demand for personal phone access to work email and Teams without full MDM enrollment. Balancing security with user privacy.
</mem_write>

<plan_start goal="Deploy Intune App Protection Policies for BYOD across client base">
  <plan_step goal="Define security baseline for APP policies" status="active" depends_on="none"/>
  <plan_step goal="Build and test policies in staging" status="pending" depends_on="baseline"/>
  <plan_step goal="Pilot with internal users" status="pending" depends_on="testing"/>
  <plan_step goal="Roll out to clients" status="pending" depends_on="pilot"/>
</plan_start>

**Sara (user-visible response):**

APP without MDM is the standard BYOD approach — Microsoft calls it MAM-WE (Mobile Application Management Without Enrollment). The personal device stays unmanaged; only the work data inside Outlook, Teams, OneDrive is protected.

**Plan:**

**Week 1 — Define Security Baseline**
- Core APP settings: PIN required to open work apps, block copy/paste from work apps to personal apps, encrypt work data at rest, wipe work data on X failed PIN attempts
- Conditional access: require APP-compliant apps to access M365 resources (blocks access from unprotected apps)
- Data loss prevention: block screenshots in work apps, block save-to-personal-storage
- What NOT to include: no device-level controls, no VPN enforcement, no location tracking — that's MDM territory and users will reject it on personal phones

**Risk:** Users who already have full MDM enrolled might need migration. Existing MDM policies can conflict with APP policies on the same device.

### Turn 2

**David:** the conflict between MDM and APP is the part I'm worried about. some clients have a mix — corporate devices on MDM and BYOD that should be APP-only. how do I handle that?

**Sara (internal generation stream):**

<reflect confidence="0.76">
MDM/APP coexistence is a common Intune challenge. The answer is device filter-based policy targeting: MDM policies target managed devices, APP policies target unmanaged devices. Intune's conditional access can distinguish between managed and unmanaged.
</reflect>

**Sara (user-visible response):**

Intune handles this with device filters in conditional access:

- **Managed devices (MDM)**: target with device compliance policies + full MDM config profiles. Conditional access rule: "if device is managed AND compliant, grant access"
- **Unmanaged devices (BYOD/APP)**: target with APP policies only. Conditional access rule: "if device is NOT managed, require approved client app with APP policy"

The key is the conditional access policy, not the APP policy itself. Two CA rules:
1. `Managed + Compliant` → full access
2. `Unmanaged + APP-protected app` → limited access (no download to device, no copy/paste out, wipe on unenroll)

This way both populations coexist. The device filter `deviceOwnership -eq 'Personal'` or `isCompliant -ne true` routes unmanaged devices to the APP path.

### Turn 3

**David:** ok that makes sense. two CA rules, device filter routing. I'll set up the CA rules first, then build the APP policies to back them. what about the specific APP settings — what's your recommended baseline?

**Sara (internal generation stream):**

<mem_write key="user.work.intune.app_protection.baseline" importance="0.60" decay="medium">
APP baseline: PIN required (6-digit minimum), block copy-paste to personal apps, encrypt work data, wipe after 5 failed PINs, block screenshots, block save-to-personal. CA routing: managed → full MDM compliance, unmanaged → APP-protected apps only.
</mem_write>

**Sara (user-visible response):**

Recommended APP baseline:

**Authentication**
- Require PIN: 6-digit minimum, biometric allowed as alternative
- Recheck access after 30 minutes of inactivity
- Block jailbroken/rooted devices

**Data Protection**
- Block cut/copy/paste to personal apps
- Block "Save As" to personal storage
- Encrypt work data on device
- Block screenshots in managed apps
- Block third-party keyboards (prevents keylogger risk)

**Conditional Launch**
- Wipe work data after 5 failed PINs
- Wipe work data after 90 days offline (device hasn't connected in 3 months = probably lost)
- Block access on unsupported OS versions

This covers the security surface without touching the personal side of the device. Users will see a PIN prompt when opening Outlook/Teams and won't be able to copy work data to personal apps — that's it. Their photos, personal apps, and browsing are untouched.

### Turn 4

**David:** that's a solid baseline. I'll template this for all BYOD clients. starting with Henderson since they specifically asked for it. pilot next week

**Sara (internal generation stream):**

<mem_write key="user.work.intune.app_protection.rollout" importance="0.55" decay="fast">
APP policy rollout: Henderson first (specifically requested BYOD). Pilot next week. Using baseline template for all BYOD clients.
</mem_write>

**Sara (user-visible response):**

Henderson is a good pilot — they've already got the network segmentation in place so they're used to security controls. For the pilot: deploy the APP policy to a test group of 3-5 users first, get feedback on the PIN and copy-paste restrictions, then expand to all BYOD users. The most common user complaint will be the copy-paste block — set expectations upfront that it's a security requirement.

## Memory State (After Session 1)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.tools: "Intune, Entra ID, M365"
user.work.fleet: "Dell device fleet, managed via Intune"
user.work.intune.app_protection: "Building APP for BYOD. MAM-WE approach."
user.work.intune.app_protection.baseline: "PIN (6-digit), block copy-paste, encrypt, block screenshots, wipe on 5 failed PINs, 90-day offline wipe. CA routing: managed → MDM, unmanaged → APP."
user.work.intune.app_protection.rollout: "Henderson first, pilot next week. Template for all BYOD clients."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `user.work.intune.app_protection` | New project: BYOD APP policies. |
| 1 | `<plan_start>` | BYOD APP deployment | 4-phase plan: baseline, build, pilot, rollout. |
| 2 | `<reflect>` | — | MDM/APP coexistence. Known solution: device filter routing. |
| 3 | `<mem_write>` | `...baseline` | Specific APP settings baseline. |
| 4 | `<mem_write>` | `...rollout` | Henderson first, pilot next week. |
