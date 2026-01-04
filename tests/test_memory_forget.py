#!/usr/bin/env python3
"""Integration test: create → forget trace removes it.
"""
import os
import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
EMAIL = os.getenv("TEST_EMAIL", "david@avery.cloud")
PASSWORD = os.getenv("TEST_PASSWORD", "Nutman17!")


def login(session: requests.Session):
    r = session.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"


def test_memory_forget():
    s = requests.Session()
    login(s)

    # Create a trace
    r = s.post(f"{BASE_URL}/memory/trace", json={"content": "Temporary trace to delete", "heads": ["semantic"]})
    assert r.status_code == 200, r.text
    trace_id = r.json().get("trace_id")
    assert trace_id

    # Forget it
    r = s.post(f"{BASE_URL}/memory/forget", json={"trace_id": trace_id})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("deleted") is True

    # Basic recall should not show it (not a strict guarantee, but good signal)
    r = s.get(f"{BASE_URL}/memory/recall", params={"q": "Temporary trace", "k": 3})
    assert r.status_code == 200, r.text
    results = r.json().get("results", [])
    assert all(x.get("trace_id") != trace_id for x in results)

    print("✅ memory forget test passed")

if __name__ == "__main__":
    test_memory_forget()

