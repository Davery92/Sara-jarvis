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
_REVERSIBLE_ACTION_TYPES = {"home_control", "all_lights_off", "lock_all"}


def record_standing_order_action(
    db: Session,
    *,
    user_id: str,
    order_id: int,
    action_type: str,
    success: bool,
    verified: Optional[bool] = None,
    correlation_id: Optional[str] = None,
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
                correlation_id, source_table, source_id
            ) VALUES (
                :user_id, :action_type, :target, :permission_tier, :reversible,
                CASE WHEN :reversible THEN NOW() + INTERVAL '5 minutes' ELSE NULL END,
                :idempotency_key, :status, NOW(), :correlation_id, 'standing_order', :order_id
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
        })
    except Exception as e:
        logger.debug(f"[action_receipt_service] standing-order shadow record failed: {e}")


def list_recent_receipts(db: Session, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT action_id, action_type, target, permission_tier, reversible,
               status, executed_at, source_table, source_id
        FROM action_receipt
        WHERE user_id = :uid
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"uid": user_id, "lim": limit}).mappings().fetchall()
    return [dict(r) for r in rows]
