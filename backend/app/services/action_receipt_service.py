"""
Action-receipt shadow recorder (SINGULAR_SARA_MASTER_PLAN §4.7/§C10).

§4.7 wants one action executor whose receipt has a permission tier and a
status that's never just a bare success flag ("completed requires verified
success criteria. Otherwise use partial, blocked, failed, or cancelled").
`standing_order_service._log_action()` already records every standing-order
action to `action_ledger` — this module shadow-records the SAME event into
the canonical `action_receipt` shape alongside it, without changing what
`action_ledger` does or how undo works.

Sync (matches `_log_action`'s sync `Session` — this codebase mixes sync and
async DB access per call site, and this shadow recorder rides whichever
session its caller already has).
"""

import hashlib
import json
import logging
from app.core.timezone import now_utc
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Action types with `undo_available=True` in the existing action_ledger are
# reversible-local by definition; everything else defaults to consequential
# (requires standing-order/explicit approval per §4.7's tier table) rather
# than assuming safety for an action type we haven't classified.
# item 5.10 (2026-07-31): light_control/lock_control/switch_control
# (PHENOMENAL_ASSISTANT_PLAN.md Phase 4 deliberation-driven home actions)
# were reversible in standing_order_service.undo_action()'s actual logic
# the whole time but missing here and from _log_action's undo_available
# flag — both silently marked them non-reversible everywhere a receipt or
# ledger row was ever shown, so Undo could never appear for them.
_REVERSIBLE_ACTION_TYPES = {
    "home_control", "all_lights_off", "lock_all",
    "light_control", "lock_control", "switch_control",
}


def record_standing_order_action(
    db: Session,
    *,
    user_id: str,
    order_id: int,
    action_type: str,
    success: bool,
    verified: Optional[bool] = None,
    correlation_id: Optional[str] = None,
    ledger_id: Optional[int] = None,
) -> None:
    """Record one standing-order action execution's receipt.

    `verified` (SINGULAR_SARA_MASTER_PLAN §C10) is the read-after-write
    check from `_verify_action_effect` — True/False when the entity's actual
    state was checked, None when it isn't checkable (e.g. a notification
    action). A bare `success=True` no longer means "completed": if we
    checked and the entity didn't reach the desired state, the receipt says
    `partial`, not `completed` — "no success state can be displayed when the
    underlying operation... only partially completed" (Definition of Done #9).
    """
    try:
        reversible = action_type in _REVERSIBLE_ACTION_TYPES
        if not success:
            status = "failed"
        elif verified is False:
            status = "partial"
        else:
            status = "completed"
        db.execute(text("""
            INSERT INTO action_receipt (
                user_id, action_type, target, permission_tier, reversible,
                undo_expires_at, idempotency_key, status, executed_at,
                correlation_id, source_table, source_id, ledger_id
            ) VALUES (
                :user_id, :action_type, :target, :permission_tier, :reversible,
                CASE WHEN :reversible THEN NOW() + INTERVAL '5 minutes' ELSE NULL END,
                :idempotency_key, :status, NOW(), :correlation_id, 'standing_order', :order_id, :ledger_id
            )
        """), {
            "user_id": user_id,
            "action_type": action_type,
            "target": f"standing_order:{order_id}",
            "permission_tier": "reversible_local" if reversible else "consequential",
            "reversible": reversible,
            "idempotency_key": f"standing_order:{order_id}:{action_type}:{now_utc().isoformat()}",
            "status": status,
            "correlation_id": correlation_id,
            "order_id": str(order_id),
            "ledger_id": ledger_id,
        })
    except Exception as e:
        logger.debug(f"[action_receipt_service] standing-order shadow record failed: {e}")


