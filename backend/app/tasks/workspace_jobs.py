"""Celery task that executes a workspace job."""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.workspace_jobs.run_workspace_job")
def run_workspace_job(job_id: str):
    from app.services.workspace_jobs import run_job
    logger.info(f"[workspace_job] running {job_id}")
    run_job(job_id)
    return {"job_id": job_id, "status": "done"}
