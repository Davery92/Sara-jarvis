"""Canonical event catalog: behavior must be declared before a kind ships."""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class EventSpec:
    domain: str
    slice_name: str
    sensitivity: str = "normal"
    retention_class: str = "standard"
    attention_base: float = 0.0
    interpret: bool = False
    coalesce: bool = False


_SPECS: Dict[str, EventSpec] = {}


def _register(domain: str, slice_name: str, kinds: str, **kwargs) -> None:
    spec = EventSpec(domain=domain, slice_name=slice_name, **kwargs)
    for kind in kinds.split():
        _SPECS[kind] = spec


_register("chat", "active_conversation", "chat.user_turn_stored", sensitivity="private", interpret=True, attention_base=0.15)
# Sara's own turn is NOT interpreted. Reading back her own draft ("I'll confirm by
# 1 PM") produced threads, notes and two days of overdue nags about a meeting that
# had already happened (Laura Weippert, 2026-08-31). Her words are not evidence.
_register("chat", "active_conversation", "chat.assistant_turn_stored", sensitivity="private", interpret=False, attention_base=0.15)
_register("chat", "active_conversation", "conversation.created conversation.closed", sensitivity="private")
_register("email", "communications", "email.received email.updated email.analyzed email.attachment_added", sensitivity="private", interpret=True, attention_base=0.35, coalesce=True)
_register("email", "communications", "email.read_state_changed", sensitivity="private")
_register("calendar", "schedule", "calendar.created calendar.updated calendar.cancelled calendar.deleted", sensitivity="private", attention_base=0.25)
_register("calendar", "schedule", "calendar.started calendar.ended", sensitivity="private", attention_base=0.2)
_register("notes", "knowledge", "note.created note.updated note.connected", sensitivity="private", interpret=True, attention_base=0.15)
_register("notes", "knowledge", "note.deleted", sensitivity="private")
_register("documents", "knowledge", "document.uploaded document.processing_completed document.updated capture.received", sensitivity="private", interpret=True, attention_base=0.2)
_register("documents", "knowledge", "document.deleted", sensitivity="private")
_register("food", "fitness_health", "food.logged food.updated food.interpretation_completed", sensitivity="health", attention_base=0.05, coalesce=True)
_register("food", "fitness_health", "food.deleted", sensitivity="health")
_register("workout", "fitness_health", "workout.started workout.set_logged workout.completed workout.abandoned workout.updated", sensitivity="health", attention_base=0.15, coalesce=True)
_register("health", "fitness_health", "health.sync_completed health.metric_transitioned health.workout_imported sleep.imported recovery.logged", sensitivity="health", attention_base=0.15, coalesce=True)
_register("tasks", "active_work", "task.queued task.started task.progressed task.completed task.failed", attention_base=0.3, coalesce=True)
_register("reminders", "open_threads", "reminder.created reminder.completed reminder.cancelled", attention_base=0.25)
_register("goals", "open_threads", "goal.created goal.updated goal.completed goal.progress_logged", attention_base=0.2)
_register("location", "david_now", "location.entered location.exited", sensitivity="location", attention_base=0.15, coalesce=True)
_register("presence", "david_now", "presence.changed app.session.started app.view.changed app.session.ended", sensitivity="location", coalesce=True)
_register("home", "home", "home.state_changed home.motion_detected home.door_changed home.light_changed home.climate_changed home.anomaly_detected", sensitivity="location", attention_base=0.1, coalesce=True)
_register("system", "sara_self", "system.health_degraded system.health_recovered sara.capability_changed", attention_base=0.45, coalesce=True)
_register("cognition", "sara_self", "world.interpretation.completed sara.deliberation.started sara.deliberation.completed", sensitivity="private", attention_base=0.0)
_register("time", "open_threads", "thread.due thread.overdue expectation.violated fact.expired", attention_base=0.45, coalesce=True)
# Closers. Invariant 3: everything open has a closer and an expiry. A resolution
# is not news — attention_base 0 — it is the event that makes a thread stop being
# news. Without these kinds nothing but a workout or a task terminal state could
# ever close a thread, which is how three Laura threads outlived the meeting.
_register("time", "open_threads", "thread.resolved thread.expired", attention_base=0.0)


def get_spec(kind: str) -> EventSpec:
    if kind in _SPECS:
        return _SPECS[kind]
    domain = (kind.split(".", 1)[0] or "system").lower()
    return EventSpec(domain=domain, slice_name="other")


def all_specs() -> Dict[str, EventSpec]:
    return dict(_SPECS)

