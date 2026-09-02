"""Ground-truth follow-up (2026-09-02, afternoon).

The eight-phase ground-truth plan shipped in the morning. Verifying it live
against the running containers turned up seven residual gaps, all of the same
family: a rule was written down but one caller didn't read it, or the code was
right and the deployment never gave it anything to read.

  1. `/docs` was never mounted, so `get_self_knowledge` had returned an error
     for every call ever made in Docker and the nightly self-model regeneration
     wrote to nothing.
  2. `resolve_predicate` existed and the expectations slice didn't use it, so
     "leave ~6:24" still rendered a line below "leaves for work 7am".
  3. theory_of_david still said "lunch at 2 AM" — a time from a life_fact that
     had already been deleted, surviving because the document is its own input.
  4. The nightly truth-maintenance report rendered as Sara's inner monologue in
     every chat turn.
  5. An all-day trip to Salem was announced as a meeting at 12:00 AM.
  6. The Salem guide finished, was written to Agent Workspace, and David was
     never told, because compose declined the candidate.
  7. Zero background token rows: the usage callback was registered in
     `main_simple.startup_event`, which Celery never runs.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

import yaml


REPO = pathlib.Path(__file__).resolve().parents[2]


# ── 1. self-knowledge is actually reachable ────────────────────────────────

class TestSelfModelDocsAreMounted:
    @pytest.mark.parametrize("compose_name", ["docker-compose.dev.yml", "docker-compose.yml"])
    def test_docs_are_mounted_into_the_services_that_read_and_write_them(self, compose_name):
        compose_path = REPO / compose_name
        if not compose_path.exists():
            pytest.skip("compose file not mounted in this environment")

        compose = yaml.safe_load(compose_path.read_text())
        for service in ("backend", "celery-worker", "celery-beat"):
            volumes = compose["services"][service].get("volumes") or []
            assert any(str(v).startswith("./docs:/docs") for v in volumes), (
                f"{service} in {compose_name} cannot see /docs — self-knowledge "
                f"returns an error and the nightly regeneration writes nothing"
            )

    def test_the_mount_is_writable(self):
        """The truth job rewrites two of these docs; `:ro` would fail silently."""
        compose_path = REPO / "docker-compose.dev.yml"
        if not compose_path.exists():
            pytest.skip("compose file not mounted in this environment")
        compose = yaml.safe_load(compose_path.read_text())
        for service in ("backend", "celery-worker", "celery-beat"):
            for volume in compose["services"][service].get("volumes") or []:
                if str(volume).startswith("./docs:/docs"):
                    assert not str(volume).endswith(":ro")

    def test_the_wiring_check_notices_when_the_directory_is_gone(self):
        from app.tasks.system_wiring_check import _check_self_model_docs

        problems = _check_self_model_docs()
        assert isinstance(problems, list)

    def test_a_missing_directory_is_reported_not_swallowed(self, monkeypatch):
        import app.tools.self_knowledge as self_knowledge

        monkeypatch.setattr(self_knowledge, "SELF_MODEL_DIR", pathlib.Path("/nope/not/here"))
        from app.tasks.system_wiring_check import _check_self_model_docs

        problems = _check_self_model_docs()
        assert len(problems) == 1
        assert "does not exist" in problems[0]

    def test_the_check_is_part_of_the_weekly_run(self):
        import inspect
        from app.tasks import system_wiring_check

        source = inspect.getsource(system_wiring_check.run_check)
        assert "_check_self_model_docs()" in source
        assert "self_model_gaps" in source


# ── 2. one departure time ──────────────────────────────────────────────────

class _RhythmRow(SimpleNamespace):
    pass


class _FakeDB:
    """Just enough Session to drive build_rhythm_summary."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, statement, params=None):
        return SimpleNamespace(fetchall=lambda: self._rows)


def _rhythm(key, hhmm, confidence=0.9, samples=30):
    hour, minute = (int(p) for p in hhmm.split(":"))
    return _RhythmRow(
        rhythm_key=key, median_time=time(hour, minute), confidence=confidence,
        sample_count=samples, window_start=None, window_end=None,
    )


