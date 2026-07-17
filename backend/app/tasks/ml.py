"""Celery tasks for the ML feature store + training pipeline (Desktop Jarvis
Overhaul C1/C2).

Scheduled via the `scheduled_job` table:
- `materialize-ml-features` at 2:30 AM ET (after consolidation at 2:00 AM,
  before daily-rhythm recompute at 3:45 AM)
- `ml-retrain-all` at 3:15 AM ET
"""
import logging
import os
from datetime import date, timedelta

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")

MODEL_FAMILIES = ["interruptibility_v2", "notification_value", "next_block", "rhythm_forecaster"]


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


@celery_app.task(name="app.tasks.ml.retrain_all", queue="cognitive")
def retrain_all():
    """Queue one train_model job per model family against the ML job plane
    (app/routes/ml_control.py) — the GPU-cluster ml-worker claims and runs
    them. Nightly; matches the voice-control training job pattern."""
    from app.services.ml.job_queue import create_ml_training_job

    queued = []
    for family in MODEL_FAMILIES:
        try:
            job = create_ml_training_job(family, requested_by="system:ml-retrain-all")
            queued.append(job["job_id"])
        except Exception as e:
            logger.error(f"retrain_all: failed to queue job for {family}: {e}")
    logger.info(f"retrain_all: queued {len(queued)} training jobs")
    return {"queued_job_ids": queued}
