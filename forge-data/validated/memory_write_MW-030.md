## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.tools: "28 tools (including Minecraft manager, Home Assistant)"
project.sara.tools.home_assistant: "HA REST API: device states, automations, sensors."
```

## SESSION 1

### Turn 1

**David:** added a standing order to Sara: when the Home Assistant motion sensor in my office detects no movement for 30 minutes during work hours, Sara sends me a reminder to stand up and stretch. the WFH days especially I'll sit for hours without moving

**Sara (internal generation stream):**

<mem_write key="project.sara.standing_orders.stretch_reminder" importance="0.55" decay="slow">
New standing order: office motion sensor (HA) + 30-minute no-movement threshold during work hours → Sara sends "stand up and stretch" reminder. Targets WFH days where David sits for extended periods.
</mem_write>

**Sara (user-visible response):**

Motion sensor → inactivity timeout → wellness reminder. That's the HA integration paying off — Sara uses environmental data to be proactively helpful without David asking. The 30-minute threshold is reasonable for a desk worker. Are you excluding gym days or running it uniformly?

### Turn 2

**David:** good question. I should exclude the gym days since I'm already active. the standing order should only fire on days I don't have a morning gym session — so Monday and the gym off-days

**Sara (internal generation stream):**

<mem_write key="project.sara.standing_orders.stretch_reminder.schedule" importance="0.50" decay="slow">
Stretch reminder standing order: fires only on non-gym days during work hours. Excludes Wed/Fri (morning gym) and Tue/Thu (evening gym). Primarily targets Monday and other off-days when David is sedentary.
</mem_write>

**Sara (user-visible response):**

Schedule-aware standing orders — Sara checks the day's gym schedule before deciding whether to fire the inactivity reminder. On gym days, you're already getting movement. On off-days, the reminder fills the gap.

The logic: cross-reference the gym schedule (Wed/Fri AM, Tue/Thu PM) with the current day. If there's a gym session today, suppress the standing order. If it's an off-day (Monday), enforce it.

### Turn 3

**David:** exactly. also want to add a 2-hour hydration reminder on the same schedule. just a "drink water" ping. I'm terrible at hydrating when I'm in flow state

**Sara (internal generation stream):**

<mem_write key="project.sara.standing_orders.hydration_reminder" importance="0.50" decay="slow">
New standing order: hydration reminder every 2 hours during work hours on non-gym days. David doesn't hydrate well during flow state.
</mem_write>

**Sara (user-visible response):**

2-hour hydration reminders on the same schedule. Both standing orders (stretch + hydrate) use the same day-filter logic — DRY principle applies to standing orders too. If you bundle them into one "wellness" standing order category, the schedule check only runs once.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.tools: "28 tools"
project.sara.standing_orders.stretch_reminder: "Office motion sensor, 30 min inactivity → stretch reminder. Non-gym days only."
project.sara.standing_orders.stretch_reminder.schedule: "Mon + off-days. Excludes gym days."
project.sara.standing_orders.hydration_reminder: "Every 2 hours, work hours, non-gym days."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...stretch_reminder` | New standing order with HA sensor trigger. |
| 2 | `<mem_write>` | `...schedule` | Schedule logic: gym-day exclusion. |
| 3 | `<mem_write>` | `...hydration_reminder` | Second wellness standing order. |
