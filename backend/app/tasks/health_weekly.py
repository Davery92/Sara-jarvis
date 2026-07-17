"""Celery task for the Sunday 6 AM ET weekly health consolidation."""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


# Default user — single-user system today. Read from DB if not provided.
def _default_user_id() -> str:
    from sqlalchemy import text
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        # Prefer a real user (david@avery.cloud); fall back to first non-test row.
        row = db.execute(
            text("SELECT id FROM app_user WHERE email='david@avery.cloud' LIMIT 1")
        ).first()
        if row:
            return row.id
        row = db.execute(text("SELECT id FROM app_user ORDER BY created_at ASC LIMIT 1")).first()
        if not row:
            raise RuntimeError("No app_user rows present")
        return row.id


@celery_app.task(bind=True, name="app.tasks.health_weekly.run_weekly_health_report")
def run_weekly_health_report_task(self, user_id: str | None = None, send_push: bool = True) -> Dict[str, Any]:
    """Run the 3-stage weekly health consolidation pipeline."""
    from app.services.health_consolidation.runner import run_weekly_health_report_sync

    uid = user_id or _default_user_id()
    logger.info(f"[task] weekly_health_report start user={uid[:8]}")
    result = run_weekly_health_report_sync(uid, send_push=send_push)
    logger.info(f"[task] weekly_health_report done: {result.get('status')} id={result.get('report_id')}")
    return result
