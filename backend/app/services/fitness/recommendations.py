"""Accepting or rejecting a coach recommendation.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 21. Completion criterion: *"User
approves an exact reviewable change, not a vague intention."*

That is what `preview` is for. It renders the typed old → proposed values,
the scope, the effective date, the coverage behind it, and whether the
proposal has gone stale — so the thing David approves is a specific diff, not
"Sara thinks I should eat less".

Four properties, and what each one prevents:

1. **Acceptance is atomic.** The target revision, the decision transition and
   the action receipt commit together. A receipt without a revision claims an
   effect that never happened; a revision without a receipt leaves a change
   nothing can trace back to an approval.
2. **Acceptance is idempotent.** The recommendation row is locked `FOR
   UPDATE` and a decision may be recorded once, so a double-tap returns the
   existing receipt rather than appending a second revision. Under
   concurrency exactly one caller wins.
3. **Staleness is refused, with a reason.** A proposal written against a
   target the athlete has since changed would otherwise be applied over the
   newer value — silently undoing a deliberate edit. Expired, superseded and
   stale proposals get a 409 naming what moved.
4. **An unsupported action does not execute.** `program_change` has no typed
   service until Step 29, so accepting one records the decision and the
   reason it could not be applied rather than improvising a plan edit. The
   advice stays readable with a link to make the change by hand.

`claim_operation` from `action_receipt_service` is deliberately NOT used:
it commits internally, which would break property 1. The receipt is written
here, in the caller's transaction, with the same `idempotency_key` discipline
and the same row shape.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    CoachRecommendationOut,
    DecisionStatus,
    ProposedChangeKind,
    TargetRevisionIn,
    TargetScope,
    TargetValues,
)
from app.services.fitness import review_audit, safety
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

#: `action_type` on the receipt. Distinct from any chat tool name, so a
#: receipt from a reviewed coaching change is never mistaken for one from a
#: chat tool call — different authorization paths, different audit meaning.
RECEIPT_ACTION_TYPE = "fitness_coach_recommendation_accepted"

#: Actions this step can actually perform. `program_change` is deliberately
#: absent: restructuring a program needs the typed program service from Step
#: 29, and improvising one from a JSON blob is how a plan gets edited in a
#: way nobody can review.
APPLICABLE_ACTIONS = frozenset({
    ProposedChangeKind.NONE,
    ProposedChangeKind.DATA_REQUEST,
    ProposedChangeKind.TARGET_REVISION,
})


class RecommendationStale(Exception):
    """The proposal no longer describes the athlete's current situation."""

    def __init__(self, message: str, *, code: str, recommendation_id: str,
                 current: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.recommendation_id = recommendation_id
        self.current = current or {}


class RecommendationUnsupported(Exception):
    """A real proposal this step cannot perform. Reviewable, not executable."""

    def __init__(self, message: str, *, action: str, recommendation_id: str):
        super().__init__(message)
        self.action = action
        self.recommendation_id = recommendation_id


# ─────────────────────────────────────────────────────────────────────────
# Preview
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class FieldChange:
    field: str
    current: Optional[float]
    proposed: Optional[float]
    unit: str

    @property
    def delta(self) -> Optional[float]:
        if self.current is None or self.proposed is None:
            return None
        return round(self.proposed - self.current, 2)

    @property
    def is_change(self) -> bool:
        return self.current != self.proposed


@dataclass
class RecommendationPreview:
    """Exactly what accepting this would do.

    `changes` is empty for a `maintain` or `request_data` proposal, and that
    is the honest rendering: accepting it records agreement, not a change.
    `blockers` is what would make acceptance fail — shown BEFORE the button
    rather than discovered by pressing it.
    """
    recommendation: CoachRecommendationOut
    applicable: bool
    changes: List[FieldChange] = field(default_factory=list)
    scope: Optional[str] = None
    effective_date: Optional[date] = None
    current_revision_id: Optional[str] = None
    latest_revision_id: Optional[str] = None
    stale: bool = False
    expired: bool = False
    blockers: List[str] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)

    @property
    def acceptable(self) -> bool:
        return self.applicable and not self.blockers


_TARGET_FIELDS = (
    ("calories", "kcal"), ("protein_g", "g"), ("carbs_g", "g"),
    ("fat_g", "g"), ("sleep_hours", "h"), ("water_ml", "ml"), ("steps", "count"),
)


