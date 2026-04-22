# Assistant Redesign Checklist

## Phase 1
Goal: establish one clear assistant-first app structure.

- [x] Make `Sara` the true home screen instead of chat-only.
- [x] Add a compact “Today” layer above chat: brief, priorities, pending follow-ups, active automations, and suggested actions.
- [x] Remove duplicate or competing primary surfaces so the assistant has one obvious center of gravity.
- [x] Simplify top-level navigation around user intents instead of internal modules.
- [x] Decide whether `Learning` remains a top-level tab or moves into a secondary area.
- [x] Turn `More` into grouped sections instead of a flat tile grid.

Exit criteria: opening the app immediately answers “what matters now?” and “what can I do next?”

## Phase 2
Goal: unify the proactive assistant experience.

- [x] Create a unified assistant inbox for notifications, discoveries, intelligence items, and background task results.
- [x] Define clear item states in that inbox: new, in progress, waiting on you, done, archived.
- [x] Define one consistent pattern for proactive assistant interruptions.
- [x] Unify ACS status, background activity, and proactive cues into one status model.
- [x] Audit every major screen for “what can I do next?” clarity.

Exit criteria: proactive behavior feels like one system, not several disconnected features.

## Phase 3
Goal: make the core assistant conversation feel simpler and smarter.

- [x] Move model picker and ephemeral mode out of the default chat header into an advanced controls sheet.
- [x] Keep the default chat experience focused on ask, speak, review, and act.
- [x] Improve the empty state on `Sara` so it suggests useful first actions.
- [x] Make suggested actions more prominent and more task-oriented.
- [x] Refine tool-status feedback so it feels calm and trustworthy instead of technical.

Exit criteria: chat feels like an assistant for normal use, with power-user controls still available but not dominant.

## Phase 4
Goal: improve voice and interaction flow.

- [x] Simplify continuous voice UX and make microphone behavior more discoverable.
- [x] Clarify the difference between tap, hold-to-talk, and continuous listening.
- [x] Make assistant actions and replies feel faster, calmer, and less mode-heavy.
- [x] Ensure proactive items can flow naturally into chat without confusing context switches.

Exit criteria: voice and chat feel like one coherent interaction model.

## Phase 5
Goal: give the app a stronger product identity.

- [x] Replace emoji-first navigation and primary iconography with a consistent icon system.
- [x] Tighten typography, spacing, and hierarchy across cards, tabs, and lists.
- [x] Reduce border-heavy “internal tool” styling and define a clearer assistant identity.
- [x] Establish one accent language for assistant actions, one for alerts, and one for passive information.

Exit criteria: the app feels intentional and productized, not just functional.

## Phase 6
Goal: validate the redesign and measure whether it works.

- [x] Define success metrics: daily assistant usage, notification-to-chat conversion, suggested-action completion, and voice usage.
- [x] Add instrumentation for the key assistant flows.
- [ ] Review the phased changes against real usage and adjust the IA if needed.

Metric definitions:
- Daily assistant usage: distinct days with `assistant.message_sent`.
- Notification-to-chat conversion: `assistant.proactive_context_opened` where `source = notification`.
- Suggested-action completion: `assistant.message_sent` where `entry_point = suggested_action`.
- Voice usage: `assistant.voice_hold_to_talk_started`, `assistant.voice_hands_free_toggled`, and voice `assistant.message_sent`.

Exit criteria: design decisions are tied to behavior, not just preference.
