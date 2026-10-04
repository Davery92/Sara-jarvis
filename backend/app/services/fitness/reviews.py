"""Generating a coach review: collect, call once, validate, store.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 20.

The shape of this module is driven by one requirement from §20.6: *"LLM/
network errors preserve deterministic state; no held transaction during
call."* So the flow is strictly:

    1. collect the state and COMMIT                  (transaction closed)
    2. open the review row and COMMIT                (transaction closed)
    3. call the model                                (no transaction held)
    4. validate, then store the result and COMMIT    (new transaction)

Holding a transaction across a model call means a slow Mac Studio pins a
database connection for the length of a generation. The fitness lane and the
chat lane share that pool, so a stuck review would degrade chat — the thing
David is actually using.

And one call, not three. The existing weekly health report runs a 3-stage
pipeline; §20.3 says that is not mandatory, and three calls over the same
deterministic state is three chances to contradict itself with no mechanism
to notice. One bounded call, validated, with a single repair turn.

The repair turn is one. A model that cannot produce the schema twice will not
produce it on the fifth attempt, and each attempt costs a wait and a GPU slot.

**No target writer is invoked here.** Generating a review changes nothing.
Recommendations are stored as proposals; Step 21 is where acceptance lives.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.prompts import fitness_coach_review as prompt_module
from app.schemas.fitness_coach import (
    CoachReviewOut,
    CoachReviewOutputV1,
    FitnessStateV1,
    Period,
    RequestedBy,
    ReviewFailureCategory,
    ReviewKind,
    ReviewStatus,
    ScienceCitation,
    ScienceSearchHit,
    ScienceTopic,
    StateSection,
)
from app.services.fitness import review_audit, safety, science
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

#: How long one generation may take, end to end. `llama-server` keeps
#: generating after a non-streaming client disconnects, so this bound plus
#: the token cap are what keep a stuck review from occupying the lane.
REVIEW_TIMEOUT_SECONDS = 180.0

#: Sections a weekly review reads. All of them: the point of the review is to
#: notice the connection between a bad week of sleep and a missed session,
#: and narrowing the input makes that invisible.
REVIEW_SECTIONS = (
    StateSection.WEIGHT, StateSection.NUTRITION, StateSection.SLEEP,
    StateSection.RECOVERY, StateSection.TRAINING, StateSection.PAIN,
    StateSection.MEASUREMENTS,
)
# PHOTOS is deliberately absent. A review's job is the numbers, and a photo
# observation is a description — folding one in would let a weekly review
# cite "looks leaner" as evidence for a calorie change, which is the
# composition claim the photo schema spends itself preventing.

#: The longer aggregates a weekly review needs beside the seven days. §20.1:
#: the prior 7 full local days plus 14/28 aggregates. The state already
#: computes 14- and 28-day means inside the weight section at span 28, so one
#: collection at 28 carries both.
REVIEW_SPAN_DAYS = 28


class ReviewDisabled(Exception):
    """The generator's feature flag is off. Not an error, a configuration."""


@dataclass
class GenerationResult:
    review: CoachReviewOut
    #: Present only on a complete review.
    output: Optional[CoachReviewOutputV1] = None
    recommendations: List[Any] = None
    #: Findings the safety gate recorded, including applied downgrades.
    notes: List[str] = None

    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []
        if self.notes is None:
            self.notes = []


# ─────────────────────────────────────────────────────────────────────────
# Step 1: the period and the state
# ─────────────────────────────────────────────────────────────────────────

def default_period(db: Session, user_id: str) -> Period:
    """The last seven COMPLETE athlete-local days.

    `end` is exclusive and is the athlete's today, so the current partial day
    is never averaged in. A review that included this morning would report a
    calorie figure that is simply the morning's.
    """
    from app.services.fitness.profile import athlete_today
    today = athlete_today(db, user_id)
    return Period(start=today - timedelta(days=7), end=today)