def preview(
    db: Session, user_id: str, recommendation_id: str,
) -> RecommendationPreview:
    """Render the proposal as a concrete diff, with its blockers.

    Read-only. Blockers are surfaced here so a client can show "this is out
    of date, ask for a fresh review" instead of offering an Accept button
    that 409s — a button that fails is worse than one that is not there.
    """
    uid = _require_user(user_id)
    rec = review_audit.get_recommendation(db, uid, recommendation_id)
    change = rec.proposed_change

    out = RecommendationPreview(
        recommendation=rec,
        applicable=change.kind in APPLICABLE_ACTIONS,
        scope=change.scope.value if change.scope else None,
        effective_date=change.effective_date,
        current_revision_id=rec.current_target_revision_id,
    )

    if rec.decision_status is not DecisionStatus.PROPOSED:
        out.blockers.append(
            f"this recommendation was already {rec.decision_status.value}; "
            f"a decision is recorded once"
        )
    if rec.expires_at and rec.expires_at <= datetime.now(timezone.utc):
        out.expired = True
        out.blockers.append(
            "this proposal has expired — the week it was about is no longer "
            "the current week"
        )
    if change.kind not in APPLICABLE_ACTIONS:
        out.blockers.append(
            f"a {change.kind.value} proposal cannot be applied automatically "
            f"yet; it is advice to act on by hand"
        )

    if change.kind is ProposedChangeKind.TARGET_REVISION and change.target_values:
        current = _current_target_values(db, uid, change)
        for name, unit in _TARGET_FIELDS:
            proposed_value = getattr(change.target_values, name, None)
            current_value = getattr(current, name, None) if current else None
            if proposed_value is None and current_value is None:
                continue
            out.changes.append(FieldChange(
                field=name, current=current_value, proposed=proposed_value,
                unit=unit,
            ))

        latest = _latest_revision_id(db, uid, change.scope)
        out.latest_revision_id = latest
        if rec.current_target_revision_id and latest and \
                latest != rec.current_target_revision_id:
            out.stale = True
            out.blockers.append(
                "the targets have changed since this was proposed, so "
                "accepting it would apply an old comparison over a newer "
                "decision"
            )
        if not any(c.is_change for c in out.changes):
            out.blockers.append(
                "the proposed values match the current targets, so there is "
                "nothing to apply"
            )

    # Coverage travels with the proposal. The confidence label is the model's
    # interpretation; this is how much data is behind it, and a reader needs
    # the pair (§9.6).
    review = review_audit.get_review(db, uid, rec.review_id, with_state=True)
    if review.input_state is not None:
        quality = review.input_state.quality
        out.coverage = {
            "observed_weight_days": quality.observed_weight_days,
            "expected_weight_days": quality.expected_weight_days,
            "nutrition_complete_days": quality.nutrition_complete_days,
            "sleep_nights": quality.sleep_nights,
            "period_start": review.period.start.isoformat(),
            "period_end": review.period.end.isoformat(),
        }
    out.limitations = [rec.limitations] if rec.limitations else []
    return out


def _current_target_values(
    db: Session, user_id: str, change,
) -> Optional[TargetValues]:
    """The targets in force on the proposal's effective date.

    Resolved for that date rather than for today, because that is the day
    the change would take effect and a block boundary in between would make
    today's numbers the wrong comparison.
    """
    from app.services.fitness.targets import resolve_targets
    on_date = change.effective_date or date.today()
    try:
        return resolve_targets(db, user_id, on_date).values
    except Exception as exc:
        logger.debug("could not resolve current targets: %s", exc)
        return None


def _latest_revision_id(
    db: Session, user_id: str, scope: Optional[TargetScope],
) -> Optional[str]:
    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": user_id}
    if scope is not None:
        clauses.append("scope = :scope")
        params["scope"] = scope.value
    row = db.execute(text(f"""
        SELECT id FROM fitness_target_revision
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC, version DESC
        LIMIT 1
    """), params).fetchone()
    return row.id if row else None


# ─────────────────────────────────────────────────────────────────────────
# Reject
# ─────────────────────────────────────────────────────────────────────────

def reject(
    db: Session,
    user_id: str,
    recommendation_id: str,
    *,
    note: Optional[str] = None,
    decided_by: str = "user",
) -> CoachRecommendationOut:
    """Record a rejection. Changes nothing, keeps the row.

    Retained because "what did you suggest and what did I do about it" has
    to stay answerable — and because a rejected proposal is the strongest
    signal available about what this athlete does not want.
    """
    uid = _require_user(user_id)
    result = review_audit.decide(
        db, uid, recommendation_id, decision=DecisionStatus.REJECTED,
        decided_by=decided_by, note=note,
    )
    db.commit()
    return result


