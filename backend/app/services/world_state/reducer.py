"""Deterministic, idempotent reducers for the first continuous world model."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models.world_model import (
    SaraPresenceSnapshot, WorldAttentionItem, WorldEntity, WorldEvent,
    WorldEventDisposition, WorldFact, WorldSnapshot, WorldThread,
)
from app.services.world_state.catalog import get_spec

REDUCER_VERSION = 1
ACTIVE_THREAD_STATUSES = {"proposed", "open", "waiting", "blocked"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _slug(value: Any) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return raw[:180] or "unknown"


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# Ground-truth invariant 1: "No invented time." A due date enters a thread only
# from a deterministic source — a calendar event, an explicit datetime written in
# the source text, David's own words, or a producer row (reminder/task/goal) that
# already carries a real time. Everything else gets due_at=NULL and a review date.
#
# The 2026-08-31 Laura Weippert incident is the canonical failure: an email that
# said only "any chance we can move this call to tomorrow afternoon?" produced a
# thread due 17:00Z, which then generated overdue events, pushes and paraphrases
# for two days about a meeting that had already happened.
DETERMINISTIC_DUE_DOMAINS = {"calendar", "reminders", "tasks", "goals"}
DETERMINISTIC_DUE_KINDS = {"chat.user_turn_stored"}

# A real datetime written out in the source text. Deliberately narrow: it must
# carry a date AND a time, or an ISO-8601 stamp. "tomorrow afternoon" is not a
# time and must not become one.
_EXPLICIT_DATETIME_RE = re.compile(
    r"""(
        \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\s*(?:Z|[+-]\d{2}:?\d{2}))?   # ISO-8601
      | (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}
        (?:,\s*\d{4})?\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)              # Tue Sep 2 at 1:00 PM
      | (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}
        (?:,\s*\d{4})?\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)              # Sep 2 at 1:00 PM
      | \d{1,2}/\d{1,2}(?:/\d{2,4})?\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)# 9/2 1:00 PM
    )""",
    re.VERBOSE,
)

_SOURCE_TEXT_KEYS = (
    "body_text", "body", "content", "text", "summary", "preview", "subject",
    "title", "description", "next_step", "original_query",
)


def _source_text(event: WorldEvent) -> str:
    """Everything in the payload a human actually wrote, concatenated."""
    p = event.payload or {}
    parts = [str(p[key]) for key in _SOURCE_TEXT_KEYS if isinstance(p.get(key), str)]
    return "\n".join(parts)[:20_000]


def _deterministic_due_at(
    event: WorldEvent, proposed: Any,
) -> Tuple[Optional[datetime], Optional[str]]:
    """Return (due_at, provenance) — ``(None, None)`` when nothing vouches for it.

    ``provenance`` is a short human-readable string naming what vouched for the
    time (the matched substring, for the text case) so a wrong deadline can be
    traced back to the thing that claimed it rather than to a model's guess.
    """
    parsed = _parse_dt(proposed)
    if parsed is None:
        return None, None

    spec = get_spec(event.kind)
    if spec.domain in DETERMINISTIC_DUE_DOMAINS:
        return parsed, f"producer:{event.kind}"
    if event.kind in DETERMINISTIC_DUE_KINDS:
        return parsed, f"david:{event.kind}"

    match = _EXPLICIT_DATETIME_RE.search(_source_text(event))
    if match:
        return parsed, f"source_text:{match.group(0).strip()[:120]}"

    return None, None


_WORD_SCORES = {
    "critical": 1.0, "urgent": 0.95, "highest": 0.9, "high": 0.8, "elevated": 0.7,
    "medium": 0.5, "moderate": 0.5, "normal": 0.5, "default": 0.5,
    "low": 0.25, "minor": 0.2, "lowest": 0.1, "none": 0.0,
}


def coerce_score(value: Any, default: float) -> float:
    """Coerce a model- or payload-supplied 0-1 score into a float.

    A local model asked for a numeric ``priority`` answers with a word about as
    often as a number, and a bare ``float("high")`` raises — which threw away a
    whole interpretation and left the event retrying forever. Words map to the
    obvious band; anything unreadable falls back to the caller's default.
    Unlike ``float(x or default)`` this also keeps a legitimate 0.0.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if not raw:
            return default
        try:
            number = float(raw.rstrip("%"))
        except ValueError:
            return _WORD_SCORES.get(raw, default)
        return number / 100.0 if raw.endswith("%") else number
    return default


