"""Thin async client for the backend's ACS v2 endpoints.

Single httpx.AsyncClient owned by the daemon, reused for every call. Methods
return parsed dicts; errors are logged and re-raised so the caller can decide
whether to abort or carry on (e.g. heartbeat survives backend blips).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("acs-daemon.backend")


class BackendClient:
    def __init__(self, base_url: str, daemon_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"X-Daemon-Token": daemon_token},
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── heartbeat ──
    async def heartbeat(
        self, *, state: str, version: str, pid: int, hostname: str,
        started_at: datetime, last_tick_summary: Optional[str],
        want_delta: bool = False, capabilities: Optional[list] = None,
    ) -> dict:
        """Post a heartbeat. Returns the parsed response (incl. ACS1 world_delta
        when want_delta=True). Empty dict on any error — heartbeats survive
        backend blips.

        `capabilities` (SINGULAR_SARA §C7) feeds the backend's
        `body_capability` record for this VM workshop — additive; older
        backends without that field simply ignore it."""
        payload = {
            "state": state, "version": version, "pid": pid, "hostname": hostname,
            "started_at": started_at.isoformat(),
            "last_tick_summary": last_tick_summary,
            "want_delta": want_delta,
            "capabilities": capabilities or [],
        }
        try:
            r = await self._client.post("/api/acs/v2/heartbeat", json=payload)
        except httpx.HTTPError as e:
            logger.warning("heartbeat network error: %s", e)
            return {}
        if r.status_code >= 400:
            logger.warning("heartbeat rejected: %s %s", r.status_code, r.text[:200])
            return {}
        logger.debug("heartbeat ok")
        try:
            return r.json() or {}
        except Exception:
            return {}

    # ── activity log ──
    async def append_activity(
        self, *, kind: str, summary: str, body: Optional[str] = None,
        tags: Optional[list[str]] = None, metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict]:
        payload = {
            "kind": kind, "summary": summary, "body": body,
            "tags": tags or [], "metadata": metadata or {},
        }
        try:
            r = await self._client.post("/api/acs/v2/activity", json=payload)
        except httpx.HTTPError as e:
            logger.warning("append_activity network error: %s", e)
            return None
        if r.status_code >= 400:
            logger.warning("append_activity rejected: %s %s", r.status_code, r.text[:200])
            return None
        return r.json()

    async def list_activity(self, *, limit: int = 20, kind: Optional[str] = None) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if kind:
            params["kind"] = kind
        try:
            r = await self._client.get("/api/acs/v2/activity", params=params)
        except httpx.HTTPError as e:
            logger.warning("list_activity network error: %s", e)
            return []
        if r.status_code >= 400:
            logger.warning("list_activity rejected: %s %s", r.status_code, r.text[:200])
            return []
        return r.json() or []

    # ── focus ──
    async def get_focus(self) -> dict:
        try:
            r = await self._client.get("/api/acs/v2/focus")
        except httpx.HTTPError as e:
            logger.warning("get_focus network error: %s", e)
            return {"topic": None, "why": None, "set_at": None}
        if r.status_code >= 400:
            return {"topic": None, "why": None, "set_at": None}
        return r.json() or {}

    async def set_focus(self, *, topic: str, why: Optional[str]) -> None:
        try:
            r = await self._client.post("/api/acs/v2/focus", json={"topic": topic, "why": why})
        except httpx.HTTPError as e:
            logger.warning("set_focus network error: %s", e)
            return
        if r.status_code >= 400:
            logger.warning("set_focus rejected: %s %s", r.status_code, r.text[:200])

    async def clear_focus(self) -> None:
        try:
            r = await self._client.delete("/api/acs/v2/focus")
        except httpx.HTTPError as e:
            logger.warning("clear_focus network error: %s", e)
            return
        if r.status_code >= 400:
            logger.warning("clear_focus rejected: %s %s", r.status_code, r.text[:200])

    # ── tools (Phase 7) ──
    # Per-tool timeouts. Web/search tools hit external APIs and can take
    # 30s+ for Tavily + content extraction; the default 15s ate them.
    _TOOL_TIMEOUTS: Dict[str, float] = {
        "web_search": 60.0,
        "web_fetch": 45.0,
        "search_notes": 20.0,
        "search_memory": 20.0,
        "write_note": 15.0,
        # Container tools — provision_container does apt installs (60-180s
        # typical), exec can run anything up to its own 600s ceiling.
        "provision_container": 1500.0,
        "list_containers": 10.0,
        "exec_in_container": 660.0,
        "destroy_container": 90.0,
        "node_status": 15.0,
        # Interests — all cheap DB ops.
        "list_interests": 10.0,
        "add_interest": 15.0,  # embedding lookup adds latency
        "bump_interest": 10.0,
        "touch_interest": 10.0,
    }

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call one of the daemon-tool endpoints. Returns either the parsed
        response on success, or {"_error": "..."} on failure (we never raise
        from here — the daemon handles the result either way and logs it)."""
        url = f"/api/acs/v2/tools/{name}"
        timeout = self._TOOL_TIMEOUTS.get(name, 15.0)
        try:
            r = await self._client.post(
                url, json=args,
                timeout=httpx.Timeout(timeout, connect=5.0),
            )
        except httpx.HTTPError as e:
            # Surface a useful error string — bare exceptions from httpx
            # often stringify to '', which leaves Sara guessing.
            err_str = str(e) or e.__class__.__name__
            logger.warning("tool %s network error: %s", name, err_str)
            return {"_error": f"network: {err_str}"}
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text[:200])
            except Exception:
                detail = r.text[:200]
            logger.warning("tool %s failed (%s): %s", name, r.status_code, detail)
            return {"_error": f"http {r.status_code}: {detail}"}
        try:
            return r.json()
        except Exception as e:
            return {"_error": f"parse: {e}"}

    # ── recall ──
    async def list_related_activity(
        self, *, topic: str, limit: int = 5,
        exclude_recent_minutes: int = 15, min_similarity: float = 0.55,
    ) -> list[dict]:
        if not topic.strip():
            return []
        params = {
            "topic": topic,
            "limit": limit,
            "exclude_recent_minutes": exclude_recent_minutes,
            "min_similarity": min_similarity,
        }
        try:
            r = await self._client.get("/api/acs/v2/activity/related", params=params)
        except httpx.HTTPError as e:
            logger.warning("list_related_activity network error: %s", e)
            return []
        if r.status_code >= 400:
            logger.warning("list_related_activity rejected: %s %s",
                           r.status_code, r.text[:200])
            return []
        return r.json() or []

    # ── inbox ──
    async def list_inbox(self, *, limit: int = 20) -> list[dict]:
        try:
            r = await self._client.get("/api/acs/v2/inbox", params={"limit": limit})
        except httpx.HTTPError as e:
            logger.warning("list_inbox network error: %s", e)
            return []
        if r.status_code >= 400:
            logger.warning("list_inbox rejected: %s %s", r.status_code, r.text[:200])
            return []
        return r.json() or []

    async def inbox_pickup(self, item_id: str) -> Optional[dict]:
        try:
            r = await self._client.post(f"/api/acs/v2/inbox/{item_id}/pickup")
        except httpx.HTTPError as e:
            logger.warning("inbox_pickup network error: %s", e)
            return None
        if r.status_code >= 400:
            logger.warning("inbox_pickup rejected: %s %s", r.status_code, r.text[:200])
            return None
        return r.json()

    async def inbox_complete(self, item_id: str, *, summary: str) -> Optional[dict]:
        try:
            r = await self._client.post(
                f"/api/acs/v2/inbox/{item_id}/complete",
                json={"summary": summary},
            )
        except httpx.HTTPError as e:
            logger.warning("inbox_complete network error: %s", e)
            return None
        if r.status_code >= 400:
            logger.warning("inbox_complete rejected: %s %s", r.status_code, r.text[:200])
            return None
        return r.json()

    async def inbox_dismiss(self, item_id: str, *, reason: str) -> Optional[dict]:
        try:
            r = await self._client.post(
                f"/api/acs/v2/inbox/{item_id}/dismiss",
                json={"reason": reason},
            )
        except httpx.HTTPError as e:
            logger.warning("inbox_dismiss network error: %s", e)
            return None
        if r.status_code >= 400:
            logger.warning("inbox_dismiss rejected: %s %s", r.status_code, r.text[:200])
            return None
        return r.json()

    # ── interests (ambient read) ──
    async def list_interests(
        self, *, limit: int = 8, min_weight: float = 0.1,
    ) -> list[dict]:
        """Read her standing interests for ambient context. Same data the
        list_interests tool returns; the daemon calls it on every think to
        show her what's pulling at her, so it lives here as a first-class
        method, not a generic call_tool."""
        try:
            r = await self._client.post(
                "/api/acs/v2/tools/list_interests",
                json={"limit": limit, "min_weight": min_weight},
            )
        except httpx.HTTPError as e:
            logger.warning("list_interests network error: %s", e)
            return []
        if r.status_code >= 400:
            logger.warning("list_interests rejected: %s %s",
                           r.status_code, r.text[:200])
            return []
        body = r.json() or {}
        return body.get("interests") or []

    # ── goals (ambient read) ──
    async def list_goals(self, *, status: str = "open") -> list[dict]:
        """Read her open goals for ambient context — the persistent intent
        that survives across thinks and restarts. Fetched on every think so
        idle cognition always sees what it committed to."""
        try:
            r = await self._client.post(
                "/api/acs/v2/tools/list_goals",
                json={"status": status},
            )
        except httpx.HTTPError as e:
            logger.warning("list_goals network error: %s", e)
            return []
        if r.status_code >= 400:
            logger.warning("list_goals rejected: %s %s",
                           r.status_code, r.text[:200])
            return []
        body = r.json() or {}
        return body.get("goals") or []

    # ── notify ──
    async def notify_david(
        self, *, title: str, body: str, priority: str = "normal",
        why: Optional[str] = None, note_id: Optional[str] = None,
    ) -> dict:
        """Send a real, ungated push notification to David. Returns the
        backend's outcome dict — {delivered, reason, notification_id} — so
        Sara knows whether her ping landed."""
        payload = {"title": title, "body": body, "priority": priority, "why": why}
        if note_id:
            payload["note_id"] = note_id
        try:
            r = await self._client.post("/api/acs/v2/notify", json=payload)
        except httpx.HTTPError as e:
            logger.warning("notify_david network error: %s", e)
            return {"delivered": False, "reason": "network_error"}
        if r.status_code >= 400:
            logger.warning("notify_david rejected: %s %s", r.status_code, r.text[:200])
            return {"delivered": False, "reason": f"http_{r.status_code}"}
        return r.json() or {"delivered": False, "reason": "no_response"}
