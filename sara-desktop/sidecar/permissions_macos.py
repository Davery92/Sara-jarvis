"""
macOS permission detection (Desktop Jarvis Overhaul A8).

Reports grant state for the four permissions the sidecar depends on:
- screen_recording: mss screenshot capture
- accessibility: pygetwindow/pynput window control, AppleScript System Events
- input_monitoring: pynput global keyboard/mouse listening
- microphone: sounddevice mic capture (voice notes, push-to-talk)

Each check degrades gracefully to "unknown" if pyobjc isn't installed rather
than crashing the sidecar — this module is a no-op on non-macOS platforms.
"""
import logging
import platform

logger = logging.getLogger(__name__)

IS_MACOS = platform.system() == "Darwin"


def _check_screen_recording() -> str:
    """granted | denied | unknown"""
    try:
        import Quartz
        # CGPreflightScreenCaptureAccess does NOT prompt — pure query.
        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            return "granted" if Quartz.CGPreflightScreenCaptureAccess() else "denied"
        return "unknown"
    except ImportError:
        return "unknown"
    except Exception as e:
        logger.debug(f"Screen recording check failed: {e}")
        return "unknown"


def _check_accessibility() -> str:
    """granted | denied | unknown"""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return "granted" if AXIsProcessTrusted() else "denied"
    except ImportError:
        return "unknown"
    except Exception as e:
        logger.debug(f"Accessibility check failed: {e}")
        return "unknown"


def _check_input_monitoring() -> str:
    """granted | denied | unknown

    There's no clean public API for Input Monitoring specifically (separate
    from Accessibility since macOS 10.15). Heuristic: if Accessibility is
    granted, pynput's global listeners generally work too in practice for
    this app's use case, so we mirror that status rather than claim a
    check we can't actually make.
    """
    return _check_accessibility()


def _check_microphone() -> str:
    """granted | denied | unknown"""
    try:
        import AVFoundation
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
        # AVAuthorizationStatusAuthorized == 3
        if status == 3:
            return "granted"
        if status in (1, 2):  # Restricted, Denied
            return "denied"
        return "unknown"  # NotDetermined
    except ImportError:
        return "unknown"
    except Exception as e:
        logger.debug(f"Microphone check failed: {e}")
        return "unknown"


# Deep-link targets for "Open System Settings" buttons in the onboarding UI.
SYSTEM_SETTINGS_URLS = {
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
}


def get_permissions_report() -> dict:
    """Return the current grant state for every permission the sidecar needs.

    Non-macOS platforms report every permission as "not_applicable" — the
    Settings > Permissions tab hides the checklist entirely in that case.
    """
    if not IS_MACOS:
        return {
            "screen_recording": "not_applicable",
            "accessibility": "not_applicable",
            "input_monitoring": "not_applicable",
            "microphone": "not_applicable",
        }

    return {
        "screen_recording": _check_screen_recording(),
        "accessibility": _check_accessibility(),
        "input_monitoring": _check_input_monitoring(),
        "microphone": _check_microphone(),
    }