def email_thread_key(conversation_id: Any, email_id: Any) -> str:
    """The one key an email follow-up thread is ever filed under.

    Keyed on the *conversation*, not the message: a five-message back-and-forth
    was opening five separate "needs attention" threads, none of which any reply
    could close. `email_sync._sync_sent_items_async` closes threads by this key,
    so producers and closers must agree on it exactly.
    """
    if conversation_id:
        return f"email:{conversation_id}"
    return f"email-action:{email_id}"


def _email_thread_key(event: WorldEvent) -> str:
    p = event.payload or {}
    # Only the payload's own conversation_id counts. event.correlation_id falls
    # back to the message id when a mail has no conversation, and treating that as
    # a conversation would file the thread under a key no sent reply can close.
    conversation_id = p.get("conversation_id")
    email_id = p.get("email_id") or event.aggregate_id or event.source_ref or "unknown"
    return email_thread_key(conversation_id, email_id)[:768]


def _event_summary(event: WorldEvent) -> str:
    p = event.payload or {}
    for key in ("summary", "status_label", "subject", "title", "name", "topic", "description", "place_name"):
        value = p.get(key)
        if value:
            return str(value).strip()[:240]
    return event.kind.replace(".", " ")


def _entity(
    db: Session, event: WorldEvent, *, kind: str, canonical_key: str,
    display_name: str, attributes: Optional[Dict[str, Any]] = None,
) -> WorldEntity:
    entity = db.execute(select(WorldEntity).where(
        WorldEntity.user_id == event.user_id,
        WorldEntity.kind == kind,
        WorldEntity.canonical_key == canonical_key,
    )).scalar_one_or_none()
    if entity is None:
        entity = WorldEntity(
            user_id=event.user_id, kind=kind, canonical_key=canonical_key,
            display_name=display_name[:512], attributes=_safe(attributes or {}),
            first_event_id=event.event_id, last_event_id=event.event_id,
        )
        db.add(entity)
        db.flush()
    else:
        entity.display_name = display_name[:512] or entity.display_name
        merged = dict(entity.attributes or {})
        merged.update(_safe(attributes or {}))
        entity.attributes = merged
        entity.last_event_id = event.event_id
        entity.status = "active"
    return entity


def _fact(
    db: Session, event: WorldEvent, *, fact_key: str, predicate: str,
    value: Any, subject_entity_id: Optional[str] = None,
    object_entity_id: Optional[str] = None, confidence: Optional[float] = None,
    confidence_basis: Optional[str] = None, extractor_version: Optional[str] = None,
    valid_from: Optional[datetime] = None, valid_to: Optional[datetime] = None,
) -> Tuple[WorldFact, bool]:
    current = db.execute(select(WorldFact).where(
        WorldFact.user_id == event.user_id,
        WorldFact.fact_key == fact_key,
        WorldFact.status == "active",
    ).order_by(WorldFact.created_at.desc()).limit(1)).scalar_one_or_none()
    normalized = _safe(value)
    if current is not None and current.value == normalized and current.object_entity_id == object_entity_id:
        current.source_event_id = event.event_id
        current.source_ref = event.source_ref
        current.last_event_sequence = event.sequence
        current.observed_at = event.observed_at
        return current, False
    if current is not None:
        current.status = "superseded"
        current.valid_to = event.occurred_at
    row = WorldFact(
        user_id=event.user_id, fact_key=fact_key, subject_entity_id=subject_entity_id,
        predicate=predicate, object_entity_id=object_entity_id, value=normalized,
        valid_from=valid_from or event.occurred_at, valid_to=valid_to,
        observed_at=event.observed_at, status="active",
        confidence=confidence if confidence is not None else event.confidence,
        confidence_basis=confidence_basis or event.confidence_basis,
        source_event_id=event.event_id, source_ref=event.source_ref,
        extractor_version=extractor_version,
        supersedes_fact_id=current.id if current is not None else None,
        last_event_sequence=event.sequence,
    )
    db.add(row)
    db.flush()
    return row, True