class TestRhythmDoesNotArgueWithAStatedFact:
    def test_a_stated_fact_suppresses_the_learned_median(self):
        """David said 07:00. The 06:24 median is an inference about a question
        he has already answered in words, and printing both is what put three
        departure times in one prompt."""
        from app.services.daily_rhythm import build_rhythm_summary

        db = _FakeDB([_rhythm("leave_home", "06:24"), _rhythm("bedtime", "21:00")])

        with_fact = build_rhythm_summary(db, "u1", on_date=date(2026, 9, 2),
                                         exclude_keys={"leave_home"})
        assert "leave" not in with_fact
        assert "bed ~21:00" in with_fact

    def test_without_a_stated_fact_the_rhythm_still_speaks(self):
        from app.services.daily_rhythm import build_rhythm_summary

        db = _FakeDB([_rhythm("leave_home", "06:24")])
        assert "leave ~6:24" in build_rhythm_summary(db, "u1", on_date=date(2026, 9, 2))

    def test_a_weak_row_says_nothing_at_all(self):
        """The live row was 8 samples at 0.48 confidence. It cleared the old
        0.4 summary bar and failed life_facts' bar — two thresholds, one
        question, which is how it got stated as fact."""
        from app.services.daily_rhythm import build_rhythm_summary

        db = _FakeDB([_rhythm("leave_home", "06:24", confidence=0.48, samples=8)])
        assert build_rhythm_summary(db, "u1", on_date=date(2026, 9, 2)) is None

    def test_too_few_samples_says_nothing_either(self):
        from app.services.daily_rhythm import build_rhythm_summary

        db = _FakeDB([_rhythm("leave_home", "06:24", confidence=0.95, samples=4)])
        assert build_rhythm_summary(db, "u1", on_date=date(2026, 9, 2)) is None

    def test_the_bar_is_life_facts_bar(self):
        """One threshold for 'good enough to say out loud', not one per caller."""
        import inspect
        from app.services import daily_rhythm

        source = inspect.getsource(daily_rhythm.build_rhythm_summary)
        assert "RHYTHM_MIN_CONFIDENCE" in source
        assert "RHYTHM_MIN_SAMPLES" in source
        assert not hasattr(daily_rhythm, "_MIN_CONFIDENCE_FOR_SUMMARY")

    @pytest.mark.asyncio
    async def test_stated_keys_come_back_for_stated_facts_only(self, monkeypatch):
        from app.services import daily_rhythm

        async def _resolve(user_id, predicate):
            if predicate == "departs_for_work_at":
                return {"value": "07:00", "source": "stated", "confidence": 0.95}
            if predicate == "bedtime_at":
                return {"value": "21:00", "source": "rhythm", "confidence": 0.8}
            return None

        monkeypatch.setattr("app.services.life_facts.resolve_predicate", _resolve)
        assert await daily_rhythm.stated_rhythm_keys("u1") == {"leave_home"}

    def test_both_renderers_filter(self):
        """Chat context and the deliberation whiteboard read the same line."""
        for path in ("app/services/context_snapshot.py", "app/services/context_writer.py"):
            source = pathlib.Path(path).read_text()
            assert "stated_rhythm_keys" in source, f"{path} renders an unfiltered rhythm line"


# ── 3. theory_of_david states no clock times ───────────────────────────────

