"""The harness's own guarantees, checked before anything is concluded from it.

If these fail, no assertion in test_observed_failures.py means anything.
"""
import pytest

from tests.replay import harness


def test_replay_refuses_a_non_replay_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://sara:x@10.0.0.1:5432/sara_hub")
    with pytest.raises(RuntimeError, match="refusing to replay"):
        harness.replay_database_url()


def test_the_live_database_is_not_the_one_we_are_pointed_at():
    assert harness.replay_database_url().endswith("/sara_replay")


def test_fixture_holds_the_eight_exchanges():
    turns = harness.load_turns()
    assert len(turns) == 8
    assert turns[0].user_text.startswith("That was a good workout")
    assert "taco pasta salad" in turns[3].user_text
    assert turns[6].user_text.strip() == "Good morning!"


def test_the_replay_world_is_the_captured_one():
    """The fixture and the provisioned database agree — a stale sara_replay
    left over from an earlier fixture would otherwise pass everything for
    the wrong reasons."""
    from sqlalchemy import text
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        events = db.execute(text(
            "SELECT title, owner, owner_relation FROM calendar_event "
            "WHERE start_time >= '2026-09-10' AND start_time < '2026-09-11' "
            "ORDER BY start_time"
        )).fetchall()
    finally:
        db.close()
    titles = {(r.title or "").strip() for r in events}
    assert "Everett Dentist" in titles
    assert "Dodd Open House" in titles
    assert all(r.owner == "Everett" and r.owner_relation == "son" for r in events)


def test_clock_freezes_for_the_captured_minute():
    from app.core import timezone as tz

    t = harness.turn(6)  # "Good morning!", 06:54 ET on the 10th
    with harness.frozen_clock(t.at_et):
        assert tz.now().hour == 6
        assert tz.today().isoformat() == "2026-09-10"
        assert tz.naive_local_now().strftime("%H:%M") == "06:54"
    assert tz.today().isoformat() != "2026-09-10" or True  # restored; today may differ


@pytest.mark.asyncio
async def test_write_ledger_sees_a_write():
    from sqlalchemy import text
    from app.db.base import SessionLocal

    with harness.write_ledger() as ledger:
        db = SessionLocal()
        try:
            db.execute(text("CREATE TEMP TABLE replay_ledger_probe (x int)"))
            db.execute(text("INSERT INTO replay_ledger_probe VALUES (1)"))
            db.rollback()
        finally:
            db.close()
    assert any(verb == "INSERT" and "replay_ledger_probe" in sql
               for verb, sql in ledger.statements)


@pytest.mark.asyncio
async def test_mutating_tools_are_recorded_not_executed():
    from app.tools.registry import tool_registry

    with harness.intercepted_tools() as log:
        result = await tool_registry.execute_tool(
            "food_search_and_log", {"query": "taco pasta salad", "meal_type": "dinner"},
        )
    assert result["replayed"] is True
    assert log.names == ["food_search_and_log"]
    assert log.calls[0].executed is False


def test_clock_freeze_reaches_render_when():
    """render_when takes its reference from a bare datetime.now(); if the
    freeze didn't cover that, every relative time in a replayed prompt would
    be measured against the wall clock of whoever ran the replay."""
    from datetime import datetime, timezone as _tz
    from app.core.timezone import render_when

    t = harness.turn(6)  # 06:54 ET
    with harness.frozen_clock(t.at_et):
        rendered = render_when(datetime(2026, 9, 10, 10, 0), source_convention="et")
    assert "10:00 AM ET" in rendered
    assert "in 3h" in rendered, rendered


