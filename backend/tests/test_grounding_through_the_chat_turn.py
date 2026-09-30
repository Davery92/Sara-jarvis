"""Grounding, exercised through the real chat turn — not through helpers.

The plan is explicit that a helper-level pass is not evidence: *"Avoid
helpers-only tests that miss a second execution path"* and *"Check both
database state and actual user-visible text; tool-return fields alone are
insufficient."* So every case here drives `SimpleLLMClient.execute_tool` (the
real execution boundary, which builds the turn ledger) and then
`_finalize_response_content` (the real single choke point every turn exit
passes through, which grounds and persists), and asserts on the text a client
would actually receive — including what came out of `text_chunk` events.
"""

import json
import uuid

import pytest

from app import main_simple as ms
from app.tools.base import ToolResult


def make_client(turn_message: str):
    """A client wired like a real turn, with the SSE events captured."""
    client = ms.SimpleLLMClient()
    client.emitted = []

    async def _capture_event(event_type, data):
        client.emitted.append((event_type, data))

    async def _noop(*a, **kw):
        return None

    client.emit_event = _capture_event
    client.emit_activity = _noop
    client._turn_message_for_mutation_gate = turn_message
    client._current_raw_user_turn = turn_message
    client._last_turn_mutating_tools_for_boundary = []
    # Per-turn grounding state, as `_chat_with_tools_inner` sets it.
    client._turn_ledger = None
    client._hold_stream_for_grounding = False
    client._held_stream_text = ""
    client._activity_responding_emitted = False
    return client


def offer(client, *names):
    client._active_tools = [
        {"type": "function", "function": {"name": n}} for n in names
    ]


def call(name, args=None, call_id=None):
    return {
        "id": call_id or f"c-{uuid.uuid4().hex[:8]}",
        "function": {"name": name, "arguments": json.dumps(args or {})},
    }


def text_chunks(client):
    return [d.get("full_content") for t, d in client.emitted if t == "text_chunk"]


async def finalize(client, text, user_id=None):
    return await client._finalize_response_content(text, [], user_id=user_id)