class TestTheoryOfDavidStatesNoTimes:
    def test_clock_times_are_found_in_every_shape_the_model_writes_them(self):
        from app.services.sara_journal_service import _clock_minutes

        assert 7 * 60 in _clock_minutes("leaves for work 7am")
        assert 7 * 60 in _clock_minutes("leaves at 7:00 AM")
        assert 14 * 60 in _clock_minutes("lunch at 2 PM")
        assert 14 * 60 in _clock_minutes("lunch at 14:00")

    def test_an_unqualified_time_is_read_both_ways(self):
        """'7:00' could be either; we do not resolve the ambiguity in the
        document's favour."""
        from app.services.sara_journal_service import _clock_minutes

        minutes = _clock_minutes("around 7:00")
        assert 7 * 60 in minutes and 19 * 60 in minutes

    def test_a_bare_number_is_not_a_time(self):
        from app.services.sara_journal_service import _clock_minutes

        assert _clock_minutes("he has 3 open threads and 12 emails") == set()

    def test_a_restated_routine_time_is_caught(self):
        from app.services.sara_journal_service import _clock_minutes

        facts = _clock_minutes("David normally: leaves for work 7:00, lunch 12:30")
        draft = "He is out the door by 7am most days and gets sharper after."
        assert _clock_minutes(draft) & facts

    def test_a_time_free_paragraph_passes(self):
        from app.services.sara_journal_service import _clock_minutes

        facts = _clock_minutes("David normally: leaves for work 7:00")
        draft = "He front-loads the day and gets terse when a deploy is pending."
        assert not (_clock_minutes(draft) & facts)

    def test_the_check_runs_and_refuses_to_store(self):
        import inspect
        from app.services.sara_journal_service import SaraJournalService

        source = inspect.getsource(SaraJournalService.write_theory_of_david)
        assert "banned_minutes" in source
        # One corrective retry, then nothing is stored — a stored contradiction
        # is permanent, because this document is its own next input.
        assert source.index("_generate_entry") < source.index("_store_entry")
        assert "return None" in source


class TestOpenArcsAreObligations:
    def test_arcs_come_from_world_thread_on_an_allowlist(self):
        """A blacklist admits every kind nobody thought of. `interest` and
        `active_conversation` rows read as obligations once narrated."""
        import inspect
        from app.services.sara_journal_service import SaraJournalService

        source = inspect.getsource(SaraJournalService.write_theory_of_david)
        assert "world_thread" in source
        assert "'commitment', 'follow_up', 'support_ticket'" in source
        assert "get_intent_graph" not in source

    def test_the_allowlist_covers_the_hyphen_drift(self):
        """The interpreter writes both `follow_up` and `follow-up`; the live
        table holds 16 of one and 5 of the other."""
        import inspect
        from app.services.sara_journal_service import SaraJournalService

        source = inspect.getsource(SaraJournalService.write_theory_of_david)
        assert "REPLACE(kind, '-', '_')" in source

    def test_self_story_excludes_the_machines_own_reports(self):
        from app.services.sara_journal_service import SELF_STORY_EXCLUDED_TYPES

        assert {"deliberation", "truth_maintenance", "self_audit"} <= SELF_STORY_EXCLUDED_TYPES


# ── 4. the audit report is not her inner monologue ─────────────────────────

class TestJournalAllowlist:
    def test_reports_are_not_thoughts(self):
        from app.services.sara_journal_service import CHAT_CONTEXT_ENTRY_TYPES

        for report in ("truth_maintenance", "self_audit", "weekly_review",
                       "self_story", "theory_of_david"):
            assert report not in CHAT_CONTEXT_ENTRY_TYPES

    def test_real_reflections_still_render(self):
        from app.services.sara_journal_service import CHAT_CONTEXT_ENTRY_TYPES

        for kind in ("deliberation", "consolidation", "conversation_close",
                     "periodic", "unified", "dream", "curiosity"):
            assert kind in CHAT_CONTEXT_ENTRY_TYPES

    @pytest.mark.asyncio
    async def test_the_chat_feed_asks_for_the_allowlist(self, monkeypatch):
        from app.services import sara_journal_service as svc

        captured = {}

        async def _fake(self, db, user_id, hours=8, limit=10, entry_types=None):
            captured["entry_types"] = entry_types
            return []

        monkeypatch.setattr(svc.SaraJournalService, "get_recent_entries", _fake)
        await svc.sara_journal.get_entries_for_conversation_context(db=None, user_id="u1")
        assert captured["entry_types"] == svc.CHAT_CONTEXT_ENTRY_TYPES

    def test_the_filter_is_an_allowlist_not_a_blacklist(self):
        """New entry types get added by whoever needs a new nightly job; the
        default must be 'not her inner monologue'."""
        import inspect
        from app.services.sara_journal_service import SaraJournalService

        source = inspect.getsource(SaraJournalService.get_recent_entries)
        assert "entry_type = ANY(:entry_types)" in source
        assert "NOT IN" not in source


