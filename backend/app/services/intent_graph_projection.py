"""
Read-only intent-graph projection (SINGULAR_SARA_MASTER_PLAN §13/§4.3/§C3).

§4.3 wants one durable graph replacing the scattered queues: David requests,
commitments, reminders, standing orders, Sara's interests/goals,
investigations, missions, and waiting questions. Actually building that graph
means new `intent`/`intent_edge` tables and a real decision about which
system becomes the source of truth for each kind — a schema migration on
shared state, deliberately not done here without walking through it first.

This module is the read-only silhouette of that graph instead: it queries
the sources that already exist (`reminder`, `standing_order`,
`autonomy_mission`, `followup_thread`, `background_task`, `sara_interest`)
and maps each row into the canonical `IntentV1` shape,
so "everything Sara currently considers open" is visible as one list today —
same discipline as `body_state_projection.py` and `truth_audit.py`: a
projection over existing truth, not a new truth store, and nothing here
writes anything back.

Sara's self-originated interests get `origin="sara"` in exactly the same
shape as David's commitments get `origin="david"` — per §4.3: "Sara
interests and self-goals remain first-class... not downgraded into
notifications or hidden cron tasks."
"""

import logging
from typing import Any, Callable, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.contracts import IntentV1

logger = logging.getLogger(__name__)


def _reminders(db: Session, user_id: str) -> List[IntentV1]:
    rows = db.execute(text("""
        SELECT id, title, reminder_time, created_at
        FROM reminder
        WHERE user_id = :uid AND is_completed = false
        ORDER BY reminder_time
    """), {"uid": user_id}).fetchall()
    return [
        IntentV1(
            intent_id=f"reminder:{r.id}",
            kind="reminder",
            origin="david",
            owner_user_id=user_id,
            status="active",
            next_step=r.title,
            next_review_at=r.reminder_time,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _standing_orders(db: Session, user_id: str) -> List[IntentV1]:
    rows = db.execute(text("""
        SELECT id, description, source, last_executed_at, created_at
        FROM standing_order
        WHERE user_id = :uid AND status = 'active'
    """), {"uid": user_id}).fetchall()
    return [
        IntentV1(
            intent_id=f"standing_order:{r.id}",
            kind="standing_order",
            origin="sara" if r.source == "pattern" else "david",
            owner_user_id=user_id,
            status="active",
            next_step=r.description,
            last_progress_at=r.last_executed_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


_MISSION_STATUS_MAP = {"pending": "proposed", "running": "active", "awaiting_confirm": "blocked"}


def _missions(db: Session, user_id: str) -> List[IntentV1]:
    rows = db.execute(text("""
        SELECT id, source, state, priority, created_at, updated_at
        FROM autonomy_mission
        WHERE user_id = :uid AND state NOT IN ('done', 'failed', 'cancelled')
    """), {"uid": user_id}).fetchall()
    return [
        IntentV1(
            intent_id=f"mission:{r.id}",
            kind="mission",
            origin="sara" if r.source and r.source != "user" else "david",
            owner_user_id=user_id,
            status=_MISSION_STATUS_MAP.get(r.state, r.state),
            priority=r.priority,
            last_progress_at=r.updated_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _followup_threads(db: Session, user_id: str) -> List[IntentV1]:
    rows = db.execute(text("""
        SELECT id, topic, priority, source, opened_at, last_mentioned_at
        FROM followup_thread
        WHERE user_id = :uid AND status = 'open'
    """), {"uid": user_id}).fetchall()
    return [
        IntentV1(
            intent_id=f"followup_thread:{r.id}",
            kind="waiting_question",
            origin="david" if r.source == "chat" else "sara",
            owner_user_id=user_id,
            status="active",
            next_step=r.topic,
            priority=str(r.priority) if r.priority is not None else None,
            last_progress_at=r.last_mentioned_at,
            created_at=r.opened_at,
        )
        for r in rows
    ]


def _background_tasks(db: Session, user_id: str) -> List[IntentV1]:
    rows = db.execute(text("""
        SELECT id, original_query, status, created_at, updated_at
        FROM background_task
        WHERE user_id = :uid AND status IN ('pending', 'running', 'needs_clarification')
    """), {"uid": user_id}).fetchall()
    return [
        IntentV1(
            intent_id=f"background_task:{r.id}",
            kind="investigation",
            origin="david",
            owner_user_id=user_id,
            status="blocked" if r.status == "needs_clarification" else "active",
            next_step=r.original_query,
            last_progress_at=r.updated_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _interests(db: Session, user_id: str) -> List[IntentV1]:
    # `sara_interest` is global (single-user app, no user_id column — see
    # feedback_activitypub_interest_block: interests are blocked via
    # `blocked`, not deleted, so a retired interest stays inspectable rather
    # than disappearing and getting silently re-created by reflection).
    rows = db.execute(text("""
        SELECT id, topic, display_name, weight, created_at, last_acted_at
        FROM sara_interest
        WHERE blocked = false
    """), {}).fetchall()
    return [
        IntentV1(
            intent_id=f"interest:{r.id}",
            kind="interest",
            origin="sara",
            owner_user_id=user_id,
            status="active",
            priority=str(round(r.weight, 2)) if r.weight is not None else None,
            next_step=r.display_name or r.topic,
            last_progress_at=r.last_acted_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


# Registry of independent sources. Each is best-effort: one source failing
# (e.g. a table absent in a fresh/test DB) doesn't take the others down —
# same discipline as `truth_audit._CHECKS`.
_SOURCES: List[Tuple[str, Callable[[Session, str], List[IntentV1]]]] = [
    ("reminders", _reminders),
    ("standing_orders", _standing_orders),
    ("missions", _missions),
    ("followup_threads", _followup_threads),
    ("background_tasks", _background_tasks),
    ("interests", _interests),
]


def get_intent_graph(db: Session, user_id: str) -> Dict[str, Any]:
    """Everything Sara currently considers open, from every existing source,
    as one list of `IntentV1` — read-only; writes nothing, migrates nothing."""
    intents: List[IntentV1] = []
    by_source: Dict[str, int] = {}
    source_errors: Dict[str, str] = {}

    for name, fn in _SOURCES:
        try:
            found = fn(db, user_id)
            intents.extend(found)
            by_source[name] = len(found)
        except Exception as e:
            logger.warning(f"[intent_graph_projection] source {name!r} failed: {e}")
            source_errors[name] = str(e)
            by_source[name] = 0

    return {
        "total": len(intents),
        "by_source": by_source,
        "source_errors": source_errors,
        "intents": [i.model_dump(mode="json") for i in intents],
    }