def compute_operation_key(
    client_message_id: Optional[str], conversation_id: Optional[str],
    tool_name: str, arguments: Optional[Dict[str, Any]],
    fallback_call_id: Optional[str] = None,
) -> str:
    """R03 review remediation round 4 (2026-09-27): a durable,
    application-controlled operation identity — NOT the model's own
    per-call tool_call_id, which the inference server assigns fresh on
    every model turn and is NOT guaranteed stable across a client retry/
    reconnect that causes the SAME logical user message to be reprocessed
    into a NEW model turn (a different tool_call_id for what is
    semantically the same authorized operation — review finding 4:
    "its key uses only the model's tool-call ID, which is not a durable
    application-wide operation identity").

    `client_message_id` is the client's OWN idempotency token for a turn
    — already used elsewhere in this codebase for exactly this purpose
    (main_simple.py's store_conversation/`_store_conversation_with_timeout`
    are idempotent on it) — and stays stable across exactly the retry this
    needs to survive.

    `conversation_id` ALONE is deliberately never used as the sole
    fallback basis: it is static across an entire conversation, so two
    genuinely DIFFERENT requests in the same conversation that happen to
    call the same tool with the same arguments (a real, unremarkable
    occurrence — e.g. two separate turns each asking to cancel some
    reminder with no ID argument yet resolved, or simply two tests
    reusing a literal "conv-1") would collide on the exact same key and
    the second, entirely legitimate call would be wrongly treated as a
    duplicate of the first — caught by exactly this shape of failure in
    `test_chat_tool_loop.py` during this round's own regression run.
    When `client_message_id` is unavailable, `fallback_call_id` (the
    model's own tool_call_id for THIS specific call) is used instead —
    weaker than `client_message_id` (does not survive a client retry,
    same limitation round 3's key had), but does not manufacture false
    collisions between unrelated calls either, which a bare
    `conversation_id` fallback does.
    """
    basis = client_message_id or fallback_call_id or conversation_id or "no-request-id"
    try:
        args_repr = json.dumps(arguments or {}, sort_keys=True, default=str)
    except Exception:
        args_repr = str(arguments)
    raw = f"{basis}:{tool_name}:{args_repr}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# How long a 'running' claim can go unresolved before it's assumed
# abandoned (the process that claimed it crashed or was killed between
# claiming and finalizing) and becomes reclaimable by a later attempt.
# Generous relative to how long a real chat tool call actually takes.
RUNNING_CLAIM_EXPIRY_SECONDS = 120


def claim_operation(
    db: Session,
    *,
    user_id: str,
    conversation_id: Optional[str],
    operation_key: str,
    tool_name: str,
    target: str,
    correlation_id: Optional[str] = None,
) -> Optional[str]:
    """Atomically claim a durable operation slot BEFORE the mutation
    runs — this is what actually prevents a duplicate EFFECT, not merely
    a duplicate log row (review finding 4: "deduplicating receipt rows
    does not prevent duplicate effects"). The row is inserted with
    `status='running'` (the plan's own vocabulary — proposed, authorized,
    RUNNING, committed, verified, failed, cancelled) via
    `ON CONFLICT (idempotency_key) DO NOTHING RETURNING action_id` — a
    genuinely atomic claim, not a read-then-write race.

    Returns the new receipt's `action_id` on a fresh claim. Returns None
    if an operation with this exact key ALREADY EXISTS (running or
    resolved) — the caller MUST NOT execute the mutation in that case;
    look the existing row up via `get_operation_by_key` and act on ITS
    outcome (or refuse concurrently, for a still-fresh running claim)
    instead.
    """
    import uuid
    try:
        reversible = tool_name in _REVERSIBLE_ACTION_TYPES
        row = db.execute(text("""
            INSERT INTO action_receipt (
                action_id, user_id, conversation_id, action_type, target,
                permission_tier, reversible, idempotency_key, status,
                executed_at, correlation_id, source_table, source_id
            ) VALUES (
                :action_id, :user_id, :conversation_id, :action_type, :target,
                :permission_tier, :reversible, :idempotency_key, 'running',
                NOW(), :correlation_id, 'chat_tool', :operation_key
            )
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
            RETURNING action_id
        """), {
            "action_id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "action_type": tool_name,
            "target": target,
            "permission_tier": "reversible_local" if reversible else "consequential",
            "reversible": reversible,
            "idempotency_key": operation_key,
            "correlation_id": correlation_id,
            "operation_key": operation_key,
        }).mappings().first()
        db.commit()
        return row["action_id"] if row else None
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"[action_receipt_service] claim_operation failed, refusing to authorize execution (fail closed): {e}")
        return None


def get_operation_by_key(db: Session, operation_key: str) -> Optional[Dict[str, Any]]:
    """Look up the (at most one, by the unique index) existing operation
    for this key — used after a lost claim race to decide whether to
    relay a terminal outcome or refuse a still-in-flight duplicate."""
    try:
        row = db.execute(text("""
            SELECT action_id, status, target, executed_at, created_at
            FROM action_receipt WHERE idempotency_key = :key
        """), {"key": operation_key}).mappings().first()
        return dict(row) if row else None
    except Exception as e:
        logger.debug(f"[action_receipt_service] get_operation_by_key failed: {e}")
        return None


