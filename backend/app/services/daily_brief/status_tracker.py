"""
Lightweight runtime status tracking for daily brief jobs.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")


def probe_briefs_writable() -> Dict[str, Any]:
    """Write+delete a probe file under BRIEFS_DIR to detect permission/mount issues.

    Returns {"ok": bool, "path": str, "error": str|None}. Logs loudly on failure —
    a non-writable briefs dir silently kills weekly_synthesis and the morning brief.
    Also consumed by the Phase-2 interoception self-check.
    """
    probe = BRIEFS_DIR / ".write_probe"
    try:
        BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok")
        probe.unlink()
        return {"ok": True, "path": str(BRIEFS_DIR), "error": None}
    except Exception as e:  # pragma: no cover - environment dependent
        logger.error(
            "BRIEFS DIR NOT WRITABLE (%s): %s — weekly_synthesis / morning brief "
            "will fail. Check ownership/uid of the data/briefs mount.",
            BRIEFS_DIR, e,
        )
        return {"ok": False, "path": str(BRIEFS_DIR), "error": str(e)}


def _utc_iso(timestamp: Optional[datetime] = None) -> str:
    ts = timestamp or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.isoformat()


class DailyBriefStatusTracker:
    """Persists operational timestamps per user under `data/briefs/<user>/status.json`."""

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR

    def _status_path(self, user_id: str) -> Path:
        user_dir = self.briefs_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "status.json"

    def get_status_path(self, user_id: str) -> Path:
        """Get the on-disk status file path."""
        return self._status_path(user_id)

    def read_status(self, user_id: str) -> Dict[str, Any]:
        """Read status document, returning an empty dict on missing/invalid state."""
        path = self._status_path(user_id)
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning(f"Failed to read daily brief status for {user_id[:8]}: {exc}")
        return {}

    def record_event(
        self,
        user_id: str,
        event_name: str,
        timestamp: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record or update a named timestamped event."""
        status = self.read_status(user_id)

        events = status.get("events")
        if not isinstance(events, dict):
            events = {}
        events[event_name] = _utc_iso(timestamp)
        status["events"] = events

        if details:
            status_details = status.get("details")
            if not isinstance(status_details, dict):
                status_details = {}
            status_details.update(details)
            status["details"] = status_details

        status["updated_at"] = _utc_iso()

        path = self._status_path(user_id)
        path.write_text(json.dumps(status, indent=2))


brief_status_tracker = DailyBriefStatusTracker()
