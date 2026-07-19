"""
Workspace jobs — declared, bounded pipelines over existing capabilities.

Each job type is a small function that gathers file references into the job's
result. The runner drives a progress surface: it shows a progress bar while
running, then swaps the surface to a file_list on completion and drops one
completion observation into Sara's attention (dedupe is inherent — a job runs
once).
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Callable

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.models.workspace_job import WorkspaceJob
from app.models.surface import Surface

logger = logging.getLogger(__name__)


# --- Job implementations ----------------------------------------------------

def _email_attachments_fetch(user_id: str, params: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """Collect attachments from recent emails matching a sender, within N days."""
    from app.models.email import Email, EmailAttachment

    sender = (params.get("sender") or "").strip().lower()
    days = int(params.get("days", 7))
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))

    q = (
        db.query(EmailAttachment, Email)
        .join(Email, EmailAttachment.email_id == Email.id)
        .filter(Email.user_id == user_id)
        .filter(Email.received_at >= since)
        .filter(EmailAttachment.is_inline == False)  # noqa: E712
    )
    if sender:
        q = q.filter(
            (Email.sender_email.ilike(f"%{sender}%"))
            | (Email.sender_name.ilike(f"%{sender}%"))
        )

    files: List[Dict[str, Any]] = []
    for att, email in q.order_by(Email.received_at.desc()).limit(100).all():
        if not att.minio_key:
            continue
        files.append({
            "name": att.filename,
            "bucket": att.minio_bucket,
            "key": att.minio_key,
            "size": att.size or 0,
            "mime": att.content_type or "application/octet-stream",
            "from": email.sender_email,
        })

    who = sender or "anyone"
    summary = f"{len(files)} attachment(s) from {who} in the last {days} day(s)"
    return {"files": files, "summary": summary}


def _files_collect(user_id: str, params: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """Collect an explicit list of already-stored files (bucket/key/name)."""
    items = params.get("files") or []
    files = [
        {
            "name": f.get("name") or f.get("filename") or "file",
            "bucket": f.get("bucket"),
            "key": f.get("key"),
            "size": f.get("size", 0),
            "mime": f.get("mime", "application/octet-stream"),
        }
        for f in items
        if f.get("key")
    ]
    return {"files": files, "summary": f"{len(files)} file(s) collected"}


JOB_REGISTRY: Dict[str, Callable[[str, Dict[str, Any], Session], Dict[str, Any]]] = {
    "email_attachments_fetch": _email_attachments_fetch,
    "files_collect": _files_collect,
}


# --- Surface patching -------------------------------------------------------

def _progress_spec(title: str, label: str, value: float) -> Dict[str, Any]:
    return {"components": [
        {"type": "markdown", "text": f"### {title}"},
        {"type": "progress", "id": "p", "value": value, "max": 100, "label": label},
    ]}


def _file_list_spec(title: str, summary: str, files: List[Dict[str, Any]], job_id: str) -> Dict[str, Any]:
    entries = [
        {"name": f["name"], "job_id": job_id, "filename": f["name"],
         "size_bytes": f.get("size", 0), "mime": f.get("mime")}
        for f in files
    ]
    return {"components": [
        {"type": "markdown", "text": f"### {title}\n{summary}"},
        {"type": "file_list", "id": "files", "files": entries},
    ]}


def _patch_surface(db: Session, surface_id: str, spec: Dict[str, Any]) -> None:
    surface = db.query(Surface).filter(Surface.id == surface_id).first()
    if not surface or surface.status != "active":
        return
    surface.spec = spec
    surface.version = (surface.version or 1) + 1
    flag_modified(surface, "spec")
    db.commit()


# --- Runner -----------------------------------------------------------------

def run_job(job_id: str) -> None:
    """Execute a workspace job end-to-end. Safe to call from a Celery task."""
    db: Session = next(get_db())
    try:
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        if not job:
            logger.warning(f"[workspace_job] {job_id} not found")
            return
        if job.status not in ("pending",):
            logger.info(f"[workspace_job] {job_id} already {job.status}, skipping")
            return

        job.status = "running"
        db.commit()

        title = (job.params or {}).get("title") or "Workspace job"
        if job.surface_id:
            _patch_surface(db, job.surface_id, _progress_spec(title, "Gathering files…", 30))

        impl = JOB_REGISTRY.get(job.job_type)
        if not impl:
            raise ValueError(f"Unknown job_type '{job.job_type}'")

        result = impl(job.user_id, job.params or {}, db)
        job.result = result
        flag_modified(job, "result")
        job.status = "completed"
        db.commit()

        if job.surface_id:
            _patch_surface(
                db, job.surface_id,
                _file_list_spec(title, result.get("summary", ""), result.get("files", []), job.id),
            )

        _notify_complete(job.user_id, title, result)
        logger.info(f"[workspace_job] {job_id} completed: {result.get('summary')}")

    except Exception as e:
        logger.error(f"[workspace_job] {job_id} failed: {e}")
        try:
            job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(e)
                db.commit()
                if job.surface_id:
                    _patch_surface(db, job.surface_id, {"components": [
                        {"type": "markdown", "text": f"### {job.params.get('title','Job')}\n⚠️ Failed: {e}"},
                    ]})
        except Exception:
            db.rollback()
    finally:
        db.close()


def _notify_complete(user_id: str, title: str, result: Dict[str, Any]) -> None:
    """One completion observation; dedupe is inherent (the job runs once)."""
    try:
        import asyncio
        from app.services.observation_log import log_observation
        n = len(result.get("files", []))
        desc = f'Workspace job "{title}" finished — {result.get("summary", f"{n} file(s)")}.'
        coro = log_observation(user_id, description=desc, salience=0.7,
                               source="workspace_job", category="task_complete")
        # Celery worker / inline call may or may not have a running loop.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("loop running")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
    except Exception as e:
        logger.warning(f"[workspace_job] completion notify failed: {e}")


def create_job(user_id: str, job_type: str, params: Dict[str, Any], surface_id: str) -> WorkspaceJob:
    """Persist a pending job. Caller dispatches the Celery task."""
    db: Session = next(get_db())
    try:
        job = WorkspaceJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            job_type=job_type,
            params=params,
            status="pending",
            surface_id=surface_id,
            result={},
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()
