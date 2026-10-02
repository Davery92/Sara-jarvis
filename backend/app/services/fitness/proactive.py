"""Turning a coaching occurrence into at most one candidate, through the
existing gates.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 25. Completion criteria: daily and
weekly loops respect opt-in and the delivery gates; the requested artifact
stays available even when the push is suppressed; one source cannot bypass
another source's dedup key.

Five rules, each with a failure behind it:

1. **One question per occurrence.** The gap is chosen deterministically from
   the coverage, not assembled from everything missing. A morning message
   asking about sleep, weight, food and soreness at once is a form, and
   David has been explicit that a repeated question he already answered is
   worse than no question at all.

2. **Recomputed at delivery, not at claim.** If he logged his weight between
   the sweep and this call, the question is already answered and asking is
   the nag. The state is rebuilt with `fresh=True` here for exactly that.

3. **The dedup key is shared, not per-source.** `fitness_gap:{date}:{metric}`
   is the same string whether the morning brief, the check-in cadence or a
   weekly review produced it — so the second producer dies structurally in
   `say_candidate.create_candidate` rather than both going out. A key with
   the source in it would let each source have its own copy, which is the
   nag-storm shape this subsystem keeps closing.

4. **A suppression is recorded.** Quiet mode, a directive, a disabled
   category and a cooldown each produce a named outcome on the run row. A
   silent bypass makes "why didn't Sara say anything" unanswerable and makes
   a suppression indistinguishable from a bug.

5. **The artifact survives the suppression.** A weekly review that was
   generated and stored stays readable in the Coach tab even when the push
   was refused. Suppressing the notification is not suppressing the work.

Nothing here changes a target or a program. A fatigue concern is a
suggestion, never an automatic deload.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fitness.data_access import _require_user

logger = logging.getLogger(__name__)

#: The shared dedup namespace. Every producer of a missing-data question uses
#: this exact shape, so two producers collide instead of both delivering.
GAP_KEY = "fitness_gap:{day}:{metric}"

#: And for a review notice, keyed on the PERIOD rather than the review id —
#: a superseded review and its replacement are one thing to tell David about.
REVIEW_KEY = "fitness_review:{period_end}"

#: Notification category. `checkin` is already gated by the rhythm anomaly
#: check and the per-category toggle in `unified_notification`, which is the
#: point of reusing it rather than inventing a category with no gates.
CATEGORY_CHECKIN = "checkin"
CATEGORY_REVIEW = "followup"

#: How long a missing-data question stays live. One day: tomorrow's question
#: is a new occurrence, and a stale one accumulating is the harping shape.
GAP_TTL = timedelta(hours=20)
REVIEW_TTL = timedelta(days=3)

#: Minimum hours between two fitness questions, whatever their metric.
#: Separate from the category cooldown because that one is per-category and
#: this is "do not ask me two fitness things in one morning".
GAP_COOLDOWN = timedelta(hours=18)


@dataclass
class GapQuestion:
    metric: str
    key: str
    question: str
    rationale: str
    #: The metric paths this is about, so the artifact can show its basis.
    evidence: List[str] = field(default_factory=list)


@dataclass
class DeliveryOutcome:
    """What happened. `delivered` and `suppressed` are both real successes.

    A run that computed a question and was correctly silenced is not a
    failure, and recording it as one would make the retry logic chase a
    preference.
    """
    delivered: bool
    candidate_id: Optional[str] = None
    suppressed_reason: Optional[str] = None
    question: Optional[GapQuestion] = None

    @property
    def noop_reason(self) -> Optional[str]:
        return self.suppressed_reason


# ─────────────────────────────────────────────────────────────────────────
# Choosing the one thing to ask
# ─────────────────────────────────────────────────────────────────────────

#: Ordered by what unblocks the most. A weigh-in gates the weekly rate;
#: confirmed food days gate every intake average; sleep gates the recovery
#: picture; pain is last because it is only askable when there was a session
#: to ask about.
GAP_ORDER = ("weight", "nutrition", "sleep", "pain")


def choose_gap(state) -> Optional[GapQuestion]:
    """The single most useful missing thing, or None.

    Deterministic: the same state always produces the same question, so two
    producers reach the same dedup key and the second one dies.
    """
    quality = state.quality
    day = state.athlete_local_date.isoformat()

    for metric in GAP_ORDER:
        question = _gap_for(metric, quality, state, day)
        if question is not None:
            return question
    return None


def _gap_for(metric: str, quality, state, day: str) -> Optional[GapQuestion]:
    if metric == "weight":
        observed = quality.observed_weight_days
        expected = quality.expected_weight_days or 7
        if observed is None or observed >= 3:
            return None
        return GapQuestion(
            metric="weight",
            key=GAP_KEY.format(day=day, metric="weight"),
            question="Did you weigh in this morning?",
            rationale=(
                f"{observed} of {expected} days have a weigh-in, and three is "
                f"the minimum for a weekly rate. Without it the rate is "
                f"unknown — not zero."
            ),
            evidence=["weight.velocity_weekly"],
        )

    if metric == "nutrition":
        complete = quality.nutrition_complete_days
        if complete >= 3:
            return None
        return GapQuestion(
            metric="nutrition",
            key=GAP_KEY.format(day=day, metric="nutrition"),
            question="Was yesterday's food log complete?",
            rationale=(
                f"{complete} fully confirmed day(s) this window. An intake "
                f"average over unconfirmed days describes logging habits "
                f"rather than eating."
            ),
            evidence=["nutrition.calories_mean"],
        )

    if metric == "sleep":
        nights = quality.sleep_nights or 0
        if nights >= 3:
            return None
        return GapQuestion(
            metric="sleep",
            key=GAP_KEY.format(day=day, metric="sleep"),
            question="How did you sleep?",
            rationale=(
                f"{nights} night(s) recorded. Sleep is the thing that most "
                f"often explains a bad session, and there is not enough here "
                f"to look."
            ),
            evidence=["sleep.duration_mean"],
        )

    if metric == "pain":
        from app.schemas.fitness_coach import StateSection
        group = state.sections.get(StateSection.PAIN)
        if group is None or not group.items:
            return None
        # Only when a session was NOT asked about. Asking again about one
        # that was is the repeat-question failure.
        for item in group.items:
            total = item.get("sessions_total") or 0
            reported = item.get("sessions_with_report") or 0
            if total > reported:
                return GapQuestion(
                    metric="pain",
                    key=GAP_KEY.format(day=day, metric="pain"),
                    question=(
                        f"How did the {item.get('exercise')} feel last "
                        f"session?"
                    ),
                    rationale=(
                        f"{reported} of {total} sessions with that movement "
                        f"were asked about. A session with no report is "
                        f"unknown, not pain-free."
                    ),
                    evidence=[],
                )
        return None
    return None


# ─────────────────────────────────────────────────────────────────────────
# Delivery
# ─────────────────────────────────────────────────────────────────────────

async def deliver_gap_question(
    db: Session,
    user_id: str,
    *,
    occurrence_key: Optional[str] = None,
) -> DeliveryOutcome:
    """Recompute, choose one question, and offer it to the delivery gates.

    Recomputed HERE rather than at claim time. The occurrence may have been
    claimed twenty minutes ago; if the athlete logged their weight in the
    meantime, the question is answered and asking it is the nag this exists
    to avoid.
    """
    uid = _require_user(user_id)

    from app.services.fitness.state import build_fitness_state

    state = build_fitness_state(db, uid, fresh=True, redis_client=None)
    question = choose_gap(state)
    if question is None:
        return DeliveryOutcome(
            delivered=False, suppressed_reason="nothing_missing",
        )

    recent = _recent_gap_question(db, uid)
    if recent is not None:
        # One fitness question per cooldown window, whatever the metric. The
        # per-category cooldown does not cover this: two different metrics
        # are the same category and would both go out.
        return DeliveryOutcome(
            delivered=False, question=question,
            suppressed_reason=f"asked_recently:{recent}",
        )

    blocked = await _delivery_blocked(uid, question)
    if blocked is not None:
        return DeliveryOutcome(
            delivered=False, question=question, suppressed_reason=blocked,
        )

    candidate_id = await _create_candidate(
        db, uid, question, kind="inform", category=CATEGORY_CHECKIN,
        ttl=GAP_TTL,
    )
    if candidate_id is None:
        # `create_candidate` returned None: a live candidate already carries
        # this dedupe key. Another producer got there first, which is the
        # shared-key design working.
        return DeliveryOutcome(
            delivered=False, question=question,
            suppressed_reason="duplicate_candidate",
        )
    return DeliveryOutcome(
        delivered=True, candidate_id=candidate_id, question=question,
    )


async def deliver_review_notice(
    db: Session,
    user_id: str,
    review,
) -> DeliveryOutcome:
    """Tell David a review is ready, if the gates allow.

    The review itself is already stored and readable in the Coach tab
    regardless of what happens here. Suppressing the notification is not
    suppressing the work, and conflating the two is how a push preference
    silently became a "don't coach me" setting.
    """
    uid = _require_user(user_id)
    open_count = sum(
        1 for rec in getattr(review, "recommendations", [])
        if rec.decision_status.value == "proposed"
    )
    question = GapQuestion(
        metric="review",
        key=REVIEW_KEY.format(period_end=review.period.end.isoformat()),
        question=(
            f"Your review for {review.period.start} to {review.period.end} is "
            f"ready"
            + (f" — {open_count} thing(s) to decide on." if open_count
               else ", with nothing to decide on.")
        ),
        rationale=review.summary or "",
        evidence=[],
    )

    blocked = await _delivery_blocked(uid, question)
    if blocked is not None:
        return DeliveryOutcome(
            delivered=False, question=question, suppressed_reason=blocked,
        )

    candidate_id = await _create_candidate(
        db, uid, question, kind="inform", category=CATEGORY_REVIEW,
        ttl=REVIEW_TTL,
    )
    if candidate_id is None:
        return DeliveryOutcome(
            delivered=False, question=question,
            suppressed_reason="duplicate_candidate",
        )
    return DeliveryOutcome(
        delivered=True, candidate_id=candidate_id, question=question,
    )


async def _delivery_blocked(user_id: str, question: GapQuestion) -> Optional[str]:
    """Every existing gate, each returning its own named reason.

    Named rather than boolean so the run row records WHICH gate fired. "It
    was suppressed" is not an answer to "why didn't Sara say anything".
    """
    # Quiet mode. Checked first because it is the broadest and the cheapest.
    try:
        from app.services.quiet_mode import is_quiet
        if is_quiet():
            return "quiet_mode"
    except Exception as exc:
        logger.debug("quiet-mode check unavailable (%s)", type(exc).__name__)

    # A standing directive ("never bring up X"), and the per-category
    # notification toggle, both live behind `_check_notification_ban`.
    try:
        from app.services.unified_notification import _check_notification_ban
        reason = await _check_notification_ban(
            user_id=user_id,
            title="Fitness",
            message=question.question,
            category=(
                CATEGORY_CHECKIN if question.metric != "review"
                else CATEGORY_REVIEW
            ),
        )
        if reason:
            return f"notification_ban:{reason[:40]}"
    except Exception as exc:
        # Fail OPEN for the candidate, not for the push. The candidate is an
        # artifact David can read; the judge and the delivery path apply
        # their own gates before anything buzzes.
        logger.debug(
            "notification-ban check unavailable (%s)", type(exc).__name__,
        )
    return None


async def _create_candidate(
    db: Session,
    user_id: str,
    question: GapQuestion,
    *,
    kind: str,
    category: str,
    ttl: timedelta,
) -> Optional[str]:
    """Queue the candidate through the existing Mind V2 path.

    Not a direct push. `say_candidate` → judge → compose → review → deliver
    is the single mouth, and a second sender bypassing it is the two-mouths
    failure that was fixed once already. The dedupe key is what makes two
    producers one delivery.
    """
    from app.core.timezone import now as local_now
    from app.db.session import get_async_session_factory
    from app.services.say_candidate import create_candidate

    summary = f"{question.question} {question.rationale}".strip()
    try:
        factory = get_async_session_factory()
        async with factory() as async_db:
            candidate_id = await create_candidate(
                async_db, user_id,
                source="fitness_coach",
                kind=kind,
                summary=summary,
                evidence=question.evidence,
                dedupe_key=question.key,
                valid_until=local_now() + ttl,
            )
            await async_db.commit()
        return str(candidate_id) if candidate_id else None
    except Exception as exc:
        logger.warning(
            "fitness candidate not queued (%s): %s", type(exc).__name__, exc,
        )
        return None


def _recent_gap_question(db: Session, user_id: str) -> Optional[str]:
    """Any fitness question asked inside the cooldown, whatever its metric.

    The per-category cooldown in `unified_notification` does not cover this:
    "did you weigh in" and "how did you sleep" are the same category, so
    both would pass it and David would get two fitness questions in one
    morning.
    """
    try:
        row = db.execute(text("""
            SELECT topic_entities[1] AS key, created_at
            FROM say_candidate
            WHERE user_id = :uid
              AND source = 'fitness_coach'
              AND topic_entities[1] LIKE 'fitness_gap:%'
              AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT 1
        """), {
            "uid": user_id,
            "since": datetime.now(timezone.utc) - GAP_COOLDOWN,
        }).fetchone()
    except Exception as exc:
        # No candidate table, or a shape change. Fail OPEN: a missed
        # cooldown costs one extra question, and failing closed would mean a
        # schema change silenced coaching entirely.
        logger.debug(
            "gap cooldown check unavailable (%s)", type(exc).__name__,
        )
        return None
    if row is None:
        return None
    key = row.key or ""
    return key.rsplit(":", 1)[-1] or "unknown"


# ─────────────────────────────────────────────────────────────────────────
# Deep links
# ─────────────────────────────────────────────────────────────────────────

def deep_link(outcome: DeliveryOutcome, *, review_id: Optional[str] = None) -> str:
    """Where tapping the notification should go.

    Carries an owned id, never a value. A lock-screen preview showing "you
    are 81.2 kg" publishes a body measurement to anyone holding the phone,
    and the id resolves under the owner's auth on the other side.
    """
    if review_id:
        return f"/fitness/coach?review={review_id}"
    metric = (outcome.question.metric if outcome.question else "") or ""
    if metric in ("weight", "nutrition", "sleep", "pain"):
        return f"/fitness/today?ask={metric}"
    return "/fitness/today"