def _retract_source(db: Session, event: WorldEvent) -> int:
    if not event.source_ref:
        return 0
    rows = db.execute(select(WorldFact).where(
        WorldFact.user_id == event.user_id,
        WorldFact.source_ref == event.source_ref,
        WorldFact.status == "active",
    )).scalars().all()
    for row in rows:
        row.status = "retracted"
        row.retracted_by_event_id = event.event_id
        row.valid_to = event.occurred_at
        row.last_event_sequence = event.sequence
    return len(rows)


def _thread(
    db: Session, event: WorldEvent, *, thread_key: str, kind: str, title: str,
    status: str = "open", next_step: Optional[str] = None,
    due_at: Optional[datetime] = None, priority: float = 0.5,
    confidence: Optional[float] = None, due_provenance: Optional[str] = None,
) -> Tuple[WorldThread, str]:
    row = db.execute(select(WorldThread).where(
        WorldThread.user_id == event.user_id,
        WorldThread.thread_key == thread_key,
    )).scalar_one_or_none()
    operation = "thread_opened"
    # A thread with no deadline is not a thread with no expiry: it comes up for
    # review in three days and is hard-expired by the nightly truth job.
    review_at = None if due_at is not None else event.occurred_at + timedelta(days=3)
    if row is None:
        row = WorldThread(
            user_id=event.user_id, thread_key=thread_key, kind=kind, status=status,
            title=title[:2000], next_step=next_step, due_at=due_at,
            next_review_at=review_at,
            priority=max(0.0, min(priority, 1.0)),
            confidence=confidence if confidence is not None else event.confidence,
            source_event_id=event.event_id, correlation_id=event.correlation_id,
            last_event_sequence=event.sequence,
        )
        row.due_provenance = due_provenance if due_at is not None else None
        db.add(row)
        db.flush()
    else:
        operation = "thread_advanced"
        old_status = row.status
        row.title = title[:2000] or row.title
        row.next_step = next_step if next_step is not None else row.next_step
        if due_at is not None:
            row.due_at = due_at
            row.due_provenance = due_provenance
        if row.due_at is None and row.next_review_at is None:
            row.next_review_at = review_at
        row.priority = max(row.priority or 0.0, priority)
        row.source_event_id = event.event_id
        row.last_event_sequence = event.sequence
        row.status = status
        if status in {"resolved", "cancelled", "expired"}:
            row.resolved_at = event.occurred_at
            operation = "thread_resolved"
        elif old_status in {"resolved", "cancelled", "expired"} and status in ACTIVE_THREAD_STATUSES:
            row.resolved_at = None
            operation = "thread_opened"
    return row, operation


# Invariant 3: everything open has a closer. These kinds exist to shut a thread
# without any domain reducer having to know about it, so an answered email, a
# finished meeting, an acknowledged push and David saying "we already did that"
# all reach the same place.
CLOSER_KINDS = {"thread.resolved": "resolved", "thread.expired": "expired"}


