"""Approved automation: narrow permissions, re-checked before every act.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 30.

This is the step where the coach may change something without asking first.
The design is almost entirely about keeping that permission small enough to
be worth granting, because the failure here is not a crash — it is a
calorie target that drifted 400 kcal over a month through fourteen
individually reasonable steps, and an athlete who cannot say when they
agreed to that.

Five rules, each with a constraint behind it:

1. **A permission is for one kind of act.** §30.2: approving the in-workout
   rest automation (`workout_command_service.DEFAULT_POLICY`) has never
   authorized a calorie or program change. One policy, one `action`, and a
   trigger refuses an action whose policy names a different one.
2. **Bounds include a rate.** A single-change ceiling with no frequency
   limit is not a limit. Both are required, and the window is counted from
   the action log rather than from a counter that can drift.
3. **Everything is re-evaluated immediately before acting**, inside the
   same transaction as the change: policy liveness, expiry, bounds, rate,
   coverage, evidence, pain, and the target revision it was computed
   against. A check done at proposal time is a check against a world that
   has moved.
4. **Outside the bounds is a proposal, not a bigger action.** §30.3. The
   automation's answer to "this needs a 300 kcal cut and you approved 100"
   is to ask, which is also what makes a narrow bound safe to grant.
5. **Every applied action has a receipt and an idempotency key.** A retry
   cannot apply twice, and `verify_action` can read back what happened.

What this module will not do: widen a bound, infer a permission from
another one, or treat an absence of data as permission. A sparse week stops
the automation — a confident small adjustment from two weigh-ins is a
response to noise.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    AUTOMATION_POLICY_VERSION,
    AutomationAction,
    AutomationDecision,
    AutomationDenial,
    AutomationOutcome,
    AutomationPolicyIn,
    AutomationPolicyOut,
)
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

UTC = timezone.utc

#: A pain report inside this window stops every automated change, not just
#: a load reduction. An automated calorie cut while something hurts is the
#: wrong priority, and the same lookback as `programming.recovery_gate`
#: keeps the two from disagreeing about how recent "recent" is.
PAIN_BLOCK_DAYS = 7

RECEIPT_ACTION_TYPE = "fitness_automation"


class AutomationError(FitnessDataError):
    """A refusal a caller can show."""


def _now() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────
# Policies
# ─────────────────────────────────────────────────────────────────────────

def grant_policy(
    db: Session,
    user_id: str,
    payload: AutomationPolicyIn,
    *,
    approved_by: str,
    enabled: bool = True,
) -> AutomationPolicyOut:
    """Record a permission.

    `approved_by` is required and may not be a model: a policy approved by
    the thing that benefits from it is not an approval, and
    `ck_automation_approved_by` refuses one at the database too.

    Granting replaces any live policy for the same action by revoking it —
    the partial unique index allows one, because two would mean two answers
    to "what did I agree to" and whichever the code read first would win.
    """
    owner = _require_user(user_id)
    if not approved_by or not approved_by.strip():
        raise AutomationError(
            "a permission records who granted it; there is no default"
        )
    if approved_by.strip().lower() in ("model", "llm", "autonomous", "system"):
        raise AutomationError(
            f"{approved_by!r} cannot approve an automation policy. A "
            f"permission granted by the thing that uses it is not a "
            f"permission."
        )
    if payload.expires_at <= _now():
        raise AutomationError(
            "the expiry is already past, so the policy would authorize "
            "nothing"
        )

    db.execute(text("""
        UPDATE fitness_automation_policy
        SET revoked_at = NOW(),
            revoked_reason = 'replaced by a newer grant',
            updated_at = NOW()
        WHERE user_id = :u AND action = :action AND revoked_at IS NULL
    """), {"u": owner, "action": payload.action.value})

    policy_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_automation_policy (
            id, user_id, action, enabled, max_change, min_change,
            max_actions_per_window, window_days, min_coverage_days,
            coverage_window_days, requires_evidence, expires_at, notify,
            note, policy_version, approved_at, approved_by,
            created_at, updated_at
        ) VALUES (
            :id, :u, :action, :enabled, :max_change, :min_change,
            :max_actions, :window_days, :min_coverage, :coverage_window,
            :requires_evidence, :expires_at, :notify, :note, :version,
            NOW(), :by, NOW(), NOW()
        )
    """), {
        "id": policy_id, "u": owner, "action": payload.action.value,
        "enabled": enabled, "max_change": payload.max_change,
        "min_change": payload.min_change,
        "max_actions": payload.max_actions_per_window,
        "window_days": payload.window_days,
        "min_coverage": payload.min_coverage_days,
        "coverage_window": payload.coverage_window_days,
        "requires_evidence": payload.requires_evidence,
        "expires_at": payload.expires_at, "notify": payload.notify,
        "note": payload.note, "version": AUTOMATION_POLICY_VERSION,
        "by": approved_by.strip(),
    })
    db.commit()
    logger.info(
        "[automation] %s policy granted for %s by %s (expires %s)",
        payload.action.value, owner, approved_by, payload.expires_at,
    )
    return get_policy(db, owner, payload.action)


