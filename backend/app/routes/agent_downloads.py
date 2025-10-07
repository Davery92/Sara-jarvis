"""
Agent Download Endpoints
Serves Windows and macOS voice agent installers
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

router = APIRouter()

# Agent files location
AGENT_ROOT = Path(__file__).parent.parent.parent.parent / "shadow-agent"
DIST_DIR = AGENT_ROOT / "dist"

# Version tracking
CURRENT_VERSION = "1.0.0"


@router.get("/agent/downloads/info")
async def get_download_info() -> Dict:
    """
    Get information about available agent downloads

    Returns:
        - Available platforms
        - Download URLs
        - Version information
        - File sizes
    """
    downloads = {}

    # Windows - Single-file installer
    windows_installer = DIST_DIR / "windows" / "SaraShadowAgent-Installer.exe"
    if windows_installer.exists():
        downloads["windows"] = {
            "platform": "Windows",
            "version": CURRENT_VERSION,
            "filename": windows_installer.name,
            "size_mb": round(windows_installer.stat().st_size / (1024 * 1024), 2),
            "download_url": "/api/agent/downloads/windows",
            "requirements": "Windows 10 or later",
            "format": "Single-file executable (no installation required)"
        }

    # macOS - Single DMG installer
    macos_installer = DIST_DIR / "macos" / "SaraShadowAgent-Installer.dmg"
    if macos_installer.exists():
        downloads["macos"] = {
            "platform": "macOS",
            "version": CURRENT_VERSION,
            "filename": macos_installer.name,
            "size_mb": round(macos_installer.stat().st_size / (1024 * 1024), 2),
            "download_url": "/api/agent/downloads/macos",
            "requirements": "macOS 10.13 (High Sierra) or later",
            "format": "DMG installer (drag-and-drop to Applications)"
        }

    if not downloads:
        return {
            "error": "No agent packages available",
            "message": "Agent packages have not been built yet. Run packaging scripts first.",
            "instructions": {
                "windows": "cd shadow-agent && python3 package_windows.py",
                "macos": "cd shadow-agent && python3 package_macos.py"
            }
        }

    return {
        "version": CURRENT_VERSION,
        "platforms": downloads,
        "features": [
            "Wake word detection (custom 'sarah' model)",
            "Voice Activity Detection (Silero VAD)",
            "Speech-to-Text via Faster-Whisper",
            "Text-to-Speech integration",
            "System tray controls",
            "Multiple modes: Always-On, Shadow-Only, Push-to-Talk",
            "Echo suppression and barge-in support"
        ],
        "setup_required": [
            "Microphone access permission",
            "Network connection to Sara backend",
            "Audio output device"
        ]
    }


@router.get("/agent/downloads/windows")
async def download_windows_agent():
    """
    Download Windows agent installer (single-file executable)

    Returns:
        Single .exe file - no installation required
    """
    windows_installer = DIST_DIR / "windows" / "SaraShadowAgent-Installer.exe"

    if not windows_installer.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Windows installer not found",
                "message": "Windows agent has not been built yet",
                "instructions": "Run: cd shadow-agent && python3 package_windows.py"
            }
        )

    logger.info(f"Serving Windows agent download: {windows_installer.name}")

    return FileResponse(
        path=windows_installer,
        media_type="application/vnd.microsoft.portable-executable",
        filename=windows_installer.name,
        headers={
            "Content-Disposition": f"attachment; filename={windows_installer.name}",
            "X-Agent-Version": CURRENT_VERSION,
            "X-Agent-Platform": "windows"
        }
    )


@router.get("/agent/downloads/macos")
async def download_macos_agent():
    """
    Download macOS agent installer (single DMG file)

    Returns:
        DMG disk image with drag-and-drop installer
    """
    macos_installer = DIST_DIR / "macos" / "SaraShadowAgent-Installer.dmg"

    if not macos_installer.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "macOS installer not found",
                "message": "macOS agent has not been built yet (requires macOS to build DMG)",
                "instructions": "Run on macOS: cd shadow-agent && python3 package_macos.py"
            }
        )

    logger.info(f"Serving macOS agent download: {macos_installer.name}")

    return FileResponse(
        path=macos_installer,
        media_type="application/x-apple-diskimage",
        filename=macos_installer.name,
        headers={
            "Content-Disposition": f"attachment; filename={macos_installer.name}",
            "X-Agent-Version": CURRENT_VERSION,
            "X-Agent-Platform": "macos"
        }
    )


@router.get("/agent/downloads/latest")
async def get_latest_version():
    """
    Check for latest agent version
    Used for auto-update checks

    Returns:
        Current version and changelog
    """
    return {
        "version": CURRENT_VERSION,
        "released": "2025-01-XX",  # Update when releasing
        "changelog": [
            "Initial release with voice control",
            "Wake word detection (custom 'sarah' model)",
            "System tray controls",
            "Multiple voice modes",
            "Echo suppression and barge-in support"
        ],
        "download_url": "/api/agent/downloads/info",
        "update_required": False,  # Set to True when new version available
        "min_backend_version": "1.0.0"
    }


@router.post("/agent/downloads/track")
async def track_download(request: Request, platform: str, version: str):
    """
    Track agent downloads (analytics)

    Args:
        platform: windows, macos, linux
        version: Version downloaded
    """
    # Get client info
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    logger.info(
        f"Agent download: platform={platform}, version={version}, "
        f"ip={client_ip}, user_agent={user_agent}"
    )

    # Could store in database for analytics
    # For now, just log it

    return {
        "status": "tracked",
        "platform": platform,
        "version": version,
        "message": "Download tracked successfully"
    }


@router.get("/agent/config/default")
async def get_default_config():
    """
    Get default configuration template
    For users to customize before first run

    Returns:
        Default config.json template
    """
    return {
        "backend_url": "ws://10.185.1.180:8000",
        "voice_mode": "always_on",  # always_on, shadow_only, push_to_talk
        "wake_word": {
            "model_path": None,  # Auto-detect
            "threshold": 0.5,  # 0.0-1.0, lower = more sensitive
            "debounce_seconds": 1.5
        },
        "vad": {
            "threshold": 0.5,
            "min_speech_duration_ms": 200,
            "min_silence_duration_ms": 500
        },
        "audio": {
            "sample_rate": 16000,
            "pre_roll_seconds": 1.5,
            "echo_suppression": True
        },
        "ui": {
            "show_notifications": True,
            "auto_start": True,
            "minimize_to_tray": True
        },
        "logging": {
            "level": "INFO",  # DEBUG, INFO, WARNING, ERROR
            "file": "~/.sara/shadow-agent-voice.log"
        }
    }


@router.get("/agent/health")
async def check_agent_compatibility():
    """
    Check if backend is compatible with voice agents
    Agents can call this to verify connectivity

    Returns:
        Backend status and voice service availability
    """
    # Check if Wyoming endpoints exist
    wyoming_available = True  # Should check actual service

    return {
        "status": "ok",
        "backend_version": CURRENT_VERSION,
        "services": {
            "wyoming_asr": {
                "available": wyoming_available,
                "endpoint": "/wyoming/asr",
                "provider": "Faster-Whisper"
            },
            "wyoming_tts": {
                "available": wyoming_available,
                "endpoint": "/wyoming/tts",
                "provider": "OpenAI TTS"
            },
            "shadow_mode": {
                "available": True,
                "endpoints": ["/shadow/*"]
            }
        },
        "features": {
            "voice_control": True,
            "shadow_mode": True,
            "tool_execution": True,
            "memory_system": True
        },
        "message": "Backend ready for voice agents"
    }