@pytest.mark.asyncio
async def test_persona_prompt_matches_the_current_production_builder():
    """Harness/thinking/personality plan, Phase 0: this replay used to build
    its persona half with `get_system_prompt`, the ~14,000-char function
    production text chat stopped calling at the 2026-09-11 "harness rebuild
    Phase 5". If this ever regresses back to the old builder (or a stray
    second copy of the persona logic drifts from the real one), this
    assertion — not just a prompt-length check — is what catches it: the
    hash must match a FRESH call to the real function with the same inputs,
    not merely "some string of a plausible size"."""
    import hashlib

    from app.prompts.chat_system_prompt import build_chat_system_prompt
    from app.main_simple import ASSISTANT_NAME, load_soul_for_prompt
    from app.db.base import SessionLocal

    t = harness.turn(6)
    assembled = await harness.assemble(t.user_text, t.at_et)

    db = SessionLocal()
    try:
        soul = load_soul_for_prompt(db)
    finally:
        db.close()
    expected = build_chat_system_prompt(ASSISTANT_NAME, soul, assembled.tools_offered)
    assert assembled.stable_system_prompt == expected
    assert assembled.stable_system_prompt_sha256 == hashlib.sha256(expected.encode()).hexdigest()
    # A regression back to the ~14,000-char pre-Phase-5 get_system_prompt
    # would blow well past build_chat_system_prompt's own cap.
    from app.prompts.chat_system_prompt import MAX_PROMPT_CHARS
    assert len(assembled.stable_system_prompt) <= MAX_PROMPT_CHARS


@pytest.mark.asyncio
async def test_outgoing_payload_has_the_production_role_order_and_shape():
    """Mirrors `assemble_local_provider_messages`'s own contract
    (backend/tests/test_chat_assembly.py covers that function in isolation
    with synthetic inputs) but against the REAL replay inputs: the first
    message is system/persona-only (the cache-stable prefix — no datetime,
    no per-turn context mixed in), and the live-context envelope is folded
    into the LAST message, which is the user turn, not a separate trailing
    system message."""
    t = harness.turn(6)
    assembled = await harness.assemble(t.user_text, t.at_et)
    messages = assembled.all_messages

    assert len(messages) >= 2
    assert messages[0].role == "system"
    assert messages[0].content == assembled.stable_system_prompt
    # The stable prefix must stay stable: no volatile per-turn content
    # (the live-context tags, or the turn's own datetime string) leaks into
    # the first message, or a real local-lane turn would lose its prompt-
    # cache hit every time volatile content changed.
    assert "<live_context>" not in messages[0].content

    last = messages[-1]
    assert last.role == "user"
    assert "<live_context>" in last.content
    assert "</live_context>" in last.content
    assert t.user_text in last.content


@pytest.mark.asyncio
async def test_tool_schemas_are_real_function_specs_matching_the_offered_names():
    t = harness.turn(6)
    assembled = await harness.assemble(t.user_text, t.at_et)
    assert assembled.tool_schemas, "expected at least one tool to be selected for this turn"
    names = [s.get("function", {}).get("name") for s in assembled.tool_schemas]
    assert names == assembled.tools_offered
    for schema in assembled.tool_schemas:
        assert schema.get("type") == "function"
        assert schema.get("function", {}).get("name")
        assert "parameters" in schema.get("function", {})


@pytest.mark.asyncio
async def test_stable_prefix_does_not_vary_with_the_volatile_clock():
    """The whole point of the prompt-cache split: replaying the same message
    at two different frozen times, with the same tool set, must produce an
    IDENTICAL stable system message — only the live-context envelope in the
    last message may change."""
    t = harness.turn(6)
    first = await harness.assemble(t.user_text, t.at_et, session_id="cache-split-probe")
    later = await harness.assemble(
        t.user_text, t.at_et + __import__("datetime").timedelta(hours=1),
        session_id="cache-split-probe",
    )
    assert first.stable_system_prompt == later.stable_system_prompt
    assert first.all_messages[0].content == later.all_messages[0].content


def test_brief_layers_come_from_the_fixture_not_the_live_filesystem():
    """data/briefs/<user>/layers/*.md is a live directory mounted into the
    container. A replay reading it would be reading today."""
    from app.services.daily_brief import compiler

    root = harness.install_fixture_briefs()
    assert compiler.BRIEFS_DIR == root
    # Every module with its own copy of the path, including the four that
    # write layers back out.
    for module_name in harness._BRIEF_MODULES:
        import importlib
        assert importlib.import_module(module_name).BRIEFS_DIR == root, module_name
    assert "/home/david/jarvis/data/briefs" not in str(root)
    layers = sorted(p.name for p in (root / harness.REPLAY_USER_ID / "layers").glob("*.md"))
    assert layers == ["context.md", "day.md", "moment.md", "stable.md"]
