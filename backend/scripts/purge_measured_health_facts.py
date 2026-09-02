#!/usr/bin/env python3
"""
purge_measured_health_facts.py — retire PKG_Health nodes that are copies of
measurements (2026-08-31 health-fabrication incident, Phase 0.3).

`health_metric` is the only authority for a number about David's body. A
PKG_Health node claiming one — `hrv = "80"`, `sleep_duration = "7.5 hours"` —
has no recorded_at, never expires, and (before Phase 0.1) could have been
minted from a number Sara invented in a previous turn. `upsert_fact` now
refuses to create them; this retires the ones already in the graph.

Idempotent: re-running after a clean pass finds nothing and exits 0. Safe to
review first — dry-run is the default, `--apply` performs the deletion.

Run from inside the backend container:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/purge_measured_health_facts.py            # dry run
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/purge_measured_health_facts.py --apply
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.personal_knowledge_graph import (  # noqa: E402
    is_authoritative_health_copy,
    is_measured_health_metric,
    is_numeric_health_value,
    personal_kg,
)


def _reason(metric: str, value: str) -> str:
    reasons = []
    if is_measured_health_metric(metric):
        reasons.append("metric owned by health_metric")
    if is_numeric_health_value(value):
        reasons.append("value is a bare measurement")
    return " + ".join(reasons)


def find_measured_health_nodes():
    """Every live PKG_Health node whose metric/value reads as a measurement."""
    if not personal_kg._ensure_driver():
        raise RuntimeError("Neo4j driver unavailable — is the graph reachable?")

    with personal_kg.driver.session() as session:
        rows = session.run("""
            MATCH (n:PKG_Health)
            WHERE n.superseded_by IS NULL
            RETURN n.pkg_id AS pkg_id, n.metric AS metric,
                   n.current_value AS current_value, n.confidence AS confidence,
                   n.last_confirmed AS last_confirmed, n.source AS source
            ORDER BY n.last_confirmed DESC
        """).data()

    return [
        r for r in rows
        if (r.get("metric") or r.get("current_value"))
        and is_authoritative_health_copy(r.get("metric") or "", r.get("current_value") or "")
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually retire the nodes (default: dry run)")
    args = parser.parse_args()

    doomed = find_measured_health_nodes()

    if not doomed:
        print("No measured PKG_Health nodes found — graph is clean.")
        return 0

    print(f"{len(doomed)} measured PKG_Health node(s):\n")
    for r in doomed:
        print(f"  {r['metric']!r} = {r['current_value']!r}")
        print(f"    confidence={r.get('confidence')} last_confirmed={r.get('last_confirmed')} "
              f"source={r.get('source')}")
        print(f"    pkg_id={r['pkg_id']}  reason: {_reason(r.get('metric') or '', r.get('current_value') or '')}")

    if not args.apply:
        print(f"\nDry run — nothing deleted. Re-run with --apply to retire these {len(doomed)}.")
        return 0

    retired, failed = 0, []
    for r in doomed:
        if personal_kg.retire_node(r["pkg_id"]):
            retired += 1
        else:
            failed.append(r["pkg_id"])

    print(f"\nRetired {retired}/{len(doomed)} (Neo4j + pkg_embedding).")
    if failed:
        print(f"FAILED: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
