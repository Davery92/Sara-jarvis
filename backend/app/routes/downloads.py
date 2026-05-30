"""Desktop app download routes."""

import logging
import os
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "downloads")

router = APIRouter(tags=["Downloads"])


_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def _version_key(v: str) -> tuple:
    """Numeric tuple for proper semver comparison (1.0.30 < 1.0.51, not lex)."""
    try:
        return tuple(int(p) for p in v.split("."))
    except Exception:
        return (0, 0, 0)


def _classify(filename: str) -> dict:
    """Derive platform / arch / agent_type / file_type from filename."""
    lower = filename.lower()

    platform = "unknown"
    arch = "x64"
    agent_type = "desktop"

    if "mac" in lower or lower.endswith(".dmg"):
        platform = "macOS"
        if "arm64" in lower:
            arch = "arm64"
    elif "linux" in lower or lower.startswith("sara-agent"):
        platform = "Linux"
        if "agent" in lower:
            agent_type = "headless"
    elif "win" in lower or lower.endswith(".exe") or lower.endswith(".asar"):
        platform = "Windows"

    if "arm64" in lower:
        arch = "arm64"

    if lower.endswith(".dmg") or (lower.endswith(".exe") and "setup" in lower):
        file_type = "installer"
    elif lower.endswith(".exe"):
        file_type = "portable"
    elif lower.endswith(".zip") or lower.endswith(".tar.gz"):
        file_type = "portable"
    elif lower.endswith(".asar"):
        file_type = "update"
    else:
        file_type = "archive"

    return {
        "platform": platform,
        "arch": arch,
        "agent_type": agent_type,
        "type": file_type,
    }


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
                classification = _classify(filename)
                downloads.append({
                    "filename": filename,
                    **classification,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

    downloads.sort(key=lambda x: (x["platform"], x["arch"]))

    # Pick the highest version present anywhere in any filename.
    version = "0.0.0"
    for d in downloads:
        m = _VERSION_RE.search(d["filename"])
        if m and _version_key(m.group(1)) > _version_key(version):
            version = m.group(1)

    # Dedup to the latest per (platform, arch, agent_type, type) — so the
    # installer and portable for the same platform both survive.
    latest: dict = {}
    for d in downloads:
        key = (d["platform"], d["arch"], d["agent_type"], d["type"])
        existing = latest.get(key)
        if not existing or d["modified"] > existing["modified"]:
            latest[key] = d
    downloads = sorted(
        latest.values(),
        key=lambda x: (x["platform"], x["arch"], x["type"]),
    )

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
