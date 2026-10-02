"""Step 23 of FITNESS_COACH_IMPLEMENTATION_PLAN: the new tools follow the
registry, mutation and receipt conventions.

Registration is not enough. Gotcha 3's cousin applies here: a tool that is
in the registry but classified read-only bypasses the execution-boundary
gate, and the failure is silent — the tool simply stays available on turns
that never asked for it.

What this file pins:

* `user_id` is never a model-visible parameter. A schema that accepted an
  owner id would let a model address another athlete's data by naming it.
* reads are classified read-only and writes are not;
* every write is `requires_user_origin`, so the autonomous loop cannot log a
  measurement or decide a coaching change on its own;
* schemas reject unknown fields, so an injected identity field is a
  validation error rather than something silently dropped;
* malformed arguments produce a `ToolResult(success=False)` with a usable
  message, never an exception out of `execute`;
* the per-turn menu is not blown out by eight new tools.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_tool_contracts.py
"""
import asyncio
import inspect

import pytest

from app.tools.base import BaseTool, ToolResult

READ_TOOLS = (
    "fitness_profile_get",
    "fitness_analytics_get",
    "fitness_measurements_get",
    "fitness_coach_review_get",
)
WRITE_TOOLS = (
    "fitness_checkin_update",
    "fitness_measurement_log",
    "fitness_coach_review_request",
    "fitness_recommendation_decide",
)
ALL_COACH_TOOLS = READ_TOOLS + WRITE_TOOLS

#: Names a model must never be able to supply. `user_id` is injected by the
#: registry; a tool that accepted one would let a model address another
#: athlete's data by naming it.
FORBIDDEN_PARAMETERS = {
    "user_id", "userId", "owner_user_id", "athlete_id", "owner",
    "account_id", "sub", "token", "auth", "as_user",
}


@pytest.fixture(scope="module")
def registry():
    from app.tools.registry import tool_registry
    return tool_registry


# ─────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────

def test_every_coach_tool_is_registered(registry):
    missing = [name for name in ALL_COACH_TOOLS if name not in registry.tools]
    assert missing == [], f"not registered: {missing}"


def test_every_coach_tool_is_in_the_fitness_category(registry):
    """Category metadata, not just registration. Retrieval selects by
    category, so a tool outside one is reachable only by exact name — which
    the model does not know."""
    listed = set(registry.TOOL_CATEGORIES["fitness"]["tools"])
    missing = [name for name in ALL_COACH_TOOLS if name not in listed]
    assert missing == [], f"not in the fitness category: {missing}"


def test_every_category_name_actually_exists(registry):
    """A category listing a tool that is not registered makes retrieval
    offer a name that cannot be dispatched."""
    for name in registry.TOOL_CATEGORIES["fitness"]["tools"]:
        assert name in registry.tools, f"{name} is listed but not registered"


def test_the_tools_are_consolidated_rather_than_one_per_section(registry):
    """`tool_retrieval.MAX_TOOLS_PER_CALL = 35` caps the per-turn menu. Seven
    per-section analytics tools would cost six more slots than one tool with
    a `section` parameter, and those slots come out of the rest of Sara's
    capability on a fitness turn."""
    from app.services.tool_retrieval import MAX_TOOLS_PER_CALL

    fitness_tools = registry.TOOL_CATEGORIES["fitness"]["tools"]
    assert len(ALL_COACH_TOOLS) <= 8
    # The whole fitness category still has to be able to fit beside other
    # categories within the per-call cap when retrieval picks it.
    assert len(fitness_tools) < MAX_TOOLS_PER_CALL * 2, (
        f"the fitness category is {len(fitness_tools)} tools against a "
        f"per-call cap of {MAX_TOOLS_PER_CALL}"
    )

    analytics = registry.tools["fitness_analytics_get"]
    sections = analytics.parameters["properties"]["section"]["enum"]
    assert len(sections) >= 7, (
        "the consolidated tool must cover the sections that would otherwise "
        "each need their own slot"
    )


# ─────────────────────────────────────────────────────────────────────────
# Identity never crosses the boundary
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ALL_COACH_TOOLS)
def test_no_tool_accepts_an_owner_identity(registry, name):
    schema = registry.tools[name].parameters
    properties = set(schema.get("properties", {}))
    leaked = properties & FORBIDDEN_PARAMETERS
    assert leaked == set(), (
        f"{name} exposes {sorted(leaked)} to the model; user_id is injected"
    )
    assert FORBIDDEN_PARAMETERS.isdisjoint(set(schema.get("required", []))), name