def set_enabled(
    db: Session, user_id: str, action: AutomationAction, enabled: bool,
) -> AutomationPolicyOut:
    """Turn a policy off or on.

    Off means future actions stop — §30 completion criterion. Not "stop
    after the current window", not "stop proposing": the gate reads
    `enabled` on every attempt, so the next one is denied.
    """
    owner = _require_user(user_id)
    updated = db.execute(text("""
        UPDATE fitness_automation_policy
        SET enabled = :enabled, updated_at = NOW()
        WHERE user_id = :u AND action = :action AND revoked_at IS NULL
        RETURNING id
    """), {"enabled": enabled, "u": owner, "action": action.value}).fetchone()
    if updated is None:
        raise LookupError(f"no live {action.value} policy")
    db.commit()
    return get_policy(db, owner, action)


def revoke_policy(
    db: Session, user_id: str, action: AutomationAction, *, reason: str,
) -> Dict[str, Any]:
    """Withdraw a permission permanently.

    The row stays, with its reason: the actions taken under it are in the
    log and a reader needs to be able to resolve the policy they name.
    """
    owner = _require_user(user_id)
    if len(reason.strip()) < 3:
        raise AutomationError("a revocation records why")
    updated = db.execute(text("""
        UPDATE fitness_automation_policy
        SET revoked_at = NOW(), revoked_reason = :reason, enabled = FALSE,
            updated_at = NOW()
        WHERE user_id = :u AND action = :action AND revoked_at IS NULL
        RETURNING id
    """), {
        "reason": reason.strip(), "u": owner, "action": action.value,
    }).fetchone()
    if updated is None:
        raise LookupError(f"no live {action.value} policy")
    db.commit()
    return {"action": action.value, "revoked": True, "policy_id": updated.id}


def get_policy(
    db: Session, user_id: str, action: AutomationAction,
) -> AutomationPolicyOut:
    owner = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, action, enabled, max_change, min_change,
               max_actions_per_window, window_days, min_coverage_days,
               coverage_window_days, requires_evidence, expires_at, notify,
               note, policy_version, approved_at, approved_by, revoked_at,
               revoked_reason
        FROM fitness_automation_policy
        WHERE user_id = :u AND action = :action
        ORDER BY revoked_at IS NULL DESC, approved_at DESC
        LIMIT 1
    """), {"u": owner, "action": action.value}).fetchone()
    if row is None:
        raise LookupError(f"no {action.value} policy")
    return _policy_out(db, owner, row)


def list_policies(db: Session, user_id: str) -> List[AutomationPolicyOut]:
    """Every policy, including revoked ones.

    Revoked included deliberately: "what did I turn off, and when" is a
    question somebody asks, and a list that hid them would make a revoked
    policy look like one that never existed.
    """
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, action, enabled, max_change, min_change,
               max_actions_per_window, window_days, min_coverage_days,
               coverage_window_days, requires_evidence, expires_at, notify,
               note, policy_version, approved_at, approved_by, revoked_at,
               revoked_reason
        FROM fitness_automation_policy
        WHERE user_id = :u
        ORDER BY revoked_at IS NULL DESC, action ASC
    """), {"u": owner}).fetchall()
    return [_policy_out(db, owner, row) for row in rows]