@pytest.mark.asyncio
async def test_a_failed_write_cannot_be_reported_as_done(monkeypatch):
    client = make_client("Add a reminder to call the vet at 5")
    offer(client, "reminders_create")

    async def _fails(name, user_id, parameters, context=None):
        return ToolResult(success=False, message="database is locked", data=None)

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _fails)

    await client.execute_tool(
        call("reminders_create", {"title": "call the vet", "reminder_time": "17:00"}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )

    final = await finalize(client, "Done — vet reminder set for 5pm.")
    assert "Done — vet reminder set for 5pm." not in final
    assert "failed" in final.lower()


@pytest.mark.asyncio
async def test_a_successful_write_keeps_the_models_own_words(monkeypatch):
    client = make_client("Add a reminder to call the vet at 5")
    offer(client, "reminders_create")

    async def _ok(name, user_id, parameters, context=None):
        return ToolResult(success=True, message="Reminder created", data={"id": "r1"})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)

    await client.execute_tool(
        call("reminders_create", {"title": "call the vet", "reminder_time": "17:00"}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )

    reply = "Done — vet reminder set for 5pm. Say hi to the dog for me."
    assert await finalize(client, reply) == reply


@pytest.mark.asyncio
async def test_a_refused_call_cannot_be_reported_as_done(monkeypatch):
    # The refusal path records its own ledger entry and returns before the
    # registry, so this also proves the ledger is written on the refusal branch.
    client = make_client("Thanks.")
    offer(client, "reminders_create")

    async def _must_not_run(*a, **kw):
        raise AssertionError("the registry must not be reached on an acknowledgement")

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

    result = await client.execute_tool(
        call("reminders_create", {"title": "call the vet", "reminder_time": "17:00"}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )
    assert json.loads(result["content"])["success"] is False

    final = await finalize(client, "Done, added that for you.")
    assert "Done, added that" not in final


@pytest.mark.asyncio
async def test_a_tool_that_raises_is_recorded_as_failed_not_omitted(monkeypatch):
    client = make_client("Add a reminder to call the vet at 5")
    offer(client, "reminders_create")

    async def _raises(name, user_id, parameters, context=None):
        raise RuntimeError("psycopg.OperationalError: connection closed")

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _raises)

    await client.execute_tool(
        call("reminders_create", {"title": "call the vet", "reminder_time": "17:00"}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )
    ledger = client._turn_outcome_ledger()
    assert ledger.writes_attempted
    assert not ledger.any_succeeded

    final = await finalize(client, "All set.")
    assert "All set." not in final


@pytest.mark.asyncio
async def test_a_false_denial_of_a_real_write_is_repaired(monkeypatch):
    client = make_client("Log 150g of chicken breast")
    offer(client, "food_log_create")

    async def _ok(name, user_id, parameters, context=None):
        return ToolResult(success=True, message="Logged chicken breast 150g",
                          data={"id": "f1"})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)

    await client.execute_tool(
        call("food_log_create", {"food": "chicken breast", "grams": 150}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )

    final = await finalize(
        client,
        "Actually I owe you a correction — I never actually logged it. "
        "No tool call went through.",
    )
    assert "never actually logged" not in final
    assert "done" in final.lower()


@pytest.mark.asyncio
async def test_the_stream_is_held_while_a_write_is_unverified(monkeypatch):
    """Plan D2: "do not stream an unverified success and attempt to correct it
    afterward." On a write turn the deltas are held; exactly one grounded
    chunk is emitted, and it is the same string that gets persisted."""
    client = make_client("Add a reminder to call the vet at 5")
    offer(client, "reminders_create")

    async def _fails(name, user_id, parameters, context=None):
        return ToolResult(success=False, message="database is locked", data=None)

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _fails)

    await client.execute_tool(
        call("reminders_create", {"title": "call the vet", "reminder_time": "17:00"}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )
    assert client._hold_stream_for_grounding is True

    # The model streams a false success. Nothing may reach the client.
    await client.emit_text_chunk("Done — ", "Done — ")
    await client.emit_text_chunk("vet reminder set.", "Done — vet reminder set.")
    assert text_chunks(client) == [], "an unverified success reached the client"

    final = await finalize(client, "Done — vet reminder set.")
    chunks = text_chunks(client)
    assert len(chunks) == 1
    assert chunks[0] == final, "the streamed text and the persisted text must be one string"
    assert "Done — vet reminder set." not in chunks[0]


@pytest.mark.asyncio
async def test_a_conversational_turn_still_streams_token_by_token(monkeypatch):
    """The overwhelming majority of turns write nothing, and must keep the
    incremental stream — holding every turn would be a real regression in how
    Sara feels to talk to."""
    client = make_client("breakfast food tastes better at night")
    offer(client, "notes_search")

    async def _ok(name, user_id, parameters, context=None):
        return ToolResult(success=True, message="no notes", data={"results": []})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)
    await client.execute_tool(call("notes_search", {"query": "breakfast"}),
                              user_id=str(uuid.uuid4()),
                              conversation_id=str(uuid.uuid4()))

    assert client._hold_stream_for_grounding is False
    await client.emit_text_chunk("It ", "It ")
    await client.emit_text_chunk("does.", "It does.")
    assert text_chunks(client) == ["It ", "It does."]

    reply = "It does. Something about the lighting."
    assert await finalize(client, reply) == reply


@pytest.mark.asyncio
async def test_a_requested_change_that_failed_is_said_out_loud(monkeypatch):
    """A reply that simply does not mention the failure is not innocent: David
    asked for a reminder, none was written, and "five is tight but fine" leaves
    him believing it exists. The honest outcome is appended."""
    client = make_client("Add a reminder to call the vet at 5")
    offer(client, "reminders_create")

    async def _fails(name, user_id, parameters, context=None):
        return ToolResult(success=False, message="database is locked", data=None)

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _fails)
    await client.execute_tool(
        call("reminders_create", {"title": "call the vet", "reminder_time": "17:00"}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )

    final = await finalize(client, "The vet closes at six, so five is tight but fine.")
    assert "failed" in final.lower()
    assert "vet closes at six" in final, "the conversational half survives"


@pytest.mark.asyncio
async def test_a_reply_with_no_status_claim_on_a_read_turn_is_untouched(monkeypatch):
    client = make_client("When does the vet close?")
    offer(client, "reminders_list")
    reply = "The vet closes at six, so five is tight but fine."
    assert await finalize(client, reply) == reply


@pytest.mark.asyncio
async def test_a_requested_change_that_never_ran_cannot_read_as_done(monkeypatch):
    """Found live on the food journey. "That was actually 150 grams, not 100."
    produced

        "Got it — 150g, not 100. That's 248 calories and 46.5g protein."

    with NO tool call at all, and the stored row still reading 100g/165cal.
    There is no status verb in that sentence for a claim pattern to catch —
    what catches it is that a change was requested and nothing was written.
    """
    client = make_client("That was actually 150 grams, not 100.")
    offer(client, "food_log_correct")

    async def _must_not_run(*a, **kw):
        raise AssertionError("no tool was called on this turn, by construction")

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _must_not_run)

    final = await finalize(
        client, "Got it — 150g, not 100. That's 248 calories and 46.5g protein.")
    assert "248" not in final, "the new value must not be stated as if stored"
    assert "not done" in final.lower()
    assert "150g, not 100" not in final
    assert "nothing was written" in final.lower() or "didn't change" in final.lower()


