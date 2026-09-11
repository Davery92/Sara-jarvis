"""The eight exchanges of 2026-09-09/10, replayed against today's code.

Phase 0 of docs/plans/SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md asks
for exactly one thing from this file: for each failure the plan observed,
say whether it still happens — reproduced, fixed, or not reproducible — and
be able to show the evidence rather than assert it.

So each class below names one observed failure and takes one of three
shapes:

* a plain assertion — the failure is FIXED, and this is what now stops it;
* `xfail(strict=True)` — the failure is REPRODUCED and still open. It fails
  today, which is the honest state, and the day someone fixes it this file
  turns red to say so;
* a skip with a reason — NOT REPRODUCIBLE from this fixture, and why.

The model-driven classes are marked `slow` and only run with
SARA_REPLAY_MODEL=1: each one is a real ~2-3 minute call to the chat lane.
They are the only tests here that can answer a question about behaviour
rather than about rendering.
"""
import os
import re

import pytest

from tests.replay import harness

pytestmark = pytest.mark.asyncio

MODEL_TESTS = os.getenv("SARA_REPLAY_MODEL") == "1"
needs_model = pytest.mark.skipif(
    not MODEL_TESTS, reason="set SARA_REPLAY_MODEL=1 to call the live model lane")


async def assembled_for(index: int):
    t = harness.turn(index)
    return t, await harness.assemble(t.user_text, t.at_et)


# ---------------------------------------------------------------------------
# "A morning greeting turned Everett's dentist appointment into David's
#  appointment in Everett."   -> FIXED
# ---------------------------------------------------------------------------

class TestCalendarOwnership:

    async def test_family_events_reach_the_prompt_as_family_events(self):
        _, assembled = await assembled_for(6)  # "Good morning!", Thu 06:54
        calendar = assembled.section("engaged_context")
        dentist = next(line for line in calendar.splitlines() if "Everett Dentist" in line)
        assert "Everett's" in dentist and "not David's" in dentist, dentist
        assert "son" in dentist

    async def test_ownership_is_not_attendance(self):
        """The plan is explicit that these are different questions: his son's
        appointment may still be David's morning."""
        _, assembled = await assembled_for(6)
        assert "ownership and attendance are separate" in assembled.section("engaged_context")

    async def test_the_world_brief_marks_ownership_too(self):
        """Two renderers read the same calendar rows; both had to be fixed,
        because whichever one is silent is the one Sara believes."""
        _, assembled = await assembled_for(6)
        brief = assembled.section("world_brief")
        dentist = [line for line in brief.splitlines() if "Everett Dentist" in line]
        assert dentist, brief
        assert all("not David's" in line for line in dentist), dentist

    async def test_no_location_is_invented_from_the_name(self):
        """Sara said "in Everett". Nothing in the calendar row says where the
        appointment is, and the prompt must not imply it does."""
        _, assembled = await assembled_for(6)
        assert not re.search(r"\bin Everett\b", assembled.text)


# ---------------------------------------------------------------------------
# "One prompt included both unavailable recent HRV and recovery prose using
#  HRV 48."   -> FIXED
# ---------------------------------------------------------------------------

class TestHrvContradiction:

    async def test_missing_hrv_is_reported_as_missing(self):
        _, assembled = await assembled_for(6)
        health = next(line for line in assembled.section("engaged_context").splitlines()
                      if "health_today" in line)
        assert "hrv=unavailable" in health, health

    async def test_no_section_states_an_hrv_number_while_it_is_unavailable(self):
        """The contradiction was across sections — the health slice said
        unavailable while the training block quoted 48 — so the assertion has
        to be over the whole assembled prompt, minus the system prompt's own
        rule text (which names HRV in order to forbid inventing it)."""
        _, assembled = await assembled_for(6)
        body = "\n".join(v for k, v in assembled.sections.items() if k != "system_prompt")
        assert not re.search(r"HRV[^a-z]{0,3}\d", body, re.IGNORECASE), body[:2000]

    async def test_measurements_carry_their_own_timestamp(self):
        _, assembled = await assembled_for(6)
        health = next(line for line in assembled.section("engaged_context").splitlines()
                      if "health_today" in line)
        assert "(measured " in health

    async def test_the_replay_never_shows_a_reading_from_after_the_turn(self):
        """Rewind check with teeth: at 6:54 AM the watch had not yet synced
        the night's sleep (9:28), so no reading may be stamped in the future."""
        _, assembled = await assembled_for(6)
        health = next(line for line in assembled.section("engaged_context").splitlines()
                      if "health_today" in line)
        assert "(in " not in health, health


# ---------------------------------------------------------------------------
# "Recalled workout remarks lacked dates."   -> FIXED (attribution)
#                                            -> REPRODUCED (relevance)
# ---------------------------------------------------------------------------

