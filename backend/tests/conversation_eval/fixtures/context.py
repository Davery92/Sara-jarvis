"""Synthetic C0/C1/C2 context fixtures.

SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md, "Fixtures" section.
All facts below are invented test data, not facts about David. Clock is
frozen at 2026-09-23 18:30 UTC; synthetic user timezone is UTC.

C0: no facts at all (persona + clock + conversation only).
C1: C0 + this case's 2-3 RELEVANT facts (each with source/date/ownership).
C2: C1 + the fixed BUSY_FACTS block below (identical across every case).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, NamedTuple

FIXED_CLOCK = datetime(2026, 9, 23, 18, 30, tzinfo=timezone.utc)
FIXED_CLOCK_LABEL = "2026-09-23 18:30 UTC"


class Fact(NamedTuple):
    text: str
    source: str
    date: str
    ownership: str  # "david" | "household" | "system"

    def render(self) -> str:
        return f"- {self.text} (source: {self.source}; {self.date}; owner: {self.ownership})"


def render_facts(facts: List[Fact], heading: str) -> str:
    if not facts:
        return ""
    lines = [f"## {heading}"] + [f.render() for f in facts]
    return "\n".join(lines)


# C2's fixed "busy" block -- IDENTICAL across every case/setting, per the
# plan ("Make its exact contents identical across settings"). Distractors
# deliberately share a word with common current-topic words (e.g. "box",
# "printer"/"dashboard", "dinner") so relevance requires understanding, not
# keyword overlap.
BUSY_FACTS: List[Fact] = [
    Fact("Project review meeting tomorrow at 10:30", "calendar_stub", "2026-09-24 10:30 UTC", "david"),
    Fact("Household member has a class today at 18:00", "calendar_stub", "2026-09-23 18:00 UTC", "household"),
    Fact("The analytics dashboard rebuild is unfinished", "project_stub", "2026-09-20", "david"),
    Fact("Groceries: eggs, coffee, dog food are low", "list_stub", "2026-09-22", "household"),
    Fact("Old debugging note: the auth-token refresh race from last sprint, unresolved", "scratchpad_stub", "2026-09-15", "david"),
    Fact("Sleep last night: 6h 40m, one wake-up logged", "health_stub", "2026-09-23 07:00 UTC", "david"),
    Fact("Dinner preference on file: prefers chicken over beef (may be stale)", "preference_stub", "2026-08-01", "david"),
]

CASE_RELEVANT_FACTS: Dict[str, List[Fact]] = {
    # "busy awareness is available, but no relevant task pending in this exchange"
    "01": [],
    "02": [
        Fact("No open tasks reference today's walk or errands", "system_stub", "2026-09-23", "system"),
    ],
    "03": [
        Fact("Bought a new notebook last week, mentioned wanting to get organized", "notes_stub", "2026-09-16", "david"),
    ],
    "06": [
        Fact("Three unread work messages arrived between 14:00 and 17:00 today", "email_stub", "2026-09-23", "david"),
    ],
    # "C2 contains a dated synthetic sleep measurement and an unrelated workout
    # plan. Neither establishes the cause of today's tiredness."
    "11": [
        Fact("Workout plan: upper body session was scheduled for this evening", "fitness_stub", "2026-09-23", "david"),
    ],
    "15": [
        Fact("Coffee brewing method logged twice before, both times drip", "notes_stub", "2026-09-10", "david"),
    ],
    # "relevant fixture says a synthetic user's printer jammed yesterday"
    "19": [
        Fact("Printer jammed yesterday, cleared after removing a torn scrap", "device_stub", "2026-09-22", "david"),
    ],
    "24": [
        Fact("Shelving project (three shelves) noted as in-progress", "project_stub", "2026-09-21", "david"),
    ],
    "29": [
        Fact("Couch was purchased three weeks ago", "notes_stub", "2026-09-02", "david"),
    ],
    # Held-out cases used later (Stage 4/5) -- kept here so Stage 4 doesn't
    # need a second pass through the plan text.
    "20": [
        Fact("Brother visiting Saturday (STALE -- superseded by the live conversation)", "calendar_stub", "2026-09-18", "household"),
    ],
    "33": [],  # deliberately empty: memory-search stub returns no matches
}

CASE_CONTEXT_NOTES: Dict[str, str] = {
    "01": "busy awareness is available, but no relevant task pending in this exchange",
    "11": "C2 contains a dated synthetic sleep measurement and an unrelated workout plan; neither establishes the cause of today's tiredness",
    "19": "relevant fixture says a synthetic user's printer jammed yesterday; C2 also contains projects, calendar, health and grocery facts",
    "20": "a stale synthetic memory says the user's brother is visiting Saturday; the live user supplies the correction to Sunday",
    "33": "there is no previous lamp conversation visible and the memory-search stub returns no matches",
    "23": "disposable reminder stub; fixed clock and UTC timezone; success returns ID test-reminder-N",
    "25": "reminder stub returns a clear failure on turn 2 and no persisted reminder",
    "40": "successful isolated reminder stub at turn 8 only; turn 15 asks for conversational recall, not a new tool lookup",
}


def build_world_state_core(case_id: str, condition: str) -> str:
    """condition in {"C0", "C1", "C2"}."""
    if condition == "C0":
        return ""
    facts = CASE_RELEVANT_FACTS.get(case_id, [])
    return render_facts(facts, "What's true right now (relevant to this conversation)")


def build_world_brief(case_id: str, condition: str) -> str:
    if condition != "C2":
        return ""
    return render_facts(BUSY_FACTS, "What's true in David's world right now")
