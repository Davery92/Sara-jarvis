"""
Intent/action reconciliation truth audit (SINGULAR_SARA_MASTER_PLAN §13/§C0).

"Add truth audits for impossible state combinations, including failed task
plus completed mission." Two real, linked tables already carry the same piece
of work under two different state machines:

  - `background_task.status` (pending/running/completed/failed/needs_clarification)
  - `autonomy_mission.state` (pending/running/awaiting_confirm/done/failed/cancelled)

linked by `background_task.task_metadata ->> 'mission_id' = autonomy_mission.id`
(see `agent_dispatch.py`, which sets that key when a dispatch's mission is
created — e.g. `task.task_metadata = {**meta, "mission_id": mission_id}`).
Nothing today enforces that both sides agree, so a mission can be marked
`done` while the task that ran it recorded `failed`, or the reverse — exactly
the kind of "false completed action" the Definition of Done (§2) targets zero
of.

This module is read-only: it finds violations, it does not fix them. Fixing
requires the transactional reconciliation planned for C10; until then this is
the instrument that makes the fracture measurable instead of anecdotal (per
the C0 exit gate: "Existing contradictions are measurable rather than
anecdotal").
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class TruthViolation:
    rule: str
    severity: str  # "critical" | "warning"
    description: str
    record_ids: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "description": self.description,
            "record_ids": self.record_ids,
        }


def _check_task_mission_mismatch(db: Session) -> List[TruthViolation]:
    """A background_task and the autonomy_mission it dispatched must not
    disagree about whether the work succeeded."""
    violations: List[TruthViolation] = []
    rows = db.execute(text("""
        SELECT bt.id AS task_id, bt.status AS task_status,
               m.id AS mission_id, m.state AS mission_state
        FROM background_task bt
        JOIN autonomy_mission m
          ON m.id::text = bt.task_metadata ->> 'mission_id'
        WHERE (bt.status = 'failed' AND m.state = 'done')
           OR (bt.status = 'completed' AND m.state = 'failed')
    """)).fetchall()
    for row in rows:
        violations.append(TruthViolation(
            rule="task_mission_state_mismatch",
            severity="critical",
            description=(
                f"background_task {row.task_id} is '{row.task_status}' but its "
                f"mission {row.mission_id} is '{row.mission_state}' — the same "
                f"work cannot be both."
            ),
            record_ids={"background_task_id": str(row.task_id), "mission_id": str(row.mission_id)},
        ))
    return violations


def _check_mission_step_consistency(db: Session) -> List[TruthViolation]:
    """A mission marked 'done' must not have a step recorded 'failed', and
    must not be missing completed steps."""
    violations: List[TruthViolation] = []

    rows = db.execute(text("""
        SELECT DISTINCT m.id AS mission_id, m.state
        FROM autonomy_mission m
        JOIN autonomy_mission_step s ON s.mission_id = m.id
        WHERE m.state = 'done' AND s.status = 'failed'
    """)).fetchall()
    for row in rows:
        violations.append(TruthViolation(
            rule="completed_mission_has_failed_step",
            severity="critical",
            description=f"mission {row.mission_id} is 'done' but has a step recorded as 'failed'.",
            record_ids={"mission_id": str(row.mission_id)},
        ))

    rows = db.execute(text("""
        SELECT id AS mission_id, total_steps, completed_steps
        FROM autonomy_mission
        WHERE state = 'done' AND completed_steps < total_steps AND total_steps > 0
    """)).fetchall()
    for row in rows:
        violations.append(TruthViolation(
            rule="completed_mission_incomplete_steps",
            severity="critical",
            description=(
                f"mission {row.mission_id} is 'done' but only {row.completed_steps}/"
                f"{row.total_steps} steps are recorded complete."
            ),
            record_ids={"mission_id": str(row.mission_id)},
        ))
    return violations


def _check_task_error_consistency(db: Session) -> List[TruthViolation]:
    """A task cannot be both 'completed' and carrying an error message."""
    violations: List[TruthViolation] = []
    rows = db.execute(text("""
        SELECT id AS task_id, error_message
        FROM background_task
        WHERE status = 'completed' AND error_message IS NOT NULL AND error_message != ''
    """)).fetchall()
    for row in rows:
        violations.append(TruthViolation(
            rule="completed_task_has_error",
            severity="warning",
            description=(
                f"background_task {row.task_id} is 'completed' but recorded "
                f"error: {row.error_message[:120]!r}."
            ),
            record_ids={"background_task_id": str(row.task_id)},
        ))
    return violations


# Registry of independent checks. Each is best-effort: one check failing
# (e.g. a table missing in a fresh/test DB) does not abort the others.
_CHECKS = [
    _check_task_mission_mismatch,
    _check_mission_step_consistency,
    _check_task_error_consistency,
]


def run_truth_audit(db: Session) -> Dict[str, Any]:
    """Run every registered truth-audit check and return a flat report."""
    violations: List[TruthViolation] = []
    check_errors: List[str] = []
    for check in _CHECKS:
        try:
            violations.extend(check(db))
        except Exception as e:
            logger.warning(f"[truth_audit] check {check.__name__} failed: {e}")
            check_errors.append(f"{check.__name__}: {e}")

    return {
        "violation_count": len(violations),
        "violations": [v.as_dict() for v in violations],
        "checks_run": len(_CHECKS),
        "check_errors": check_errors,
    }