def reclaim_stale_running_operation(
    db: Session, operation_key: str, expiry_seconds: int = RUNNING_CLAIM_EXPIRY_SECONDS,
) -> Optional[str]:
    """Reconciliation for a claim that was taken but never resolved (the
    process that claimed it crashed) — the same "next poll naturally
    reclaims it" pattern used for reminder/timer delivery (R06 remainder).
    A conditional UPDATE re-checks `status = 'running'` AND staleness
    atomically, so a genuinely still-in-flight claim is never touched, and
    two callers racing to reclaim the same stale row can't both succeed.
    Returns the `action_id` if reclaimed, else None.
    """
    try:
        row = db.execute(text("""
            UPDATE action_receipt SET executed_at = NOW()
            WHERE idempotency_key = :key AND status = 'running'
              AND executed_at < NOW() - (:expiry_seconds * INTERVAL '1 second')
            RETURNING action_id
        """), {"key": operation_key, "expiry_seconds": expiry_seconds}).mappings().first()
        db.commit()
        return row["action_id"] if row else None
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug(f"[action_receipt_service] reclaim_stale_running_operation failed: {e}")
        return None


def finalize_operation(
    db: Session,
    action_id: str,
    *,
    success: bool,
    result_message: str = "",
    result_data: Optional[Dict[str, Any]] = None,
    verified: Optional[bool] = None,
) -> None:
    """Record the REAL outcome of a claimed operation — the only place a
    `running` row transitions to a terminal state (`completed`/`partial`/
    `failed`). The WHERE clause only ever transitions a row still
    `status = 'running'`, so a lost race after a claim-expiry reclaim
    can't clobber a result someone else already recorded, and finalizing
    twice (e.g. a duplicate call site) is a safe no-op the second time.

    `target` is refined here too when `result_data` reveals a better one
    than was available at claim time (e.g. a newly created entity's own
    id) — never overwrites a target that was already meaningful.
    """
    try:
        if not success:
            status = "failed"
        elif verified is False:
            status = "partial"
        else:
            status = "completed"
        evidence = []
        if result_message:
            evidence.append({"kind": "tool_result_message", "value": result_message[:500]})
        db.execute(text("""
            UPDATE action_receipt
            SET status = :status, evidence_refs = CAST(:evidence_refs AS jsonb)
            WHERE action_id = :action_id AND status = 'running'
        """), {"status": status, "evidence_refs": json.dumps(evidence), "action_id": action_id})
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug(f"[action_receipt_service] finalize_operation failed: {e}")


_TARGET_ID_FIELDS = (
    "id", "note_id", "reminder_id", "timer_id", "plan_id", "thread_id",
    "task_id", "event_id", "order_id", "goal_id", "folder_id", "recipe_id",
)


def _infer_chat_tool_target(
    tool_name: str, arguments: Optional[Dict[str, Any]], result_data: Optional[Dict[str, Any]],
) -> str:
    for source in (result_data, arguments):
        if isinstance(source, dict):
            for field in _TARGET_ID_FIELDS:
                value = source.get(field)
                if value:
                    return f"{tool_name}:{value}"
    try:
        arg_str = json.dumps(arguments, sort_keys=True, default=str)[:200] if arguments else ""
    except Exception:
        arg_str = str(arguments)[:200]
    return f"{tool_name}:{arg_str}"


def find_receipts(
    db: Session,
    *,
    user_id: str,
    conversation_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """R03 "when challenged, verify the relevant record": look up actual
    `action_receipt` rows for this user, optionally scoped to a
    conversation and/or tool name, optionally filtered by a free-text
    match against `target`/`action_type`. Ordered newest first.

    Returns `[]` (never an error) when nothing matches — callers MUST
    render that as "no record found," never as proof the action failed:
    a receipt might exist under a different tool_name spelling, or the
    action might have happened through a non-chat path this table doesn't
    cover (see verify_action's own tool description for the exact honest
    phrasing this is meant to support).
    """
    clauses = ["user_id = :user_id"]
    params: Dict[str, Any] = {"user_id": user_id, "lim": limit}
    if conversation_id:
        clauses.append("conversation_id = :conversation_id")
        params["conversation_id"] = conversation_id
    if tool_name:
        clauses.append("action_type = :tool_name")
        params["tool_name"] = tool_name
    if query:
        clauses.append("(target ILIKE :q OR action_type ILIKE :q)")
        params["q"] = f"%{query}%"
    sql = f"""
        SELECT action_id, user_id, conversation_id, action_type, target,
               status, executed_at, created_at, undone, reversible
        FROM action_receipt
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT :lim
    """
    try:
        rows = db.execute(text(sql), params).mappings().fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[action_receipt_service] find_receipts failed: {e}")
        return []


def list_recent_receipts(db: Session, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT action_id, action_type, target, permission_tier, reversible,
               status, executed_at, source_table, source_id,
               ledger_id, undo_expires_at, undone
        FROM action_receipt
        WHERE user_id = :uid
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"uid": user_id, "lim": limit}).mappings().fetchall()
    return [dict(r) for r in rows]
