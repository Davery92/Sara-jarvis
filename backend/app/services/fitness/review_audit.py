"""Storage and the status machine for coach reviews. No model calls.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 19. The gate for this step is
explicit: *"storage/audit state machine and idempotency work without model
integration"* — so this module knows how to open, advance and freeze a
review, and nothing about how one is generated. Step 20 adds the generator
on top.

The four properties this enforces, and what each one prevents:

1. **Idempotency is a database unique index, not a check-then-insert.**
   `open_review` inserts with `ON CONFLICT ... DO NOTHING` and returns the
   existing row. Two workers racing on the same due date therefore produce
   one review and one model call rather than two differently worded answers
   to one question.

2. **A completed review is immutable.** The migration's trigger refuses to
   change its inputs or output; this module never tries. A correction to the
   underlying data produces a LINKED REVISION through `supersede`, so the
   old review still says what it said on the data it had. That is the only
   way "why did you tell me to cut?" stays answerable after the numbers
   move.

3. **The status machine has terminal states.** `complete`, `failed` and
   `insufficient_data` accept no further transitions. Allowing a completed
   review to go back to `running` would mean a stored conclusion could be
   silently replaced in place.

4. **Every read is owner-scoped in the WHERE clause**, not by filtering
   afterwards. A review holds the athlete's body numbers, their goal and
   their limitations; a missed scope here is the worst available outcome.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    COACH_REVIEW_OUTPUT_VERSION,
    CoachRecommendationOut,
    CoachReviewDetail,
    CoachReviewOut,
    CoachReviewOutputV1,
    ConfidenceCategory,
    DecisionStatus,
    FitnessStateV1,
    Period,
    ProposedChange,
    ProposedChangeKind,
    RecommendationCategory,
    RequestedBy,
    ReviewFailureCategory,
    ReviewKind,
    ReviewStatus,
    TERMINAL_REVIEW_STATUSES,
)
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

#: How long an unanswered recommendation stays actionable. A proposal about
#: last week's training is not advice three weeks later, and an unexpiring
#: one accumulates into a list nobody reads.
DEFAULT_RECOMMENDATION_TTL_DAYS = 14

#: Cap on the stored failure detail. A category plus a short line is what a
#: retry decision needs; the prompt and the transcript are deliberately not
#: stored (see the module docstring).
MAX_ERROR_DETAIL = 500

#: Legal transitions. Terminal states have none, which is what makes a
#: stored conclusion un-replaceable in place.
ALLOWED_TRANSITIONS: Dict[ReviewStatus, frozenset] = {
    ReviewStatus.PENDING: frozenset({
        ReviewStatus.RUNNING, ReviewStatus.FAILED,
        ReviewStatus.INSUFFICIENT_DATA,
    }),
    ReviewStatus.RUNNING: frozenset({
        ReviewStatus.COMPLETE, ReviewStatus.FAILED,
        ReviewStatus.INSUFFICIENT_DATA,
    }),
    ReviewStatus.COMPLETE: frozenset(),
    ReviewStatus.FAILED: frozenset(),
    ReviewStatus.INSUFFICIENT_DATA: frozenset(),
}


class ReviewConflict(Exception):
    """An illegal transition, or a terminal review someone tried to change."""

    def __init__(self, message: str, *, review_id: str, status: ReviewStatus):
        super().__init__(message)
        self.review_id = review_id
        self.status = status


# ─────────────────────────────────────────────────────────────────────────
# Hashing
# ─────────────────────────────────────────────────────────────────────────

def input_hash(state: FitnessStateV1) -> str:
    """A fingerprint of the numbers a review will reason from.

    Deliberately excludes `as_of` and `data_revision`. Including them would
    make every run a different question — the same week's figures assembled
    two minutes apart would get two model calls and two answers, which is
    exactly what the idempotency index exists to prevent. What IS included
    is everything that changes the numbers: the period, the metrics, the
    goal, the targets and the coverage.
    """
    payload = state.model_dump(
        mode="json",
        exclude={"as_of", "data_revision", "degraded_dependencies", "freshness"},
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prompt_hash(template: str) -> str:
    """A fingerprint of the prompt TEXT, so a silent edit is detectable.

    The text itself is not stored. A hash answers "was this the same prompt?"
    without keeping a copy of the instructions beside every athlete's
    private data.
    """
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────
# Opening a review
# ─────────────────────────────────────────────────────────────────────────

def open_review(
    db: Session,
    user_id: str,
    *,
    kind: ReviewKind,
    state: FitnessStateV1,
    prompt_version: str,
    prompt_template_hash: Optional[str] = None,
    model_requested: Optional[str] = None,
    provider: Optional[str] = None,
    requested_by: RequestedBy = RequestedBy.SCHEDULE,
    run_id: Optional[str] = None,
    supersedes_id: Optional[str] = None,
) -> CoachReviewOut:
    """Open a review, or return the one that already answers this question.

    Idempotent through the database's own unique index rather than a
    check-then-insert: two schedulers firing on the same due date produce one
    review and one model call. A check-then-insert loses that race and the
    athlete gets two differently worded answers to one question.

    `supersedes_id` links this run to an earlier review of the same period —
    used when corrected data makes the old one stale. The old review is NOT
    modified beyond its `superseded_by_id` pointer; its inputs and its
    conclusion stay exactly as they were.
    """
    uid = _require_user(user_id)
    if state.period is None:
        raise FitnessDataError("a review needs an explicit period")
    if state.user_id != uid:
        # The state carries its own owner. A mismatch means the caller is
        # about to store one athlete's numbers under another's review.
        raise FitnessDataError(
            "the state's owner does not match the review's owner"
        )

    digest = input_hash(state)
    review_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    if supersedes_id:
        previous = _row(db, uid, supersedes_id)
        if previous is None:
            raise LookupError("the review to supersede was not found")
        revision = int(previous.revision) + 1
        # Link the OLD row forward BEFORE inserting the new one.
        # `uq_coach_review_current` is a partial unique index, so PostgreSQL
        # checks it at every statement: inserting the successor while the
        # predecessor is still unlinked means two current reviews for one
        # period for the duration of one statement, and the index refuses
        # it. The self-FK is DEFERRABLE precisely so this order works.
        db.execute(text("""
            UPDATE fitness_coach_review SET superseded_by_id = :new
            WHERE id = :old AND user_id = :uid
        """), {"new": review_id, "old": supersedes_id, "uid": uid})
    else:
        revision = 1
        # One current answer per period. A second independent review — a new
        # prompt version, or data that moved — is a linked REVISION, and the
        # caller has to say which review it revises. Letting it through as a
        # parallel current row is the two-live-answers condition where
        # nothing in the system says which is right.
        existing_current = db.execute(text("""
            SELECT id, input_hash, prompt_version, status
            FROM fitness_coach_review
            WHERE user_id = :uid AND kind = :kind
              AND period_start = :start AND period_end = :end
              AND superseded_by_id IS NULL
        """), {
            "uid": uid, "kind": kind.value,
            "start": state.period.start, "end": state.period.end,
        }).fetchone()
        if existing_current is not None and (
            existing_current.input_hash != digest
            or existing_current.prompt_version != prompt_version
        ):
            raise ReviewConflict(
                "a review of this period already exists with different "
                "inputs or a different prompt version; supersede it rather "
                "than opening a parallel one",
                review_id=existing_current.id,
                status=ReviewStatus(existing_current.status),
            )

    inserted = db.execute(text("""
        INSERT INTO fitness_coach_review (
            id, user_id, kind, period_start, period_end, status,
            input_state, input_hash, state_schema_version, analytics_version,
            data_revision, collected_at, source_cutoff,
            model_requested, provider, prompt_version, prompt_hash,
            requested_by, run_id, attempt, supersedes_id, revision
        ) VALUES (
            :id, :uid, :kind, :start, :end, 'pending',
            CAST(:state AS jsonb), :hash, :schema_v, :analytics_v,
            :revision_fp, :collected, :cutoff,
            :model, :provider, :prompt_v, :prompt_h,
            :by, :run, 1, :sup, :rev
        )
        ON CONFLICT (user_id, kind, period_start, period_end, input_hash,
                     prompt_version)
        DO NOTHING
        RETURNING id
    """), {
        "id": review_id, "uid": uid, "kind": kind.value,
        "start": state.period.start, "end": state.period.end,
        "state": state.model_dump_json(),
        "hash": digest,
        "schema_v": state.schema_version,
        "analytics_v": state.analytics_version,
        "revision_fp": state.data_revision,
        "collected": state.as_of, "cutoff": now,
        "model": model_requested, "provider": provider,
        "prompt_v": prompt_version, "prompt_h": prompt_template_hash,
        "by": requested_by.value, "run": run_id,
        "sup": supersedes_id, "rev": revision,
    }).fetchone()

    if inserted is None:
        # Someone already asked this exact question. Return their run.
        existing = db.execute(text("""
            SELECT * FROM fitness_coach_review
            WHERE user_id = :uid AND kind = :kind
              AND period_start = :start AND period_end = :end
              AND input_hash = :hash AND prompt_version = :prompt_v
        """), {
            "uid": uid, "kind": kind.value,
            "start": state.period.start, "end": state.period.end,
            "hash": digest, "prompt_v": prompt_version,
        }).fetchone()
        if existing is None:  # pragma: no cover - the conflict just happened
            raise FitnessDataError("review conflicted but could not be read back")
        if supersedes_id:
            # A retried supersede. The forward link above pointed at an id
            # that was never inserted, so put it back to the row that really
            # does supersede it — otherwise the predecessor is orphaned and
            # the chain breaks.
            db.execute(text("""
                UPDATE fitness_coach_review SET superseded_by_id = :real
                WHERE id = :old AND user_id = :uid
            """), {"real": existing.id, "old": supersedes_id, "uid": uid})
        return _review_out(existing)

    return _review_out(_row(db, uid, review_id))


def find_current_review(
    db: Session, user_id: str, *, kind: ReviewKind, period: Period,
) -> Optional[CoachReviewOut]:
    """The live review for this period, if any. Superseded ones are excluded."""
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT * FROM fitness_coach_review
        WHERE user_id = :uid AND kind = :kind
          AND period_start = :start AND period_end = :end
          AND superseded_by_id IS NULL
        ORDER BY revision DESC
        LIMIT 1
    """), {
        "uid": uid, "kind": kind.value,
        "start": period.start, "end": period.end,
    }).fetchone()
    return _review_out(row) if row else None