class TestRecallRendering:

    async def test_every_recall_line_says_who_said_it_and_when(self):
        _, assembled = await assembled_for(0)  # "That was a good workout after that break"
        lines = [l for l in assembled.section("engaged_context").splitlines()
                 if l.startswith("- [") and "id=" in l]
        assert lines, "no recall traces rendered for a turn that should recall"
        for line in lines:
            meta = line[2:line.index("]")]
            assert any(w in meta for w in ("David said", "Sara suggested", "Sara's note",
                                           "a tool confirmed", "a document shows",
                                           "a summary states", "on record", "an open thread",
                                           "a tracked commitment", "an artifact shows")), meta
            assert re.search(r"\d+ (minute|hour|day|week|month)s? ago|yesterday|today", meta), meta

    async def test_a_greeting_does_not_go_looking_for_old_greetings(self):
        from app.services.context_snapshot import should_skip_recall
        assert should_skip_recall("Good morning!") is True
        assert should_skip_recall("thanks!") is True

    async def test_a_short_question_that_needs_memory_still_gets_it(self):
        """The old rule skipped recall for anything under five words, which
        is most of the messages that need it most."""
        from app.services.context_snapshot import should_skip_recall
        assert should_skip_recall("What did we decide?") is False
        assert should_skip_recall("Same as yesterday?") is False

    @pytest.mark.xfail(strict=True, reason=(
        "OPEN — Phase 2 'rank current-topic evidence above unrelated personal "
        "background' is not implemented. Replaying 'That was a good workout "
        "after that break' still returns four notes about Salem, an agent task "
        "and a rescheduled call, and nothing about the workout."))
    async def test_recall_is_about_what_david_just_said(self):
        _, assembled = await assembled_for(0)
        recall = "\n".join(l for l in assembled.section("engaged_context").splitlines()
                           if l.startswith("- [") and "id=" in l)
        assert re.search(r"workout|lift|leg|squat|press|set|gym", recall, re.IGNORECASE), recall


# ---------------------------------------------------------------------------
# "A casual workout comment prompted questions about already logged
#  activity."   -> REPRODUCED (the record still isn't in the prompt)
# ---------------------------------------------------------------------------

class TestLoggedWorkoutIsAvailable:

    async def test_the_last_set_is_in_the_brief(self):
        _, assembled = await assembled_for(0)
        assert re.search(r"Last logged:.*Leg Curl", assembled.section("world_brief"))

    @pytest.mark.xfail(strict=True, reason=(
        "OPEN — Phase 1 asks for 'a compact completed-workout summary when the "
        "current exchange refers to it'. Nothing assembles one: the brief "
        "carries a single last set, so a remark about the whole session still "
        "leaves Sara asking David what he did. 14 sets across 6 exercises were "
        "in workout_log the whole time."))
    async def test_the_whole_session_can_be_consulted(self):
        _, assembled = await assembled_for(0)
        # 14 sets / 6 exercises were logged that afternoon; any honest summary
        # of the session mentions more than the single most recent set.
        exercises = re.findall(r"Leg Curl|Leg Press|Calf|Squat|Lunge|Extension",
                               assembled.text, re.IGNORECASE)
        assert len(set(e.lower() for e in exercises)) >= 3, sorted(set(exercises))


# ---------------------------------------------------------------------------
# "The personal narrative repeatedly described a low-stress equilibrium as
#  established understanding."   -> REPRODUCED
# ---------------------------------------------------------------------------

class TestPersonalNarrative:

    async def test_a_stale_narrative_is_suppressed(self):
        """The 72-hour expiry does work — shown by ageing the row in the
        disposable replay database and reassembling."""
        from sqlalchemy import text
        from app.db.base import SessionLocal

        t, assembled = await assembled_for(6)
        assert "What you understand about David" in assembled.section("engaged_context")

        db = SessionLocal()
        try:
            db.execute(text(
                "UPDATE sara_journal SET created_at = created_at - interval '10 days' "
                "WHERE entry_type = 'theory_of_david'"))
            db.commit()
        finally:
            db.close()
        # rewind=False: the rewind would restore the row we just aged.
        aged = await harness.assemble(t.user_text, t.at_et, rewind=False)
        assert "What you understand about David" not in aged.section("engaged_context")

    @pytest.mark.xfail(strict=True, reason=(
        "OPEN — Phase 4. Suppressing the stress substrate stops NEW paragraphs "
        "from being written that way; it does nothing about the paragraph "
        "already stored, which is fed back in as the seed of every rewrite. "
        "The Sept 10 prompt still opens 'David maintains a low-stress "
        "equilibrium ... his current stress signature remains relaxed', with no "
        "evidence behind it and no way for Sara to say where it came from."))
    async def test_the_narrative_does_not_assert_a_mood_as_settled_fact(self):
        _, assembled = await assembled_for(6)
        narrative = assembled.section("engaged_context")
        start = narrative.find("What you understand about David")
        block = narrative[start:start + 1200] if start >= 0 else ""
        assert not re.search(
            r"(low-stress equilibrium|stress signature remains|remains relaxed)",
            block, re.IGNORECASE), block