@pytest.mark.asyncio
async def test_a_requested_change_that_did_run_keeps_its_words(monkeypatch):
    client = make_client("That was actually 150 grams, not 100.")
    offer(client, "food_log_correct")

    async def _ok(name, user_id, parameters, context=None):
        return ToolResult(success=True, message="Fixed that entry: amount (x1.5).",
                          data={"log_id": "f1"})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)
    await client.execute_tool(
        call("food_log_correct", {"log_id": "f1", "scale_by": 1.5}),
        user_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()),
    )
    reply = "Got it — 150g, not 100. That's 248 calories and 46.5g protein."
    assert await finalize(client, reply) == reply


@pytest.mark.asyncio
async def test_an_ordinary_conversational_turn_is_never_subjected_to_this(monkeypatch):
    client = make_client("breakfast food tastes better at night, right?")
    offer(client, "notes_search")
    reply = "It does. Something about eating eggs when the world has stopped asking things of you."
    assert await finalize(client, reply) == reply


@pytest.mark.asyncio
async def test_a_question_is_never_subjected_to_this(monkeypatch):
    client = make_client("What time is the vet one set for?")
    offer(client, "reminders_list")
    reply = "5pm on Thursday, October 1st."
    assert await finalize(client, reply) == reply


@pytest.mark.asyncio
async def test_an_unwritten_instruction_keeps_the_reply_and_adds_the_truth(monkeypatch):
    """Found live: "Add a reminder to water the plants tonight at 8." produced
    no tool call at all, and stripping every sentence with a digit in it left
    "I didn't change anything — nothing was written." as Sara's ENTIRE answer.
    An honest correction should be added to the reply, not replace it."""
    client = make_client("Add a reminder to water the plants tonight at 8.")
    offer(client, "reminders_create")

    reply = "Set for 8:00 PM. You've got about eight minutes."
    final = await finalize(client, reply)
    assert "eight minutes" in final, "the conversational half must survive"
    assert "not done" in final.lower()
    assert "Set for 8:00 PM" not in final, "the action claim still goes"


@pytest.mark.asyncio
async def test_the_scoped_note_names_only_this_request(monkeypatch):
    """A bare "I didn't change anything" made the model answer the NEXT turn
    with "I have to own that last 'Done.' ... That 'Done' was wrong of me" about
    a write that had really happened."""
    client = make_client("That was actually 150 grams, not 100.")
    offer(client, "food_log_correct")
    final = await finalize(client, "Got it — 150g. That's 248 calories.")
    assert "that last change specifically" in final.lower()
    assert "stand as they were" in final.lower()


@pytest.mark.asyncio
async def test_an_elliptical_turn_is_not_force_grounded(monkeypatch):
    """An elliptical follow-up carries no operation words of its own, so
    `turn_requests_a_mutation` is False for it and this check does not fire.
    Stated as a limitation rather than left as a surprise: if the model fails to
    act on "And one for the dentist at 9am", the reply is not corrected by this
    layer."""
    client = make_client("And one for the dentist on October 2nd at 9am.")
    offer(client, "reminders_create")
    assert await finalize(client, "Sure thing.") == "Sure thing."


# ---------------------------------------------------------------------------
# The readback reads the ROW, through the real turn (gap 2, 2026-09-29)
# ---------------------------------------------------------------------------


def _make_reminder(user_id, title, when, completed=False):
    """A real row in the real database, so the readback has something to read."""
    from app.db.session import get_db
    from app.models.reminder import Reminder

    gen = get_db()
    db = next(gen)
    try:
        row = Reminder(
            user_id=user_id, title=title, reminder_time=when,
            is_completed=completed,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)
    finally:
        db.close()


def _ensure_user():
    from app.db.session import get_db
    from app.models.user import User

    gen = get_db()
    db = next(gen)
    try:
        u = User(
            email=f"readback-{uuid.uuid4().hex[:8]}@test.invalid",
            password_hash="x",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return str(u.id)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_appended_state_is_read_from_the_row_not_the_tool_result(monkeypatch):
    """The tool says one thing; the row says another. David gets the row.

    This is the whole point of gap 2. A tool's return value is a report about a
    write from the code that performed it; the row is the fact. Here the tool
    reports the OLD time and the row holds the NEW one, and what reaches David
    has to be the row's.
    """
    from datetime import datetime, timedelta

    user_id = _ensure_user()
    when = datetime.utcnow().replace(microsecond=0) + timedelta(days=1)
    row_id = _make_reminder(user_id, "Call the vet", when)

    client = make_client("Move the vet one to tomorrow")
    offer(client, "reminders_reschedule")

    async def _ok(name, user_id, parameters, context=None):
        # Deliberately WRONG about the time, and silent about the title.
        return ToolResult(success=True, message="rescheduled to 5pm today",
                          data={"id": row_id})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)

    await client.execute_tool(
        call("reminders_reschedule", {"reminder_id": row_id, "new_time": "tomorrow"}),
        user_id=user_id, conversation_id=str(uuid.uuid4()),
    )

    final = await finalize(client, "Okay.", user_id=user_id)
    assert "Call the vet" in final, final
    assert "as of just now" in final, final
    assert "5pm today" not in final, "the tool's own account must not be the readback"


