#!/usr/bin/env python3
"""Integration test for memory trace/recall endpoints.
Run against a live backend. Set BASE_URL via env if not localhost.
"""
import os
import requests
import time

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
EMAIL = os.getenv("TEST_EMAIL", "david@avery.cloud")
PASSWORD = os.getenv("TEST_PASSWORD", "Nutman17!")


def login(session: requests.Session):
    r = session.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"


def test_memory_recall_flow():
    s = requests.Session()
    login(s)

    # Create two traces
    payloads = [
        {"content": "Met Alex for coffee at Blue Bottle. Discussed vector DBs and embeddings.", "heads": ["semantic"]},
        {"content": "Reading about HNSW indexing for semantic search.", "heads": ["semantic"]},
    ]
    for p in payloads:
        r = s.post(f"{BASE_URL}/memory/trace", json=p)
        assert r.status_code == 200, f"trace create failed: {r.status_code} {r.text}"

    # Give Redis a moment
    time.sleep(0.3)

    # Recall
    r = s.get(f"{BASE_URL}/memory/recall", params={"q": "vector database search", "k": 5})
    assert r.status_code == 200, f"recall failed: {r.status_code} {r.text}"
    data = r.json()
    assert "results" in data
    assert len(data["results"]) >= 1
    # Check that at least one result references our content
    contents = "\n".join([x.get("content", "") for x in data["results"]])
    assert "vector" in contents.lower() or "hnsw" in contents.lower()

    print("✅ memory recall test passed")

if __name__ == "__main__":
    test_memory_recall_flow()