def _policy_out(db: Session, user_id: str, row: Any) -> AutomationPolicyOut:
    used = _actions_in_window(
        db, user_id, AutomationAction(row.action), int(row.window_days),
    )
    return AutomationPolicyOut(
        id=row.id, action=AutomationAction(row.action),
        enabled=bool(row.enabled), max_change=float(row.max_change),
        min_change=float(row.min_change),
        max_actions_per_window=int(row.max_actions_per_window),
        window_days=int(row.window_days),
        min_coverage_days=int(row.min_coverage_days),
        coverage_window_days=int(row.coverage_window_days),
        requires_evidence=bool(row.requires_evidence),
        expires_at=row.expires_at, notify=bool(row.notify), note=row.note,
        approved_at=row.approved_at, approved_by=row.approved_by,
        revoked_at=row.revoked_at, revoked_reason=row.revoked_reason,
        policy_version=int(row.policy_version),
        actions_in_window=used,
    )


def _actions_in_window(
    db: Session, user_id: str, action: AutomationAction, window_days: int,
) -> int:
    """Applied actions inside the window, counted from the log.

    From the log rather than a counter column: a counter drifts when a
    transaction rolls back after incrementing it, and the drift is in the
    permissive direction.
    """
    return db.execute(text("""
        SELECT COUNT(*) FROM fitness_automation_action
        WHERE user_id = :u AND action = :action
          AND decision IN ('applied', 'applied_notified')
          AND created_at >= NOW() - (:days || ' days')::interval
    """), {
        "u": user_id, "action": action.value, "days": str(window_days),
    }).scalar() or 0


# ─────────────────────────────────────────────────────────────────────────
# The gate (§30.3)
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class AutomationRequest:
    """One proposed automated change, before anything is checked.

    `change` is signed and in the action's own unit; the bound is compared
    against its magnitude, because a 200 kcal cut and a 200 kcal increase
    are the same size of decision.

    `idempotency_key` is the caller's: a daily nutrition sweep uses the
    day, a progression apply uses the session. Without one, a retry after
    a dropped connection applies the change twice.
    """
    action: AutomationAction
    change: float
    idempotency_key: str
    reason: str
    #: What this was computed from, for the receipt's evidence list.
    evidence_refs: List[Dict[str, Any]] = None
    #: The target revision the change was computed against. A mismatch at
    #: apply time is a stale action.
    expected_target_revision_id: Optional[str] = None
    expected_program_revision: Optional[int] = None
    #: Accepted-science chunk ids, when the policy requires evidence.
    science_chunk_ids: Sequence[str] = ()
    #: Applied by the caller inside the same transaction, given the
    #: approved change. Returning a revision id links the receipt to it.
    apply: Optional[Any] = None


@dataclass
class GateResult:
    allowed: bool
    denial: Optional[AutomationDenial]
    reason: str
    policy: Optional[AutomationPolicyOut] = None
    coverage_days: Optional[int] = None


