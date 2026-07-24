"""
Scheduler diet — job classification (SINGULAR_SARA_MASTER_PLAN §4.4/§C11).

"Classify every scheduled job into: sensor, maintenance, anchor, legacy
cognition." This module holds the one classifier (shared with
`scripts/singular_sara_inventory.py`, which used to keep its own copy) and
persists the result onto `scheduled_job.singular_class` (added by
`migrations/add_scheduled_job_singular_class.py`) so the eventual diet has a
durable starting point instead of a report that has to be regenerated.

Best-effort heuristic only — every job should be hand-reviewed before C12
actually retires anything based on this classification.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_LEGACY_COGNITION_HINTS = (
    "deliberat", "checkin", "check_in", "anticipat", "idle", "daemon",
    "reflect", "dream", "consolidat", "curiosity", "self_audit", "self-audit",
)
_ANCHOR_HINTS = ("morning", "evening", "brief", "anchor", "wake")
_MAINTENANCE_HINTS = (
    "cleanup", "retention", "sync", "train", "heartbeat", "flush",
    "watchdog", "backup", "vacuum", "compact", "prune", "expire",
)
_SENSOR_HINTS = (
    "poll", "fetch", "ingest", "detect", "compute", "score", "calc",
    "pattern", "predict", "baseline",
)


def classify_job(job: Dict[str, Any]) -> str:
    haystack = " ".join(
        str(job.get(k, "") or "") for k in ("key", "display_name", "task_name", "category", "description")
    ).lower()
    if any(h in haystack for h in _LEGACY_COGNITION_HINTS):
        return "legacy_cognition"
    if any(h in haystack for h in _ANCHOR_HINTS):
        return "anchor"
    if any(h in haystack for h in _MAINTENANCE_HINTS):
        return "maintenance"
    if any(h in haystack for h in _SENSOR_HINTS):
        return "sensor"
    return "unclassified"


def backfill_singular_class(db: Session) -> Dict[str, Any]:
    """Classify every row in `scheduled_job` and persist the result onto its
    `singular_class` column. Idempotent — re-running just re-classifies."""
    rows = db.execute(text("""
        SELECT key, display_name, description, category, task_name FROM scheduled_job
    """)).mappings().fetchall()

    by_class: Dict[str, int] = {}
    for r in rows:
        job = dict(r)
        singular_class = classify_job(job)
        by_class[singular_class] = by_class.get(singular_class, 0) + 1
        db.execute(text("""
            UPDATE scheduled_job SET singular_class = :cls WHERE key = :key
        """), {"cls": singular_class, "key": job["key"]})

    db.commit()
    return {"total": len(rows), "by_singular_class": by_class}


def list_by_class(db: Session, singular_class: str = None) -> List[Dict[str, Any]]:
    query = "SELECT key, display_name, category, task_name, enabled, singular_class FROM scheduled_job"
    params: Dict[str, Any] = {}
    if singular_class:
        query += " WHERE singular_class = :cls"
        params["cls"] = singular_class
    query += " ORDER BY singular_class, key"
    rows = db.execute(text(query), params).mappings().fetchall()
    return [dict(r) for r in rows]