def _close_threads(db: Session, event: WorldEvent, status: str) -> List[WorldThread]:
    """Close the threads a closer event names, by id or by key.

    Accepts ``thread_id``/``aggregate_id`` for a single thread and ``thread_keys``
    for a set (the sent-reply closer names a conversation, which may have opened
    more than one thread before the one-thread-per-conversation rule landed).
    """
    p = event.payload or {}
    ids = [str(v) for v in (p.get("thread_ids") or []) if v]
    single = p.get("thread_id") or (event.aggregate_id if event.aggregate_type == "world_thread" else None)
    if single:
        ids.append(str(single))
    keys = [str(v) for v in (p.get("thread_keys") or []) if v]
    if p.get("thread_key"):
        keys.append(str(p["thread_key"]))
    if not ids and not keys:
        return []

    conditions = []
    if ids:
        conditions.append(WorldThread.id.in_(ids))
    if keys:
        conditions.append(WorldThread.thread_key.in_(keys))

    rows = db.execute(select(WorldThread).where(
        WorldThread.user_id == event.user_id,
        WorldThread.status.in_(tuple(ACTIVE_THREAD_STATUSES)),
        or_(*conditions),
    )).scalars().all()
    for row in rows:
        row.status = status
        row.resolved_at = event.occurred_at
        row.source_event_id = event.event_id
        row.last_event_sequence = event.sequence
    return list(rows)


def _event_state(event: WorldEvent) -> Dict[str, Any]:
    p = dict(event.payload or {})
    # Never copy raw content into the hot snapshot.
    for key in ("content", "body", "body_text", "text", "image_base64", "embedding"):
        p.pop(key, None)
    p.update({
        "event_id": event.event_id,
        "kind": event.kind,
        "source_ref": event.source_ref,
        "occurred_at": event.occurred_at.isoformat(),  # time-ok: snapshot storage, not prompt text
    })
    return _safe(p)


