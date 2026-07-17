## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.multi_device: "Smart content routing by device class + activity state"
infra.jarvis: "10.185.1.180 — orchestrator"
```

## SESSION 1

### Turn 1

**David:** decided on the multi-device routing strategy. three device classes: desktop (full context, WebSocket), mobile (push notifications, truncated context), voice (minimal context, audio response). each class gets different content formatting

**Sara (internal generation stream):**

<mem_write key="project.sara.multi_device.device_classes" importance="0.75" decay="slow">
Multi-device routing: three device classes. Desktop: full context, WebSocket delivery. Mobile: push notifications, truncated context. Voice: minimal context, audio response. Each class has different content formatting.
</mem_write>

**Sara (user-visible response):**

Three-class routing with format-specific delivery is the right architecture. The context budget already differentiates text (8000) from voice (4000) — the mobile class slots in between. What's the mobile context budget?

### Turn 2

**David:** mobile gets 3000 tokens. enough for a useful response but not overwhelming on a phone screen. also mobile responses strip markdown formatting — plain text only

**Sara (internal generation stream):**

<mem_write key="project.sara.multi_device.mobile_config" importance="0.60" decay="slow">
Mobile device class: 3000 token context budget, plain text responses (markdown stripped). Push notification delivery.
</mem_write>

**Sara (user-visible response):**

3000 tokens plain text for mobile is the right density. The markdown stripping is smart — mobile push notifications can't render markdown anyway, and even in-app views look cleaner with plain text on small screens.

How does Sara determine which device class to route to? Is it based on the requesting device, or the most-available device?

### Turn 3

**David:** requesting device determines the class. if I send a message from my phone, Sara formats for mobile. if I'm at the desktop, full context. the activity state machine also factors in — if I'm AWAY from the desktop, proactive notifications go to mobile instead

**Sara (internal generation stream):**

<mem_write key="project.sara.multi_device.routing_logic" importance="0.65" decay="slow">
Multi-device routing logic: requesting device determines content class. Activity state machine modifies routing for proactive notifications — if AWAY from desktop, notifications route to mobile instead.
</mem_write>

**Sara (user-visible response):**

Request-based routing for user-initiated messages, state-aware routing for proactive notifications. That covers both cases cleanly. The activity state override for notifications is the key insight — a notification that goes to a sleeping desktop is wasted.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.multi_device: "Three classes: desktop (full/WebSocket), mobile (push/3000 tokens/plain text), voice (minimal/audio)."
project.sara.multi_device.device_classes: "Desktop, mobile, voice. Different content formatting per class."
project.sara.multi_device.mobile_config: "3000 tokens, plain text, push notifications."
project.sara.multi_device.routing_logic: "Request-based for user messages. Activity state-aware for proactive notifications."
infra.jarvis: "10.185.1.180 — orchestrator"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...device_classes` | Architecture decision: three device classes with specific delivery methods. |
| 2 | `<mem_write>` | `...mobile_config` | Mobile-specific config: token budget, plain text. |
| 3 | `<mem_write>` | `...routing_logic` | Routing decision: request-based + state-aware for notifications. |
