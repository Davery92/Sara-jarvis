"""Celery tasks for the Fitness Coach review.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 20.2. On the `health` queue, with a
bounded retry and a hard time limit.

Three deliberate differences from `health_weekly.py`, which this sits beside:

* **There is no `_default_user_id()`.** That helper picks a user by email
  and falls back to the oldest row — a solo-owner stub, which is exactly
  what Step 2 of this plan existed to remove from the fitness HTTP path.
  Putting one back in a task would reintroduce it where nobody is looking,
  so `user_id` is required and an empty one is an error.
* **The retry is bounded and the time limit is hard.** A review that hangs
  on a slow Mac Studio must not hold a worker slot indefinitely: the
  `health` lane also carries the morning health rollups, and a stuck review
  would delay those.
* **A failure is recorded on the review row, not only in the log.** The
  generator marks the review `failed` with a category before raising, so a
  task that exhausts its retries leaves a row David can see rather than a
  review stuck at `running` forever.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

#: Hard ceiling for one generation, slightly above the generator's own
#: timeout so the generator gets to record its failure before the worker
#: kills the task. A task killed first would leave the review `running`.
TASK_TIME_LIMIT = 300
TASK_SOFT_TIME_LIMIT = 240

#: Retries are for transport, not for content. A rejected output is a
#: terminal `failed` review and must not be retried — the generator already
#: spent its one repair turn, and a third attempt produces a third opinion.
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 60


@celery_app.task(
    bind=True,
    name="app.tasks.fitness_coach.generate_review",
    time_limit=TASK_TIME_LIMIT,
    soft_time_limit=TASK_SOFT_TIME_LIMIT,
    max_retries=MAX_RETRIES,
)
def generate_review_task(
    self, user_id: str, review_id: str,
) -> Dict[str, Any]:
    """Generate one already-opened review.

    `user_id` is explicit and required: there is no default owner anywhere in
    this subsystem, and a task that guessed one would write a review of one
    athlete's data under another's id.
    """
    from app.db.session import SessionLocal
    from app.services.fitness import reviews

    if not user_id or not str(user_id).strip():
        raise ValueError(
            "generate_review requires an explicit user_id; there is no "
            "default owner"
        )
    if not review_id:
        raise ValueError("generate_review requires a review_id")

    logger.info(
        "[fitness-coach] generating review %s for user=%s",
        review_id, str(user_id)[:8],
    )
    db = SessionLocal()
    try:
        result = asyncio.run(reviews.generate(db, user_id, review_id))
        logger.info(
            "[fitness-coach] review %s -> %s (model=%s)",
            review_id, result.review.status.value, result.review.model_actual,
        )
        return {
            "review_id": review_id,
            "status": result.review.status.value,
            "model_actual": result.review.model_actual,
            "recommendations": len(result.recommendations),
            "notes": result.notes,
        }
    except reviews.ReviewDisabled as exc:
        # Not an error and not retryable: the flag is off on purpose.
        logger.info("[fitness-coach] %s", exc)
        return {"review_id": review_id, "status": "disabled"}
    except Exception as exc:
        # The generator records its own terminal failure before raising for
        # anything it can categorise, so reaching here means something
        # unexpected. Retry the transport a bounded number of times, then
        # leave the row as the generator left it.
        logger.warning(
            "[fitness-coach] review %s raised (%s): %s",
            review_id, type(exc).__name__, exc,
        )
        if self.request.retries < MAX_RETRIES:
            raise self.retry(
                exc=exc, countdown=RETRY_BACKOFF_SECONDS * (self.request.retries + 1),
            )
        _force_terminal(review_id, user_id, exc)
        raise
    finally:
        db.close()


def _force_terminal(review_id: str, user_id: str, exc: Exception) -> None:
    """Last resort: never leave a review `running`.

    A row stuck at `running` is the one state nothing can interpret — the UI
    shows a spinner forever and a scheduler will not open a replacement
    because one already exists for the period.
    """
    from app.db.session import SessionLocal
    from app.schemas.fitness_coach import ReviewFailureCategory
    from app.services.fitness import review_audit

    db = SessionLocal()
    try:
        review_audit.mark_failed(
            db, user_id, review_id,
            category=ReviewFailureCategory.INTERNAL_ERROR,
            detail=f"{type(exc).__name__}: {exc}"[:400],
        )
        db.commit()
    except Exception as inner:
        logger.error(
            "[fitness-coach] could not record terminal failure for %s (%s)",
            review_id, type(inner).__name__,
        )
        db.rollback()
    finally:
        db.close()


@celery_app.task(
    bind=True, name="app.tasks.fitness_coach.expire_recommendations",
)
def expire_recommendations_task(self, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Mark passed-deadline proposals expired. Retained, never deleted.

    `user_id` optional here because this is a maintenance sweep over rows
    that are already owner-scoped in the UPDATE — it changes a status and
    reads nothing out, so there is no owner to leak to.
    """
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.services.fitness.review_audit import expire_stale_recommendations

    db = SessionLocal()
    try:
        if user_id:
            owners = [user_id]
        else:
            owners = [
                r[0] for r in db.execute(text("""
                    SELECT DISTINCT user_id FROM fitness_coach_recommendation
                    WHERE decision_status = 'proposed'
                      AND expires_at IS NOT NULL AND expires_at <= NOW()
                """)).fetchall()
            ]
        total = 0
        for owner in owners:
            total += expire_stale_recommendations(db, owner)
        db.commit()
        return {"expired": total, "athletes": len(owners)}
    finally:
        db.close()