def evaluate(
    db: Session, user_id: str, request: AutomationRequest,
) -> GateResult:
    """Every guard, in order, with the reason named.

    Order matters for the message more than the outcome: a reader wants to
    know the first reason this was not allowed, and "there is no policy" is
    more useful than "the data is sparse" when both are true.

    This is a pure read. `execute` calls it again inside the write
    transaction, because a check whose result is used later is a check
    against a world that has moved.
    """
    owner = _require_user(user_id)

    try:
        policy = get_policy(db, owner, request.action)
    except LookupError:
        return GateResult(
            allowed=False, denial=AutomationDenial.NO_POLICY,
            reason=(
                f"No {request.action.value} policy exists. Nothing is "
                f"automated by default, and no other approval implies this "
                f"one."
            ),
        )

    if policy.revoked_at is not None:
        return GateResult(
            allowed=False, denial=AutomationDenial.POLICY_REVOKED,
            reason=(
                f"The {request.action.value} policy was revoked "
                f"{policy.revoked_at:%Y-%m-%d}"
                + (f": {policy.revoked_reason}" if policy.revoked_reason else "")
            ),
            policy=policy,
        )
    if not policy.enabled:
        return GateResult(
            allowed=False, denial=AutomationDenial.POLICY_DISABLED,
            reason=f"The {request.action.value} policy is switched off.",
            policy=policy,
        )
    if policy.expires_at <= _now():
        return GateResult(
            allowed=False, denial=AutomationDenial.POLICY_EXPIRED,
            reason=(
                f"The {request.action.value} policy expired "
                f"{policy.expires_at:%Y-%m-%d}. A permission with no end is "
                f"one nobody remembers giving, so it has one."
            ),
            policy=policy,
        )

    magnitude = abs(float(request.change))
    if magnitude > policy.max_change:
        return GateResult(
            allowed=False, denial=AutomationDenial.OUTSIDE_BOUNDS,
            reason=(
                f"A change of {magnitude:g} is outside the approved bound of "
                f"{policy.max_change:g}. This becomes a proposal rather than "
                f"a larger action."
            ),
            policy=policy,
        )
    if magnitude < policy.min_change:
        return GateResult(
            allowed=False, denial=AutomationDenial.OUTSIDE_BOUNDS,
            reason=(
                f"A change of {magnitude:g} is below the {policy.min_change:g} "
                f"floor — too small to be worth a change to somebody's plan."
            ),
            policy=policy,
        )

    used = _actions_in_window(db, owner, request.action, policy.window_days)
    if used >= policy.max_actions_per_window:
        return GateResult(
            allowed=False, denial=AutomationDenial.RATE_LIMITED,
            reason=(
                f"{used} {request.action.value} action(s) already applied in "
                f"the last {policy.window_days} day(s), which is the "
                f"approved limit. A size bound without a frequency bound is "
                f"not a bound."
            ),
            policy=policy,
        )

    coverage = _coverage_days(
        db, owner, request.action, policy.coverage_window_days,
    )
    if coverage < policy.min_coverage_days:
        return GateResult(
            allowed=False, denial=AutomationDenial.INSUFFICIENT_COVERAGE,
            reason=(
                f"{coverage} day(s) of data in the last "
                f"{policy.coverage_window_days}, against a minimum of "
                f"{policy.min_coverage_days}. An adjustment from this much "
                f"is a response to noise."
            ),
            policy=policy, coverage_days=coverage,
        )

    if policy.requires_evidence and not request.science_chunk_ids:
        return GateResult(
            allowed=False, denial=AutomationDenial.EVIDENCE_REQUIRED,
            reason=(
                f"The {request.action.value} policy requires accepted "
                f"evidence and none was supplied."
            ),
            policy=policy, coverage_days=coverage,
        )

    pain = _recent_pain(db, owner)
    if pain is not None and request.action is not AutomationAction.PAIN_LOAD_REDUCTION:
        return GateResult(
            allowed=False, denial=AutomationDenial.PAIN_REPORTED,
            reason=(
                f"Pain was reported at {pain}/10 in the last "
                f"{PAIN_BLOCK_DAYS} days. An automated change while "
                f"something hurts is the wrong priority — this needs a "
                f"person."
            ),
            policy=policy, coverage_days=coverage,
        )

    stale = _revision_moved(db, owner, request)
    if stale:
        return GateResult(
            allowed=False, denial=AutomationDenial.STALE_REVISION,
            reason=stale, policy=policy, coverage_days=coverage,
        )

    return GateResult(
        allowed=True, denial=None,
        reason=(
            f"Inside the approved bound ({magnitude:g} of "
            f"{policy.max_change:g}), {used + 1} of "
            f"{policy.max_actions_per_window} in {policy.window_days} days, "
            f"{coverage} day(s) of data."
        ),
        policy=policy, coverage_days=coverage,
    )


