"""
Focus Tracker

Consumes per-interval ticks from activity_monitor and turns them into:

  - focus_span events: a completed span of attention on a single (app, window),
    with aggregate counters and a derived activity state. Emitted when the
    window changes, the user goes idle, or the span hits MAX_SPAN_SECONDS.

  - activity_state events: emitted on transitions between derived states like
    DESK_FOCUSED_WORK, DESK_COMMUNICATION, DESK_BROWSING, DESK_MEETING,
    DESK_IDLE. These are NOT the central ActivityStateMachine states — they
    are desktop-derived signals that ACS can use alongside HA / calendar /
    presence input.

Spans shorter than MIN_SPAN_SECONDS are dropped as window-switching noise.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# A span shorter than this is treated as a flick — never emitted.
MIN_SPAN_SECONDS = 5.0

# Even on a single window, emit a span every MAX_SPAN_SECONDS so ACS gets
# periodic "still focused on X" updates rather than waiting indefinitely.
MAX_SPAN_SECONDS = 600.0  # 10 minutes


# ── State classifier ─────────────────────────────────────────────────────────
#
# Rule-based: app name (case-insensitive) and window-title substrings vote on
# the derived state. Add to these as you notice misclassifications.

_EDITOR_APPS = {
    "cursor.exe", "cursor",
    "code.exe", "code",
    "code - insiders.exe",
    "vim", "nvim", "gvim.exe",
    "emacs",
    "sublime_text.exe", "subl",
    "idea64.exe", "idea",
    "pycharm64.exe", "pycharm",
    "rider64.exe",
    "webstorm64.exe",
    "goland64.exe",
    "clion64.exe",
    "rubymine64.exe",
    "datagrip64.exe",
    "windsurf.exe",
    "atom.exe",
    "notepad++.exe",
}

_TERMINAL_APPS = {
    "windowsterminal.exe", "wt.exe",
    "powershell.exe", "pwsh.exe",
    "cmd.exe",
    "alacritty.exe",
    "tabby.exe",
    "terminal", "iterm2",
    "gnome-terminal", "konsole", "xterm",
}

_COMMUNICATION_APPS = {
    "slack.exe", "slack",
    "discord.exe", "discord",
    "teams.exe", "ms-teams.exe",
    "outlook.exe", "olk.exe",
    "thunderbird.exe",
    "signal.exe",
    "telegram.exe",
    "mail",  # macOS
    "messages",
}

_BROWSER_APPS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    "opera.exe", "vivaldi.exe", "arc.exe", "zen.exe",
    "safari",
}

_MEETING_APPS = {
    "zoom.exe", "zoom",
    "cpthost.exe",  # GoToMeeting
    "webex.exe",
    "googlemeet",
}

_MEETING_TITLE_HINTS = (
    "zoom meeting",
    "microsoft teams meeting",
    "google meet",
    "webex meeting",
)


def classify_state(app: Optional[str], window: Optional[str], idle_seconds: float) -> str:
    """Map (app, window, idle) to a desktop-derived activity state."""
    if idle_seconds >= 60:
        return "DESK_IDLE"

    app_l = (app or "").lower()
    window_l = (window or "").lower()

    # Meeting hint via window title beats almost anything else.
    if any(hint in window_l for hint in _MEETING_TITLE_HINTS):
        return "DESK_MEETING"

    if app_l in _MEETING_APPS:
        return "DESK_MEETING"

    if app_l in _EDITOR_APPS or app_l in _TERMINAL_APPS:
        return "DESK_FOCUSED_WORK"

    if app_l in _COMMUNICATION_APPS:
        return "DESK_COMMUNICATION"

    if app_l in _BROWSER_APPS:
        return "DESK_BROWSING"

    if not app_l:
        return "DESK_UNKNOWN"

    return "DESK_UNKNOWN"


# ── Span tracking ────────────────────────────────────────────────────────────


@dataclass
class _Span:
    app: Optional[str]
    window: Optional[str]
    start_ts: float
    keyboard_events: int = 0
    mouse_events: int = 0
    last_seen_ts: float = field(default_factory=time.time)


def _spans_match(a: _Span, app: Optional[str], window: Optional[str]) -> bool:
    """Two consecutive ticks belong to the same span if app+window match."""
    return (a.app or "") == (app or "") and (a.window or "") == (window or "")


FocusSpanCallback = Callable[[dict], Awaitable[None] | None]
StateChangeCallback = Callable[[dict], Awaitable[None] | None]
BrowserContextProvider = Callable[[], Optional[dict]]


def _is_browser_app(app: Optional[str]) -> bool:
    return (app or "").lower() in _BROWSER_APPS


class FocusTracker:
    """Stateful: feed one tick at a time via on_tick()."""

    def __init__(
        self,
        on_focus_span: Optional[FocusSpanCallback] = None,
        on_state_change: Optional[StateChangeCallback] = None,
        browser_context_provider: Optional[BrowserContextProvider] = None,
    ):
        self.on_focus_span = on_focus_span
        self.on_state_change = on_state_change
        self.browser_context_provider = browser_context_provider
        self._current: Optional[_Span] = None
        self._state: Optional[str] = None
        self._state_since: float = time.time()

    async def on_tick(self, summary: dict) -> None:
        """
        Called once per activity_monitor report interval. `summary` is the dict
        returned by ActivityMonitor.get_activity_summary().
        """
        now = time.time()
        app = summary.get("active_app")
        window = summary.get("active_window")
        kb = int(summary.get("keyboard_events", 0))
        mouse = int(summary.get("mouse_events", 0))
        idle_seconds = float(summary.get("idle_seconds", 0))

        # ── State classification ────────────────────────────────────────────
        new_state = classify_state(app, window, idle_seconds)
        if new_state != self._state:
            previous = self._state
            self._state = new_state
            self._state_since = now
            await self._emit_state(previous, new_state, now, app, window)

        # ── Span tracking ───────────────────────────────────────────────────
        if self._current is None:
            self._current = _Span(app=app, window=window, start_ts=now, last_seen_ts=now)
            return

        if _spans_match(self._current, app, window):
            # Same window: accumulate counters.
            self._current.keyboard_events += kb
            self._current.mouse_events += mouse
            self._current.last_seen_ts = now
            # If this span has been running too long, emit it as a checkpoint
            # and start a fresh one on the same window.
            if now - self._current.start_ts >= MAX_SPAN_SECONDS:
                await self._end_span(now, "max_duration")
                self._current = _Span(app=app, window=window, start_ts=now, last_seen_ts=now)
            return

        # Window changed: emit the previous span (if long enough) and open a new one.
        await self._end_span(now, "window_changed")
        self._current = _Span(app=app, window=window, start_ts=now, last_seen_ts=now)
        # The tick that crosses the boundary belongs to the new span.
        self._current.keyboard_events += kb
        self._current.mouse_events += mouse

    async def flush(self) -> None:
        """End any in-flight span. Call on shutdown."""
        if self._current is not None:
            await self._end_span(time.time(), "shutdown")
            self._current = None

    async def _end_span(self, end_ts: float, reason: str) -> None:
        span = self._current
        if span is None:
            return
        duration = end_ts - span.start_ts
        if duration < MIN_SPAN_SECONDS:
            # Too short — drop as window-switch noise.
            return
        payload = {
            "app": span.app,
            "window": span.window,
            "start_ts": span.start_ts,
            "end_ts": end_ts,
            "duration_seconds": round(duration, 2),
            "keyboard_events": span.keyboard_events,
            "mouse_events": span.mouse_events,
            "derived_state": self._state,
            "end_reason": reason,
        }
        # If the user was in a browser, enrich with active tab info from the
        # extension. Provider may return None if the extension hasn't reported
        # recently — in which case we just send the raw window title.
        if _is_browser_app(span.app) and self.browser_context_provider:
            try:
                ctx = self.browser_context_provider()
            except Exception:
                ctx = None
            if ctx:
                if ctx.get("url"):
                    payload["url"] = ctx["url"]
                if ctx.get("domain"):
                    payload["domain"] = ctx["domain"]
                if ctx.get("title"):
                    payload["page_title"] = ctx["title"]
        if self.on_focus_span:
            try:
                result = self.on_focus_span(payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error(f"focus_span callback failed: {e}")
        logger.info(
            "focus_span emitted: app=%s window=%r duration=%.1fs (%s)",
            span.app, (span.window or "")[:50], duration, reason
        )

    async def _emit_state(
        self,
        previous: Optional[str],
        new: str,
        now: float,
        app: Optional[str],
        window: Optional[str],
    ) -> None:
        if not self.on_state_change:
            return
        payload = {
            "state": new,
            "previous_state": previous,
            "since_ts": now,
            "active_app": app,
            "active_window": window,
        }
        try:
            result = self.on_state_change(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception as e:
            logger.error(f"activity_state callback failed: {e}")
        logger.info("activity_state: %s -> %s", previous, new)