# ─────────────────────────────────────────────────────────────────────────
# Accept
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class AcceptanceResult:
    recommendation: CoachRecommendationOut
    #: The receipt that proves an execution happened. Always present on an
    #: accepted row — the database refuses one without it.
    action_receipt_id: str
    applied_revision_id: Optional[str] = None
    #: Rendered from the COMMITTED outcome, not from the intent. A message
    #: composed before the write would describe a change that may not have
    #: landed.
    message: str = ""
    duplicate: bool = False


def accept(
    db: Session,
    user_id: str,
    recommendation_id: str,
    *,
    decided_by: str = "user",
    note: Optional[str] = None,
) -> AcceptanceResult:
    """Apply a proposal and record the decision, atomically.

    The order inside one transaction:

        lock the recommendation  →  re-check  →  append the revision
        →  write the receipt  →  transition the decision  →  commit

    Locking first is what makes concurrent acceptance safe: the second caller
    blocks, then finds the row already decided and returns the first
    caller's receipt instead of appending a second revision.

    Re-checking after the lock, not before, is the other half. A proposal
    that was acceptable when the preview rendered may have gone stale in
    between — the athlete could have edited their targets on another device.
    """
    uid = _require_user(user_id)

    locked = db.execute(text("""
        SELECT id, review_id, decision_status, action_receipt_id,
               applied_revision_id, expires_at, proposed_change,
               current_target_revision_id, category
        FROM fitness_coach_recommendation
        WHERE id = :id AND user_id = :uid
        FOR UPDATE
    """), {"id": recommendation_id, "uid": uid}).fetchone()
    if locked is None:
        # 404 for a foreign id, never 403: confirming it exists is itself a
        # disclosure.
        raise LookupError("recommendation not found")

    if locked.decision_status == DecisionStatus.ACCEPTED.value:
        # Idempotent. The caller gets the receipt from the first acceptance
        # rather than a second revision appended to the athlete's history.
        existing = review_audit.get_recommendation(db, uid, recommendation_id)
        return AcceptanceResult(
            recommendation=existing,
            action_receipt_id=existing.action_receipt_id or "",
            applied_revision_id=existing.applied_revision_id,
            message=_committed_message(db, uid, existing),
            duplicate=True,
        )
    if locked.decision_status != DecisionStatus.PROPOSED.value:
        raise RecommendationStale(
            f"this recommendation was already {locked.decision_status}; a "
            f"decision is recorded once",
            code="already_decided", recommendation_id=recommendation_id,
            current={"decision_status": locked.decision_status},
        )

    view = preview(db, uid, recommendation_id)
    if view.expired:
        raise RecommendationStale(
            "this proposal has expired; ask for a fresh review",
            code="expired", recommendation_id=recommendation_id,
        )
    if view.stale:
        raise RecommendationStale(
            "the targets have changed since this was proposed; ask for a "
            "fresh review rather than applying an old comparison over a "
            "newer decision",
            code="stale_target", recommendation_id=recommendation_id,
            current={
                "proposed_against": view.current_revision_id,
                "latest_revision_id": view.latest_revision_id,
            },
        )
    if not view.applicable:
        raise RecommendationUnsupported(
            f"a {view.recommendation.action.value} proposal cannot be applied "
            f"automatically yet. The advice stands and is yours to act on; "
            f"nothing has been changed.",
            action=view.recommendation.action.value,
            recommendation_id=recommendation_id,
        )
    if view.blockers:
        raise RecommendationStale(
            "; ".join(view.blockers),
            code="not_acceptable", recommendation_id=recommendation_id,
        )

    change = view.recommendation.proposed_change
    applied_revision_id: Optional[str] = None

    if change.kind is ProposedChangeKind.TARGET_REVISION:
        # Re-run the numeric safety checks at acceptance. They ran at
        # generation, but the current target may have moved since, and a
        # 10% step against the old target can be a 25% step against the new
        # one. The bounds are about what reaches the athlete, not about what
        # the model said.
        _recheck_bounds(db, uid, view)
        applied_revision_id = _append_revision(
            db, uid, view, recommendation_id,
        )

    receipt_id = _write_receipt(
        db, uid, view, applied_revision_id=applied_revision_id,
    )

    decided = review_audit.decide(
        db, uid, recommendation_id, decision=DecisionStatus.ACCEPTED,
        decided_by=decided_by, note=note,
        action_receipt_id=receipt_id,
        applied_revision_id=applied_revision_id,
    )
    db.commit()

    return AcceptanceResult(
        recommendation=decided,
        action_receipt_id=receipt_id,
        applied_revision_id=applied_revision_id,
        message=_committed_message(db, uid, decided),
    )