def _coverage_days(
    db: Session, user_id: str, action: AutomationAction, window_days: int,
) -> int:
    """Days with the data this action depends on.

    Different per action on purpose: a calorie adjustment needs food logs
    and weigh-ins, a progression apply needs logged sets. Counting "any
    fitness row" would let a fortnight of weigh-ins authorize a nutrition
    change computed from two food logs.
    """
    since = f"{window_days} days"
    if action in (AutomationAction.CALORIE_ADJUST,
                  AutomationAction.MACRO_ADJUST):
        # `health_metric` is the authority for body numbers (§6), and
        # `food_log.logged_at` is naive ET wall-clock while
        # `health_metric.recorded_at` is aware timestamptz — hence the two
        # different bounds. Counting days where BOTH exist, because a
        # calorie adjustment needs intake and weight: a fortnight of
        # weigh-ins with no food logs cannot authorize a change computed
        # from intake.
        return db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT DATE(logged_at) AS d FROM food_log
                WHERE user_id = :u
                  AND logged_at >= NOW() - CAST(:since AS interval)
                INTERSECT
                SELECT DATE(recorded_at) AS d FROM health_metric
                WHERE user_id = :u AND metric_type = 'weight'
                  AND recorded_at >= NOW() - CAST(:since AS interval)
            ) AS both_days
        """), {"u": user_id, "since": since}).scalar() or 0

    if action in (AutomationAction.PROGRESSION_APPLY,
                  AutomationAction.SCHEDULED_DELOAD,
                  AutomationAction.PAIN_LOAD_REDUCTION):
        return db.execute(text("""
            SELECT COUNT(DISTINCT session_date) FROM workout_log
            WHERE user_id = :u
              AND COALESCE(skipped, FALSE) = FALSE
              AND session_date >= CURRENT_DATE - CAST(:days AS integer)
        """), {"u": user_id, "days": window_days}).scalar() or 0

    return 0


def _recent_pain(db: Session, user_id: str) -> Optional[int]:
    """Worst pain severity reported in the block window, or None.

    None is "nothing reported", which is not zero — a zero would read as
    "checked and fine", and the gate must not treat silence as consent.
    """
    try:
        severity = db.execute(text("""
            SELECT MAX(severity) FROM fitness_pain_report
            WHERE user_id = :u AND superseded_by_id IS NULL
              AND COALESCE(pain_present, FALSE) = TRUE
              AND occurred_at >= NOW() - CAST(:since AS interval)
        """), {"u": user_id, "since": f"{PAIN_BLOCK_DAYS} days"}).scalar()
    except Exception as exc:
        # A gate that cannot read the pain reports does not proceed as
        # though there were none.
        logger.warning("[automation] pain reports unreadable: %s", exc)
        return 10
    return int(severity) if severity is not None else None


def _revision_moved(
    db: Session, user_id: str, request: AutomationRequest,
) -> Optional[str]:
    """Why the thing being changed has moved, or None."""
    if request.expected_target_revision_id:
        current = db.execute(text("""
            SELECT id FROM fitness_target_revision
            WHERE user_id = :u AND valid_until IS NULL
            ORDER BY valid_from DESC, created_at DESC
            LIMIT 1
        """), {"u": user_id}).scalar()
        if current != request.expected_target_revision_id:
            return (
                f"The change was computed against target revision "
                f"{request.expected_target_revision_id} and the current one "
                f"is {current}. Somebody edited their targets in between."
            )
    if request.expected_program_revision is not None:
        current_program = db.execute(text("""
            SELECT MAX(revision) FROM fitness_program_revision
            WHERE user_id = :u AND activated_at IS NOT NULL
        """), {"u": user_id}).scalar()
        if (current_program or 0) != request.expected_program_revision:
            return (
                f"The change was computed against program revision "
                f"{request.expected_program_revision} and the program is now "
                f"at {current_program or 0}."
            )
    return None


def execute(
    db: Session, user_id: str, request: AutomationRequest,
) -> AutomationOutcome:
    """Re-check, apply, receipt, log — in one transaction.

    The order is the design:

        re-evaluate  →  apply (the caller's callable)  →  write the receipt
        →  log the action  →  commit

    Re-evaluating here rather than trusting an earlier `evaluate` is §30.3:
    a policy can be revoked, pain can be reported and a target can be
    edited between a proposal and its execution, and all three must stop
    it. The re-check is in the same transaction as the change, so there is
    no window.

    A denial is logged too. "The automation did nothing on Tuesday" is a
    question somebody asks, and a log that only recorded successes answers
    it with silence.

    Nothing here widens a bound. An outside-bound change returns
    `PROPOSED`, and turning it into a proposal is the caller's job — this
    module does not write recommendations, because then its own denial
    could become its own authorization.
    """
    owner = _require_user(user_id)
    if not request.idempotency_key or not request.idempotency_key.strip():
        raise AutomationError(
            "an automated action needs an idempotency key, or a retry after "
            "a dropped connection applies the change twice"
        )

    existing = db.execute(text("""
        SELECT id, action, decision, denial, reason, applied_change,
               receipt_id, recommendation_id, policy_id, notified
        FROM fitness_automation_action
        WHERE user_id = :u AND idempotency_key = :key
    """), {"u": owner, "key": request.idempotency_key}).fetchone()
    if existing is not None:
        # Already attempted. Return what happened rather than doing it
        # again: this is the retry case the key exists for.
        return _outcome_from_row(existing)

    gate = evaluate(db, owner, request)
    if not gate.allowed:
        decision = (
            AutomationDecision.PROPOSED
            if gate.denial is AutomationDenial.OUTSIDE_BOUNDS
            else AutomationDecision.DENIED
        )
        return _log(
            db, owner, request, decision=decision, denial=gate.denial,
            reason=gate.reason, policy=gate.policy,
            coverage_days=gate.coverage_days, applied_change=None,
            receipt_id=None,
        )

    applied_revision_id: Optional[str] = None
    if request.apply is not None:
        try:
            applied_revision_id = request.apply(db, request.change)
        except Exception as exc:
            db.rollback()
            logger.warning(
                "[automation] %s apply failed (%s): %s",
                request.action.value, type(exc).__name__, exc,
            )
            # Logged as a denial with the failure named, in its own
            # transaction: an attempt that errored is not an attempt that
            # never happened, and the next sweep should see it.
            return _log(
                db, owner, request, decision=AutomationDecision.DENIED,
                denial=AutomationDenial.MISSING_DATA,
                reason=f"the change could not be applied: {exc}"[:800],
                policy=gate.policy, coverage_days=gate.coverage_days,
                applied_change=None, receipt_id=None,
            )

    receipt_id = _write_receipt(
        db, owner, request, applied_revision_id=applied_revision_id,
    )
    notify = bool(gate.policy and gate.policy.notify)
    outcome = _log(
        db, owner, request,
        decision=(
            AutomationDecision.APPLIED_NOTIFIED if notify
            else AutomationDecision.APPLIED
        ),
        denial=None, reason=gate.reason, policy=gate.policy,
        coverage_days=gate.coverage_days,
        applied_change=float(request.change), receipt_id=receipt_id,
        commit=True,
    )
    logger.info(
        "[automation] %s applied %+g for %s (receipt %s)",
        request.action.value, request.change, owner, receipt_id,
    )
    return outcome


def _log(
    db: Session,
    user_id: str,
    request: AutomationRequest,
    *,
    decision: AutomationDecision,
    denial: Optional[AutomationDenial],
    reason: str,
    policy: Optional[AutomationPolicyOut],
    coverage_days: Optional[int],
    applied_change: Optional[float],
    receipt_id: Optional[str],
    commit: bool = True,
) -> AutomationOutcome:
    """Record the attempt and return the outcome.

    `policy_snapshot` holds the bounds as they were: a policy can be
    edited, and "what were the limits when this fired" has to survive that.
    """
    action_id = str(uuid.uuid4())
    snapshot = policy.model_dump(mode="json") if policy else None
    try:
        db.execute(text("""
            INSERT INTO fitness_automation_action (
                id, user_id, policy_id, action, decision, denial, reason,
                applied_change, receipt_id, policy_snapshot,
                target_revision_id, program_revision, coverage_days,
                idempotency_key, notified, created_at
            ) VALUES (
                :id, :u, :policy, :action, :decision, :denial, :reason,
                :change, :receipt, CAST(:snapshot AS JSONB),
                :target_revision, :program_revision, :coverage, :key,
                FALSE, NOW()
            )
        """), {
            "id": action_id, "u": user_id,
            "policy": policy.id if policy else None,
            "action": request.action.value, "decision": decision.value,
            "denial": denial.value if denial else None,
            "reason": reason[:800], "change": applied_change,
            "receipt": receipt_id,
            "snapshot": json.dumps(snapshot) if snapshot else None,
            "target_revision": request.expected_target_revision_id,
            "program_revision": request.expected_program_revision,
            "coverage": coverage_days, "key": request.idempotency_key,
        })
        if commit:
            db.commit()
    except IntegrityError:
        db.rollback()
        # Another worker logged the same attempt. Theirs is the record.
        row = db.execute(text("""
            SELECT id, action, decision, denial, reason, applied_change,
                   receipt_id, recommendation_id, policy_id, notified
            FROM fitness_automation_action
            WHERE user_id = :u AND idempotency_key = :key
        """), {"u": user_id, "key": request.idempotency_key}).fetchone()
        if row is not None:
            return _outcome_from_row(row)
        raise

    return AutomationOutcome(
        action=request.action, decision=decision, denial=denial,
        reason=reason[:800], applied_change=applied_change,
        receipt_id=receipt_id, policy_id=policy.id if policy else None,
        idempotency_key=request.idempotency_key,
        notified=False,
    )


def _outcome_from_row(row: Any) -> AutomationOutcome:
    return AutomationOutcome(
        action=AutomationAction(row.action),
        decision=AutomationDecision(row.decision),
        denial=AutomationDenial(row.denial) if row.denial else None,
        reason=row.reason,
        applied_change=(
            float(row.applied_change) if row.applied_change is not None
            else None
        ),
        receipt_id=row.receipt_id,
        recommendation_id=row.recommendation_id,
        policy_id=row.policy_id, notified=bool(row.notified),
    )


def _write_receipt(
    db: Session,
    user_id: str,
    request: AutomationRequest,
    *,
    applied_revision_id: Optional[str],
) -> str:
    """The durable proof, in the caller's transaction.

    Not `action_receipt_service.claim_operation`: that commits internally,
    which would split the receipt from the change it describes. A receipt
    that committed while the change rolled back would claim an effect that
    never happened — the one thing a receipt must never do.

    `permission_tier` is `consequential` rather than `routine`: this moved
    somebody's calorie or load target without asking at the time, and the
    fact that it was pre-approved does not make it routine.
    """
    action_id = str(uuid.uuid4())
    key = f"fitness_automation:{request.idempotency_key}"
    evidence = list(request.evidence_refs or [])
    evidence.append({"kind": "automation_action", "value": request.action.value})
    if applied_revision_id:
        evidence.append(
            {"kind": "target_revision", "value": applied_revision_id}
        )
    for chunk_id in request.science_chunk_ids or ():
        evidence.append({"kind": "science_chunk", "value": chunk_id})

    row = db.execute(text("""
        INSERT INTO action_receipt (
            action_id, user_id, action_type, target, permission_tier,
            reversible, idempotency_key, status, evidence_refs, executed_at,
            source_table, source_id, created_at
        ) VALUES (
            CAST(:action_id AS uuid), :u, :action_type, :target,
            'consequential', TRUE, :key, 'completed',
            CAST(:evidence AS jsonb), NOW(),
            'fitness_automation_action', :source_id, NOW()
        )
        ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
        DO NOTHING
        RETURNING action_id
    """), {
        "action_id": action_id, "u": user_id,
        "action_type": RECEIPT_ACTION_TYPE,
        "target": applied_revision_id or f"automation:{request.action.value}",
        "key": key, "evidence": json.dumps(evidence),
        "source_id": request.idempotency_key,
    }).fetchone()
    if row is not None:
        return str(row.action_id)

    existing = db.execute(text("""
        SELECT action_id FROM action_receipt WHERE idempotency_key = :key
    """), {"key": key}).fetchone()
    if existing is None:  # pragma: no cover - the conflict just happened
        raise AutomationError("the automation receipt could not be written")
    return str(existing.action_id)


def recent_actions(
    db: Session, user_id: str, *, limit: int = 30,
) -> List[Dict[str, Any]]:
    """What the automation has done and not done.

    Denials included: "why did nothing happen on Tuesday" is the question
    this answers, and a log of successes answers it with silence. §30.5's
    monitoring reads the same rows.
    """
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, action, decision, denial, reason, applied_change,
               receipt_id, recommendation_id, policy_id, coverage_days,
               notified, created_at
        FROM fitness_automation_action
        WHERE user_id = :u
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"u": owner, "limit": max(1, min(limit, 200))}).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row._mapping)
        item["applied_change"] = (
            float(item["applied_change"])
            if item["applied_change"] is not None else None
        )
        if item.get("created_at"):
            item["created_at"] = item["created_at"].isoformat()
        out.append(item)
    return out


def health(db: Session, user_id: str, *, days: int = 30) -> Dict[str, Any]:
    """§30.5: what the automation is doing, per action.

    Deliberately counts denials by reason. An automation that is denied
    every day for insufficient coverage is not working as agreed — it is
    configured for data that does not exist, and the fix is a conversation
    rather than a wider bound.
    """
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT action, decision, denial, COUNT(*) AS n
        FROM fitness_automation_action
        WHERE user_id = :u
          AND created_at >= NOW() - (:days || ' days')::interval
        GROUP BY action, decision, denial
        ORDER BY action, decision
    """), {"u": owner, "days": str(days)}).fetchall()

    per_action: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        bucket = per_action.setdefault(row.action, {
            "applied": 0, "proposed": 0, "denied": 0, "denials": {},
        })
        if row.decision in ("applied", "applied_notified"):
            bucket["applied"] += row.n
        elif row.decision == "proposed":
            bucket["proposed"] += row.n
        else:
            bucket["denied"] += row.n
            if row.denial:
                bucket["denials"][row.denial] = (
                    bucket["denials"].get(row.denial, 0) + row.n
                )

    policies = []
    for policy in list_policies(db, owner):
        policies.append({
            "action": policy.action.value,
            "enabled": policy.enabled,
            "live": policy.is_live,
            "expires_at": policy.expires_at.isoformat(),
            "expired": policy.expires_at <= _now(),
            "actions_in_window": policy.actions_in_window,
            "max_actions_per_window": policy.max_actions_per_window,
        })

    return {
        "window_days": days,
        "policies": policies,
        "by_action": per_action,
        # A policy with no live grant is the normal state, and the health
        # view says so rather than looking like a broken automation.
        "any_enabled": any(one["enabled"] and one["live"] for one in policies),
    }