def collect_state(
    db: Session,
    user_id: str,
    period: Period,
) -> FitnessStateV1:
    """The frozen input. `fresh=True` — a review input never comes from cache.

    A stored audit has to be reproducible from records. One assembled from a
    cache could not be: nothing in the row would say which cached generation
    it came from.

    Committed before returning, so no transaction is held across the model
    call that follows.
    """
    from app.services.fitness.state import build_fitness_state

    uid = _require_user(user_id)
    state = build_fitness_state(
        db, uid,
        period_end=period.end,
        span=(period.end - period.start).days,
        sections=list(REVIEW_SECTIONS),
        fresh=True,
        redis_client=None,
    )
    # A separate, wider collection for the longer aggregates. The weight
    # section's 14- and 28-day means need the longer window; the weekly
    # figures must still be the weekly figures, so this is merged in rather
    # than replacing them.
    if (period.end - period.start).days < REVIEW_SPAN_DAYS:
        wider = build_fitness_state(
            db, uid, period_end=period.end, span=REVIEW_SPAN_DAYS,
            sections=[StateSection.WEIGHT], fresh=True, redis_client=None,
        )
        weight = state.sections.get(StateSection.WEIGHT)
        wide_weight = wider.sections.get(StateSection.WEIGHT)
        if weight and wide_weight:
            for key in ("mean_14d", "mean_28d", "trend_slope_weekly"):
                if key in wide_weight.metrics:
                    weight.metrics[key] = wide_weight.metrics[key]
            # The plotted series too, so a 28-day trend can be seen rather
            # than only asserted.
            weight.items = wide_weight.items
    db.commit()
    return state


def compact_for_prompt(state: FitnessStateV1) -> Dict[str, Any]:
    """The state, trimmed to what the model needs to reason.

    Drops the per-day chart series and the raw measurement list: a month of
    daily points is thousands of tokens that the metrics already summarise,
    and a model given both will quote the raw points instead of the computed
    figure — which is how a number with no coverage statement reaches the
    athlete.
    """
    payload = state.model_dump(mode="json", exclude={"user_id"})
    for section in payload.get("sections", {}).values():
        if isinstance(section, dict):
            # The items list is for charts. Pain items stay — they carry the
            # denominator the model has to quote.
            if section.get("section") != "pain":
                section["items"] = []
    # The owner id again, from the nested objects. `exclude={"user_id"}`
    # only drops the top-level field; the profile, the goals and the
    # limitations each carry their own copy, so the id went into the prompt
    # anyway. The model has no use for it and it is the one field that
    # identifies whose body this is.
    _strip_owner_ids(payload)
    return payload


def _strip_owner_ids(node: Any) -> None:
    """Remove every `user_id` at any depth, in place."""
    if isinstance(node, dict):
        node.pop("user_id", None)
        for value in node.values():
            _strip_owner_ids(value)
    elif isinstance(node, list):
        for item in node:
            _strip_owner_ids(item)


# ─────────────────────────────────────────────────────────────────────────
# Step 2: the review row
# ─────────────────────────────────────────────────────────────────────────

def request_review(
    db: Session,
    user_id: str,
    *,
    kind: ReviewKind = ReviewKind.WEEKLY,
    period: Optional[Period] = None,
    requested_by: RequestedBy = RequestedBy.USER,
    force: bool = False,
) -> CoachReviewOut:
    """Create or replay a queued review, and return it immediately.

    Returns a row with a status, not a result: generation happens in a Celery
    task on the `health` queue. A request that waited for the model would
    hold an HTTP connection for up to three minutes, and a timeout on the
    caller's side would leave a running generation nobody is waiting for.

    Idempotent through `review_audit.open_review`'s unique index, so a
    double-tap produces one review and one model call.
    """
    uid = _require_user(user_id)
    window = period or default_period(db, uid)
    state = collect_state(db, uid, window)

    stale = review_audit.needs_rerun(db, uid, kind=kind, state=state)
    if stale is not None and not force:
        # The data moved since the existing review. Saying so rather than
        # silently superseding: a rerun costs a model call, and the caller
        # should be the one deciding to spend it.
        raise review_audit.ReviewConflict(
            "a review of this period exists but the data has changed since; "
            "request again with force=true to produce a linked revision",
            review_id=stale.id, status=stale.status,
        )

    review = review_audit.open_review(
        db, uid, kind=kind, state=state,
        prompt_version=prompt_module.PROMPT_VERSION,
        prompt_template_hash=review_audit.prompt_hash(prompt_module.prompt_text()),
        model_requested=_requested_model(),
        provider="local",
        requested_by=requested_by,
        supersedes_id=stale.id if (stale is not None and force) else None,
    )
    db.commit()
    return review


