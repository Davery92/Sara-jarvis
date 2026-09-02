from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.schemas.world_events import EventEnvelopeV2, SaraPresenceV1
from app.services.world_state.catalog import get_spec
from app.services.world_state.reducer import _attention_score, _presence_values


def event(kind: str, payload=None, **overrides):
    values = {
        "kind": kind,
        "payload": payload or {},
        "aggregate_id": "aggregate-1",
        "source_ref": "source:1",
        "source": "test",
        "is_backfill": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_event_envelope_is_versioned_and_utc():
    envelope = EventEnvelopeV2(
        user_id="user-1", kind="note.created", source="test",
        dedupe_key="note:1:v1",
    )
    assert envelope.schema_version == 2
    assert envelope.event_id
    assert envelope.occurred_at.tzinfo is not None
    assert envelope.confidence_basis == "observed"


def test_catalog_declares_sensitive_domains_and_interpretation():
    email = get_spec("email.received")
    health = get_spec("health.metric_transitioned")
    assert email.domain == "email"
    assert email.sensitivity == "private"
    assert email.interpret is True
    assert health.sensitivity == "health"


def test_app_open_never_manufactures_cognition_presence():
    assert _presence_values(event("app.session.started")) is None
    assert _presence_values(event("app.view.changed")) is None


def test_task_progress_has_expiring_truthful_presence():
    values = _presence_values(event(
        "task.progressed",
        {"status_label": "Searching the web", "title": "Compare flights", "task_id": "task-1"},
    ))
    assert values["state"] == "acting"
    assert values["headline"] == "Searching the web"
    assert values["task_id"] == "task-1"
    assert values["valid_until"] > datetime.now(timezone.utc)


def test_failed_work_is_attention_worthy():
    score = _attention_score(event("task.failed", {"error": "connection refused"}))[-1]
    assert score >= 0.39


def test_presence_contract_rejects_permanent_thinking_by_requiring_expiry():
    now = datetime.now(timezone.utc)
    presence = SaraPresenceV1(
        user_id="user-1", state="deliberating", headline="Thinking",
        updated_at=now, valid_until=now + timedelta(minutes=10),
    )
    assert presence.valid_until > presence.updated_at


def test_word_scores_do_not_crash_the_interpreter():
    """Sara's interoception log caught this live: a local model answered
    ``"priority": "high"`` on an email.received interpretation, ``float("high")``
    raised, the whole extraction was discarded, and the event sat in
    interpreter_status='retry' re-burning an LLM call every drain cycle."""
    from app.services.world_state.reducer import coerce_score

    assert coerce_score("high", 0.5) == 0.8
    assert coerce_score("HIGH", 0.5) == 0.8
    assert coerce_score(" Medium ", 0.5) == 0.5
    assert coerce_score("low", 0.5) == 0.25
    assert coerce_score("critical", 0.5) == 1.0


def test_score_coercion_keeps_real_numbers_and_falls_back_otherwise():
    from app.services.world_state.reducer import coerce_score

    assert coerce_score(0.73, 0.5) == 0.73
    assert coerce_score("0.73", 0.5) == 0.73
    assert coerce_score("80%", 0.5) == 0.8
    # A legitimate zero survives — `float(x or default)` silently lost it.
    assert coerce_score(0, 0.5) == 0.0
    assert coerce_score(0.0, 0.5) == 0.0
    # Unreadable input falls back instead of raising.
    assert coerce_score("sometime soon", 0.5) == 0.5
    assert coerce_score(None, 0.65) == 0.65
    assert coerce_score("", 0.65) == 0.65
    assert coerce_score({"a": 1}, 0.65) == 0.65
    assert coerce_score(True, 0.65) == 0.65


def test_interpreter_cleans_a_word_valued_thread_into_a_usable_score():
    from app.services.world_state.interpreter import _clean_result

    cleaned = _clean_result(
        {
            "headline": "AWS is retiring Fargate tasks",
            "threads": [{"title": "Migrate ECS tasks", "priority": "high", "confidence": "medium"}],
            "facts": [{"predicate": "vendor_deadline", "value": "2026-09-04", "confidence": "high"}],
        },
        event("email.received", {}, event_id="e-1"),
    )
    assert cleaned["threads"][0]["priority"] == 0.8
    assert cleaned["threads"][0]["confidence"] == 0.5
    # Facts clamp confidence at 0.85 — "high" (0.8) stays under the ceiling.
    assert cleaned["facts"][0]["confidence"] == 0.8
