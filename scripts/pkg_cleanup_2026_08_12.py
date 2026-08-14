#!/usr/bin/env python3
"""
PKG cleanup — one-off data fix for the "still recovering" stale-context bug.

See docs/plans/HYGIENE_AND_STALE_CONTEXT_FIX_PLAN_2026_08_12.md, Part A1.
Root cause: nightly decay correctly drops Neo4j confidence on stale facts,
but nothing ever read confidence for freshness (only `status`/`target_date`),
so a Feb 23 illness — long since resolved — kept showing up in chat context
as if it were current. A2-A5 fix the read/write paths; this script cleans
up the data already sitting in Neo4j + the pgvector shadow.

Idempotent — safe to re-run. Dry run by default; pass --apply to execute.

Usage (from repo root, with .env populated):
    python3 scripts/pkg_cleanup_2026_08_12.py            # dry run
    python3 scripts/pkg_cleanup_2026_08_12.py --apply    # execute
"""
import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from app.services.personal_knowledge_graph import personal_kg, is_transient_health_text

STALE_GOAL_DAYS = 60

# The plan's writeup says status='resolved', but PKG_FRESH_FILTER (and every
# other freshness check in personal_knowledge_graph.py) only excludes
# PKG_CLOSED_STATUSES = ["completed", "abandoned", "archived", "stale"].
# Setting 'resolved' would silently reintroduce the exact bug this script
# fixes — the node would look closed but still pass every freshness filter.
# "completed" is the closest real closed-status and actually gets excluded.
CLOSE_STATUS = "completed"


def _driver_or_exit():
    if not personal_kg._ensure_driver():
        print("Neo4j unreachable — aborting.")
        sys.exit(1)


def find_transient_illness_nodes():
    """Health nodes describing a transient illness state, and any
    still-active 'recover from illness' Goal — the exact shape of the Feb
    23 / May 31 bug. Not date-scoped, so it catches any repeat of the
    pattern, not just the two known instances."""
    illness_health = []
    with personal_kg.driver.session() as session:
        result = session.run(
            """
            MATCH (n:PKG_Health)
            WHERE n.superseded_by IS NULL
              AND (n.status IS NULL OR toLower(n.status) <> $close_status)
            RETURN n.pkg_id as pkg_id, properties(n) as props
            """,
            {"close_status": CLOSE_STATUS},
        )
        for record in result:
            props = record["props"] or {}
            if is_transient_health_text(props.get("metric", ""), props.get("current_value", "")):
                illness_health.append({"pkg_id": record["pkg_id"], **props})

    illness_goals = []
    with personal_kg.driver.session() as session:
        result = session.run(
            """
            MATCH (g:PKG_Goal)
            WHERE g.superseded_by IS NULL
              AND toLower(coalesce(g.status, 'active')) = 'active'
              AND toLower(coalesce(g.description, '')) CONTAINS 'recover'
              AND g.confidence < 0.5
            RETURN g.pkg_id as pkg_id, properties(g) as props
            """
        )
        for record in result:
            illness_goals.append({"pkg_id": record["pkg_id"], **(record["props"] or {})})

    return illness_health, illness_goals