def _reduce_domain(db: Session, event: WorldEvent) -> Tuple[Dict[str, Any], List[str], Dict[str, List[str]]]:
    p = event.payload or {}
    kind = event.kind
    state = _event_state(event)
    outcomes: List[str] = ["absorbed", "state_updated"]
    outputs: Dict[str, List[str]] = {"entities": [], "facts": [], "threads": [], "attention": []}

    if kind.endswith(".deleted") or kind.endswith(".cancelled"):
        retracted = _retract_source(db, event)
        if retracted:
            outcomes.append("retracted")
            state["retracted_fact_count"] = retracted

    aggregate_id = event.aggregate_id or p.get("id") or p.get("email_id") or p.get("event_id") or p.get("note_id") or p.get("document_id") or p.get("log_id") or p.get("session_id") or event.source_ref
    spec = get_spec(kind)

    if kind in CLOSER_KINDS:
        closed = _close_threads(db, event, CLOSER_KINDS[kind])
        outputs["threads"].extend(t.id for t in closed)
        state["threads_closed"] = len(closed)
        if closed:
            outcomes.append("thread_resolved")
        return state, list(dict.fromkeys(outcomes)), outputs

    if spec.domain == "chat":
        conv_id = p.get("conversation_id") or event.aggregate_id or "unknown"
        entity = _entity(db, event, kind="conversation", canonical_key=str(conv_id), display_name=p.get("title") or "Conversation", attributes={"conversation_id": conv_id})
        outputs["entities"].append(entity.id)
        fact, changed = _fact(db, event, fact_key=f"conversation:{conv_id}:last_turn", predicate="last_turn", value={"role": p.get("role"), "preview": p.get("preview"), "episode_id": p.get("episode_id")}, subject_entity_id=entity.id)
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")
        thread, op = _thread(db, event, thread_key=f"conversation:{conv_id}", kind="active_conversation", title=p.get("title") or "Active conversation", status="resolved" if kind == "conversation.closed" else "open", priority=0.5)
        outputs["threads"].append(thread.id)
        outcomes.append(op)

    elif spec.domain == "email":
        email_id = str(aggregate_id or "unknown")
        email = _entity(db, event, kind="email", canonical_key=email_id, display_name=p.get("subject") or "Email", attributes={"sender_email": p.get("sender_email")})
        outputs["entities"].append(email.id)
        if p.get("sender_email") or p.get("sender_name"):
            person_key = (p.get("sender_email") or _slug(p.get("sender_name"))).lower()
            person = _entity(db, event, kind="person", canonical_key=person_key, display_name=p.get("sender_name") or p.get("sender_email"), attributes={"email": p.get("sender_email")})
            outputs["entities"].append(person.id)
            fact, _ = _fact(db, event, fact_key=f"email:{email_id}:sender", predicate="sent_by", value=None, subject_entity_id=email.id, object_entity_id=person.id)
            outputs["facts"].append(fact.id)
        fact, changed = _fact(db, event, fact_key=f"email:{email_id}:state", predicate="email_state", value={"subject": p.get("subject"), "is_read": p.get("is_read"), "action_required": p.get("action_required"), "importance": p.get("importance_score")}, subject_entity_id=email.id)
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")
        if p.get("action_required"):
            thread, op = _thread(db, event, thread_key=_email_thread_key(event), kind="follow_up", title=p.get("subject") or "Email needs attention", next_step=p.get("summary") or "Review email", priority=coerce_score(p.get("importance_score"), 0.6))
            outputs["threads"].append(thread.id)
            outcomes.append(op)

    elif spec.domain == "calendar":
        cal_id = str(aggregate_id or "unknown")
        entity = _entity(db, event, kind="calendar_item", canonical_key=cal_id, display_name=p.get("title") or "Calendar event")
        outputs["entities"].append(entity.id)
        status = "cancelled" if kind.endswith(("cancelled", "deleted")) else "ended" if kind.endswith("ended") else "started" if kind.endswith("started") else "scheduled"
        fact, changed = _fact(db, event, fact_key=f"calendar:{cal_id}:schedule", predicate="schedule", value={"title": p.get("title"), "start_time": p.get("start_time"), "end_time": p.get("end_time"), "location": p.get("location"), "status": status}, subject_entity_id=entity.id, valid_from=_parse_dt(p.get("start_time")), valid_to=_parse_dt(p.get("end_time")))
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")

    elif spec.domain in {"notes", "documents"}:
        entity_kind = "note" if spec.domain == "notes" else "document"
        item_id = str(aggregate_id or "unknown")
        entity = _entity(db, event, kind=entity_kind, canonical_key=item_id, display_name=p.get("title") or p.get("filename") or entity_kind.title(), attributes={"processing_status": p.get("processing_status")})
        outputs["entities"].append(entity.id)
        fact, changed = _fact(db, event, fact_key=f"{entity_kind}:{item_id}:state", predicate=f"{entity_kind}_state", value={"title": p.get("title"), "filename": p.get("filename"), "is_processed": p.get("is_processed"), "summary": p.get("summary")}, subject_entity_id=entity.id)
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")

    elif spec.domain in {"food", "workout", "health"}:
        key = str(aggregate_id or kind)
        fact, changed = _fact(db, event, fact_key=f"{spec.domain}:{key}:state", predicate=f"{spec.domain}_state", value=state)
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")
        if spec.domain == "workout" and kind in {"workout.started", "workout.completed", "workout.abandoned"}:
            status = "open" if kind == "workout.started" else "resolved" if kind == "workout.completed" else "cancelled"
            thread, op = _thread(db, event, thread_key=f"workout:{key}", kind="plan", title=p.get("title") or p.get("name") or "Workout", status=status, priority=0.5)
            outputs["threads"].append(thread.id)
            outcomes.append(op)

    elif spec.domain in {"tasks", "reminders", "goals"}:
        key = str(aggregate_id or p.get("task_id") or p.get("reminder_id") or p.get("goal_id") or "unknown")
        terminal = kind.endswith(("completed", "cancelled"))
        failed = kind.endswith("failed")
        status = "resolved" if terminal else "blocked" if failed else "open"
        due_at, due_provenance = _deterministic_due_at(event, p.get("due_at"))
        thread, op = _thread(db, event, thread_key=f"{spec.domain}:{key}", kind="commitment" if spec.domain != "tasks" else "plan", title=p.get("title") or p.get("original_query") or p.get("description") or spec.domain.title(), status=status, next_step=p.get("status_label"), due_at=due_at, due_provenance=due_provenance, priority=coerce_score(p.get("priority"), 0.5))
        outputs["threads"].append(thread.id)
        outcomes.append(op)

    elif spec.domain in {"location", "presence", "home", "system", "time", "cognition"}:
        fact_key = f"{spec.domain}:{_slug(aggregate_id or p.get('entity_id') or kind)}:latest"
        fact, changed = _fact(db, event, fact_key=fact_key, predicate=f"{spec.domain}_state", value=state)
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")

    # Explicit deterministic entities/facts/threads are available to trusted
    # producers and to the separately bounded interpretation worker.
    for item in p.get("entities", []) if isinstance(p.get("entities"), list) else []:
        if not isinstance(item, dict) or not item.get("kind") or not item.get("canonical_key"):
            continue
        entity = _entity(
            db, event,
            kind=str(item["kind"])[:64],
            canonical_key=str(item["canonical_key"])[:512],
            display_name=str(item.get("name") or item["canonical_key"])[:512],
            attributes=item.get("attributes") if isinstance(item.get("attributes"), dict) else None,
        )
        outputs["entities"].append(entity.id)

    for item in p.get("facts", []) if isinstance(p.get("facts"), list) else []:
        if not isinstance(item, dict) or not item.get("predicate"):
            continue
        key = item.get("fact_key") or f"explicit:{event.event_id}:{item['predicate']}:{len(outputs['facts'])}"
        fact, changed = _fact(db, event, fact_key=key, predicate=item["predicate"], value=item.get("value"), confidence=item.get("confidence"), confidence_basis=item.get("confidence_basis"), extractor_version=item.get("extractor_version"))
        outputs["facts"].append(fact.id)
        if changed:
            outcomes.append("connected")

    # Invariant 2: "Sara's words are not evidence." An interpretation of Sara's own
    # assistant turn may refresh entities and facts about the conversation, but it
    # may never open a thread — otherwise she reads back her own draft ("I'll
    # confirm by 1 PM") as an obligation David incurred. The catalog also keeps the
    # interpreter off that kind entirely; this is the second lock on the same door.
    interpreted_kind = str(p.get("source_event_kind") or "")
    thread_items = p.get("threads", []) if isinstance(p.get("threads"), list) else []
    if interpreted_kind == "chat.assistant_turn_stored" or kind == "chat.assistant_turn_stored":
        if thread_items:
            outcomes.append("threads_discarded_own_speech")
        thread_items = []

    for item in thread_items:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        thread_key = item.get("thread_key") or f"explicit:{event.event_id}:{len(outputs['threads'])}"
        due_at, due_provenance = _deterministic_due_at(event, item.get("due_at"))
        thread, operation = _thread(
            db, event,
            thread_key=str(thread_key)[:768],
            kind=str(item.get("kind") or "follow_up")[:32],
            title=str(item["title"])[:2000],
            status=str(item.get("status") or "open")[:24],
            next_step=str(item.get("next_step"))[:2000] if item.get("next_step") else None,
            due_at=due_at, due_provenance=due_provenance,
            priority=coerce_score(item.get("priority"), 0.5),
            confidence=coerce_score(item.get("confidence"), float(event.confidence)),
        )
        outputs["threads"].append(thread.id)
        outcomes.append(operation)

    return state, list(dict.fromkeys(outcomes)), outputs


