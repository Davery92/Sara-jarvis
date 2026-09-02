"""
Agent Activity — the single source of truth for "what is Sara doing right now".

Every path that dispatches work on Sara's behalf must be visible here, because
this is what BOTH the UI (web badge, iOS floating pill) and Sara's own
`get_background_tasks` tool read. Before this module existed the route merged
`background_task` + `research_plan` inline while the tool queried only
`background_task`, so Sara could truthfully report "nothing is running" while a
research plan was mid-flight — which is exactly how the 2026-09-01 Salem
incident produced three concurrent duplicate handoffs.

Dispatch-path audit (2026-09-01):
  - chat handoffs / agent dispatch / fleet + host dispatch → `background_task`
    (`agent_dispatch.py` writes the row for every target, including managed hosts)
  - code mode                                             → `background_task`
  - research plans (origin `david_chat` AND `sara_internal`) → `research_plan`
  - meeting research (`meeting_research.build_prep`) runs synchronously inside
    the calendar-prep beat; it never outlives a request, so there is nothing to
    show. `automation_task` rows are standing orders (recurring schedules), not
    in-flight agent runs.
Anything new that runs on Sara's behalf and cannot be seen here is a bug.
"""

import logging
from typing import Any, Iterable, List, Optional

from pydantic import BaseModel
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Statuses the UI and the tool both treat as "in flight".
ACTIVE_STATUSES = ("pending", "running", "needs_clarification")


class TaskResponse(BaseModel):
    id: str
    status: str
    task_type: str
    original_query: str
    result_note_id: Optional[str] = None
    workspace_folder_id: Optional[str] = None
    clarification_question: Optional[str] = None
    error_message: Optional[str] = None
    status_label: Optional[str] = None  # friendly current-step label (e.g. code mode: "editing mul.py")
    origin: Optional[str] = None        # research plans: 'david_chat' | 'sara_internal'
    cancellable: bool = False           # client may offer a Cancel button
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    active_count: int
    total_count: int


def task_to_response(task) -> TaskResponse:
    """Convert a BackgroundTask model row to the wire shape."""
    return TaskResponse(
        id=task.id,
        status=task.status,
        task_type=task.task_type,
        original_query=task.original_query,
        result_note_id=task.result_note_id,
        workspace_folder_id=task.workspace_folder_id,
        clarification_question=task.clarification_question,
        error_message=task.error_message,
        status_label=(task.task_metadata or {}).get("status_label"),
        # The cancel endpoint handles background_task rows too, so anything
        # still in flight gets a Cancel button in the iOS sheet.
        cancellable=task.status in ACTIVE_STATUSES,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        updated_at=task.updated_at.isoformat() if getattr(task, "updated_at", None) else None,
    )


# Research plans live in their own `research_plan` table with their own API and
# no UI of their own, so they never appeared in Background Tasks — Sara would
# correctly report dispatching research and nothing showed up. Map them into the
# background-task shape and merge them into the recent/active listings.
RESEARCH_STATUS_MAP = {
    "draft": "pending",
    "paused": "pending",       # only set by the explicit /pause endpoint
    "stalled": "pending",      # lane sick; a resume attempt is scheduled
    "running": "running",
    "complete": "completed",
    "completed": "completed",
    "partial": "completed",    # some steps landed; findings were synthesized
    # `stuck` means the research agent asked Sara a question and is waiting for
    # her answer — it is in flight, not dead. It used to map to `failed`, which
    # would now light the iOS pill red for a plan that is working fine.
    "stuck": "needs_clarification",
    "failed": "failed",
    "cancelled": "failed",
}

# research_plan.status values that mean "this plan still owns the lane".
# Single-flight, cancel, and the create-time guard all key off this list.
RESEARCH_LIVE_STATUSES = ("draft", "running", "stuck", "stalled", "paused")

# Terminal statuses — nothing is going to move these on its own.
RESEARCH_TERMINAL_STATUSES = ("complete", "completed", "partial", "failed", "cancelled")