@pytest.mark.asyncio
async def test_another_owners_row_is_never_read_back(monkeypatch):
    """Owner scoping holds at the readback too. A row that is not David's reads
    as unavailable, never as content."""
    from datetime import datetime, timedelta

    owner = _ensure_user()
    someone_else = _ensure_user()
    when = datetime.utcnow().replace(microsecond=0) + timedelta(days=1)
    row_id = _make_reminder(owner, "Their private appointment", when)

    client = make_client("Move that one")
    offer(client, "reminders_reschedule")

    async def _ok(name, user_id, parameters, context=None):
        return ToolResult(success=True, message="done", data={"id": row_id})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)

    await client.execute_tool(
        call("reminders_reschedule", {"reminder_id": row_id, "new_time": "tomorrow"}),
        user_id=someone_else, conversation_id=str(uuid.uuid4()),
    )

    final = await finalize(client, "Okay.", user_id=someone_else)
    assert "Their private appointment" not in final, final


# ---------------------------------------------------------------------------
# Bounded recovery, through the real turn (gap 3, 2026-09-29)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_explicit_request_with_no_tool_call_is_recovered(monkeypatch):
    """The acceptance trial's exact failure, end to end.

    "Scratch the vet one, I already called them." produced no call and the reply
    was a non sequitur. The recovered call goes through `execute_tool`, so the
    contract authorizes it and the receipt records it, and grounding then
    reports the outcome instead of a denial.
    """
    from datetime import datetime, timedelta

    user_id = _ensure_user()
    row_id = _make_reminder(
        user_id, "Call the vet",
        datetime.utcnow().replace(microsecond=0) + timedelta(days=1))

    client = make_client("Scratch the vet one, I already called them.")
    offer(client, "reminders_cancel")
    client._turn_recovery_attempted = False
    client._turn_conversation_id = str(uuid.uuid4())

    executed = []

    async def _ok(name, user_id, parameters, context=None):
        executed.append((name, dict(parameters)))
        return ToolResult(success=True, message="Cancelled", data={"id": row_id})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)

    # The model calls NOTHING this turn. That is the whole premise.
    final = await finalize(client, "Hey! How's your morning going?", user_id=user_id)

    assert executed, "the request was never recovered"
    assert executed[0][0] == "reminders_cancel"
    assert executed[0][1]["reminder_id"] == row_id
    assert "didn't" not in final.lower() and "nothing was written" not in final.lower()


@pytest.mark.asyncio
async def test_recovery_runs_at_most_once_per_turn(monkeypatch):
    from datetime import datetime, timedelta

    user_id = _ensure_user()
    _make_reminder(user_id, "Call the vet",
                   datetime.utcnow().replace(microsecond=0) + timedelta(days=1))

    client = make_client("Scratch the vet one.")
    offer(client, "reminders_cancel")
    client._turn_recovery_attempted = False
    client._turn_conversation_id = str(uuid.uuid4())

    calls = []

    async def _ok(name, user_id, parameters, context=None):
        calls.append(name)
        return ToolResult(success=True, message="Cancelled", data={"id": "r"})

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _ok)

    await finalize(client, "Hey!", user_id=user_id)
    await finalize(client, "Hey again!", user_id=user_id)
    assert len(calls) == 1, calls


@pytest.mark.asyncio
async def test_a_turn_that_did_call_something_is_not_recovered(monkeypatch):
    """Recovery exists for the turn that made NO call. A turn whose call failed
    is a different situation, and re-running it behind the model's back would be
    a second write attempt David never saw the first outcome of."""
    from datetime import datetime, timedelta

    user_id = _ensure_user()
    row_id = _make_reminder(
        user_id, "Call the vet",
        datetime.utcnow().replace(microsecond=0) + timedelta(days=1))

    client = make_client("Scratch the vet one.")
    offer(client, "reminders_cancel")
    client._turn_recovery_attempted = False
    client._turn_conversation_id = str(uuid.uuid4())

    calls = []

    async def _fails(name, user_id, parameters, context=None):
        calls.append(name)
        return ToolResult(success=False, message="database is locked", data=None)

    monkeypatch.setattr(ms.tool_registry, "execute_tool", _fails)

    await client.execute_tool(
        call("reminders_cancel", {"reminder_id": row_id}),
        user_id=user_id, conversation_id=str(uuid.uuid4()),
    )
    final = await finalize(client, "Done — cancelled.", user_id=user_id)

    assert len(calls) == 1, "the failed write must not be silently retried"
    assert "failed" in final.lower()