def _attention_score(event: WorldEvent) -> Tuple[float, float, float, float, float]:
    spec = get_spec(event.kind)
    p = event.payload or {}
    salience = float(p.get("salience", spec.attention_base) or 0.0)
    novelty = float(p.get("novelty", 0.5 if spec.attention_base else 0.0) or 0.0)
    urgency = float(p.get("urgency", 0.0) or 0.0)
    uncertainty = float(p.get("uncertainty", 0.0) or 0.0)
    actionability = float(p.get("actionability", 0.6 if p.get("action_required") else 0.0) or 0.0)
    if event.kind.endswith("failed") or event.kind.endswith("overdue") or event.kind == "system.health_degraded":
        salience, urgency = max(salience, 0.65), max(urgency, 0.55)
    aggregate = min(1.0, salience * 0.4 + novelty * 0.15 + urgency * 0.25 + uncertainty * 0.05 + actionability * 0.15)
    return salience, novelty, urgency, uncertainty, aggregate


def _upsert_attention(db: Session, event: WorldEvent, outputs: Dict[str, List[str]]) -> Optional[WorldAttentionItem]:
    # App/view presence never manufactures a cognition wake.
    if event.kind.startswith("app.") or event.is_backfill:
        return None
    salience, novelty, urgency, uncertainty, aggregate = _attention_score(event)
    if aggregate < 0.25:
        return None
    spec = get_spec(event.kind)
    logical = event.aggregate_id or event.source_ref or event.kind
    coalesce_key = f"{event.kind}:{logical}" if spec.coalesce else f"event:{event.event_id}"
    row = db.execute(select(WorldAttentionItem).where(
        WorldAttentionItem.user_id == event.user_id,
        WorldAttentionItem.coalesce_key == coalesce_key,
    )).scalar_one_or_none()
    if row is None:
        row = WorldAttentionItem(
            user_id=event.user_id, source_event_id=event.event_id,
            domain=spec.domain, description=_event_summary(event),
            salience=salience, novelty=novelty, urgency=urgency,
            uncertainty=uncertainty, actionability=float((event.payload or {}).get("actionability", 0.0) or 0.0),
            aggregate_score=aggregate, coalesce_key=coalesce_key,
            valid_until=_parse_dt((event.payload or {}).get("valid_until")) or (_now() + timedelta(days=2)),
        )
        db.add(row)
        db.flush()
    else:
        row.source_event_id = event.event_id
        row.description = _event_summary(event)
        row.salience = max(row.salience, salience)
        row.novelty = max(row.novelty, novelty)
        row.urgency = max(row.urgency, urgency)
        row.uncertainty = max(row.uncertainty, uncertainty)
        row.aggregate_score = max(row.aggregate_score, aggregate)
        row.occurrence_count += 1
        row.last_seen_at = _now()
        if row.status in {"resolved", "expired"}:
            row.status = "queued"
            row.resolved_at = None
    outputs["attention"].append(row.id)
    return row


