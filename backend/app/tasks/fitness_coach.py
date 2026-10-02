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
from typing import Any, Dict, List, Optional

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


# ─────────────────────────────────────────────────────────────────────────
# The cadence sweep (Step 24)
# ─────────────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.tasks.fitness_coach.sweep_due_occurrences",
    time_limit=120,
    soft_time_limit=100,
)
def sweep_due_occurrences(self) -> Dict[str, Any]:
    """Claim due per-athlete coaching occurrences and enqueue them.

    ONE global task, driven by one `scheduled_job` row. It is the only thing
    in this subsystem that reads without an owner, because its job is to find
    out whose turn it is — everything it then does is per-owner and explicit.

    This task is EXPECTED to be dispatched twice sometimes: `DBScheduler`
    seeds UTC `last_run_at`, which makes a daily ET cron fire twice (see
    `tests/test_db_scheduler_beat_double_fire.py`). The unique index on
    `(user_id, kind, occurrence_at)` absorbs that into one artifact, which is
    why the ledger exists rather than a "have we run yet" flag.

    The claim is written and COMMITTED before the enqueue. If the enqueue
    then fails, the row stays non-terminal and the next sweep reclaims it
    after the claim expiry — whereas enqueueing first would lose the
    occurrence whenever the process died in between, with no row to notice.
    """
    from app.db.session import SessionLocal
    from app.services.fitness import coaching_jobs

    db = SessionLocal()
    claimed: list = []
    try:
        for schedule in coaching_jobs.due_schedules(db):
            try:
                occurrence = coaching_jobs.claim_occurrence(db, schedule)
            except Exception as exc:
                logger.warning(
                    "[fitness-coach] could not claim %s for user=%s (%s): %s",
                    schedule.kind, str(schedule.user_id)[:8],
                    type(exc).__name__, exc,
                )
                db.rollback()
                continue
            # Committed per occurrence, not per sweep. One athlete's failure
            # must not roll back another athlete's claim.
            db.commit()
            if occurrence is not None:
                claimed.append(occurrence)
    finally:
        db.close()

    enqueued = 0
    for occurrence in claimed:
        if _enqueue(occurrence):
            enqueued += 1

    logger.info(
        "[fitness-coach] sweep claimed=%d enqueued=%d",
        len(claimed), enqueued,
    )
    return {"claimed": len(claimed), "enqueued": enqueued}


def _enqueue(occurrence) -> bool:
    """Send one occurrence to its task, and record that we did.

    The task name comes from `coaching_jobs.KIND_TASKS`, a mapping in code.
    An athlete's settings never supply one: a task name in a user-writable
    row is arbitrary code execution with extra steps.
    """
    from app.db.session import SessionLocal
    from app.services.fitness import coaching_jobs

    try:
        from app.celery_app import celery_app as app
        result = app.send_task(
            occurrence.task_name,
            kwargs={
                "user_id": occurrence.user_id,
                "run_id": occurrence.run_id,
            },
            queue=coaching_jobs.KIND_QUEUE,
        )
        task_id = getattr(result, "id", None)
    except Exception as exc:
        # The claim row survives. The next sweep reclaims it after the
        # expiry rather than the occurrence disappearing.
        logger.warning(
            "[fitness-coach] enqueue failed for run=%s (%s): %s",
            occurrence.run_id, type(exc).__name__, exc,
        )
        return False

    db = SessionLocal()
    try:
        coaching_jobs.mark_enqueued(db, occurrence.run_id, celery_task_id=task_id)
        db.commit()
    except Exception as exc:
        logger.debug(
            "[fitness-coach] could not stamp enqueued for %s (%s)",
            occurrence.run_id, type(exc).__name__,
        )
        db.rollback()
    finally:
        db.close()
    return True


