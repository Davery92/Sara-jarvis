## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.standing_orders: "CRUD + trigger eval + action exec + undo window"
```

## SESSION 1

### Turn 1

**David:** built a new standing order category: travel mode. when I'm traveling (detected by HA geofence or manual toggle), Sara adjusts her behavior: suppresses non-urgent home automation alerts, shifts notifications to mobile-only, and adds a "return ETA" context block to the morning briefing

**Sara (internal generation stream):**

<mem_write key="project.sara.standing_orders.travel_mode" importance="0.70" decay="slow">
New standing order category: travel mode. Trigger: HA geofence departure or manual toggle. Behavior: suppress non-urgent home alerts, mobile-only notifications, morning briefing adds return ETA context. Sara adapts to David being away from home.
</mem_write>

**Sara (user-visible response):**

Travel mode as a standing order is a natural extension of the activity state machine. The HA geofence trigger means Sara detects the departure automatically — you leave the geofence, Sara switches modes. Manual toggle is the fallback for edge cases where geofence doesn't fire.

The mobile-only shift is smart — desktop notifications are useless if you're not home. What does "non-urgent" mean in this context? Same exception list as sleep mode (UPS, server health, security)?

### Turn 2

**David:** same exceptions plus one more: if the kid's school calls (identified by caller ID automation in HA), that gets through too. everything else waits until I'm back or I manually check in

**Sara (internal generation stream):**

<mem_write key="project.sara.standing_orders.travel_mode.exceptions" importance="0.60" decay="slow">
Travel mode exceptions: UPS events, server health failures, HA security alerts, AND kid's school calls (identified by HA caller ID automation). All other notifications suppressed or deferred.
</mem_write>

**Sara (user-visible response):**

School calls as an exception is the right addition for a parent. The exception set across modes now: sleep mode = infrastructure + security; travel mode = same + school calls. Layered appropriately.

### Turn 3

**David:** also added an auto-return trigger. when the geofence detects I'm back home, travel mode disables and all deferred notifications get delivered as a summary batch

**Sara (internal generation stream):**

<mem_write key="project.sara.standing_orders.travel_mode.return" importance="0.55" decay="slow">
Travel mode auto-return: HA geofence detects return home → travel mode disabled → all deferred notifications delivered as summary batch.
</mem_write>

**Sara (user-visible response):**

Geofence return → batch summary of deferred notifications. You walk in the door and get a "here's what happened while you were gone" briefing. That's the travel mode lifecycle: depart → suppress → return → catch up. Clean.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.standing_orders: "CRUD + trigger eval + action exec + undo window + travel mode"
project.sara.standing_orders.travel_mode: "HA geofence trigger. Suppress non-urgent, mobile-only, return ETA in briefing."
project.sara.standing_orders.travel_mode.exceptions: "UPS, server health, HA security, school calls."
project.sara.standing_orders.travel_mode.return: "Geofence return → deferred notification summary batch."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...travel_mode` | New standing order category with triggers and behaviors. |
| 2 | `<mem_write>` | `...exceptions` | Exception set for travel mode. |
| 3 | `<mem_write>` | `...return` | Auto-return trigger and batch delivery. |