@pytest.mark.parametrize("name", ALL_COACH_TOOLS)
def test_every_schema_rejects_unknown_fields(registry, name):
    """`additionalProperties: false`. Without it an injected `user_id` is
    silently dropped rather than refused, and a silently dropped field is a
    model instruction nobody reads and a behaviour nobody tested."""
    schema = registry.tools[name].parameters
    assert schema.get("additionalProperties") is False, (
        f"{name} accepts unknown properties"
    )


@pytest.mark.parametrize("name", ALL_COACH_TOOLS)
def test_execute_takes_user_id_positionally_and_not_from_the_model(registry, name):
    signature = inspect.signature(registry.tools[name].execute)
    parameters = list(signature.parameters)
    assert parameters[0] == "user_id", (
        f"{name}.execute must take the injected user_id first"
    )


# ─────────────────────────────────────────────────────────────────────────
# Mutation classification
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", READ_TOOLS)
def test_read_tools_are_classified_read_only(name):
    """A read misclassified as a write needs action evidence to survive the
    gate, so a plain question cannot reach the tool that answers it."""
    from app.services.tool_mutation import is_mutating_tool
    assert not is_mutating_tool(name), name


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_write_tools_are_classified_mutating(name):
    """A write misclassified as a read bypasses the execution boundary
    entirely, and the failure is silent — the tool just stays available."""
    from app.services.tool_mutation import is_mutating_tool
    assert is_mutating_tool(name), name


def test_requesting_a_review_is_explicitly_classified_as_a_write():
    """It carries "review" and "coach", both read tokens, and no mutating
    one — so the token rules called it read-only. It creates a durable row
    and queues a model call."""
    from app.services.tool_mutation import EXPLICIT_MUTATING, is_mutating_tool

    assert "fitness_coach_review_request" in EXPLICIT_MUTATING
    assert is_mutating_tool("fitness_coach_review_request")


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_every_write_requires_a_user_turn(registry, name):
    """`requires_user_origin` blocks the autonomous loop. Deciding a coaching
    change, or recording a measurement, is the athlete's."""
    assert registry.tools[name].requires_user_origin is True, name


@pytest.mark.parametrize("name", READ_TOOLS)
def test_reads_do_not_require_a_user_turn(registry, name):
    """Sara's own cognition has to be able to look things up, which is the
    whole reason reads and writes are classified separately."""
    assert registry.tools[name].requires_user_origin is False, name


def test_deciding_a_recommendation_cannot_be_authorized_by_a_correction():
    """It changes the targets the athlete eats against. `UPDATE` is the one
    operation kind a bare correction can authorize, and a correction is not
    an approval."""
    from app.services.operation_contract import (
        _AUTHORITY, OperationKind, UtteranceClass, operation_kind_for,
    )

    kind = operation_kind_for("fitness_recommendation_decide")
    assert kind is OperationKind.RECURRING
    assert UtteranceClass.CORRECTION not in _AUTHORITY[kind]
    assert UtteranceClass.CONFIRMATION in _AUTHORITY[kind]


def test_requesting_a_review_is_a_create_not_a_read():
    from app.services.operation_contract import OperationKind, operation_kind_for
    assert operation_kind_for("fitness_coach_review_request") is OperationKind.CREATE


# ─────────────────────────────────────────────────────────────────────────
# Schemas say enough to be used correctly
# ─────────────────────────────────────────────────────────────────────────

def test_the_analytics_tool_enumerates_its_sections(registry):
    """A free-text `section` would be guessed at, and a guess produces a
    tool error instead of an answer."""
    schema = registry.tools["fitness_analytics_get"].parameters
    enum = schema["properties"]["section"]["enum"]
    assert "weight" in enum and "pain" in enum and "quality" in enum
    assert schema["required"] == ["section"]


def test_the_check_in_tool_bounds_every_scale(registry):
    """An out-of-range answer is refused rather than clamped: a 15 clamped to
    10 is a number the athlete never gave."""
    properties = registry.tools["fitness_checkin_update"].parameters["properties"]
    for field in ("energy", "fatigue", "soreness_level", "stress",
                  "motivation", "sleep_quality"):
        assert properties[field]["minimum"] == 1, field
        assert properties[field]["maximum"] == 10, field
    assert properties["sleep_hours"]["maximum"] == 24


def test_the_check_in_tool_tells_the_model_not_to_invent_values(registry):
    """The strongest available control is a schema, and the second strongest
    is saying it in the description."""
    description = registry.tools["fitness_checkin_update"].description.lower()
    assert "only the fields" in description
    assert "never fill in" in description


def test_the_decide_tool_says_it_needs_an_unambiguous_yes(registry):
    description = registry.tools["fitness_recommendation_decide"].description.lower()
    assert "unambiguous yes" in description
    assert "never call this on your own judgement" in description


