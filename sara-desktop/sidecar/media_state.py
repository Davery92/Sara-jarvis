"""Desktop system-audio awareness (Desktop Jarvis Overhaul A6/B2.4).

Reports whether media is currently playing on this desktop, so the Jetson
can boost its wake-word/barge-in thresholds instead of treating the TV or
music as ambient noise it must fight through at the same sensitivity as a
quiet room.
"""
import logging
import platform

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"


async def is_media_playing() -> bool:
    """Best-effort check; returns False (not True) on any failure or on
    platforms without an implementation — a false negative here just means
    the Jetson stays at its normal sensitivity, which is the safe default."""
    if IS_WINDOWS:
        return await _is_media_playing_windows()
    if IS_MACOS:
        return _is_media_playing_macos_coreaudio()
    return False


async def _is_media_playing_windows() -> bool:
    """GlobalSystemMediaTransportControls — any app with an active,
    playing media session (Spotify, browser video, etc.)."""
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )

        manager = await SessionManager.request_async()
        for session in manager.get_sessions():
            info = session.get_playback_info()
            # PLAYING == 4 in the GlobalSystemMediaTransportControlsSessionPlaybackStatus enum
            if info and info.playback_status == 4:
                return True
        return False
    except ImportError:
        logger.debug("winsdk not installed; media_state always reports False on Windows")
        return False
    except Exception as e:
        logger.debug(f"Windows media session check failed: {e}")
        return False


def _is_media_playing_macos_coreaudio() -> bool:
    """No public "now playing" API without private MediaRemote framework
    reverse-engineering — fall back to measuring actual output audio
    level as a heuristic (per the plan's documented fallback)."""
    try:
        import sounddevice as sd
        import numpy as np

        # Loopback capture requires a monitor/aggregate device most Macs
        # don't have configured by default — this is intentionally a soft
        # no-op (returns False) until such a device is set up, rather than
        # guessing at a nonexistent one.
        devices = sd.query_devices()
        loopback = next(
            (i for i, d in enumerate(devices)
             if d.get("max_input_channels", 0) > 0 and "loopback" in d.get("name", "").lower()),
            None,
        )
        if loopback is None:
            return False

        frames = sd.rec(1024, samplerate=44100, channels=1, device=loopback, blocking=True)
        rms = float(np.sqrt(np.mean(frames.astype(np.float32) ** 2) + 1e-10))
        return rms > 0.01
    except Exception as e:
        logger.debug(f"macOS CoreAudio media check failed: {e}")
        return False