def _requested_model() -> Optional[str]:
    """What we intend to ask. `model_actual` records what answered."""
    try:
        from app.core.llm import get_background_llm_client
        return get_background_llm_client().primary_model
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# Steps 3-4: the model call, and storing the result
# ─────────────────────────────────────────────────────────────────────────

async def generate(
    db: Session,
    user_id: str,
    review_id: str,
) -> GenerationResult:
    """Run one review to a terminal state.

    Every exit path is terminal: complete, failed or insufficient_data. A
    review left `running` because a worker died is the one state nothing can
    interpret, so the exception handler is as careful as the happy path.
    """
    from app.core.feature_flags import Flag, is_enabled

    uid = _require_user(user_id)
    if not is_enabled(Flag.FITNESS_COACH_REVIEW):
        raise ReviewDisabled(
            "FITNESS_COACH_REVIEW is off. The state, the analytics and the "
            "stored audit all work without it; only new opinions are gated."
        )

    detail = review_audit.get_review(db, uid, review_id, with_state=True)
    if detail.status in (ReviewStatus.COMPLETE, ReviewStatus.FAILED,
                         ReviewStatus.INSUFFICIENT_DATA):
        # Already answered. A duplicate worker returns the one artifact
        # rather than producing a second.
        return GenerationResult(
            review=detail, output=detail.output,
            recommendations=detail.recommendations,
            notes=["this review was already complete"],
        )
    if detail.input_state is None:
        review_audit.mark_running(db, uid, review_id)
        failed = review_audit.mark_failed(
            db, uid, review_id,
            category=ReviewFailureCategory.STATE_UNAVAILABLE,
            detail="the stored input snapshot could not be read back",
        )
        db.commit()
        return GenerationResult(review=failed)

    state = detail.input_state

    # Coverage is checked BEFORE the model. A review generated from two data
    # points produces confident text about noise, and the right answer is to
    # say what would help — not to spend a call producing something that has
    # to be ignored.
    verdict = safety.assess_coverage(state)
    if not verdict.sufficient:
        review_audit.mark_running(db, uid, review_id)
        out = review_audit.mark_insufficient_data(
            db, uid, review_id,
            detail=(verdict.reason or "")[:400],
        )
        db.commit()
        return GenerationResult(
            review=out,
            notes=[verdict.reason or "", "wanted: " + ", ".join(verdict.wanted)],
        )

    review_audit.mark_running(db, uid, review_id)
    db.commit()

    # Accepted evidence for this review's own questions (Step 28.5).
    # Retrieved BEFORE the call and bounded, because the passages are the
    # citable set: the validator later keeps only ids from exactly this
    # list, so a model shown more than it can be checked against would have
    # its extra citations stripped and the text resting on them kept.
    evidence = await _retrieve_evidence(db, uid, state)
    # Those reads opened an implicit transaction. Ending it is not
    # housekeeping: holding one across the model call pins a database
    # connection for the length of a generation, and the fitness lane
    # shares that pool with chat — a review stuck on a slow Mac Studio
    # would degrade the thing David is actually using. A rollback is the
    # right verb because nothing above wrote anything.
    db.rollback()

    # No transaction from here until the result is stored.
    try:
        parsed, model_actual, errors = await _call_and_parse(state, evidence)
    except Exception as exc:
        logger.warning(
            "fitness review %s: model call failed (%s): %s",
            review_id, type(exc).__name__, exc,
        )
        failed = review_audit.mark_failed(
            db, uid, review_id,
            category=_failure_category(exc),
            detail=f"{type(exc).__name__}: {exc}"[:400],
        )
        db.commit()
        # The deterministic state is untouched: nothing above this line
        # wrote anything but the review's own status.
        return GenerationResult(review=failed)

    if parsed is None:
        failed = review_audit.mark_failed(
            db, uid, review_id,
            category=ReviewFailureCategory.INVALID_OUTPUT,
            detail="; ".join(errors)[:400],
            model_actual=model_actual,
        )
        db.commit()
        return GenerationResult(review=failed, notes=errors)

    report = safety.validate_output(
        parsed, state, evidence_attached=bool(evidence),
    )
    if report.rejected:
        failed = review_audit.mark_failed(
            db, uid, review_id,
            category=_safety_category(report),
            detail="; ".join(report.rejections)[:400],
            model_actual=model_actual,
        )
        db.commit()
        return GenerationResult(review=failed, notes=report.rejections)

    output = report.output or parsed

    # §28.5: only the exact supplied ids survive. A model asked to cite its
    # sources produces a real record with the wrong chunk, or a well-formed
    # id for a paper that suits the claim better than the one it was shown;
    # both resolve to real-looking text, and the offered set is the only
    # check that does not require reading every citation by hand.
    citations, rejected_citations = science.validate_citations(
        db, uid, _cited_science(output), evidence,
    )
    if rejected_citations:
        logger.info(
            "fitness review %s: %d fabricated citation(s) stripped: %s",
            review_id, len(rejected_citations), "; ".join(rejected_citations),
        )

    complete = review_audit.mark_complete(
        db, uid, review_id, output=output, model_actual=model_actual,
    )
    _store_citations(
        db, uid, review_id, citations, offered=len(evidence),
    )
    recommendations = review_audit.record_recommendations(
        db, uid, review_id, output,
        current_target_revision_id=(
            state.targets.revision_id if state.targets else None
        ),
        current_phase_id=(state.program or {}).get("phase", {}).get("id"),
    )
    db.commit()
    return GenerationResult(
        review=complete, output=output,
        recommendations=recommendations,
        notes=report.downgrades + rejected_citations,
    )


