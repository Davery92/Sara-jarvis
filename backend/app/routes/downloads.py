"""Desktop app download routes."""

import logging
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "downloads")

router = APIRouter(tags=["Downloads"])


@router.get("/api/downloads")
async def list_downloads(
    current_user: User = Depends(get_current_user)
):
    """List available desktop app downloads"""
    downloads = []

    if os.path.exists(DOWNLOADS_DIR):
        for filename in os.listdir(DOWNLOADS_DIR):
            filepath = os.path.join(DOWNLOADS_DIR, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)

                # Determine platform and arch
                platform = "unknown"
                arch = "x64"
                agent_type = "desktop"

                if "mac" in filename.lower():
                    platform = "macOS"
                    if "arm64" in filename.lower():
                        arch = "arm64"
                elif "win" in filename.lower():
                    platform = "Windows"
                elif "linux" in filename.lower() or "agent" in filename.lower():
                    platform = "Linux"
                    agent_type = "headless"
                elif filename.endswith(".asar"):
                    platform = "Windows"

                # Determine file type
                file_type = "archive"
                if filename.endswith(".exe"):
                    file_type = "installer"
                elif filename.endswith(".dmg"):
                    file_type = "installer"
                elif filename.endswith(".zip") or filename.endswith(".tar.gz"):
                    file_type = "portable"
                elif filename.endswith(".asar"):
                    file_type = "update"

                downloads.append({
                    "filename": filename,
                    "platform": platform,
                    "arch": arch,
                    "type": file_type,
                    "agent_type": agent_type,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

    downloads.sort(key=lambda x: (x["platform"], x["arch"]))

    version = "1.0.36"
    for d in downloads:
        if "1.0." in d["filename"]:
            try:
                v = d["filename"].split("-")[1]
                if v > version:
                    version = v
            except Exception:
                pass

    # Only keep the latest version per platform+arch combo
    latest: dict = {}
    for d in downloads:
        key = (d["platform"], d["arch"], d["agent_type"])
        existing = latest.get(key)
        if not existing or d["modified"] > existing["modified"]:
            latest[key] = d
    downloads = sorted(latest.values(), key=lambda x: (x["platform"], x["arch"]))

    return {"downloads": downloads, "version": version}


@router.get("/api/downloads/{filename}")
async def download_file(
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Download a desktop app installer"""
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(DOWNLOADS_DIR, safe_filename)

    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "application/octet-stream"
    if safe_filename.endswith(".zip"):
        media_type = "application/zip"
    elif safe_filename.endswith(".tar.gz"):
        media_type = "application/gzip"
    elif safe_filename.endswith(".exe"):
        media_type = "application/x-msdownload"
    elif safe_filename.endswith(".dmg"):
        media_type = "application/x-apple-diskimage"

    return FileResponse(
        filepath,
        media_type=media_type,
        filename=safe_filename
    )
