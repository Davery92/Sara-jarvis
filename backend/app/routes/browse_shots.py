"""Serve browser screenshots captured by the `browse` tool.

The agent's investigation reports embed `![](…/api/browse-shots/<id>.png)`
image URLs; this serves the PNGs that were scp'd back from the VM.
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

BROWSE_SHOTS_DIR = os.path.abspath(
    os.environ.get("BROWSE_SHOTS_DIR", "/app/uploads/browse")
)


@router.get("/browse-shots/{name}")
async def get_browse_shot(name: str):
    # Defend against path traversal — only a bare filename is allowed.
    if "/" in name or ".." in name or not name.endswith(".png"):
        raise HTTPException(status_code=400, detail="Invalid name")
    path = os.path.join(BROWSE_SHOTS_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/png")