def needs_rerun(
    db: Session, user_id: str, *, kind: ReviewKind, state: FitnessStateV1,
) -> Optional[CoachReviewOut]:
    """The current review this state would supersede, or None.

    None means either there is no review for the period, or the existing one
    already reasoned from exactly these numbers. The second case is the one
    that matters: re-running it would spend a model call to restate a
    conclusion that has not changed.
    """
    if state.period is None:
        return None
    current = find_current_review(db, user_id, kind=kind, period=state.period)
    if current is None:
        return None
    if current.input_hash == input_hash(state):
        return None
    return current


# ─────────────────────────────────────────────────────────────────────────
# The status machine
# ─────────────────────────────────────────────────────────────────────────

def _transition(
    db: Session, user_id: str, review_id: str, to: ReviewStatus,
    assignments: Dict[str, Any],
) -> CoachReviewOut:
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, status, attempt FROM fitness_coach_review
        WHERE id = :id AND user_id = :uid
        FOR UPDATE
    """), {"id": review_id, "uid": uid}).fetchone()
    if row is None:
        # 404, never 403: confirming the row exists to someone who does not
        # own it is itself a disclosure.
        raise LookupError("review not found")

    current = ReviewStatus(row.status)
    if to not in ALLOWED_TRANSITIONS[current]:
        raise ReviewConflict(
            f"a review that is {current.value} cannot become {to.value}"
            + (" — terminal reviews are immutable; supersede it instead"
               if current in TERMINAL_REVIEW_STATUSES else ""),
            review_id=review_id, status=current,
        )

    assignments = dict(assignments)
    assignments["status"] = to.value
    columns = ", ".join(
        f"{name} = CAST(:{name} AS jsonb)" if name in ("output", "evidence_refs")
        else f"{name} = :{name}"
        for name in assignments
    )
    params = dict(assignments)
    params["id"] = review_id
    params["uid"] = uid
    db.execute(text(f"""
        UPDATE fitness_coach_review SET {columns}
        WHERE id = :id AND user_id = :uid
    """), params)
    return _review_out(_row(db, uid, review_id))


def mark_running(
    db: Session, user_id: str, review_id: str, *,
    model_actual: Optional[str] = None, run_id: Optional[str] = None,
) -> CoachReviewOut:
    """Claim the review for a worker.

    `model_actual` is recorded here rather than at completion so that a run
    which times out still says which model was asked. A fallback that
    answered as the primary makes every later comparison meaningless.
    """
    assignments: Dict[str, Any] = {}
    if model_actual is not None:
        assignments["model_actual"] = model_actual
    if run_id is not None:
        assignments["run_id"] = run_id
    return _transition(db, user_id, review_id, ReviewStatus.RUNNING, assignments)


def mark_complete(
    db: Session,
    user_id: str,
    review_id: str,
    *,
    output: CoachReviewOutputV1,
    model_actual: Optional[str] = None,
    evidence_refs: Optional[Sequence[str]] = None,
) -> CoachReviewOut:
    """Freeze the review with its validated output.

    After this the row's inputs and output are immutable — the migration's
    trigger refuses to change them. Everything that follows (recommendations,
    acceptance, the target revision) hangs off this frozen record.
    """
    assignments: Dict[str, Any] = {
        "output": output.model_dump_json(),
        "summary": output.summary,
        "evidence_refs": json.dumps(list(evidence_refs or output.referenced_evidence())),
        "output_schema_version": output.output_version,
        "evaluated_at": datetime.now(timezone.utc),
    }
    if model_actual is not None:
        assignments["model_actual"] = model_actual
    return _transition(db, user_id, review_id, ReviewStatus.COMPLETE, assignments)


def mark_failed(
    db: Session,
    user_id: str,
    review_id: str,
    *,
    category: ReviewFailureCategory,
    detail: Optional[str] = None,
    model_actual: Optional[str] = None,
) -> CoachReviewOut:
    """Record that no output was produced, and why — as a category.

    `detail` is truncated. A failed review that banked the full prompt and
    the raw model text would make this table the largest copy of the
    athlete's private data in the database, kept for the least useful reason.
    """
    assignments: Dict[str, Any] = {
        "error_category": category.value,
        "error_detail": (detail or "")[:MAX_ERROR_DETAIL] or None,
        "evaluated_at": datetime.now(timezone.utc),
    }
    if model_actual is not None:
        assignments["model_actual"] = model_actual
    return _transition(db, user_id, review_id, ReviewStatus.FAILED, assignments)


def mark_insufficient_data(
    db: Session, user_id: str, review_id: str, *, detail: Optional[str] = None,
) -> CoachReviewOut:
    """A distinct terminal state, not a failure.

    "There is not enough data to say anything useful" is a correct and
    complete answer, and the right response to it is to log more — not to
    retry the model. Folding it into `failed` would make a retry loop chase
    a condition no retry can fix.
    """
    return _transition(
        db, user_id, review_id, ReviewStatus.INSUFFICIENT_DATA,
        {
            "error_category": ReviewFailureCategory.INSUFFICIENT_DATA.value,
            "error_detail": (detail or "")[:MAX_ERROR_DETAIL] or None,
            "evaluated_at": datetime.now(timezone.utc),
        },
    )


def record_attempt(db: Session, user_id: str, review_id: str) -> int:
    """Increment the attempt counter. Permitted only before a terminal state."""
    uid = _require_user(user_id)
    row = db.execute(text("""
        UPDATE fitness_coach_review SET attempt = attempt + 1
        WHERE id = :id AND user_id = :uid
          AND status NOT IN ('complete', 'failed', 'insufficient_data')
        RETURNING attempt
    """), {"id": review_id, "uid": uid}).fetchone()
    if row is None:
        raise ReviewConflict(
            "a terminal review's attempt count cannot change",
            review_id=review_id, status=ReviewStatus.COMPLETE,
        )
    return int(row.attempt)


def supersede(
    db: Session,
    user_id: str,
    review_id: str,
    *,
    state: FitnessStateV1,
    prompt_version: str,
    kind: ReviewKind,
    **kwargs: Any,
) -> CoachReviewOut:
    """Open a linked successor after the underlying data changed.

    The old review is retained in full. It was a correct reading of the data
    it had, and it is the only record of why a decision was made at the time
    — overwriting it would make the audit trail describe only the present.
    """
    return open_review(
        db, user_id, kind=kind, state=state, prompt_version=prompt_version,
        supersedes_id=review_id, **kwargs,
    )


# ─────────────────────────────────────────────────────────────────────────
# Recommendations
# ─────────────────────────────────────────────────────────────────────────

def record_recommendations(
    db: Session,
    user_id: str,
    review_id: str,
    output: CoachReviewOutputV1,
    *,
    current_target_revision_id: Optional[str] = None,
    current_phase_id: Optional[str] = None,
    ttl_days: int = DEFAULT_RECOMMENDATION_TTL_DAYS,
) -> List[CoachRecommendationOut]:
    """Store the review's recommendations as PROPOSALS.

    Nothing here applies anything. `decision_status` starts at `proposed`
    and the database refuses to let a row claim `accepted` without an action
    receipt or the target revision it produced, so a recommendation cannot
    masquerade as a change that happened.

    `current_target_revision_id` records what each proposal was measured
    against, which is how a stale proposal — one written against a target the
    athlete has since changed — is detectable at acceptance time rather than
    being silently applied over the newer value.
    """
    uid = _require_user(user_id)
    review = _row(db, uid, review_id)
    if review is None:
        raise LookupError("review not found")

    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    out: List[CoachRecommendationOut] = []

    for index, rec in enumerate(output.recommendations):
        rec_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO fitness_coach_recommendation (
                id, review_id, user_id, category, action, title, rationale,
                confidence, confidence_basis, limitations,
                metric_paths, evidence_refs, proposed_change,
                current_target_revision_id, current_phase_id,
                expires_at, decision_status, priority
            ) VALUES (
                :id, :review, :uid, :cat, :action, :title, :why,
                :conf, :basis, :limits,
                CAST(:paths AS jsonb), CAST(:evidence AS jsonb),
                CAST(:change AS jsonb),
                :target_rev, :phase,
                :expires, 'proposed', :priority
            )
        """), {
            "id": rec_id, "review": review_id, "uid": uid,
            "cat": rec.category.value,
            "action": rec.proposed_change.kind.value,
            "title": rec.headline, "why": rec.rationale,
            "conf": rec.confidence.value, "basis": rec.confidence_basis,
            "limits": "\n".join(output.limitations) or None,
            "paths": json.dumps(list(rec.metric_paths)),
            "evidence": json.dumps(list(rec.evidence_refs)),
            "change": rec.proposed_change.model_dump_json(),
            "target_rev": current_target_revision_id,
            "phase": current_phase_id,
            "expires": expires,
            # Order as the model ranked them, clamped into the column's
            # range. Not a model-supplied number: a self-assigned priority
            # of 1 on every item is how everything becomes urgent.
            "priority": min(index + 1, 10),
        })
        out.append(get_recommendation(db, uid, rec_id))
    return out