def _update_snapshot(db: Session, event: WorldEvent, state: Dict[str, Any]) -> WorldSnapshot:
    spec = get_spec(event.kind)
    row = db.execute(select(WorldSnapshot).where(WorldSnapshot.user_id == event.user_id).with_for_update()).scalar_one_or_none()
    if row is None:
        row = WorldSnapshot(user_id=event.user_id, revision=0, last_event_sequence=0, snapshot={"slices": {}, "recent_changes": []}, coverage={})
        db.add(row)
        db.flush()
    if event.sequence <= (row.last_event_sequence or 0):
        return row
    snap = dict(row.snapshot or {})
    slices = dict(snap.get("slices") or {})
    slices[spec.slice_name] = {
        "updated_at": event.observed_at.isoformat(), "source_event_id": event.event_id,  # time-ok: snapshot storage, not prompt text
        "source_sequence": event.sequence, "confidence": event.confidence,
        "stale": False, "data": state,
    }
    recent = list(snap.get("recent_changes") or [])
    recent.append({
        "event_id": event.event_id, "sequence": event.sequence, "kind": event.kind,
        "occurred_at": event.occurred_at.isoformat(), "source_ref": event.source_ref,  # time-ok: snapshot storage, not prompt text
        "summary": _event_summary(event),
    })
    snap.update({"schema_version": 2, "user_id": event.user_id, "slices": slices, "recent_changes": recent[-100:]})
    coverage = dict(row.coverage or {})
    coverage[spec.domain] = {"last_event_sequence": event.sequence, "last_kind": event.kind, "updated_at": event.observed_at.isoformat()}  # time-ok: snapshot storage, not prompt text
    row.snapshot = snap
    row.coverage = coverage
    row.revision = (row.revision or 0) + 1
    row.last_event_sequence = event.sequence
    row.as_of = event.observed_at
    return row


