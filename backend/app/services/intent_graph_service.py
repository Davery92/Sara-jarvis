"""
Intent-graph service — real persistence (SINGULAR_SARA_MASTER_PLAN §4.3/§C3).

Two things `intent_graph_projection.py` (the read-only silhouette) can't do:

  1. `sync_from_projections`: idempotently upsert what the projection already
     computes into the real `intent`/`intent_edge` tables, keyed by
     (source_table, source_id) so re-running never duplicates a row — it
     updates the existing one or inserts a new one. This is *populating* the
     graph, not migrating ownership: the source tables (`reminder`,
     `standing_order`, etc.) remain authoritative; `intent` is a durable,
     queryable mirror until a later phase actually cuts ownership over.

  2. `transition_intent`: the "Define state transitions and enforce them in
     one service" deliverable — illegal transitions (e.g. `done` -> `active`)
     raise instead of silently succeeding, so "nothing can be both completed
     and failed" (§C3 exit gate) is enforced going forward for anything
     written through here.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# proposed -> active/cancelled/deferred; active -> blocked/done/failed/cancelled;
# blocked -> active/cancelled/failed; deferred -> active/cancelled;
# done/failed/cancelled are terminal.
_LEGAL_TRANSITIONS: Dict[str, set] = {
    "proposed": {"active", "cancelled", "deferred"},
    "active": {"blocked", "done", "failed", "cancelled"},
    "blocked": {"active", "cancelled", "failed"},
    "deferred": {"active", "cancelled"},
    "done": set(),
    "failed": set(),
    "cancelled": set(),
}


class IllegalTransitionError(ValueError):
    pass


def transition_intent(db: Session, intent_id: str, new_status: str) -> Dict[str, Any]:
    """Move an intent to `new_status`, enforcing the legal-transition map.
    Raises `IllegalTransitionError` rather than silently applying an
    impossible state change."""
    row = db.execute(text("SELECT status FROM intent WHERE intent_id = :id"),
                     {"id": intent_id}).fetchone()
    if row is None:
        raise ValueError(f"no such intent: {intent_id!r}")

    current = row[0]
    if new_status == current:
        return {"intent_id": intent_id, "status": current, "changed": False}

    allowed = _LEGAL_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise IllegalTransitionError(
            f"cannot transition intent {intent_id!r} from {current!r} to {new_status!r} "
            f"(allowed: {sorted(allowed) or 'none — terminal state'})"
        )

    db.execute(text("""
        UPDATE intent SET status = :status, updated_at = NOW() WHERE intent_id = :id
    """), {"status": new_status, "id": intent_id})
    db.commit()
    return {"intent_id": intent_id, "status": new_status, "changed": True}


def _upsert(db: Session, intent: Dict[str, Any], source_table: str, source_id: str) -> None:
    db.execute(text("""
        INSERT INTO intent (
            intent_id, kind, origin, owner_user_id, status, priority, next_step,
            permission_tier, last_progress_at, next_review_at, correlation_id,
            source_table, source_id, created_at, updated_at
        ) VALUES (
            :intent_id, :kind, :origin, :owner_user_id, :status, :priority, :next_step,
            :permission_tier, :last_progress_at, :next_review_at, :correlation_id,
            :source_table, :source_id, COALESCE(:created_at, NOW()), NOW()
        )
        ON CONFLICT (intent_id) DO UPDATE SET
            status = EXCLUDED.status,
            priority = EXCLUDED.priority,
            next_step = EXCLUDED.next_step,
            last_progress_at = EXCLUDED.last_progress_at,
            next_review_at = EXCLUDED.next_review_at,
            updated_at = NOW()
    """), {
        "intent_id": intent["intent_id"],
        "kind": intent["kind"],
        "origin": intent["origin"],
        "owner_user_id": intent["owner_user_id"],
        "status": intent["status"],
        "priority": intent.get("priority"),
        "next_step": intent.get("next_step"),
        "permission_tier": intent.get("permission_tier"),
        "last_progress_at": intent.get("last_progress_at"),
        "next_review_at": intent.get("next_review_at"),
        "correlation_id": intent.get("correlation_id"),
        "source_table": source_table,
        "source_id": source_id,
        "created_at": intent.get("created_at"),
    })


def sync_from_projections(db: Session, user_id: str) -> Dict[str, Any]:
    """Upsert every intent the read-only projection currently sees into the
    real `intent` table. Idempotent: re-running updates existing rows
    (matched by intent_id, which already encodes source_table:source_id)
    rather than duplicating them.

    Does NOT delete rows for intents the projection no longer sees (e.g. a
    reminder that got completed) — that reconciliation is a deliberate
    follow-up (matching §8 migration rule: dual-read before cutting over
    deletes), not a side effect of a sync call.
    """
    from app.services.intent_graph_projection import get_intent_graph

    graph = get_intent_graph(db, user_id)
    upserted = 0
    errors: List[str] = []

    for intent in graph["intents"]:
        try:
            source_table, source_id = intent["intent_id"].split(":", 1)
            _upsert(db, intent, source_table, source_id)
            upserted += 1
        except Exception as e:
            logger.warning(f"[intent_graph_service] upsert failed for {intent.get('intent_id')}: {e}")
            errors.append(f"{intent.get('intent_id')}: {e}")

    db.commit()
    return {
        "seen": graph["total"],
        "upserted": upserted,
        "errors": errors,
        "by_source": graph["by_source"],
    }


def list_intents(db: Session, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read the real, persisted intent table (as opposed to the live
    re-computed projection) — what's actually durable right now."""
    query = "SELECT * FROM intent WHERE owner_user_id = :uid"
    params: Dict[str, Any] = {"uid": user_id}
    if status:
        query += " AND status = :status"
        params["status"] = status
    query += " ORDER BY updated_at DESC"

    rows = db.execute(text(query), params).mappings().fetchall()
    return [dict(r) for r in rows]