def _occurrence_task(name: str):
    """Shared shape for the per-kind tasks.

    Every one of them: re-check the preference, do the work, record a
    terminal state. The re-check is the important part — an occurrence
    claimed at 06:58 must not run at 07:00 if the athlete switched the
    cadence off at 06:59.
    """
    def decorator(func):
        @celery_app.task(
            bind=True, name=name, time_limit=TASK_TIME_LIMIT,
            soft_time_limit=TASK_SOFT_TIME_LIMIT, max_retries=1,
        )
        def wrapper(self, user_id: str, run_id: str) -> Dict[str, Any]:
            from app.db.session import SessionLocal
            from app.services.fitness import coaching_jobs

            if not user_id or not str(user_id).strip():
                raise ValueError(
                    f"{name} requires an explicit user_id; there is no "
                    f"default owner"
                )
            db = SessionLocal()
            try:
                context = coaching_jobs.begin_run(db, user_id, run_id)
                db.commit()
                if context is None:
                    # Already terminal, or the preference changed. `begin_run`
                    # recorded which, so this is visible rather than silent.
                    return {"run_id": run_id, "status": "noop"}
                outcome = func(db, user_id, run_id, context)
                db.commit()
                return {"run_id": run_id, **(outcome or {})}
            except Exception as exc:
                logger.warning(
                    "[fitness-coach] %s failed for run=%s (%s): %s",
                    name, run_id, type(exc).__name__, exc,
                )
                db.rollback()
                try:
                    coaching_jobs.fail_run(
                        db, user_id, run_id,
                        category=type(exc).__name__[:40],
                        detail=str(exc),
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                raise
            finally:
                db.close()
        return wrapper
    return decorator


@_occurrence_task("app.tasks.fitness_coach.run_scheduled_review")
def run_scheduled_review(db, user_id: str, run_id: str, context) -> Dict[str, Any]:
    """A review on the athlete's own cadence.

    Gated on `FITNESS_COACH_PROACTIVE` separately from
    `FITNESS_COACH_REVIEW`: an on-demand review David asked for and an
    unprompted weekly one are different consents, and "stop bringing this up
    on your own" must not also mean "refuse when asked".
    """
    import asyncio

    from app.core.feature_flags import Flag, is_enabled
    from app.schemas.fitness_coach import RequestedBy, ReviewKind
    from app.services.fitness import coaching_jobs, reviews

    if not is_enabled(Flag.FITNESS_COACH_PROACTIVE):
        coaching_jobs.noop_run(db, user_id, run_id, "proactive_disabled")
        return {"status": "noop", "reason": "proactive_disabled"}

    kind_map = {
        "weekly_review": ReviewKind.WEEKLY,
        "biweekly_review": ReviewKind.BIWEEKLY,
        "monthly_review": ReviewKind.MONTHLY,
    }
    review_kind = kind_map.get(context["kind"], ReviewKind.WEEKLY)

    try:
        review = reviews.request_review(
            db, user_id, kind=review_kind,
            requested_by=RequestedBy.SCHEDULE,
        )
    except Exception as exc:
        # A review of this period already exists with the same data. Not a
        # failure: the answer has not changed, so spending a model call to
        # restate it would be the error.
        if type(exc).__name__ == "ReviewConflict":
            coaching_jobs.noop_run(db, user_id, run_id, "review_already_current")
            return {"status": "noop", "reason": "review_already_current"}
        raise

    result = asyncio.run(reviews.generate(db, user_id, review.id))
    coaching_jobs.complete_run(db, user_id, run_id, review_id=review.id)
    return {
        "status": result.review.status.value,
        "review_id": review.id,
    }


@_occurrence_task("app.tasks.fitness_coach.run_daily_checkin")
def run_daily_checkin(db, user_id: str, run_id: str, context) -> Dict[str, Any]:
    """Ask for ONE missing thing, chosen from the data.

    One, not all of them. A morning message asking about sleep, weight, food
    and soreness at once is a form, and David has been explicit that a
    repeated question he has already answered is worse than no question.

    Recomputed here rather than at claim time: if he logged his weight
    between the sweep and this task, the question is already answered and
    asking it is the nag.
    """
    from app.services.fitness import coaching_jobs
    from app.services.fitness.state import build_fitness_state

    state = build_fitness_state(db, user_id, fresh=True, redis_client=None)
    gap = _priority_gap(state)
    if gap is None:
        coaching_jobs.noop_run(db, user_id, run_id, "nothing_missing")
        return {"status": "noop", "reason": "nothing_missing"}

    coaching_jobs.complete_run(db, user_id, run_id, candidate_id=gap["key"])
    return {"status": "completed", "asked_about": gap["metric"]}


def _priority_gap(state) -> Optional[Dict[str, Any]]:
    """The single most useful missing thing, deterministically chosen.

    Ordered by what unblocks the most: a weigh-in gates the weekly rate,
    confirmed food days gate every intake average, and pain is last because
    it is only askable when there was a session to ask about.
    """
    quality = state.quality
    day = state.athlete_local_date.isoformat()

    observed = quality.observed_weight_days
    if observed is not None and observed < 3:
        return {
            "metric": "weight",
            "key": f"fitness_gap:{day}:weight",
            "question": "Did you weigh in this morning?",
        }
    if quality.nutrition_complete_days < 3:
        return {
            "metric": "nutrition",
            "key": f"fitness_gap:{day}:nutrition",
            "question": "Was yesterday's food log complete?",
        }
    if (quality.sleep_nights or 0) < 3:
        return {
            "metric": "sleep",
            "key": f"fitness_gap:{day}:sleep",
            "question": "How did you sleep?",
        }
    return None


@_occurrence_task("app.tasks.fitness_coach.run_measurement_nudge")
def run_measurement_nudge(db, user_id: str, run_id: str, context) -> Dict[str, Any]:
    """A tape-measurement reminder, on the athlete's own cadence.

    Suppressed when they already measured since the last occurrence —
    reminding someone to do something they have done is the clearest form of
    not having looked.
    """
    from datetime import timedelta as _td

    from app.services.fitness import coaching_jobs
    from app.services.fitness.observations import list_measurements

    recent = list_measurements(
        db, user_id,
        start_date=state_window_start(context), end_date=None, limit=5,
    )
    if recent:
        coaching_jobs.noop_run(db, user_id, run_id, "already_measured")
        return {"status": "noop", "reason": "already_measured"}

    day = context["occurrence_at"].date().isoformat()
    coaching_jobs.complete_run(
        db, user_id, run_id, candidate_id=f"fitness_gap:{day}:measurements",
    )
    return {"status": "completed", "asked_about": "measurements"}


def state_window_start(context):
    """The start of the window a nudge checks for recent activity.

    Half the cadence, so a reminder is suppressed by anything done since
    roughly the midpoint — long enough that yesterday's reading counts, short
    enough that a reading from two cycles ago does not.
    """
    from datetime import timedelta as _td
    occurrence = context["occurrence_at"]
    return (occurrence - _td(days=7)).date()


@_occurrence_task("app.tasks.fitness_coach.run_photo_nudge")
def run_photo_nudge(db, user_id: str, run_id: str, context) -> Dict[str, Any]:
    """A progress-photo reminder. Suppressed if one was taken recently.

    Photos are the most intrusive thing this system asks for, so the
    suppression window is generous and the cadence defaults to 28 days.
    """
    from sqlalchemy import text as _text

    from app.services.fitness import coaching_jobs

    try:
        recent = db.execute(_text("""
            SELECT 1 FROM progress_photo
            WHERE user_id = :uid AND created_at >= :since
            LIMIT 1
        """), {
            "uid": user_id, "since": context["occurrence_at"],
        }).fetchone()
    except Exception as exc:
        # No photo table, or it is shaped differently. A nudge is not worth
        # failing a run over.
        logger.debug(
            "[fitness-coach] photo check unavailable (%s)", type(exc).__name__,
        )
        recent = None

    if recent is not None:
        coaching_jobs.noop_run(db, user_id, run_id, "already_photographed")
        return {"status": "noop", "reason": "already_photographed"}

    day = context["occurrence_at"].date().isoformat()
    coaching_jobs.complete_run(
        db, user_id, run_id, candidate_id=f"fitness_gap:{day}:photos",
    )
    return {"status": "completed", "asked_about": "photos"}