def _presence_values(event: WorldEvent) -> Optional[Dict[str, Any]]:
    p = event.payload or {}
    now = _now()
    if event.kind.startswith("app.") or event.kind.startswith("presence."):
        return None
    if event.kind in {"task.started", "task.progressed"}:
        return {"state": "acting", "headline": p.get("status_label") or "Working on a task", "detail": p.get("title") or p.get("original_query"), "task_id": p.get("task_id") or event.aggregate_id, "valid_until": now + timedelta(minutes=30)}
    if event.kind == "task.failed" or event.kind == "system.health_degraded":
        return {"state": "degraded", "headline": p.get("summary") or p.get("error") or "Something needs attention", "detail": p.get("detail"), "valid_until": now + timedelta(hours=2)}
    if event.kind == "sara.deliberation.started":
        return {"state": "deliberating", "headline": p.get("headline") or "Thinking something through", "detail": p.get("detail"), "valid_until": now + timedelta(minutes=10)}
    if event.kind == "world.interpretation.completed":
        return {"state": "observing", "headline": p.get("headline") or "Updated my understanding", "detail": p.get("detail"), "valid_until": now + timedelta(minutes=10)}
    if event.kind == "chat.user_turn_stored":
        return {"state": "engaged", "headline": "In conversation", "detail": p.get("preview"), "valid_until": now + timedelta(minutes=10)}
    if event.kind in {"task.completed", "sara.deliberation.completed"}:
        return {"state": "observing", "headline": p.get("status_label") or p.get("summary") or "Finished", "detail": p.get("detail"), "valid_until": now + timedelta(minutes=10)}
    if event.kind in {"email.received", "document.processing_completed", "note.updated", "calendar.updated"}:
        return {"state": "observing", "headline": _event_summary(event), "detail": event.kind.replace(".", " "), "valid_until": now + timedelta(minutes=10)}
    return None


def _update_presence(db: Session, event: WorldEvent) -> Optional[SaraPresenceSnapshot]:
    values = _presence_values(event)
    if values is None or event.is_backfill:
        return None
    row = db.execute(select(SaraPresenceSnapshot).where(SaraPresenceSnapshot.user_id == event.user_id).with_for_update()).scalar_one_or_none()
    if row is None:
        row = SaraPresenceSnapshot(user_id=event.user_id, revision=0, valid_until=values["valid_until"])
        db.add(row)
    row.revision = (row.revision or 0) + 1
    row.state = values["state"]
    row.headline = str(values["headline"] or "Available")[:500]
    row.detail = str(values.get("detail"))[:1000] if values.get("detail") else None
    row.source = event.source
    row.correlation_id = event.correlation_id
    row.event_id = event.event_id
    row.task_id = values.get("task_id")
    row.updated_at = _now()
    row.valid_until = values["valid_until"]
    return row


def reduce_world_event(db: Session, event: WorldEvent) -> WorldEventDisposition:
    existing = db.execute(select(WorldEventDisposition).where(WorldEventDisposition.event_id == event.event_id)).scalar_one_or_none()
    if existing:
        return existing
    # Serialize state application per user. This makes ordering and supersession
    # deterministic while allowing different users to process concurrently.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:uid))"), {"uid": event.user_id})
    state, outcomes, outputs = _reduce_domain(db, event)
    attention = _upsert_attention(db, event, outputs)
    if attention is not None:
        outcomes.append("attention_queued")
    snapshot = _update_snapshot(db, event, state)
    presence = _update_presence(db, event)
    outputs["snapshot"] = [str(snapshot.revision)]
    if presence is not None:
        outputs["presence"] = [str(presence.revision)]
    spec = get_spec(event.kind)
    if spec.interpret and not event.is_backfill:
        outcomes.append("interpretation_queued")
    disposition = WorldEventDisposition(
        event_id=event.event_id, user_id=event.user_id,
        reducer_version=REDUCER_VERSION, outcomes=list(dict.fromkeys(outcomes)),
        reason="Applied deterministic domain state; expression remains independently gated.",
        state_delta={"slice": spec.slice_name, "state": state}, output_ids=outputs,
    )
    db.add(disposition)
    db.flush()
    return disposition