# ---------------------------------------------------------------------------
# "Summaries carried earlier assistant assumptions forward" / "do not inject
#  yesterday's material under a current 'Today' heading."   -> REPRODUCED
# ---------------------------------------------------------------------------

class TestDailySummary:

    @pytest.mark.xfail(strict=True, reason=(
        "OPEN — Phase 4. At 06:54 on Thursday the day layer is still "
        "Wednesday's, printed under the heading '## Today'. The heading names "
        "the right date, which is why nobody noticed; the model is being told "
        "that yesterday is today."))
    async def test_today_means_today(self):
        _, assembled = await assembled_for(6)
        headings = re.findall(r"^## Today.*$", assembled.text, re.MULTILINE)
        assert headings, "no Today heading at all"
        assert all("September 10" in h or "Thursday" in h for h in headings), headings

    @pytest.mark.xfail(strict=True, reason=(
        "OPEN — Phase 4. The day layer summarises Sara's own turns as if they "
        "were events: 'Sara confirms this is a successful close to their "
        "training-day targets', 'she offers to schedule tomorrow's meals'. Her "
        "suggestions graduate into the record of David's day."))
    async def test_saras_own_suggestions_do_not_become_the_days_record(self):
        _, assembled = await assembled_for(6)
        start = assembled.text.find("## Today")
        block = assembled.text[start:start + 2000] if start >= 0 else ""
        assert not re.search(r"\bSara (confirms|notes|offers|suggests)\b", block), block


# ---------------------------------------------------------------------------
# Accounting: "final prompt accounting includes every injected section"
# ---------------------------------------------------------------------------

class TestPromptAccounting:

    async def test_every_character_belongs_to_a_named_section(self):
        _, assembled = await assembled_for(6)
        accounted = sum(len(v) for v in assembled.sections.values() if v)
        joins = 2 * (len([v for v in assembled.sections.values() if v]) - 1)
        assert assembled.chars == accounted + joins

    async def test_the_uncovered_blocks_are_written_down_not_forgotten(self):
        """Phase 2 has to put one budget over the whole assembled context.
        This test exists so the list of what the harness does NOT assemble
        stays visible while that work is done."""
        assert harness.SECTION_GAPS
        assert all(isinstance(gap, str) and gap for gap in harness.SECTION_GAPS)

    async def test_assembly_writes_nothing(self):
        """Building a prompt is a read. Anything else is a bug — and would
        mean the ordinary chat path mutates state before the model has said
        a word."""
        t = harness.turn(6)
        harness.rewind_to(t.at_et)
        with harness.write_ledger() as ledger:
            await harness.assemble(t.user_text, t.at_et, rewind=False)
        assert ledger.statements == [], ledger.statements[:5]


# ---------------------------------------------------------------------------
# Behaviour: the gates that need the model
# ---------------------------------------------------------------------------

@needs_model
class TestPlannedDinnerIsNotEaten:
    """'Dinner is going to be beef heavy taco pasta salad' — the turn that
    produced an invented recipe and a food_log row David had to delete."""

    async def test_no_food_is_logged_for_a_planned_meal(self):
        t = harness.turn(3)
        response = await harness.respond(t.user_text, t.at_et, conversation_id="replay-3")
        assert not response.called("food_search_and_log"), \
            [c.arguments for c in response.tools.named("food_search_and_log")]
        assert response.writes.touching("food_log") == []

    async def test_no_recipe_is_asserted_as_fact(self):
        t = harness.turn(3)
        response = await harness.respond(t.user_text, t.at_et, conversation_id="replay-3b")
        # The failure was a specific invented quantity list presented as
        # David's meal. A gram/ounce figure attached to the dinner is the
        # tell; talking about the dish is fine.
        assert not re.search(r"\d+\s*(g|grams|oz|ounces)\b", response.text or ""), response.text


@needs_model
class TestCasualWorkoutRemark:
    """'That was a good workout after that break' — answered with questions
    about what he'd already logged, then nutrition and calendar management."""

    async def test_a_remark_does_not_trigger_unrequested_writes(self):
        t = harness.turn(0)
        response = await harness.respond(t.user_text, t.at_et, conversation_id="replay-0")
        mutating = [c.name for c in response.tools.calls if c.name in harness.MUTATING_TOOLS]
        assert mutating == [], mutating