def research_plan_to_response(row) -> TaskResponse:
    """Render a research_plan row in the background-task response shape."""
    raw = getattr(row, "status", None) or ""
    mapped = RESEARCH_STATUS_MAP.get(raw, "running")
    steps = row.n_steps or 0
    label = None
    if steps and mapped in ACTIVE_STATUSES:
        step_no = min((row.current_step_index or 0) + 1, steps)
        # The step title is what makes the iOS pill legible ("Researching:
        # Peabody Essex Museum deep-dive") instead of a bare "Step 2 of 6".
        title = (getattr(row, "current_step_title", None) or "").strip()
        label = f"Step {step_no} of {steps}"
        if title:
            label = f"{label} — {title}"[:120]
    if raw == "stalled":
        label = f"Paused (LLM lane unavailable){' · ' + label if label else ''}"[:120]
    elif raw == "stuck":
        label = f"Waiting on Sara{' · ' + label if label else ''}"[:120]
    elif raw == "cancelled":
        label = "Cancelled"
    return TaskResponse(
        id=row.id,
        status=mapped,
        task_type="research_plan",
        original_query=row.title or row.objective or "Research plan",
        error_message=row.error_log or None,
        status_label=label,
        origin=getattr(row, "origin", None),
        cancellable=raw in RESEARCH_LIVE_STATUSES,
        created_at=row.created_at.isoformat() if row.created_at else None,
        started_at=row.started_at.isoformat() if row.started_at else None,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


_RESEARCH_SELECT = """
    SELECT id, title, objective, status, current_step_index, origin,
           jsonb_array_length(steps) AS n_steps,
           steps -> COALESCE(current_step_index, 0) ->> 'title' AS current_step_title,
           error_log, created_at, started_at, completed_at, updated_at
    FROM research_plan
    WHERE user_id = :uid
"""


def recent_research_plans(db, user_id: str, limit: int, include_active: bool) -> List[TaskResponse]:
    """Recent research plans for a user, newest first. Never raises — a broken
    research table must not take down the whole task list."""
    try:
        sql = _RESEARCH_SELECT
        if not include_active:
            sql += " AND status IN ('complete','completed','partial','stuck','failed','cancelled')"
        sql += " ORDER BY created_at DESC LIMIT :lim"
        rows = db.execute(text(sql), {"uid": user_id, "lim": limit}).fetchall()
        return [research_plan_to_response(r) for r in rows]
    except Exception as e:
        logger.warning("Could not load research plans for agent activity: %s", e)
        return []


def merge_task_lists(tasks: Iterable[TaskResponse], plans: Iterable[TaskResponse], limit: int) -> List[TaskResponse]:
    """Interleave the two sources newest-first and cap at `limit`."""
    merged = list(tasks) + list(plans)
    merged.sort(key=lambda t: t.created_at or "", reverse=True)
    return merged[:limit]


def list_response(task_responses: Iterable[TaskResponse]) -> TaskListResponse:
    tasks = list(task_responses)
    active = len([t for t in tasks if t.status in ACTIVE_STATUSES])
    return TaskListResponse(tasks=tasks, active_count=active, total_count=len(tasks))


async def get_agent_activity(
    db,
    user_id: str,
    limit: int = 25,
    include_active: bool = True,
    active_only: bool = False,
) -> List[TaskResponse]:
    """Everything Sara is doing (or recently did), from every dispatch path.

    `active_only` returns just the in-flight rows — the `/active` contract.
    Callers that want the counts should wrap the result in `list_response`.
    """
    from app.services.background_task_service import get_background_task_service

    service = get_background_task_service()

    if active_only:
        tasks = await service.get_active_tasks(db, user_id)
        plans = [
            p for p in recent_research_plans(db, user_id, limit, True)
            if p.status in ACTIVE_STATUSES
        ]
    else:
        # The stall watchdog lives on the active path; run it here too so a hung
        # task can't sit in the recent feed looking alive just because the
        # client polls /recent (the iOS pill and web badge both do).
        try:
            service.expire_stalled_tasks(db, user_id)
        except Exception as e:
            logger.warning("Stalled-task watchdog failed: %s", e)
        tasks = await service.get_recent_tasks(
            db, user_id, limit=limit, include_active=include_active
        )
        plans = recent_research_plans(db, user_id, limit, include_active)

    return merge_task_lists([task_to_response(t) for t in tasks], plans, limit)


# A live status is only believable for so long. The single-flight guard blocks
# new research while one of these rows exists, so a row nothing will ever move
# again would wedge research permanently — and there was exactly such a row in
# prod when this was written (a `stuck` plan from 2026-08-19). Age them out:
#   running — run_research_plan's Celery hard limit is ~6.1h, and every step
#             writes updated_at, so a `running` row untouched for 6h is a dead
#             worker, not a busy one.
#   others  — `stuck` waits at most SARA_ANSWER_TIMEOUT (1h) for Sara, `stalled`
#             resumes in 15 min, and a `draft` exists only between the INSERT
#             and the dispatch a line later. 2h is generous for all three.
# Actual concurrency is still prevented by the executor's Redis lane lock, so
# ageing out here can only ever cost us a queued plan, never a second agent.
RUNNING_MAX_AGE = "6 hours"
IDLE_LIVE_MAX_AGE = "2 hours"


def active_research_plans(db, user_id: str) -> List[Any]:
    """Raw rows for every research plan that still owns the lane, oldest first.

    Used by the create-time single-flight guard and by the cancel path. Returns
    `[]` rather than raising so a research-table problem can never block chat.
    """
    try:
        rows = db.execute(
            text(
                _RESEARCH_SELECT
                + f"""
                  AND (
                    (status = 'running'
                     AND COALESCE(updated_at, created_at) > NOW() - INTERVAL '{RUNNING_MAX_AGE}')
                    OR (status = ANY(:idle_live)
                        AND COALESCE(updated_at, created_at) > NOW() - INTERVAL '{IDLE_LIVE_MAX_AGE}')
                  )
                ORDER BY created_at ASC
                """
            ),
            {
                "uid": user_id,
                "idle_live": [s for s in RESEARCH_LIVE_STATUSES if s != "running"],
            },
        ).fetchall()
        return list(rows)
    except Exception as e:
        logger.warning("Could not check for live research plans: %s", e)
        return []
