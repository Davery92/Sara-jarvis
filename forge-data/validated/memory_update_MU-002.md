## Memory State (Session 1 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.exchange_online: "Using shared mailboxes for client ticketing. Current approach: one shared mailbox per client, forwarding rules to tech assignments."
```

## SESSION 1

### Turn 1

**David:** rethinking the shared mailbox setup for clients. the one-mailbox-per-client approach is hitting the 50GB limit on two of our bigger clients

**Sara (internal generation stream):**

<mem_read key="user.work.exchange_online">
  <mem_result>Using shared mailboxes for client ticketing. One shared mailbox per client, forwarding rules to tech assignments.</mem_result>
</mem_read>

**Sara (user-visible response):**

50GB on a shared mailbox means those clients generate a lot of ticket volume. The options are: auto-archive policies to keep the mailbox under limit, split into multiple mailboxes per client (defeats the purpose), or migrate the ticketing workflow off shared mailboxes entirely. What direction are you leaning?

### Turn 2

**David:** moving away from shared mailboxes for the high-volume clients. going to use Microsoft 365 Groups with a connected mailbox instead. the Group mailbox doesn't have the 50GB limit — it uses the group's SharePoint storage for attachments, so the mailbox stays lean. plus it gives us a shared calendar and file library per client

**Sara (internal generation stream):**

<mem_update key="user.work.exchange_online">
Migrating high-volume clients from shared mailboxes to Microsoft 365 Groups with connected mailbox. Group mailbox offloads attachments to SharePoint, avoiding the 50GB shared mailbox limit. Adds shared calendar and file library per client. Lower-volume clients staying on shared mailboxes for now.
</mem_update>

**Sara (user-visible response):**

M365 Groups is the better architecture for high-volume clients. SharePoint-backed attachment storage solves the capacity problem and the shared calendar + file library are useful extras you get for free. The Group mailbox also supports Planner integration if you ever want to layer task tracking on top.

Are you migrating the existing mail from the shared mailboxes, or starting fresh?

### Turn 3

**David:** starting fresh for the two big clients. their old tickets are archived in PSA anyway, we don't need them in Exchange. I'll set up the Groups this week and update the forwarding rules

**Sara (internal generation stream):**

<mem_write key="user.work.exchange_online.migration_plan" importance="0.60" decay="fast">
M365 Groups migration for 2 high-volume clients: starting fresh (old tickets in PSA archive). Setting up Groups this week with updated forwarding rules.
</mem_write>

**Sara (user-visible response):**

Clean cut with PSA as the archive is the right call — no need to migrate old mail that's already in the ticketing system. When you set up the Groups, make sure the default reply address matches the old shared mailbox so clients don't notice the backend change.

### Turn 4

**David:** good catch, yeah I'll alias the old address onto the Group. thanks

**Sara (internal generation stream):**

<reflect confidence="0.82">
David confirming he'll alias the old address. Minor implementation detail, not worth a separate memory entry — it's implied by the migration approach. Conversational close.
</reflect>

**Sara (user-visible response):**

That'll make the transition invisible to the clients. Smooth migration.

## Memory State (After Session 1)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.exchange_online: "Migrating high-volume clients from shared mailboxes to M365 Groups. Group mailbox offloads attachments to SharePoint, avoids 50GB limit. Lower-volume clients stay on shared mailboxes."
user.work.exchange_online.migration_plan: "2 high-volume clients migrating this week. Fresh start, old mail in PSA. Forwarding rules updated, old address aliased."
```

---

*Time gap: a week later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** Exchange migration is done. both clients on M365 Groups now. but I hit a snag — the Group mailbox doesn't support send-as by default, you have to enable it via PowerShell

**Sara (internal generation stream):**

<mem_read key="user.work.exchange_online.*">
  <mem_result>Migrating high-volume clients to M365 Groups. 2 clients this week. Old address aliased.</mem_result>
</mem_read>

<mem_update key="user.work.exchange_online">
High-volume clients migrated to M365 Groups with connected mailbox. Works well but send-as requires explicit PowerShell enablement (not available in admin GUI). Lower-volume clients remain on shared mailboxes.
</mem_update>

**Sara (user-visible response):**

`Add-RecipientPermission` for send-as on the Group — yeah, that's one of those M365 things that should be in the admin center but isn't. Did you script it or do it manually?

### Turn 2

**David:** scripted. wrote a quick PowerShell function that takes the Group name and a list of tech email addresses and grants send-as to all of them. added it to our onboarding runbook so future clients get it automatically

**Sara (internal generation stream):**

<mem_write key="user.work.exchange_online.send_as_script" importance="0.55" decay="medium">
PowerShell function for granting send-as on M365 Groups: takes Group name + tech email list, grants send-as permissions. Added to client onboarding runbook.
</mem_write>

**Sara (user-visible response):**

Scripted and in the runbook — that's the way to do it. One-time pain for permanent automation. If you're maintaining an MSP tooling repo, that function should live there too so it's version-controlled and other techs can use it.

### Turn 3

**David:** it's in our internal PowerShell module already. we've got a whole library of M365 client setup scripts

**Sara (internal generation stream):**

<mem_write key="user.work.tools.powershell_module" importance="0.50" decay="slow">
Marvel IT maintains an internal PowerShell module with M365 client setup scripts, including send-as provisioning for Groups.
</mem_write>

**Sara (user-visible response):**

Having a centralized PowerShell module for client provisioning is solid MSP practice. Keeps everything consistent and auditable. If you ever need to onboard a new tech, they just import the module.

## Memory State (After Session 2)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.work.exchange_online: "High-volume clients on M365 Groups (connected mailbox, SharePoint-backed). Lower-volume on shared mailboxes. Send-as requires PowerShell enablement."
user.work.exchange_online.migration_plan: "COMPLETE. 2 clients migrated, send-as scripted."
user.work.exchange_online.send_as_script: "PowerShell function for Group send-as. In client onboarding runbook."
user.work.tools.powershell_module: "Internal PowerShell module with M365 client setup scripts."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `user.work.exchange_online` | Retrieve current Exchange approach to engage with David's rethink. |
| S1T2 | `<mem_update>` | `user.work.exchange_online` | Direction change: shared mailboxes → M365 Groups. UPDATE same key, don't duplicate. |
| S1T3 | `<mem_write>` | `user.work.exchange_online.migration_plan` | Migration specifics: 2 clients, fresh start, timeline. Fast decay — event. |
| S1T4 | `<reflect>` | — | Address aliasing is an implementation detail, not a separate fact. |
| S2T1 | `<mem_read>` | `user.work.exchange_online.*` | Recall migration context for session 2 continuity. |
| S2T1 | `<mem_update>` | `user.work.exchange_online` | Migration complete, send-as gotcha discovered. Update existing key. |
| S2T2 | `<mem_write>` | `user.work.exchange_online.send_as_script` | New tooling fact: PowerShell function in runbook. |
| S2T3 | `<mem_write>` | `user.work.tools.powershell_module` | New infrastructure fact: internal PowerShell module. Slow decay — stable tooling. |
