"""Serve desktop app update files for electron-updater."""
import os
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/updates", tags=["Desktop Updates"])

UPDATES_DIR = os.environ.get("DESKTOP_UPDATES_DIR", "/updates")


@router.get("/{filename}")
async def get_update_file(filename: str):
    """Serve update artifacts (latest.yml, .exe, .zip, .blockmap, etc.).

    No auth required — electron-updater calls this before the user logs in.
    The files are not sensitive (same binaries the user already has).
    """
    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = os.path.join(UPDATES_DIR, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    # Guess media type
    if filename.endswith(".yml") or filename.endswith(".yaml"):
        media_type = "text/yaml"
    elif filename.endswith(".exe"):
        media_type = "application/octet-stream"
    elif filename.endswith(".zip"):
        media_type = "application/zip"
    elif filename.endswith(".blockmap"):
        media_type = "application/octet-stream"
    elif filename.endswith(".7z"):
        media_type = "application/x-7z-compressed"
    else:
        media_type = "application/octet-stream"

    return FileResponse(filepath, media_type=media_type, filename=filename)