# ── 5. an all-day event has no clock ───────────────────────────────────────

class TestAllDayEventsAreNotMidnightMeetings:
    def test_render_when_gives_a_date_not_a_time(self):
        from app.core.timezone import render_when

        rendered = render_when(datetime(2026, 9, 3, 0, 0), source_convention="et", all_day=True)
        assert rendered == "Thu Sep 3 (all day)"
        assert "12:00 AM" not in rendered

    def test_the_expectations_slice_skips_all_day_when_picking_a_meeting(self):
        source = pathlib.Path("app/services/context_snapshot.py").read_text()
        assert "COALESCE(all_day, FALSE) AS all_day" in source
        assert "next((r for r in upcoming_rows if not r.all_day), None)" in source

    def test_an_all_day_event_is_still_reported_without_a_time(self):
        source = pathlib.Path("app/services/context_snapshot.py").read_text()
        assert 'exp_data["next_event"]' in source
        assert "all_day=True" in source

    def test_the_whiteboard_does_not_count_minutes_to_an_all_day_event(self):
        source = pathlib.Path("app/services/context_writer.py").read_text()
        assert "snapshot.next_event_minutes_away = None" in source

    def test_the_derived_refresher_obeys_the_same_rule(self):
        """It writes the same working-memory field, so whichever ran last used
        to win."""
        source = pathlib.Path("app/services/memory_subscribers.py").read_text()
        assert "None if row.all_day else max(0, minutes_away)" in source

    def test_the_deliberation_prompt_never_says_in_none_min(self):
        source = pathlib.Path("app/services/deliberation_prompt.py").read_text()
        assert "if memory.next_event_minutes_away is None:" in source


# ── 6. a finished request is always announced ──────────────────────────────

def _research_candidate(**overrides):
    candidate = {
        "id": "cand-1", "kind": "alert", "source": "research_executor",
        "summary": "A very long report body about Salem…",
        "evidence": [{"note_id": "n1", "plan_id": "026cb418",
                      "origin": "david_chat", "title": "Salem travel guide"}],
        "judge_reason": "David asked for this",
    }
    candidate.update(overrides)
    return candidate


