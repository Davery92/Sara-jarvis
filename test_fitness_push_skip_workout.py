#!/usr/bin/env python3
"""Scenario test: push and skip workout behaviors."""
import os
import httpx
import asyncio
from datetime import datetime, timedelta

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


async def run():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        # Login (use env USER_EMAIL/USER_PASSWORD)
        email = os.getenv("USER_EMAIL", "david@avery.cloud")
        password = os.getenv("USER_PASSWORD", "changeme")
        r = await client.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()

        # Propose/commit a quick plan for tomorrow
        propose = {
            "profile": {}, "goals": {"goal_type":"hypertrophy"},
            "equipment":["dumbbell"], "days_per_week":3, "session_len_min":45,
            "preferences":{"style":"full"}
        }
        r = await client.post("/fitness/plan/propose", json=propose)
        r.raise_for_status()
        draft = r.json()

        start_date = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        edits = {"plan": draft.get("days",""), "schedule": {"start_date": start_date, "time":"18:00"}}
        r = await client.post("/fitness/plan/commit", json={"plan_id": draft.get("plan_id"), "edits": edits})
        r.raise_for_status()
        created = r.json().get("created", [])
        if not created:
            print("No workouts created")
            return
        workout_id = created[0]["workout_id"]
        print("Using workout:", workout_id)

        # Push workout
        r = await client.post(f"/fitness/workouts/{workout_id}/push")
        r.raise_for_status()
        print("Push result:", r.json())

        # Skip workout
        r = await client.post(f"/fitness/workouts/{workout_id}/skip")
        r.raise_for_status()
        print("Skip result:", r.json())

if __name__ == "__main__":
    asyncio.run(run())