def get_recommendation(
    db: Session, user_id: str, recommendation_id: str,
) -> CoachRecommendationOut:
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT * FROM fitness_coach_recommendation
        WHERE id = :id AND user_id = :uid
    """), {"id": recommendation_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("recommendation not found")
    return _recommendation_out(row)


def list_recommendations(
    db: Session,
    user_id: str,
    *,
    review_id: Optional[str] = None,
    status: Optional[DecisionStatus] = None,
    include_expired: bool = False,
    limit: int = 50,
) -> List[CoachRecommendationOut]:
    uid = _require_user(user_id)
    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": uid, "lim": max(1, min(limit, 200))}
    if review_id:
        clauses.append("review_id = :review")
        params["review"] = review_id
    if status:
        clauses.append("decision_status = :status")
        params["status"] = status.value
    if not include_expired:
        # An expired proposal is retained but is not advice any more, and a
        # proposal past its deadline is expired whether or not the sweep has
        # run yet. Both are excluded from the default list and both stay
        # queryable with `include_expired`, because "what did you suggest in
        # September" has to remain answerable.
        clauses.append("decision_status <> 'expired'")
        clauses.append(
            "(decision_status <> 'proposed' OR expires_at IS NULL "
            "OR expires_at > NOW())"
        )
    rows = db.execute(text(f"""
        SELECT * FROM fitness_coach_recommendation
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC, priority ASC
        LIMIT :lim
    """), params).fetchall()
    return [_recommendation_out(r) for r in rows]


def decide(
    db: Session,
    user_id: str,
    recommendation_id: str,
    *,
    decision: DecisionStatus,
    decided_by: str = "user",
    note: Optional[str] = None,
    action_receipt_id: Optional[str] = None,
    applied_revision_id: Optional[str] = None,
) -> CoachRecommendationOut:
    """Record a decision. Does not perform the change.

    Accepting a proposal and applying it are two steps on purpose. This
    records the decision; the caller performs the change and passes back the
    receipt or the revision it produced. The database refuses an `accepted`
    row with neither, so "I accepted it" cannot be stored as though the
    change had happened.
    """
    uid = _require_user(user_id)
    if decision is DecisionStatus.PROPOSED:
        raise FitnessDataError("'proposed' is the initial state, not a decision")
    if decision is DecisionStatus.ACCEPTED and not (
        action_receipt_id or applied_revision_id
    ):
        raise FitnessDataError(
            "accepting a recommendation requires the action receipt or the "
            "target revision it produced — otherwise the row would claim an "
            "effect it did not have"
        )

    row = db.execute(text("""
        SELECT decision_status FROM fitness_coach_recommendation
        WHERE id = :id AND user_id = :uid
        FOR UPDATE
    """), {"id": recommendation_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("recommendation not found")
    if row.decision_status != DecisionStatus.PROPOSED.value:
        raise FitnessDataError(
            f"this recommendation was already {row.decision_status}; a "
            "decision is recorded once"
        )

    db.execute(text("""
        UPDATE fitness_coach_recommendation
        SET decision_status = :status,
            decided_at = NOW(),
            decided_by = :by,
            decision_note = :note,
            action_receipt_id = :receipt,
            applied_revision_id = :revision
        WHERE id = :id AND user_id = :uid
    """), {
        "status": decision.value, "by": decided_by, "note": note,
        "receipt": action_receipt_id, "revision": applied_revision_id,
        "id": recommendation_id, "uid": uid,
    })
    return get_recommendation(db, uid, recommendation_id)


def expire_stale_recommendations(db: Session, user_id: str) -> int:
    """Mark passed-deadline proposals expired. Retained, never deleted.

    A proposal about last week's training is not advice three weeks later,
    but "what did you suggest and what did I do about it" has to stay
    answerable — so this changes the status and keeps the row.
    """
    uid = _require_user(user_id)
    result = db.execute(text("""
        UPDATE fitness_coach_recommendation
        SET decision_status = 'expired', decided_at = NOW(), decided_by = 'expiry'
        WHERE user_id = :uid AND decision_status = 'proposed'
          AND expires_at IS NOT NULL AND expires_at <= NOW()
    """), {"uid": uid})
    return result.rowcount or 0


# ─────────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────────

def list_reviews(
    db: Session,
    user_id: str,
    *,
    kind: Optional[ReviewKind] = None,
    include_superseded: bool = False,
    limit: int = 20,
) -> List[CoachReviewOut]:
    uid = _require_user(user_id)
    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": uid, "lim": max(1, min(limit, 100))}
    if kind:
        clauses.append("kind = :kind")
        params["kind"] = kind.value
    if not include_superseded:
        clauses.append("superseded_by_id IS NULL")
    rows = db.execute(text(f"""
        SELECT * FROM fitness_coach_review
        WHERE {' AND '.join(clauses)}
        ORDER BY period_end DESC, revision DESC
        LIMIT :lim
    """), params).fetchall()
    return [_review_out(r) for r in rows]


def get_review(
    db: Session, user_id: str, review_id: str, *, with_state: bool = False,
) -> CoachReviewDetail:
    """One review. `with_state` adds the frozen input snapshot.

    Opt-in because it is a whole `FitnessStateV1` — the screen that answers
    "what did you reason from?" wants it; a list does not, and shipping it
    by default would put the athlete's full state into every response.
    """
    uid = _require_user(user_id)
    row = _row(db, uid, review_id)
    if row is None:
        raise LookupError("review not found")

    base = _review_out(row).model_dump()
    detail = CoachReviewDetail(**base)

    if row.output:
        try:
            detail.output = CoachReviewOutputV1.model_validate(_as_json(row.output))
        except Exception as exc:
            # A stored output that no longer validates is a schema change,
            # not a reason to serve nothing. The summary and the
            # recommendations are still true statements of what was said.
            logger.warning(
                "stored review %s output does not validate against the current "
                "schema (%s); serving summary only", review_id, type(exc).__name__,
            )
    if with_state and row.input_state:
        try:
            detail.input_state = FitnessStateV1.model_validate(_as_json(row.input_state))
        except Exception as exc:
            logger.warning(
                "stored review %s input state does not validate (%s)",
                review_id, type(exc).__name__,
            )
    detail.recommendations = list_recommendations(
        db, uid, review_id=review_id, include_expired=True,
    )
    return detail


def revision_chain(
    db: Session, user_id: str, review_id: str,
) -> List[CoachReviewOut]:
    """Every revision of this review, oldest first.

    Walked through the supersedes links rather than selected by period, so a
    chain stays intact even if a later revision covers a corrected period.
    """
    uid = _require_user(user_id)
    rows = db.execute(text("""
        WITH RECURSIVE back AS (
            SELECT * FROM fitness_coach_review
            WHERE id = :id AND user_id = :uid
            UNION
            SELECT r.* FROM fitness_coach_review r
            JOIN back b ON r.id = b.supersedes_id
            WHERE r.user_id = :uid
        ), forward AS (
            SELECT * FROM fitness_coach_review
            WHERE id = :id AND user_id = :uid
            UNION
            SELECT r.* FROM fitness_coach_review r
            JOIN forward f ON r.id = f.superseded_by_id
            WHERE r.user_id = :uid
        )
        SELECT * FROM back
        UNION
        SELECT * FROM forward
        ORDER BY revision ASC
    """), {"id": review_id, "uid": uid}).fetchall()
    return [_review_out(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# Row adapters
# ─────────────────────────────────────────────────────────────────────────

def _row(db: Session, user_id: str, review_id: str):
    return db.execute(text("""
        SELECT * FROM fitness_coach_review
        WHERE id = :id AND user_id = :uid
    """), {"id": review_id, "uid": user_id}).fetchone()


def _as_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _review_out(row: Any) -> CoachReviewOut:
    m = dict(row._mapping)
    return CoachReviewOut(
        id=m["id"], user_id=m["user_id"], kind=ReviewKind(m["kind"]),
        period=Period(start=m["period_start"], end=m["period_end"]),
        status=ReviewStatus(m["status"]),
        input_hash=m["input_hash"],
        state_schema_version=m["state_schema_version"],
        analytics_version=m["analytics_version"],
        data_revision=m.get("data_revision"),
        collected_at=m["collected_at"],
        source_cutoff=m.get("source_cutoff"),
        model_requested=m.get("model_requested"),
        model_actual=m.get("model_actual"),
        provider=m.get("provider"),
        prompt_version=m["prompt_version"],
        prompt_hash=m.get("prompt_hash"),
        output_schema_version=m.get("output_schema_version"),
        summary=m.get("summary"),
        evidence_refs=list(_as_json(m.get("evidence_refs")) or []),
        error_category=(
            ReviewFailureCategory(m["error_category"])
            if m.get("error_category") else None
        ),
        error_detail=m.get("error_detail"),
        run_id=m.get("run_id"),
        attempt=int(m.get("attempt") or 1),
        revision=int(m.get("revision") or 1),
        supersedes_id=m.get("supersedes_id"),
        superseded_by_id=m.get("superseded_by_id"),
        requested_by=RequestedBy(m.get("requested_by") or "schedule"),
        evaluated_at=m.get("evaluated_at"),
        created_at=m["created_at"],
    )


def _recommendation_out(row: Any) -> CoachRecommendationOut:
    m = dict(row._mapping)
    change = _as_json(m.get("proposed_change")) or {}
    try:
        proposed = ProposedChange.model_validate(change)
    except Exception:
        # A stored proposal that no longer validates must not be rendered as
        # an actionable change. `none` is the honest reading.
        proposed = ProposedChange()
    return CoachRecommendationOut(
        id=m["id"], review_id=m["review_id"], user_id=m["user_id"],
        category=RecommendationCategory(m["category"]),
        action=ProposedChangeKind(m.get("action") or "none"),
        title=m["title"], rationale=m["rationale"],
        confidence=ConfidenceCategory(m["confidence"]),
        confidence_basis=m.get("confidence_basis"),
        limitations=m.get("limitations"),
        metric_paths=list(_as_json(m.get("metric_paths")) or []),
        evidence_refs=list(_as_json(m.get("evidence_refs")) or []),
        proposed_change=proposed,
        current_target_revision_id=m.get("current_target_revision_id"),
        current_phase_id=m.get("current_phase_id"),
        expires_at=m.get("expires_at"),
        decision_status=DecisionStatus(m["decision_status"]),
        decided_at=m.get("decided_at"),
        decided_by=m.get("decided_by"),
        decision_note=m.get("decision_note"),
        action_receipt_id=m.get("action_receipt_id"),
        applied_revision_id=m.get("applied_revision_id"),
        priority=int(m.get("priority") or 5),
        created_at=m["created_at"],
    )