# ─────────────────────────────────────────────────────────────────────────
# Step 28.5: bounded accepted evidence
# ─────────────────────────────────────────────────────────────────────────

#: At most this many passages reach the prompt. Bounded for two reasons,
#: and the second is the real one: the context budget, and the fact that
#: the offered set IS the citable set. Twenty passages a reviewer cannot
#: check is how an unverifiable bibliography appears under a weekly review.
MAX_EVIDENCE_PASSAGES = 4

#: What a weekly review is actually deciding about. Retrieval is scoped to
#: these rather than run on the summary text: a free-text query built from
#: the model's own framing would retrieve whatever supports it.
REVIEW_EVIDENCE_QUERIES: Tuple[Tuple[str, Tuple[ScienceTopic, ...]], ...] = (
    (
        "rate of weight change and calorie adjustment during a fat loss or "
        "gaining phase",
        (ScienceTopic.NUTRITION,),
    ),
    (
        "protein intake and training volume for muscle growth in trained "
        "lifters",
        (ScienceTopic.NUTRITION, ScienceTopic.HYPERTROPHY),
    ),
    (
        "sleep duration and recovery effects on strength and training "
        "performance",
        (ScienceTopic.SLEEP, ScienceTopic.RECOVERY),
    ),
)


async def _retrieve_evidence(
    db: Session, user_id: str, state: FitnessStateV1,
) -> List[ScienceSearchHit]:
    """Accepted passages relevant to this review's questions.

    Never fails the review. An empty list is a normal outcome — most
    libraries are empty, and the prompt says so explicitly in that case
    (`NO_CORPUS_NOTE`) rather than letting the model fill the gap from
    memory. A retrieval error is logged and treated the same way: a review
    without evidence is worth having, and a review that did not happen
    because the GPU host was down is not.
    """
    # No feature-flag check here: `generate` already refuses to run with
    # FITNESS_COACH_REVIEW off, and a second gate would only make this
    # helper return nothing for a reason that has nothing to do with the
    # library.
    try:
        if science.coverage(db, user_id)["accepted_total"] == 0:
            return []
    except Exception as exc:
        logger.info("fitness review: science coverage unreadable: %s", exc)
        return []

    athlete = _science_athlete_context(state)
    collected: Dict[str, ScienceSearchHit] = {}
    for query, topics in REVIEW_EVIDENCE_QUERIES:
        try:
            hits = await science.search(
                db, user_id, query, topics=topics, athlete=athlete, limit=2,
            )
        except Exception as exc:
            logger.info(
                "fitness review: science retrieval failed for %r: %s",
                query[:40], exc,
            )
            continue
        for hit in hits:
            # One passage per record across all three queries. Three
            # paragraphs of one paper read as three sources, which is the
            # quiet way a single study becomes "the literature".
            collected.setdefault(hit.record_id, hit)

    ranked = sorted(
        collected.values(), key=lambda hit: hit.score, reverse=True,
    )
    return ranked[:MAX_EVIDENCE_PASSAGES]


