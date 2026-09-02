"""Ground-truth Phase 7: the nightly job that keeps the invariants true.

Every other phase stops a class of untruth being created. This one cleans up what
rots anyway and audits what goes stale silently — the things that, before, were
only ever caught by another manual audit weeks later.
"""
from __future__ import annotations

import pathlib

from app.tasks import truth_maintenance as tm


class TestItIsDeterministic:
    def test_no_model_call_anywhere_in_the_job(self):
        """A job whose purpose is deciding what is still true must not be able
        to invent anything."""
        source = pathlib.Path("app/tasks/truth_maintenance.py").read_text()
        for forbidden in ("chat_completion", "llm_client", "get_background_llm_client"):
            assert forbidden not in source, f"{forbidden} has no business in this job"


class TestLifeFactSanity:
    def test_the_windows_match_the_plan(self):
        assert tm.LIFE_FACT_SANE_WINDOWS["lunch_at"] == ("11:00", "15:00")
        assert tm.LIFE_FACT_SANE_WINDOWS["wakes_at"] == ("04:00", "09:00")
        assert tm.LIFE_FACT_SANE_WINDOWS["departs_for_work_at"] == ("05:30", "09:30")
        assert tm.LIFE_FACT_SANE_WINDOWS["bedtime_at"] == ("20:00", "24:00")

    def test_a_two_am_lunch_is_outside_its_window(self):
        low, high = tm.LIFE_FACT_SANE_WINDOWS["lunch_at"]
        assert not (tm._minutes(low) <= tm._minutes("02:00") <= tm._minutes(high))

    def test_a_real_lunch_is_inside_it(self):
        low, high = tm.LIFE_FACT_SANE_WINDOWS["lunch_at"]
        assert tm._minutes(low) <= tm._minutes("12:30") <= tm._minutes(high)

    def test_flagged_facts_are_defanged_not_deleted(self):
        source = pathlib.Path("app/tasks/truth_maintenance.py").read_text()
        assert "SET confidence = 0.2" in source
        assert "DELETE FROM life_fact" not in source


class TestExpiryWindows:
    def test_they_match_the_inline_sweep(self):
        """The nightly job and the 1-minute temporal sweep must not drift."""
        from app.services.world_state import temporal

        assert tm.DUE_THREAD_GRACE_HOURS == temporal.DUE_THREAD_GRACE.total_seconds() / 3600
        assert tm.UNDATED_THREAD_LIFETIME_DAYS == temporal.UNDATED_THREAD_LIFETIME.days


class TestTheGeneratedDocBlock:
    def test_hand_written_prose_around_the_markers_survives(self):
        existing = (
            "# Heading\n\nHand-written intro that must survive.\n\n"
            f"{tm.GENERATED_START}\nold generated\n{tm.GENERATED_END}\n\n"
            "Hand-written outro that must also survive.\n"
        )
        result = tm._splice_generated(existing, "NEW BODY", "Heading")
        assert "Hand-written intro that must survive." in result
        assert "Hand-written outro that must also survive." in result
        assert "NEW BODY" in result
        assert "old generated" not in result

    def test_a_doc_with_no_markers_gets_the_block_appended(self):
        result = tm._splice_generated("# Heading\n\nProse only.\n", "NEW BODY", "Heading")
        assert "Prose only." in result
        assert tm.GENERATED_START in result and "NEW BODY" in result

    def test_the_two_self_model_docs_carry_the_markers(self):
        for rel in ("../docs/sara_self_model_autonomous.md",
                    "../docs/sara_self_model_capabilities.md"):
            path = pathlib.Path(rel)
            if not path.exists():  # not mounted in this container
                continue
            assert tm.GENERATED_START in path.read_text()


class TestTheJournalLineIsHonest:
    def test_a_quiet_night_says_nothing_happened(self):
        """The plan's acceptance row: a gate summary with zero writes must not
        contain a completion verb about cleanup."""
        assert tm.brief_line.__doc__
        # brief_line returns "" when there is nothing — the morning brief then
        # prints no line at all rather than claiming work.
        source = pathlib.Path("app/tasks/truth_maintenance.py").read_text()
        assert 'if not threads and not reminders:\n        return ""' in source

    def test_the_report_records_a_bug_counter_for_leaked_sara_speech(self):
        source = pathlib.Path("app/tasks/truth_maintenance.py").read_text()
        assert "threads_expired_from_sara_speech" in source
        assert "the Phase 1 lock has leaked" in source


class TestItIsScheduled:
    def test_the_task_is_routed_to_maintenance(self):
        source = pathlib.Path("app/celery_app.py").read_text()
        assert '"app.tasks.truth_maintenance"' in source
        assert '"app.tasks.truth_maintenance.*": {"queue": "maintenance"}' in source

    def test_the_migration_seeds_the_job_row(self):
        migration = pathlib.Path(
            "alembic/versions/150_truth_maintenance_report.py"
        ).read_text()
        assert "'truth-maintenance'" in migration
        assert "'50 3 * * *'" in migration       # 03:50 ET
        assert "'America/New_York'" in migration
        assert "'user'" in migration             # visibility