def _recheck_bounds(db: Session, user_id: str, view: RecommendationPreview) -> None:
    """Absolute and step bounds, against the target in force NOW."""
    change = view.recommendation.proposed_change
    values = change.target_values
    if values is None:
        raise FitnessDataError("the proposal carries no target values")

    findings = safety._absolute_bounds(values, "proposal")
    current = _current_target_values(db, user_id, change)
    findings += safety._step_bounds(values, current, "proposal")
    if findings:
        raise FitnessDataError(
            "this proposal no longer passes the safety bounds against your "
            "current targets: " + "; ".join(f.message for f in findings)
        )


def _append_revision(
    db: Session,
    user_id: str,
    view: RecommendationPreview,
    recommendation_id: str,
) -> str:
    """Create the target revision, linked back to this recommendation.

    `review_recommendation_id` is what makes the chain complete: the
    revision names the proposal, the proposal names the review, and the
    review holds the frozen state. "Why am I eating 2850?" walks all the way
    back to the numbers.
    """
    from app.services.fitness.targets import create_target_revision

    change = view.recommendation.proposed_change
    assert change.target_values is not None and change.scope is not None
    revision = create_target_revision(
        db, user_id,
        TargetRevisionIn(
            scope=change.scope,
            phase_id=view.recommendation.current_phase_id
            if change.scope is TargetScope.PHASE else None,
            valid_from=change.effective_date or date.today(),
            training=change.target_values,
            source="coach_review",
            review_recommendation_id=recommendation_id,
        ),
        approved_by=user_id,
        # The caller owns the commit: the revision, the receipt and the
        # decision land together or not at all.
        commit=False,
    )
    return revision.id


def _write_receipt(
    db: Session,
    user_id: str,
    view: RecommendationPreview,
    *,
    applied_revision_id: Optional[str],
) -> str:
    """The durable proof, in the caller's transaction.

    Not `action_receipt_service.claim_operation`: that commits internally,
    which would split this from the revision it describes. A receipt that
    committed while the revision rolled back would claim an effect that
    never happened — which is the one thing a receipt must never do.

    The idempotency key is the recommendation id, so a replay cannot produce
    a second receipt even if the row lock were somehow lost.
    """
    rec = view.recommendation
    action_id = str(uuid.uuid4())
    target = applied_revision_id or f"recommendation:{rec.id}"
    evidence = [
        {"kind": "coach_review", "value": rec.review_id},
        {"kind": "recommendation", "value": rec.id},
    ]
    if applied_revision_id:
        evidence.append(
            {"kind": "target_revision", "value": applied_revision_id}
        )

    row = db.execute(text("""
        INSERT INTO action_receipt (
            action_id, user_id, action_type, target, permission_tier,
            reversible, idempotency_key, status, evidence_refs, executed_at,
            source_table, source_id, created_at
        ) VALUES (
            CAST(:action_id AS uuid), :uid, :action_type, :target,
            'consequential', TRUE, :key, 'completed',
            CAST(:evidence AS jsonb), NOW(),
            'fitness_coach_recommendation', :rec_id, NOW()
        )
        ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
        DO NOTHING
        RETURNING action_id
    """), {
        "action_id": action_id, "uid": user_id,
        "action_type": RECEIPT_ACTION_TYPE, "target": target,
        "key": f"fitness_coach_rec:{rec.id}",
        "evidence": json.dumps(evidence), "rec_id": rec.id,
    }).fetchone()

    if row is not None:
        return str(row.action_id)

    # A receipt for this recommendation already exists. Return it rather than
    # failing: the row lock means this can only happen on a retry of a
    # transaction that got this far and rolled back afterwards.
    existing = db.execute(text("""
        SELECT action_id FROM action_receipt WHERE idempotency_key = :key
    """), {"key": f"fitness_coach_rec:{rec.id}"}).fetchone()
    if existing is None:  # pragma: no cover - the conflict just happened
        raise FitnessDataError("the acceptance receipt could not be written")
    return str(existing.action_id)


