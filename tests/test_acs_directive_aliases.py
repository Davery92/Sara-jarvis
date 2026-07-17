#!/usr/bin/env python3
"""Check that ACS directive aliases normalize to canonical directive types.

Usage:
  BASE_URL=http://localhost:8000 ACCESS_TOKEN=... ACS_TEST_MUTATE=1 python3 test_acs_directive_aliases.py

This test mutates server state and will skip unless ACS_TEST_MUTATE=1.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "").strip()
ACS_TEST_MUTATE = os.environ.get("ACS_TEST_MUTATE", "").strip() == "1"


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


def main():
    if not ACCESS_TOKEN:
        print("SKIP: ACCESS_TOKEN not set")
        return 0
    if not ACS_TEST_MUTATE:
        print("SKIP: ACS_TEST_MUTATE=1 not set")
        return 0

    unique_content = f"api test alias {int(time.time())}"
    created = request_json("POST", "/api/acs/directive", {
        "directive_type": "research",
        "content": unique_content,
        "priority": "normal",
        "source": "api_test",
    })
    directive_id = created["id"]

    directives = request_json("GET", "/api/acs/directives?limit=20")
    found = None
    for directive in directives.get("directives", []):
        if directive.get("id") == directive_id:
            found = directive
            break

    assert found is not None, "Created directive was not returned by list endpoint"
    assert found["directive_type"] == "focus", (
        f"Expected alias 'research' to normalize to 'focus', got {found['directive_type']!r}"
    )

    request_json("DELETE", f"/api/acs/directive/{directive_id}")
    print("ACS directive alias check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}")
        raise
