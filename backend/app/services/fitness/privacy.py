"""Export and deletion for the fitness subsystem.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 30: "privacy export/deletion with
multi-year history" is on the step's test list, and there was no such path
in this codebase — so this is it, scoped to the tables this plan's steps
created plus the core fitness ones they read.

Two things it is careful about, both learned from the progress-photo
delete in Step 26:

* **An export says what it could not read.** A partial export presented as
  complete is worse than a failed one: somebody checking whether their data
  is all there would conclude it is. Every table that errored is named in
  the result.
* **A deletion says what it could not delete.** "Deleted" while rows remain
  is the one message this must not send. Object-storage bytes are
  particularly easy to get wrong — the photo path already tracks a
  `pending_cleanup` state for exactly that, and this reports it rather than
  claiming the photos are gone.

Deletion order is foreign keys first, and it is one transaction: a
half-deleted athlete is worse than an undeleted one, because the half that
remains is unreachable from the half that is gone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

UTC = timezone.utc

#: Rows per table in one export page. A multi-year history is tens of
#: thousands of sets, and an unbounded export is a request that times out
#: and gets retried forever.
EXPORT_PAGE = 5000

#: Every fitness table an athlete owns, with the column that owns it.
#: Ordered child-first, which is the deletion order: a parent deleted first
#: either fails on a foreign key or cascades silently, and neither is a
#: thing to find out in production.
#: The owner column is NOT always `user_id`: `fitness_measurement_type` and
#: `exercise_library` use `owner_user_id`, and assuming otherwise took the
#: whole deletion down with an UndefinedColumn the first time this ran.
#: `_owner_column` verifies each one against the catalogue, so a rename
#: shows up as a named failure rather than a rolled-back deletion.
OWNED_TABLES: Tuple[Tuple[str, str], ...] = (
    # Step 27-30 additions.
    ("fitness_automation_action", "user_id"),
    ("fitness_automation_policy", "user_id"),
    ("fitness_source_adapter", "user_id"),
    ("fitness_science_chunk", "user_id"),
    ("fitness_science_curation_event", "user_id"),
    ("fitness_science_annotation", "user_id"),
    ("fitness_science_revision", "user_id"),
    ("fitness_science_record", "user_id"),
    ("fitness_science_refresh_run", "user_id"),
    ("fitness_program_draft", "user_id"),
    ("fitness_template_revision", "user_id"),
    ("fitness_program_revision", "user_id"),
    ("fitness_photo_analysis", "user_id"),
    # The coach core.
    ("fitness_coach_recommendation", "user_id"),
    ("fitness_coach_review", "user_id"),
    ("fitness_coaching_job_run", "user_id"),
    ("fitness_coaching_schedule", "user_id"),
    ("fitness_target_revision", "user_id"),
    ("fitness_athlete_goal", "user_id"),
    ("fitness_athlete_limitation", "user_id"),
    ("fitness_athlete_profile_change", "user_id"),
    ("fitness_athlete_profile", "user_id"),
    ("fitness_measurement_period", "user_id"),
    ("fitness_measurement_type", "owner_user_id"),
    ("fitness_pain_report", "user_id"),
    ("fitness_exercise_performance", "user_id"),
    # Logs and plans.
    ("progress_photo", "user_id"),
    ("workout_log", "user_id"),
    ("workout", "user_id"),
    ("food_log", "user_id"),
    ("daily_recovery_log", "user_id"),
    ("fitness_daily_log", "user_id"),
    ("cardio_log", "user_id"),
    ("fitness_note", "user_id"),
    ("fitness_settings", "user_id"),
    ("fitness_goals", "user_id"),
    ("fitness_plan", "user_id"),
    ("fitness_template", "user_id"),
    ("fitness_phase", "user_id"),
    ("fitness_program", "user_id"),
)

#: Tables whose rows are the athlete's but which other subsystems also
#: read. Exported, never deleted by this path: `health_metric` is the
#: authority for body numbers across the whole system, and a fitness-scoped
#: deletion silently emptying it would take the health history with it.
EXPORT_ONLY_TABLES: Tuple[Tuple[str, str], ...] = (
    ("health_metric", "user_id"),
    ("action_receipt", "user_id"),
)


def _owner_column(db: Session, table: str, expected: str) -> Optional[str]:
    """The owner column, verified against the catalogue.

    None when the table does not exist or has no such column. Checked
    rather than assumed because the column is not uniformly `user_id` —
    `fitness_measurement_type` uses `owner_user_id` — and a wrong guess
    took the whole deletion down with an UndefinedColumn, which rolls back
    every table that had already succeeded.
    """
    return db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = :table AND column_name = :column
    """), {"table": table, "column": expected}).scalar()


@dataclass
class ExportResult:
    user_id: str
    generated_at: datetime
    tables: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    #: Tables that exist but could not be read, named. A partial export
    #: presented as complete is worse than a failed one.
    unreadable: List[str] = field(default_factory=list)
    #: Tables that do not exist in this database at all — expected, since
    #: this list spans several plan steps.
    absent: List[str] = field(default_factory=list)
    truncated: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unreadable and not self.truncated


