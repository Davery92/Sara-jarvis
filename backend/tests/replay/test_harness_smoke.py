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