def _science_athlete_context(state: FitnessStateV1) -> science.AthleteContext:
    """Applicability context from the state's own profile section.

    Taken from the state rather than re-queried so the evidence is scored
    against the same snapshot the review reasons over. A profile edited
    mid-review would otherwise rank the evidence against one athlete
    description and the review text against another.
    """
    profile = state.profile
    if profile is None:
        return science.AthleteContext()
    level = getattr(profile, "training_level", None)
    level = getattr(level, "value", level)
    sex = getattr(profile, "calculation_sex", None)
    sex = getattr(sex, "value", sex)
    if sex in ("unknown", "prefer_not_to_say"):
        sex = None
    if level == "unknown":
        level = None
    # Age from `date_of_birth`, which is the field the profile actually
    # carries — there is no `age_years`, and a getattr for one would have
    # silently returned None and dropped the older/youth signal entirely.
    age = None
    born = getattr(profile, "date_of_birth", None)
    if born is not None:
        today = state.athlete_local_date
        age = today.year - born.year - (
            (today.month, today.day) < (born.month, born.day)
        )
    return science.AthleteContext(training_level=level, sex=sex, age=age)


def _cited_science(output: CoachReviewOutputV1) -> List[Dict[str, Any]]:
    """Citations the model claimed, as raw dicts for validation.

    `evidence_refs` carries both metric paths (checked by
    `safety.validate_references`) and science chunk ids. They are told
    apart by shape: a metric path contains a dot and a chunk id is a uuid.
    Anything that is neither is left for the metric validator to reject, so
    a malformed ref cannot slip through by failing both checks.
    """
    cited: List[Dict[str, Any]] = []
    for ref in output.referenced_evidence():
        token = (ref or "").strip()
        if not token or "." in token:
            continue
        cited.append({"chunk_id": token})
    return cited


def _store_citations(
    db: Session,
    user_id: str,
    review_id: str,
    citations: Sequence["ScienceCitation"],
    *,
    offered: int,
) -> None:
    """Persist the validated citation trail on the review row.

    `science_offered` is stored even when nothing was cited, because a
    review that was given no evidence and one where retrieval never ran are
    different things: the first is a fact about the library, the second is
    a bug, and one NULL cannot say which.
    """
    from sqlalchemy import text as sql_text

    try:
        db.execute(sql_text("""
            UPDATE fitness_coach_review SET
                science_citations = CAST(:citations AS JSONB),
                science_policy_version = :policy,
                science_offered = :offered
            WHERE id = :id AND user_id = :u
        """), {
            "citations": json.dumps([
                citation.model_dump(mode="json") for citation in citations
            ]),
            "policy": science.SCIENCE_RANKING_POLICY_VERSION,
            "offered": offered, "id": review_id, "u": user_id,
        })
    except Exception as exc:
        # The review itself is already complete and worth keeping. A lost
        # citation trail is a gap in the audit, not a reason to fail a
        # review the athlete is waiting for — and the log says which review.
        logger.warning(
            "fitness review %s: citation trail not stored: %s",
            review_id, exc,
        )


async def _call_and_parse(
    state: FitnessStateV1,
    evidence: Optional[Sequence[ScienceSearchHit]] = None,
) -> Tuple[Optional[CoachReviewOutputV1], Optional[str], List[str]]:
    """One call, then at most one repair. Returns (output, model, errors)."""
    payload = compact_for_prompt(state)
    allowed = state.metric_paths()
    passages = [
        hit.model_dump(mode="json") for hit in (evidence or [])
    ]
    user_prompt = prompt_module.build_user_prompt(
        payload, allowed,
        has_science_corpus=bool(passages), evidence=passages or None,
    )

    content, model_actual = await _chat(
        prompt_module.SYSTEM_PROMPT, user_prompt,
    )
    output, errors = _parse_output(content)
    if output is not None:
        # A reference failure is repairable — the model cited a path that
        # does not exist and can be told to drop it. A safety failure is not:
        # see `check_language`.
        reference_errors = [
            f.message for f in safety.validate_references(output, state)
        ]
        if not reference_errors:
            return output, model_actual, []
        errors = reference_errors

    # The repair turn re-sends the same evidence. Dropping it would let the
    # repaired output cite ids it can no longer see, which the validator
    # then strips — a repair that silently loses the citations.
    repair_prompt = (
        user_prompt + "\n\n" + prompt_module.build_repair_prompt(errors)
    )
    repaired_content, repair_model = await _chat(
        prompt_module.SYSTEM_PROMPT, repair_prompt,
    )
    repaired, repair_errors = _parse_output(repaired_content)
    if repaired is None:
        return None, repair_model or model_actual, errors + repair_errors
    return repaired, repair_model or model_actual, []