def _committed_message(
    db: Session, user_id: str, rec: CoachRecommendationOut,
) -> str:
    """Rendered from the committed rows, never from the intent.

    `outcome_grounding` exists because a prompt rule cannot stop a model from
    claiming it did something; the same applies to a confirmation message. If
    the revision is not in the database, this does not say it was applied.
    """
    if rec.applied_revision_id:
        row = db.execute(text("""
            SELECT valid_from, calories, protein_g, scope, version
            FROM fitness_target_revision
            WHERE id = :id AND user_id = :uid
        """), {"id": rec.applied_revision_id, "uid": user_id}).fetchone()
        if row is None:
            return (
                "Recorded your acceptance, but the target revision is not in "
                "the database — nothing has changed. This is a fault on our "
                "side."
            )
        parts = [f"{row.calories} kcal"] if row.calories is not None else []
        if row.protein_g is not None:
            parts.append(f"{row.protein_g} g protein")
        return (
            f"Applied from {row.valid_from}: "
            + (", ".join(parts) or "new targets")
            + f" ({row.scope} scope, revision {row.version})."
        )
    if rec.action is ProposedChangeKind.DATA_REQUEST:
        return (
            "Noted — I'll ask for that data rather than guessing at it. "
            "Nothing about your plan changed."
        )
    return "Noted. Nothing about your plan changed."


# ─────────────────────────────────────────────────────────────────────────
# Chain
# ─────────────────────────────────────────────────────────────────────────

def trace(db: Session, user_id: str, revision_id: str) -> Dict[str, Any]:
    """Walk a target revision back to the numbers behind it.

    revision → recommendation → review → frozen state. This is the answer to
    "why am I eating 2850?", and it exists because the chain is only useful
    if something actually follows it.
    """
    uid = _require_user(user_id)
    revision = db.execute(text("""
        SELECT id, scope, valid_from, version, source,
               review_recommendation_id, calories, protein_g
        FROM fitness_target_revision
        WHERE id = :id AND user_id = :uid
    """), {"id": revision_id, "uid": uid}).fetchone()
    if revision is None:
        raise LookupError("target revision not found")

    out: Dict[str, Any] = {
        "revision": {
            "id": revision.id, "scope": revision.scope,
            "valid_from": revision.valid_from.isoformat(),
            "version": revision.version, "source": revision.source,
            "calories": revision.calories, "protein_g": revision.protein_g,
        },
        "recommendation": None, "review": None,
    }
    if not revision.review_recommendation_id:
        # A manual edit. Saying so explicitly: "no review behind this" is a
        # real and common answer, and an empty object would read as a gap.
        out["origin"] = "set by hand, with no coach review behind it"
        return out

    try:
        rec = review_audit.get_recommendation(
            db, uid, revision.review_recommendation_id,
        )
    except LookupError:
        out["origin"] = "the recommendation behind this revision is gone"
        return out

    out["recommendation"] = {
        "id": rec.id, "category": rec.category.value,
        "title": rec.title, "rationale": rec.rationale,
        "confidence": rec.confidence.value,
        "confidence_basis": rec.confidence_basis,
        "metric_paths": rec.metric_paths,
        "decided_at": rec.decided_at.isoformat() if rec.decided_at else None,
        "decided_by": rec.decided_by,
    }
    review = review_audit.get_review(db, uid, rec.review_id, with_state=True)
    out["review"] = {
        "id": review.id,
        "period": {
            "start": review.period.start.isoformat(),
            "end": review.period.end.isoformat(),
        },
        "model_actual": review.model_actual,
        "prompt_version": review.prompt_version,
        "analytics_version": review.analytics_version,
        "summary": review.summary,
    }
    if review.input_state is not None:
        # The exact figures cited, as they stood. Not recomputed: the point
        # is what the decision was made on, not what it would say today.
        out["cited_metrics"] = {
            path: _metric_snapshot(review.input_state, path)
            for path in rec.metric_paths
        }
    out["origin"] = "accepted from a coach review"
    return out


def _metric_snapshot(state, path: str) -> Optional[Dict[str, Any]]:
    if "." not in path:
        return None
    section_name, key = path.split(".", 1)
    for section, group in state.sections.items():
        if section.value == section_name:
            metric = group.metrics.get(key)
            if metric is None:
                return None
            return {
                "value": metric.value, "unit": metric.unit.value,
                "observed_days": metric.observed_days,
                "expected_days": metric.expected_days,
                "unavailable_reason": (
                    metric.unavailable_reason.value
                    if metric.unavailable_reason else None
                ),
            }
    return None
