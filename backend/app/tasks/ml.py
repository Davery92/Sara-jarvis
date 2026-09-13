"""Celery tasks for the ML feature store + training pipeline (Desktop Jarvis
Overhaul C1/C2).

Scheduled via the `scheduled_job` table:
- `materialize-ml-features` at 2:30 AM ET (after consolidation at 2:00 AM,
  before daily-rhythm recompute at 3:45 AM)
- `sync-ml-notification-outcomes`

There is no nightly retrain. `retrain_all` queued into a Redis job plane with
no worker and no caller — the docstring advertised a 3:15 AM job that never
had a `scheduled_job` row — so it was deleted on 2026-09-13. Training is
started by hand from Settings > Intelligence via `routes/ml_control.py`.
"""
import logging
import os
from datetime import date, timedelta

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)
SOLO_USER_ID = get_owner_id()


@celery_app.task(name="app.tasks.ml.materialize_features", queue="cognitive")
def materialize_features():
    """Roll up yesterday's activity into one ml_feature_daily row."""
    from app.db.base import SessionLocal
    from app.services.ml.feature_store import materialize_features as _materialize

    target_date = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        try:
            features = _materialize(db, SOLO_USER_ID, target_date)
        except Exception as e:
            db.rollback()
            logger.error(f"materialize_features failed for {target_date}: {e}")
            return {"date": target_date.isoformat(), "error": str(e)}

    logger.info(f"materialize_features: computed feature row for {target_date}")
    return {"date": target_date.isoformat(), "total_focus_seconds": features.get("total_focus_seconds")}


@celery_app.task(name="app.tasks.ml.backfill_features", queue="cognitive")
def backfill_features(days: int = 30):
    """Manual/one-time backfill — run once to seed history for training."""
    from app.db.base import SessionLocal
    from app.services.ml.feature_store import backfill_features as _backfill

    with SessionLocal() as db:
        updated = _backfill(db, SOLO_USER_ID, days=days)
    logger.info(f"backfill_features: {updated} days materialized")
    return {"updated": updated}


@celery_app.task(name="app.tasks.ml.sync_notification_outcomes", queue="cognitive")
def sync_notification_outcomes():
    """Back-fill ml_notification_outcome.outcome from notification_log's
    engaged/dismissed_at/read_at columns, which get updated well after the
    row is first written (see _record_ml_notification_features)."""
    from app.db.base import SessionLocal
    from sqlalchemy import text

    updated = 0
    with SessionLocal() as db:
        try:
            result = db.execute(text("""
                UPDATE ml_notification_outcome mno
                SET outcome = CASE
                        WHEN nl.engaged THEN 'acted'
                        WHEN nl.read_at IS NOT NULL THEN 'opened'
                        WHEN nl.dismissed_at IS NOT NULL THEN 'dismissed'
                        WHEN nl.sent_at < NOW() - INTERVAL '48 hours' THEN 'ignored'
                        ELSE NULL
                    END,
                    outcome_latency_seconds = EXTRACT(EPOCH FROM (
                        COALESCE(nl.read_at, nl.dismissed_at) - nl.sent_at
                    ))
                FROM notification_log nl
                WHERE mno.notification_log_id = nl.id::text
                  AND mno.outcome IS NULL
                  AND (
                        nl.engaged OR nl.read_at IS NOT NULL OR nl.dismissed_at IS NOT NULL
                        OR nl.sent_at < NOW() - INTERVAL '48 hours'
                      )
            """))
            updated = result.rowcount or 0
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"sync_notification_outcomes failed: {e}")
            return {"updated": 0, "error": str(e)}

    logger.info(f"sync_notification_outcomes: {updated} rows updated")
    return {"updated": updated}