def test_the_review_request_tool_says_it_changes_nothing(registry):
    description = registry.tools["fitness_coach_review_request"].description.lower()
    assert "changes nothing by itself" in description
    assert "only call this when they asked" in description


def test_the_review_get_tool_says_it_does_not_generate(registry):
    """Otherwise a model reading reviews would spend a minute of GPU time per
    question by accident."""
    description = registry.tools["fitness_coach_review_get"].description
    assert "does NOT generate" in description


def test_the_analytics_tool_tells_the_model_not_to_compute(registry):
    description = registry.tools["fitness_analytics_get"].description.lower()
    assert "instead of computing anything yourself" in description
    assert "says why" in description


# ─────────────────────────────────────────────────────────────────────────
# Malformed arguments
# ─────────────────────────────────────────────────────────────────────────

def _run(tool, **kwargs) -> ToolResult:
    return asyncio.run(tool.execute("nobody-at-all", **kwargs))


def test_a_bad_section_is_a_refusal_not_an_exception(registry):
    result = _run(registry.tools["fitness_analytics_get"], section="vibes")
    assert isinstance(result, ToolResult)
    assert result.success is False
    # And it says what the valid ones are, so the next attempt can work.
    assert "weight" in result.message


def test_a_missing_required_field_is_a_refusal(registry):
    result = _run(registry.tools["fitness_analytics_get"])
    assert result.success is False


def test_a_malformed_date_is_refused_rather_than_coerced(registry):
    """A model writing "last Tuesday" into a date field is a real
    occurrence, and coercing it to today attributes data to the wrong day."""
    result = _run(
        registry.tools["fitness_analytics_get"],
        section="weight", start_date="last Tuesday",
    )
    assert result.success is False
    assert "ISO date" in result.message


def test_an_inverted_window_is_refused(registry):
    result = _run(
        registry.tools["fitness_analytics_get"], section="weight",
        start_date="2026-09-28", end_date="2026-09-21",
    )
    assert result.success is False
    assert "after start_date" in result.message


def test_an_unbounded_window_is_refused(registry):
    """A multi-year window is the request shape that takes a shared database
    down, and no coaching question needs one."""
    result = _run(
        registry.tools["fitness_analytics_get"], section="weight",
        start_date="2015-01-01", end_date="2026-09-28",
    )
    assert result.success is False
    assert "maximum" in result.message


def test_an_empty_check_in_is_refused_with_an_explanation(registry):
    result = _run(registry.tools["fitness_checkin_update"])
    assert result.success is False
    assert "only the fields" in result.message


def test_an_out_of_range_scale_is_refused(registry):
    """The schema says 1-10; the service validates again. A model that
    ignores the schema still cannot write a 50."""
    result = _run(registry.tools["fitness_checkin_update"], energy=50)
    assert result.success is False


def test_a_bad_decision_value_is_refused(registry):
    result = _run(
        registry.tools["fitness_recommendation_decide"],
        recommendation_id="whatever", decision="maybe",
    )
    assert result.success is False
    assert "accept" in result.message


def test_a_missing_recommendation_id_is_refused(registry):
    result = _run(
        registry.tools["fitness_recommendation_decide"],
        recommendation_id="   ", decision="accept",
    )
    assert result.success is False


def test_a_naive_measurement_timestamp_is_refused(registry):
    """A naive stamp cannot be placed on a calendar day without guessing a
    zone, and the guess moves the reading to the wrong day."""
    result = _run(
        registry.tools["fitness_measurement_log"],
        type_code="waist_circumference", value=81.0, unit="cm",
        measured_at="2026-09-28T07:00:00",
    )
    assert result.success is False
    assert "timezone" in result.message


def test_every_tool_returns_a_tool_result(registry):
    """Not a dict and not a raw exception: the dispatch layer and the chat
    loop both depend on the type."""
    for name in ALL_COACH_TOOLS:
        tool = registry.tools[name]
        result = asyncio.run(tool.execute("nobody-at-all"))
        assert isinstance(result, ToolResult), name


def test_a_read_tool_with_an_unknown_owner_writes_nothing(registry):
    """A read must not create a profile row as a side effect of being asked
    about a user who has none."""
    from sqlalchemy import text
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        before = db.execute(text(
            "SELECT COUNT(*) FROM fitness_athlete_profile"
        )).scalar()
        _run(registry.tools["fitness_profile_get"])
        db.rollback()
        after = db.execute(text(
            "SELECT COUNT(*) FROM fitness_athlete_profile"
        )).scalar()
        assert after == before
    finally:
        db.close()
