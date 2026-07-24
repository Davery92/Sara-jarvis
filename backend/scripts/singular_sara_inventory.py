#!/usr/bin/env python3
"""
Machine-readable inventory of enabled jobs and notification/mailbox/action/
recall/status call sites (SINGULAR_SARA_MASTER_PLAN §13 item 1 / §C0).

The plan's baseline deliverable is "a machine-readable inventory of all 86
enabled jobs, cognitive prompts, recall callers, notification writers,
mailbox writers, action writers, and status projections" — so that the
fracture described in §3.2 ("86 scheduled jobs... `sara_inbox`, `jarvis_inbox`,
`autonomy_attention_item`... multiple mailbox concepts") is measurable rather
than anecdotal (the C0 exit gate). This script produces that snapshot.

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/singular_sara_inventory.py [--out /tmp/inventory.json]

Two passes:
  1. DB: every `scheduled_job` row, heuristically classified into the C11
     scheduler-diet taxonomy (sensor | maintenance | anchor | legacy_cognition
     | unclassified) — a starting point for that later reclassification, not
     the reclassification itself.
  2. Static: a source-tree scan for the call sites behind "multiple mailbox
     concepts," "notification writers," and "store-specific recall" — a
     snapshot, not a build-time enforcement tool (that's the C8 static-
     analysis exit gate's job).

Read-only. Does not change scheduling, notification, or recall behavior.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

APP_ROOT = Path(__file__).parent.parent / "app"

# --- Pass 1: scheduled_job classification -----------------------------------
# Classifier now lives in app.services.scheduler_diet (§C11), shared with the
# persisted `scheduled_job.singular_class` backfill — this script no longer
# keeps its own copy.


def inventory_scheduled_jobs() -> dict:
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.services.scheduler_diet import classify_job

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT key, display_name, description, category, task_name,
                   enabled, visibility
            FROM scheduled_job
            ORDER BY category, key
        """)).fetchall()
    finally:
        db.close()

    jobs = []
    by_class: dict = {}
    by_category: dict = {}
    enabled_count = 0
    for r in rows:
        job = {
            "key": r.key,
            "display_name": r.display_name,
            "category": r.category,
            "task_name": r.task_name,
            "enabled": r.enabled,
            "visibility": r.visibility,
        }
        job["singular_class"] = classify_job({**job, "description": r.description})
        jobs.append(job)
        if r.enabled:
            enabled_count += 1
        by_class[job["singular_class"]] = by_class.get(job["singular_class"], 0) + 1
        by_category[r.category] = by_category.get(r.category, 0) + 1

    return {
        "total_jobs": len(jobs),
        "enabled_jobs": enabled_count,
        "by_singular_class": by_class,
        "by_category": by_category,
        "jobs": jobs,
    }


# --- Pass 2: static call-site scan -------------------------------------------

_PATTERNS = {
    "notification_writers": re.compile(r"\bsend_notification\s*\(|\bunified_notification\b"),
    "mailbox_writers": re.compile(r"\b(sara_inbox|jarvis_inbox|autonomy_attention_item|followup_thread)\b"),
    "action_writers": re.compile(r"\baction_ledger\b"),
    "recall_callers": re.compile(r"\bmemory\.recall\(|\bpersonal_kg\.(query_semantic|search)\(|\bmemory_service\."),
    "status_projections": re.compile(
        r"@(router|app)\.get\([\"'][^\"']*(status|brief|health|metrics)"
    ),
}


def inventory_call_sites() -> dict:
    results = {name: [] for name in _PATTERNS}
    for path in APP_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            continue
        rel = str(path.relative_to(APP_ROOT.parent))
        for line_no, line in enumerate(content.splitlines(), start=1):
            for name, pattern in _PATTERNS.items():
                if pattern.search(line):
                    results[name].append(f"{rel}:{line_no}")
    return {name: {"count": len(hits), "sites": hits} for name, hits in results.items()}


def build_inventory() -> dict:
    return {
        "scheduled_jobs": inventory_scheduled_jobs(),
        "call_sites": inventory_call_sites(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="Write JSON report to this path instead of stdout")
    args = parser.parse_args()

    report = build_inventory()
    output = json.dumps(report, indent=2, default=str)

    if args.out:
        Path(args.out).write_text(output)
        print(f"Wrote inventory to {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