class TestDavidRequestedResultsAreAnnounced:
    def test_a_david_chat_result_is_recognised(self):
        from app.services.judge import is_david_requested

        assert is_david_requested(_research_candidate()) is True

    def test_an_unprompted_candidate_is_not(self):
        from app.services.judge import is_david_requested

        assert is_david_requested(
            {"source": "deliberation", "kind": "inform", "evidence": []}) is False

    def test_the_batching_guard_still_uses_the_same_test(self):
        from app.services.judge import _is_david_chat_result

        assert _is_david_chat_result([_research_candidate()], "cand-1") is True

    def test_the_fallback_names_the_report(self):
        from app.services.compose import fallback_utterance

        text = fallback_utterance(_research_candidate())["text"]
        assert text == "Your Salem travel guide report is ready in Agent Workspace."

    def test_the_fallback_survives_a_missing_title(self):
        from app.services.compose import fallback_utterance

        candidate = _research_candidate(evidence=[{"origin": "david_chat"}])
        assert "report is ready in Agent Workspace" in fallback_utterance(candidate)["text"]
        assert "None" not in fallback_utterance(candidate)["text"]

    def test_compose_falls_back_rather_than_declining(self):
        import inspect
        from app.tasks import compose as compose_task

        source = inspect.getsource(compose_task._run_async)
        assert "david_waiting = is_david_requested(candidate)" in source
        assert "composed = fallback_utterance(candidate)" in source

    def test_a_review_kill_also_falls_back(self):
        """Review and the hedging linter judge the prose. The plain
        announcement has no prose to object to, and the Salem guide was
        finished, filed, and never mentioned."""
        import inspect
        from app.tasks import compose as compose_task

        source = inspect.getsource(compose_task._run_async)
        assert "if final_text is None and david_waiting:" in source

    def test_the_kill_verdict_is_still_recorded_honestly(self):
        """Falling back changes what David hears, not what the ledger says."""
        import inspect
        from app.tasks import compose as compose_task

        source = inspect.getsource(compose_task._run_async)
        fallback_at = source.index("if final_text is None and david_waiting:")
        insert_at = source.index("INSERT INTO composed_utterance", fallback_at)
        assert '"verdict": review["verdict"]' in source[insert_at:]

    def test_delivery_selects_on_final_text_not_just_the_verdict(self):
        """Found while verifying this live: compose fell back correctly, the row
        was written with the right text, and delivery skipped it because it
        selected `review_verdict IN ('approve','edit')`. The Salem failure one
        step further down the pipe."""
        source = pathlib.Path("app/tasks/mindv2_deliver.py").read_text()
        assert "OR cu.final_text IS NOT NULL" in source

    def test_the_delivery_widening_is_additive(self):
        """Everything the old query selected must still be selected — an `edit`
        verdict whose edited_text came back empty still delivers the composed
        text, exactly as before."""
        source = pathlib.Path("app/tasks/mindv2_deliver.py").read_text()
        assert "cu.review_verdict IN ('approve', 'edit') OR" in source

    def test_the_candidate_carries_a_title_for_the_fallback(self):
        source = pathlib.Path("app/services/research/executor.py").read_text()
        assert '"title": plan.get("title")' in source


# ── 7. background model calls are attributed ───────────────────────────────

class TestBackgroundTokenAccounting:
    def test_the_worker_wires_a_callback_on_fork(self):
        from celery.signals import worker_process_init

        import app.celery_signals  # noqa: F401  (registers on import)

        names = {getattr(r, "__name__", "") for r in worker_process_init._live_receivers(None)}
        assert "_wire_token_accounting" in names

    def test_the_worker_uses_the_synchronous_writer(self):
        """A prefork child has no long-lived event loop, so an asyncio queue
        would be drained by a worker task that dies with the first task's
        loop — every background call reporting into a void."""
        import inspect
        from app import celery_signals

        source = inspect.getsource(celery_signals._wire_token_accounting)
        body = source[source.index("try:"):]
        assert "record_token_usage_sync" in body
        assert "queue_token_usage" not in body

    def test_wiring_it_actually_registers(self, monkeypatch):
        import app.celery_signals as celery_signals
        import app.core.llm as llm

        original = llm.get_token_usage_callback()
        try:
            celery_signals._wire_token_accounting()
            from app.services.token_usage_service import record_token_usage_sync

            assert llm.get_token_usage_callback() is record_token_usage_sync
        finally:
            llm.set_token_usage_callback(original)

    def test_both_model_tiers_report(self):
        """The fast tier and the bg-lane fallback are separate success paths;
        attributing only one leaves a hole exactly where the fallback lives."""
        source = pathlib.Path("app/core/llm.py").read_text()
        assert source.count("_record_background_usage(result, caller, use_model)") == 2

    def test_the_callback_signature_matches_what_llm_calls_with(self):
        import inspect
        from app.core.llm import _record_background_usage
        from app.services.token_usage_service import record_token_usage_sync

        called_with = set(re.findall(r"(\w+)=", inspect.getsource(_record_background_usage)))
        accepted = set(inspect.signature(record_token_usage_sync).parameters)
        assert {"prompt_tokens", "completion_tokens", "total_tokens",
                "model", "operation_type"} <= accepted
        assert {"prompt_tokens", "completion_tokens", "total_tokens",
                "model", "operation_type"} <= called_with

    def test_the_aggregate_update_is_shared_not_duplicated(self):
        from app.services.token_usage_service import _apply_aggregate, update_aggregate

        assert callable(_apply_aggregate)
        assert callable(update_aggregate)
