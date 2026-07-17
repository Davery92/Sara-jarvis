## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.tools.home_assistant: "HA REST API: device states, automations, sensors."
infra.home.network: "Tailscale mesh (avery.cloud). Home Assistant."
```

## SESSION 1

### Turn 1

**David:** got Home Assistant automations synced to Sara's standing orders. when HA triggers a "goodnight" routine (turns off lights, locks doors, arms alarm), Sara automatically switches to sleep mode — suppresses all non-emergency notifications until the morning planning trigger at 7 AM

**Sara (internal generation stream):**

<mem_write key="project.sara.activity_state.sleep_integration" importance="0.70" decay="slow">
HA "goodnight" routine triggers Sara sleep mode. Suppresses all non-emergency notifications until 7 AM morning planning. Bidirectional: HA automation → Sara activity state change.
</mem_write>

**Sara (user-visible response):**

HA goodnight → Sara sleep mode is a clean environmental trigger. Sara's activity state changes based on real-world signals instead of a fixed schedule. If you go to bed at 9 PM one night and 11 PM the next, Sara adapts because the lights-off signal is the trigger, not the clock.

What qualifies as "emergency" that still gets through during sleep mode?

### Turn 2

**David:** infrastructure alerts only. UPS power events, server health failures, and security alerts from HA (door open after midnight, motion where there shouldn't be). everything else waits for morning

**Sara (internal generation stream):**

<mem_write key="project.sara.activity_state.sleep_exceptions" importance="0.65" decay="slow">
Sleep mode notification exceptions: UPS power events, server health failures (watchdog), HA security alerts (unexpected door/motion after midnight). All other notifications suppressed until 7 AM.
</mem_write>

**Sara (user-visible response):**

Infrastructure + security as the exception categories — those are the two that justify waking someone up. A failed server health check at 2 AM is worth knowing about; a consolidation report can wait. Clean separation.

### Turn 3

**David:** exactly. also added a "good morning" trigger — when HA detects the first motion sensor hit in the kitchen (me making coffee), Sara exits sleep mode and starts the morning planning cycle. so the wake time is also activity-driven, not clock-driven

**Sara (internal generation stream):**

<mem_write key="project.sara.activity_state.morning_trigger" importance="0.65" decay="slow">
Sara morning wake trigger: first HA motion sensor hit in kitchen. Exits sleep mode, starts morning planning cycle. Activity-driven wake time instead of fixed clock.
</mem_write>

**Sara (user-visible response):**

Kitchen motion sensor as the morning trigger — Sara wakes up when David wakes up. The 7 AM planning is now a fallback in case the motion sensor doesn't fire (you're not home, sensor issue), not the primary trigger. The whole sleep/wake cycle is now environment-aware.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.activity_state.sleep_integration: "HA goodnight → Sara sleep mode. Suppresses non-emergency notifications."
project.sara.activity_state.sleep_exceptions: "UPS, server health, HA security alerts pass through."
project.sara.activity_state.morning_trigger: "Kitchen motion sensor → exit sleep, start planning."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...sleep_integration` | Major activity state enhancement. HA → Sara state change. |
| 2 | `<mem_write>` | `...sleep_exceptions` | Exception categories for sleep mode. Safety-critical. |
| 3 | `<mem_write>` | `...morning_trigger` | Morning trigger: kitchen motion sensor. Environment-driven wake. |