def export_fitness_data(
    db: Session, user_id: str, *, page: int = EXPORT_PAGE,
) -> ExportResult:
    """Everything the fitness subsystem holds about one athlete.

    Owner-scoped in every query. Bounded per table, and a table that hit
    the bound is listed in `truncated` — an export that silently stopped at
    5000 sets would tell somebody their four-year history is four months
    long.
    """
    owner = _require_user(user_id)
    result = ExportResult(user_id=owner, generated_at=datetime.now(UTC))

    for table, column in OWNED_TABLES + EXPORT_ONLY_TABLES:
        exists = db.execute(text(
            "SELECT to_regclass(:name) IS NOT NULL"
        ), {"name": table}).scalar()
        if not exists:
            result.absent.append(table)
            continue
        if _owner_column(db, table, column) is None:
            # Named, not skipped silently: an export missing a table
            # because its owner column was renamed is an incomplete export,
            # and the reader has to be told which one.
            result.unreadable.append(
                f"{table}: no {column} column — the owner column was "
                f"renamed and this list is stale"
            )
            continue
        try:
            rows = db.execute(text(f"""
                SELECT * FROM {table} WHERE {column} = :u
                LIMIT :limit
            """), {"u": owner, "limit": page + 1}).fetchall()
        except Exception as exc:
            db.rollback()
            logger.warning(
                "[privacy] %s unreadable for export: %s", table, exc,
            )
            result.unreadable.append(f"{table}: {exc}"[:300])
            continue

        if len(rows) > page:
            result.truncated.append(table)
            rows = rows[:page]
        result.tables[table] = [
            _jsonable(dict(row._mapping)) for row in rows
        ]
        result.counts[table] = len(rows)

    return result


def _jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        elif hasattr(value, "__float__") and not isinstance(value, (int, float, bool)):
            out[key] = float(value)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            # Never in an export body. A photo's bytes belong behind the
            # owner-checked file route, not inlined into a JSON document
            # that will end up in a downloads folder.
            out[key] = f"<{len(bytes(value))} bytes omitted>"
        else:
            out[key] = value
    return out


@dataclass
class DeletionResult:
    user_id: str
    deleted: Dict[str, int] = field(default_factory=dict)
    #: Named, not swallowed. "Deleted" while rows remain is the one message
    #: this must not send.
    failed: List[str] = field(default_factory=list)
    absent: List[str] = field(default_factory=list)
    #: Object-storage bytes that could not be removed. The photo path
    #: already tracks this state; reporting it is the difference between a
    #: deletion and a claim.
    pending_cleanup: int = 0
    kept_tables: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failed and self.pending_cleanup == 0


def delete_fitness_data(
    db: Session, user_id: str, *, confirm: str,
) -> DeletionResult:
    """Delete one athlete's fitness data, child tables first.

    `confirm` must be the athlete's own id. Not a boolean: a stray `True`
    from a mis-parsed query string deletes a training history, and the id
    is the one value a caller cannot supply by accident.

    One transaction. A half-deleted athlete is worse than an undeleted one,
    because the half that remains is unreachable from the half that is
    gone.

    `health_metric` and `action_receipt` are deliberately NOT deleted here
    and are named in `kept_tables`: the first is the authority for body
    numbers across the whole system and the second is the audit trail for
    actions that affected more than fitness. Emptying either from a
    fitness-scoped call would be a deletion nobody asked for.
    """
    owner = _require_user(user_id)
    if confirm != owner:
        raise FitnessDataError(
            "deletion requires the athlete's own id as confirmation — a "
            "boolean flag is something a mis-parsed request can supply by "
            "accident, and this is not an action to take by accident"
        )

    result = DeletionResult(user_id=owner)
    result.kept_tables = [table for table, _ in EXPORT_ONLY_TABLES]

    # Photo bytes first, and through the service that knows about object
    # storage: deleting the rows would orphan the files, and the athlete
    # would have been told their photos are gone while the bytes remain.
    try:
        from app.services.fitness import photos

        rows = db.execute(text("""
            SELECT id FROM progress_photo
            WHERE user_id = :u AND deleted_at IS NULL
        """), {"u": owner}).fetchall()
        for row in rows:
            outcome = photos.delete_photo(db, owner, row.id)
            if not outcome.get("deleted"):
                result.pending_cleanup += 1
    except Exception as exc:
        db.rollback()
        logger.warning("[privacy] photo cleanup failed: %s", exc)
        result.failed.append(f"progress_photo bytes: {exc}"[:300])

    try:
        for table, column in OWNED_TABLES:
            exists = db.execute(text(
                "SELECT to_regclass(:name) IS NOT NULL"
            ), {"name": table}).scalar()
            if not exists:
                result.absent.append(table)
                continue
            resolved = _owner_column(db, table, column)
            if resolved is None:
                # A table whose owner column moved is a table this cannot
                # scope a delete to. Reported as a failure rather than
                # skipped: the deletion is incomplete and saying otherwise
                # is the message this must not send.
                result.failed.append(
                    f"{table}: no {column} column, so rows could not be "
                    f"scoped to one athlete"
                )
                continue
            deleted = db.execute(text(
                f"DELETE FROM {table} WHERE {resolved} = :u"
            ), {"u": owner})
            result.deleted[table] = deleted.rowcount or 0
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("[privacy] deletion rolled back: %s", exc)
        result.failed.append(f"deletion rolled back: {exc}"[:300])
        result.deleted = {}
        return result

    logger.info(
        "[privacy] deleted %d fitness rows for %s across %d tables",
        sum(result.deleted.values()), owner, len(result.deleted),
    )
    return result