async def _chat(system: str, user: str) -> Tuple[str, Optional[str]]:
    """One bounded call to the local background model.

    `enable_thinking: False` nested in `chat_template_kwargs` — without it
    Qwen returns an empty `content` for structured output (§9). `max_tokens`
    is always set: `llama-server` keeps generating after a non-streaming
    client disconnects, and an uncapped background call once produced an
    all-night outage.
    """
    from app.core.llm import get_background_llm_client

    client = get_background_llm_client()
    started = time.monotonic()
    response = await client.chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=prompt_module.TEMPERATURE,
        max_tokens=prompt_module.MAX_OUTPUT_TOKENS,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        request_timeout=REVIEW_TIMEOUT_SECONDS,
        # Pinned to the bg lane. The fast tier's 16k slots cannot hold a
        # month of state, and a silent truncation there would make the model
        # reason from a partial state while the stored snapshot shows the
        # whole one.
        tier="bg",
        caller="fitness_coach_review",
    )
    elapsed = time.monotonic() - started

    try:
        content = (response["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        content = ""
    # The model the SERVER reports, not the one we asked for. A fallback that
    # answered as the primary makes every comparison between runs meaningless.
    model_actual = (response or {}).get("model") or None
    usage = (response or {}).get("usage") or {}
    logger.info(
        "[fitness-coach] model=%s prompt=%s out=%s %.1fs",
        model_actual, usage.get("prompt_tokens", "?"),
        usage.get("completion_tokens", "?"), elapsed,
    )
    if not content:
        raise ValueError("the model returned no parseable content")
    return content, model_actual


def _parse_output(content: str) -> Tuple[Optional[CoachReviewOutputV1], List[str]]:
    """Strict schema validation over a tolerant JSON extraction.

    Tolerant about the wrapper (fences, leading chatter) because those are
    formatting noise the model routinely adds and rejecting them wastes a
    turn. Strict about the CONTENT: `extra="forbid"` throughout
    `CoachReviewOutputV1`, so an invented field is a rejection rather than
    something silently dropped on the way to storage.
    """
    raw = _extract_json(content)
    if raw is None:
        return None, ["the output contained no JSON object"]
    try:
        return CoachReviewOutputV1.model_validate(raw), []
    except Exception as exc:
        return None, [_short_validation_error(exc)]


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _short_validation_error(exc: Exception) -> str:
    """A compact message for the repair turn and the stored detail.

    Pydantic's full error payload is long and quotes the input, which would
    put the athlete's numbers into `error_detail` — a column that
    deliberately does not hold their data.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            parts = []
            for item in errors()[:6]:
                location = ".".join(str(p) for p in item.get("loc", ()))
                parts.append(f"{location}: {item.get('msg')}")
            return "; ".join(parts) or str(exc)[:300]
        except Exception:
            pass
    return str(exc)[:300]


def _failure_category(exc: Exception) -> ReviewFailureCategory:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return ReviewFailureCategory.MODEL_TIMEOUT
    if "connect" in name or "unreachable" in text or "connection" in name:
        return ReviewFailureCategory.MODEL_UNAVAILABLE
    if "no parseable content" in text:
        return ReviewFailureCategory.MODEL_UNAVAILABLE
    return ReviewFailureCategory.INTERNAL_ERROR


def _safety_category(report: safety.SafetyReport) -> ReviewFailureCategory:
    codes = {f.code for f in report.findings if f.severity == "reject"}
    if codes & {"unknown_metric_path", "unknown_evidence_ref",
                "change_rests_on_unknowns"}:
        return ReviewFailureCategory.UNGROUNDED_CLAIM
    if codes & {"diagnosis", "diagnostic_claim", "treatment_advice",
                "fabricated_citation"}:
        return ReviewFailureCategory.SAFETY_REFUSED
    return ReviewFailureCategory.SCHEMA_VIOLATION
