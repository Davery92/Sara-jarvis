#!/usr/bin/env python3
"""Integration test: consolidation stub creates a summary and edges.
"""
import os
import requests
from datetime import datetime

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
EMAIL = os.getenv("TEST_EMAIL", "david@avery.cloud")
PASSWORD = os.getenv("TEST_PASSWORD", "Nutman17!")


def login(session: requests.Session):
    r = session.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"


def test_memory_consolidate_today():
    s = requests.Session()
    login(s)

    # Seed a couple traces for today
    for txt in [
        "Morning run with Alex; planned week goals.",
        "Afternoon: prototyped memory recall pipeline with Redis and pgvector.",
    ]:
        r = s.post(f"{BASE_URL}/memory/trace", json={"content": txt, "heads": ["semantic"]})
        assert r.status_code == 200, r.text

    # Consolidate for today
    today = datetime.utcnow().date().isoformat()
    r = s.post(f"{BASE_URL}/memory/consolidate", json={"day": today})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("edges_created", 0) >= 1

    print("✅ memory consolidation test passed")

if __name__ == "__main__":
    test_memory_consolidate_today()

