"""
Research plan cancellation + id resolution.

Two things live here because both the API route and Sara's tools need them:

`resolve_plan_id` — Sara quotes 8-char id prefixes in prose and then reads them
back to herself. An exact `WHERE id = :id` therefore answers "Plan not found"
for a plan that is very much running, which is half of why she reported nothing
was happening during the 2026-09-01 Salem incident.

`cancel_research_plan` — the explicit kill path. A plan that is merely marked
`cancelled` in the DB still has a Celery worker grinding through steps against
the LLM lane, so we revoke the task (terminate=True) as well; the executor's
own per-step reload of the plan is the backstop for a revoke that doesn't land.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.services.agent_activity import RESEARCH_LIVE_STATUSES

logger = logging.getLogger(__name__)

# Below this, a prefix is too ambiguous to act on (a uuid4's first 8 hex chars
# already give ~4 billion buckets; 4 chars would not).
MIN_PREFIX_LEN = 8


def resolve_plan_id(db, user_id: str, plan_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a full-or-prefix plan id to a single plan id owned by `user_id`.

    Returns `(plan_id, None)` on success or `(None, reason)` on failure.
    """
    raw = (plan_id or "").strip()
    if not raw:
        return None, "Missing plan_id"

    row = db.execute(
        text("SELECT id FROM research_plan WHERE id = :id AND user_id = :uid"),
        {"id": raw, "uid": user_id},
    ).fetchone()
    if row:
        return row.id, None

    if len(raw) < MIN_PREFIX_LEN:
        return None, (
            f"'{raw}' is too short to match a plan id — give at least "
            f"{MIN_PREFIX_LEN} characters."
        )

    rows = db.execute(
        text(
            "SELECT id, title FROM research_plan "
            "WHERE user_id = :uid AND id LIKE :prefix ORDER BY created_at DESC LIMIT 5"
        ),
        {"uid": user_id, "prefix": raw + "%"},
    ).fetchall()

    if len(rows) == 1:
        return rows[0].id, None
    if len(rows) > 1:
        listing = ", ".join(f"{r.id} ({r.title})" for r in rows)
        return None, f"'{raw}' matches {len(rows)} plans: {listing}"
    return None, None  # no match — caller supplies the recent-plans listing


def recent_plans_hint(db, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """The user's most recent plans, for a not-found message.

    Handing the model real ids beats a bare failure: it self-corrects instead of
    concluding the plan does not exist.
    """
    try:
        rows = db.execute(
            text(
                "SELECT id, title, status, current_step_index, "
                "       jsonb_array_length(steps) AS n_steps "
                "FROM research_plan WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"uid": user_id, "lim": limit},
        ).fetchall()
        return [
            {
                "plan_id": r.id,
                "title": r.title,
                "status": r.status,
                "progress": f"{(r.current_step_index or 0)}/{r.n_steps or 0}",
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Could not list recent research plans: %s", e)
        return []


def revoke_celery_task(celery_task_id: Optional[str]) -> bool:
    """Best-effort revoke of the worker running a plan. Never raises."""
    if not celery_task_id:
        return False
    try:
        from app.celery_app import celery_app
        celery_app.control.revoke(celery_task_id, terminate=True, signal="SIGTERM")
        return True
    except Exception as e:
        logger.warning("Could not revoke celery task %s: %s", celery_task_id, e)
        return False


def cancel_research_plan(db, user_id: str, plan_id: str) -> Dict[str, Any]:
    """Cancel a research plan by full id or id prefix.

    Returns `{"cancelled": bool, ...}`. A non-research id returns
    `{"cancelled": False, "error": None}` so callers can fall through to other
    task kinds without treating it as an error.
    """
    resolved, reason = resolve_plan_id(db, user_id, plan_id)
    if not resolved:
        return {"cancelled": False, "error": reason}

    row = db.execute(
        text(
            "SELECT id, title, status, celery_task_id FROM research_plan "
            "WHERE id = :id AND user_id = :uid"
        ),
        {"id": resolved, "uid": user_id},
    ).fetchone()
    if not row:
        return {"cancelled": False, "error": "Plan not found"}

    if row.status not in RESEARCH_LIVE_STATUSES:
        return {
            "cancelled": False,
            "id": row.id,
            "title": row.title,
            "error": f"Plan is already {row.status}",
        }

    revoked = revoke_celery_task(row.celery_task_id)

    db.execute(
        text(
            "UPDATE research_plan "
            "SET status = 'cancelled', completed_at = NOW(), updated_at = NOW(), "
            "    error_log = COALESCE(error_log, '') || :note "
            "WHERE id = :id"
        ),
        {"id": row.id, "note": "\nCancelled by user."},
    )
    db.commit()

    # The executor reloads the plan between steps and honours 'cancelled', so
    # even a revoke that missed its worker stops at the next step boundary.
    logger.info(
        "Cancelled research plan %s (%s); celery revoke=%s",
        row.id, row.title, revoked,
    )
    return {
        "cancelled": True,
        "id": row.id,
        "title": row.title,
        "kind": "research_plan",
        "celery_revoked": revoked,
    }
