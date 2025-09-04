#!/usr/bin/env python3
"""Scenario tests for fitness readiness and push/skip."""
import os
import httpx
import asyncio

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        # Login (use env USER_EMAIL/USER_PASSWORD)
        email = os.getenv("USER_EMAIL", "david@avery.cloud")
        password = os.getenv("USER_PASSWORD", "changeme")
        r = await client.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()

        # Propose
        payload = {
            "profile": {}, "goals": {"goal_type":"hypertrophy"},
            "equipment":["dumbbell","barbell"], "days_per_week":4, "session_len_min":60,
            "preferences":{"style":"UL/UL"}
        }
        r = await client.post("/fitness/plan/propose", json=payload)
        r.raise_for_status()
        draft = r.json()
        print("Proposed plan:", draft.get("plan_id"))

        # Commit with immediate schedule for next 4 days (using server-side defaults)
        edits = {"plan": draft.get("days",""), "schedule": {"start_date": os.getenv("START_DATE",""), "time":"18:00"}}
        r = await client.post("/fitness/plan/commit", json={"plan_id": draft.get("plan_id"), "edits": edits})
        r.raise_for_status()
        created = r.json()
        print("Created:", created)

        # Readiness yellow
        r = await client.post("/fitness/readiness", json={"energy":3,"soreness":3,"stress":3,"time_available_min":45,"hrv_ms":60,"rhr":65,"sleep_hours":6.0})
        r.raise_for_status()
        print("Readiness yellow:", r.json())

        # Readiness red
        r = await client.post("/fitness/readiness", json={"energy":1,"soreness":5,"stress":5,"time_available_min":30,"hrv_ms":40,"rhr":75,"sleep_hours":4.0})
        r.raise_for_status()
        print("Readiness red:", r.json())

if __name__ == "__main__":
    asyncio.run(main())