def find_stale_active_goals(days=STALE_GOAL_DAYS):
    """Active goals not confirmed in `days` — printed for David to review
    by hand (some may still be live: Vertex AI quota x2, Travelers demo,
    GLP-1 supplementation per the plan). Never auto-closed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with personal_kg.driver.session() as session:
        result = session.run(
            """
            MATCH (g:PKG_Goal)
            WHERE g.superseded_by IS NULL
              AND toLower(coalesce(g.status, 'active')) = 'active'
              AND g.last_confirmed < $cutoff
            RETURN g.pkg_id as pkg_id, properties(g) as props
            ORDER BY g.last_confirmed ASC
            """,
            {"cutoff": cutoff},
        )
        return [{"pkg_id": r["pkg_id"], **(r["props"] or {})} for r in result]


def find_garbage_health_nodes():
    """Extractor garbage: Health nodes with neither a metric nor a value —
    upsert_fact() now refuses to create these (A5), but existing rows
    predate that guard.

    Excludes kind IS NOT NULL: health_consolidation/runner.py mints a
    legitimate weekly_summary Health sub-schema (kind + headline, no
    metric/current_value) that looks identical to garbage under a naive
    "metric IS NULL AND current_value IS NULL" filter — verified live
    2026-08-12, all 15 initial matches were real weekly summaries, zero
    were actual garbage."""
    with personal_kg.driver.session() as session:
        result = session.run(
            """
            MATCH (n:PKG_Health)
            WHERE n.superseded_by IS NULL
              AND n.metric IS NULL AND n.current_value IS NULL
              AND n.kind IS NULL
            RETURN n.pkg_id as pkg_id, properties(n) as props
            """
        )
        return [{"pkg_id": r["pkg_id"], **(r["props"] or {})} for r in result]


def close_nodes(pkg_ids, label, apply: bool):
    if not pkg_ids:
        return
    verb = "Closing" if apply else "[dry-run] Would close"
    print(f"{verb} {len(pkg_ids)} {label} node(s) -> status='{CLOSE_STATUS}'")
    if not apply:
        return
    now = datetime.now(timezone.utc).isoformat()
    with personal_kg.driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.pkg_id IN $pkg_ids SET n.status = $status, n.stale_at = $now",
            {"pkg_ids": pkg_ids, "status": CLOSE_STATUS, "now": now},
        )


def delete_nodes(pkg_ids, label, apply: bool):
    if not pkg_ids:
        return
    verb = "Deleting" if apply else "[dry-run] Would delete"
    print(f"{verb} {len(pkg_ids)} {label} node(s)")
    if not apply:
        return
    with personal_kg.driver.session() as session:
        session.run("MATCH (n) WHERE n.pkg_id IN $pkg_ids DETACH DELETE n", {"pkg_ids": pkg_ids})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Execute changes (default: dry run)")
    args = parser.parse_args()
    apply = args.apply

    _driver_or_exit()

    print("=" * 70)
    print(f"PKG cleanup — {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 70)

    print("\n--- 1. Transient illness Health nodes + 'recover' Goal ---")
    illness_health, illness_goals = find_transient_illness_nodes()
    for h in illness_health:
        print(f"  Health {h['pkg_id']}: {h.get('metric')!r} = {h.get('current_value')!r} "
              f"(confidence={h.get('confidence')}, last_confirmed={h.get('last_confirmed')})")
    for g in illness_goals:
        print(f"  Goal {g['pkg_id']}: {g.get('description')!r} "
              f"(confidence={g.get('confidence')}, last_confirmed={g.get('last_confirmed')})")
    if not illness_health and not illness_goals:
        print("  none found")
    close_nodes([h["pkg_id"] for h in illness_health], "illness Health", apply)
    close_nodes([g["pkg_id"] for g in illness_goals], "'recover' Goal", apply)

    print(f"\n--- 2. Active goals stale >{STALE_GOAL_DAYS}d (REVIEW ONLY — not auto-closed) ---")
    stale_goals = find_stale_active_goals()
    if not stale_goals:
        print("  none")
    for g in stale_goals:
        print(f"  Goal {g['pkg_id']}: {g.get('description')!r} "
              f"(last_confirmed={g.get('last_confirmed')}, confidence={g.get('confidence')})")
    if stale_goals:
        print("  -> Review by hand and close individually once confirmed dead.")

    print("\n--- 3. Garbage Health nodes (NULL metric AND NULL value) ---")
    garbage = find_garbage_health_nodes()
    for h in garbage:
        print(f"  Health {h['pkg_id']}: confidence={h.get('confidence')}, source={h.get('source')}")
    if not garbage:
        print("  none found")
    delete_nodes([h["pkg_id"] for h in garbage], "garbage Health", apply)

    print("\n--- 4. Reconcile pkg_embedding.confidence from Neo4j ---")
    stats = personal_kg.reconcile_embedding_confidence(dry_run=not apply)
    verb = "Reconciled" if apply else "[dry-run] Would reconcile"
    print(f"  {verb}: {stats['updated']} confidence update(s), {stats['deleted']} orphaned shadow row(s) deleted")

    print("\n" + "=" * 70)
    print("Dry run complete. Re-run with --apply to execute." if not apply else "Applied.")


if __name__ == "__main__":
    main()
