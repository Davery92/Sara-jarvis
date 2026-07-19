"""
Workspace jobs API — status + download for files collected by a workspace job.

GET /api/workspace/files/{job_id}/{filename} streams the file from wherever it
lives in object storage (attachments keep their original bucket). Authed and
ownership-checked, same posture as the artifact download endpoint. Kept separate
from routes/workspace.py (workbench-canvas state) to avoid tangling the two.
"""
import logging
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.models.workspace_job import WorkspaceJob
from app.core.config import settings
from app.main_simple import get_db, get_current_user

router = APIRouter(prefix="/api/workspace", tags=["workspace-jobs"])
logger = logging.getLogger(__name__)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    job = db.query(WorkspaceJob).filter(
        WorkspaceJob.id == job_id, WorkspaceJob.user_id == current_user.id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/files/{job_id}/{filename}")
async def download_workspace_file(
    job_id: str,
    filename: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = db.query(WorkspaceJob).filter(
        WorkspaceJob.id == job_id, WorkspaceJob.user_id == current_user.id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    files = (job.result or {}).get("files", [])
    entry = next((f for f in files if f.get("name") == filename), None)
    if not entry or not entry.get("key"):
        raise HTTPException(status_code=404, detail="File not found in job")

    bucket = entry.get("bucket") or settings.minio_bucket
    key = entry["key"]
    mime = entry.get("mime") or "application/octet-stream"

    try:
        from minio import Minio
        minio_url = settings.minio_url.replace("http://", "").replace("https://", "")
        client = Minio(
            minio_url,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )
        response = client.get_object(bucket, key)
        content = response.read()
        response.close()
        response.release_conn()
    except Exception as e:
        logger.error(f"workspace file fetch failed ({bucket}/{key}): {e}")
        raise HTTPException(status_code=502, detail="Failed to retrieve file from storage")

    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        BytesIO(content),
        media_type=mime,
        headers={"Content-Disposition": disposition},
    )
