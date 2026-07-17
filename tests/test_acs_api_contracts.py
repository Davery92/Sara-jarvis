#!/usr/bin/env python3
"""Lightweight ACS API contract checks.

Usage:
  BASE_URL=http://localhost:8000 ACCESS_TOKEN=... python3 test_acs_api_contracts.py

If ACCESS_TOKEN is omitted, the script exits successfully with a skip message.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "").strip()


def request_json(method: str, path: str, payload: dict | None = None):
    data = None
    headers = {"Content-Type": "application/json"}
    if ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def assert_has_keys(obj: dict, required: list[str], label: str):
    missing = [key for key in required if key not in obj]
    assert not missing, f"{label} missing keys: {missing}"


def main():
    if not ACCESS_TOKEN:
        print("SKIP: ACCESS_TOKEN not set")
        return 0

    snapshot = request_json("GET", "/api/acs/snapshot")
    assert_has_keys(snapshot, ["state"], "snapshot")
    if "live_session" in snapshot and snapshot["live_session"] is not None:
        assert_has_keys(snapshot["live_session"], ["id", "mode", "turns", "elapsed_minutes"], "live_session")
    if "last_session" in snapshot and snapshot["last_session"] is not None:
        assert_has_keys(snapshot["last_session"], ["mode", "turns", "notes_created", "end_reason"], "last_session")

    sessions_resp = request_json("GET", "/api/acs/sessions?limit=5")
    assert_has_keys(sessions_resp, ["sessions", "total"], "sessions response")
    assert isinstance(sessions_resp["sessions"], list), "sessions must be a list"
    for session in sessions_resp["sessions"]:
        assert_has_keys(
            session,
            ["id", "state", "started_at", "turns_completed", "notes_created", "duration_minutes", "duration_seconds"],
            "session summary",
        )

    print("ACS API contract checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}")
        raise
