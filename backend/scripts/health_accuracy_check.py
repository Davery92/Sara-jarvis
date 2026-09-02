#!/usr/bin/env python3
"""
health_accuracy_check.py — asserts, against the live stack, that Sara cannot
state a health number she doesn't have (HEALTH_DATA_ACCURACY_FIX_PLAN_2026_08_31).

The incident this guards: asked why he felt exhausted, Sara produced a
seven-day HRV table in which every value was invented. Sleep was 6/7 correct.
The split is the diagnosis — the sleep path returned data, the HRV path
returned nothing, and rather than report an absence she completed the pattern.

Four checks, matching the plan's verification harness:

  1. no-invention    — every number a 14-day history returns exists in
                       `health_metric`, and every gap day is reported as one.
  2. no-stale        — no health number reaches the model without either a
                       today `recorded_at` or an explicit as-of date.
  3. no-loop         — a measurement cannot be minted as a PKG fact, so
                       Sara's own output can't come back as evidence.
  4. regression      — the four poisoned nodes from 2026-08-31 are gone and
                       cannot be recreated.

Run 1-3 before and after each phase. Like verify_sara_alive.py this is
deliberately NOT pytest: it hits the real DB, the real Neo4j graph and the
real tool code paths, which is the point.

Run from inside the backend container:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/health_accuracy_check.py [--check no-invention|...] [--days 14]
"""
import argparse
import asyncio
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
METRICS = ("hrv", "resting_hr", "sleep_hours")


class Check:
    def __init__(self, name):
        self.name, self.passed, self.detail = name, None, ""

    def ok(self, detail=""):
        self.passed, self.detail = True, detail
        return self

    def fail(self, detail=""):
        self.passed, self.detail = False, detail
        return self

    def skip(self, detail=""):
        self.passed, self.detail = None, detail
        return self


async def _run(name, coro):
    try:
        result = await coro
        return result if isinstance(result, Check) else Check(name).ok(str(result or ""))
    except Exception as e:
        return Check(name).fail(f"{type(e).__name__}: {e}")


# ───────────────────── 1. no invention ─────────────────────

async def check_no_invention(user_id: str, days: int) -> list:
    """Every number the trend path returns must exist in health_metric, and
    every day without a reading must be reported as missing rather than
    dropped from the series."""
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.core.timezone import local_day_bounds, today as local_today
    from app.services.health_insight_service import health_insight_service, alias_chain
    from app.tools.health import HealthTrendTool

    checks = []
    db = SessionLocal()
    try:
        for metric in METRICS:
            # Ground truth straight from the authoritative table, bucketed in ET.
            cutoff = local_day_bounds(local_today() - timedelta(days=days - 1))[0]
            rows = db.execute(text("""
                SELECT DATE(recorded_at AT TIME ZONE 'America/New_York') AS day,
                       AVG(value) AS avg_value
                FROM health_metric
                WHERE user_id = :uid AND metric_type = ANY(:m) AND recorded_at >= :cutoff
                GROUP BY 1
            """), {"uid": user_id, "m": alias_chain(metric), "cutoff": cutoff}).fetchall()
            truth = {r.day.isoformat(): float(r.avg_value) for r in rows if r.day}

            trend = await health_insight_service.get_trend_analysis(user_id, db, metric, days)
            daily = trend.get("daily_data") or []

            name = f"1.{metric} — {days}-day series matches health_metric"
            if len(daily) != days:
                checks.append(Check(name).fail(
                    f"series has {len(daily)} entries for a {days}-day window — "
                    "gap days are being dropped, not reported"))
                continue

            invented = [
                d["day"] for d in daily
                if d["avg_value"] is not None
                and abs(d["avg_value"] - truth.get(d["day"], float("nan"))) > 0.01
            ]
            unreported = [d for d in truth if d not in {x["day"] for x in daily}]
            reported_gaps = [d["day"] for d in daily if d["avg_value"] is None]
            expected_gaps = sorted(set(x["day"] for x in daily) - set(truth))

            if invented:
                checks.append(Check(name).fail(f"values with no health_metric row: {invented}"))
            elif unreported:
                checks.append(Check(name).fail(f"real days missing from the series: {unreported}"))
            elif sorted(reported_gaps) != expected_gaps:
                checks.append(Check(name).fail(
                    f"gap days reported {sorted(reported_gaps)} != actual gaps {expected_gaps}"))
            elif not truth:
                checks.append(Check(name).skip(
                    f"no {metric} rows at all in {days} days — series correctly reports "
                    f"{len(reported_gaps)} missing days"))
            else:
                checks.append(Check(name).ok(
                    f"{len(truth)} real day(s), {len(reported_gaps)} explicitly reported as missing"))

        # And the rendered tool output — what the model actually reads — must
        # name the gap days in words, not just carry them as nulls in a dict.
        async def rendered_gaps_visible():
            out = await HealthTrendTool().execute(user_id=user_id, metric_type="hrv", days=days)
            body = out.message or ""
            gap_lines = body.count("no data recorded")
            if "Coverage" not in body and "No " not in body:
                return Check("1.render — gaps stated in the tool's own output").fail(
                    f"no coverage line in output: {body[:200]!r}")
            return Check("1.render — gaps stated in the tool's own output").ok(
                f"{gap_lines} day(s) rendered as 'no data recorded'")
        checks.append(await _run("1.render", rendered_gaps_visible()))
    finally:
        db.close()
    return checks


# ───────────────────── 2. no stale assertion ─────────────────────

_BARE_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_DATED = ("recorded ", "as of ", "no data", "unavailable", "not recorded", "not measured")


async def check_no_stale(user_id: str) -> list:
    """Every health line the model is handed must carry a date or an explicit
    absence. A bare number is indistinguishable from a fresh reading."""
    from app.db.session import SessionLocal
    from app.services.health_insight_service import health_insight_service
    from app.services.context_snapshot import get_world_state

    checks = []
    db = SessionLocal()
    try:
        async def context_lines_dated():
            ctx = await health_insight_service.get_relevant_health_context(
                user_id, db, conversation_text="why am I so tired today")
            if not ctx:
                return Check("2.1 health context lines carry a date").skip(
                    "no health context produced (no readings in 24h)")
            offenders = [
                ln for ln in ctx.split("\n")
                if ln.strip().startswith("-") and _BARE_NUMBER.search(ln)
                and not any(tok in ln.lower() for tok in _DATED)
            ]
            if offenders:
                return Check("2.1 health context lines carry a date").fail(
                    f"undated number(s): {offenders}")
            return Check("2.1 health context lines carry a date").ok(
                f"{len(ctx.splitlines())} line(s), all dated or explicitly absent")
        checks.append(await _run("2.1", context_lines_dated()))

        async def world_slice_states_absence():
            world = await get_world_state(db, user_id=user_id)
            slice_ = world.health_today
            if slice_ is None:
                return Check("2.2 health_today names every expected metric").fail(
                    "slice missing entirely")
            from app.services.context_snapshot import EXPECTED_HEALTH_METRICS
            missing = [m for m in EXPECTED_HEALTH_METRICS if m not in slice_.data]
            if missing:
                return Check("2.2 health_today names every expected metric").fail(
                    f"omitted (rather than reported unavailable): {missing}")
            unavailable = [m for m, v in slice_.data.items()
                           if isinstance(v, str) and v.startswith("unavailable")]
            if slice_.confidence == 1.0 and unavailable:
                return Check("2.2 health_today names every expected metric").fail(
                    f"confidence 1.0 while {unavailable} are unavailable")
            return Check("2.2 health_today names every expected metric").ok(
                f"confidence={slice_.confidence}, unavailable={unavailable or 'none'}")
        checks.append(await _run("2.2", world_slice_states_absence()))

        async def pkg_states_no_measurements():
            from app.services.memory_recall import recall_facts_prose
            prose = await recall_facts_prose(query="hrv sleep recovery heart rate",
                                             k=10, user_id=user_id)
            # Only Health-shaped lines ("David's hrv: 54"). A PKG_Goal line
            # ("David's goal: keep resting HR near 63-65 bpm") legitimately
            # contains numbers — it states an intention, not a reading.
            health_line = re.compile(r"^\s*-\s*David's (?!goal[: ])[^:]+:")
            offenders = [
                ln for ln in (prose or "").split("\n")
                if health_line.match(ln) and _BARE_NUMBER.search(ln)
                and not any(tok in ln.lower() for tok in _DATED)
            ]
            if offenders:
                return Check("2.3 knowledge-graph prose asserts no undated number").fail(
                    f"{offenders}")
            return Check("2.3 knowledge-graph prose asserts no undated number").ok(
                "no undated health numbers in recalled facts")
        checks.append(await _run("2.3", pkg_states_no_measurements()))
    finally:
        db.close()
    return checks


# ───────────────────── 3. no fabrication loop ─────────────────────

async def check_no_loop(user_id: str) -> list:
    """Sara's own assertions must not be able to become durable facts. The
    gate is upsert_fact itself, so it's testable without spending a model call.
    """
    from app.services.personal_knowledge_graph import personal_kg, is_authoritative_health_copy

    checks = []

    # These are verbatim from the 2026-08-31 transcript and graph.
    fabricated = [
        ("hrv", "80"), ("hrv", "87"), ("sleep_duration", "7.5 hours"),
        ("Sleep duration", "Trending down (slept in a bit today)"),
        ("Sleep Quality", "Poor (barely slept)"),
        ("resting heart rate", "54 bpm"), ("steps", "12,431"),
    ]
    accepted = []
    for metric, value in fabricated:
        if not is_authoritative_health_copy(metric, value):
            accepted.append((metric, value))
    checks.append(
        Check("3.1 measurement detector rejects the 08-31 values").fail(
            f"would still be minted: {accepted}")
        if accepted else
        Check("3.1 measurement detector rejects the 08-31 values").ok(
            f"all {len(fabricated)} refused"))

    async def upsert_refuses():
        pkg_id = personal_kg.upsert_fact(
            fact_type="Health",
            properties={"metric": "hrv", "current_value": "80", "trend": "stable"},
            confidence=0.99,
            source="health_accuracy_check",
            dedup_key="health_accuracy_check:probe",
        )
        if pkg_id:
            personal_kg.retire_node(pkg_id)
            return Check("3.2 upsert_fact refuses a measured Health fact").fail(
                f"created {pkg_id} (now retired)")
        return Check("3.2 upsert_fact refuses a measured Health fact").ok("returned None")
    checks.append(await _run("3.2", upsert_refuses()))

    async def qualitative_still_works():
        """The gate must not swallow legitimate qualitative health knowledge —
        a rejection that catches everything is as useless as one that catches
        nothing."""
        pkg_id = personal_kg.upsert_fact(
            fact_type="Health",
            properties={"metric": "chest development",
                        "current_value": "chronically underdeveloped relative to back"},
            confidence=0.8,
            source="health_accuracy_check",
            dedup_key="health_accuracy_check:qualitative_probe",
        )
        if not pkg_id:
            return Check("3.3 qualitative Health facts still mint").fail(
                "a non-numeric attribute was refused — the filter is too broad")
        personal_kg.retire_node(pkg_id)
        return Check("3.3 qualitative Health facts still mint").ok("minted, then cleaned up")
    checks.append(await _run("3.3", qualitative_still_works()))

    async def formatter_drops_measurements():
        from app.services.pkg_context_provider import pkg_context
        sentence = pkg_context._fact_to_sentence(
            "Health", {"metric": "hrv", "current_value": "80", "last_confirmed": None})
        if sentence.strip():
            return Check("3.4 read path drops legacy measured nodes").fail(
                f"rendered {sentence!r}")
        return Check("3.4 read path drops legacy measured nodes").ok(
            "measured Health node renders as empty")
    checks.append(await _run("3.4", formatter_drops_measurements()))

    return checks


# ───────────────────── 4. regression against the incident ─────────────────────

async def check_regression(user_id: str) -> list:
    """The four poisoned nodes named in the plan must be gone from the graph."""
    from app.services.personal_knowledge_graph import personal_kg, is_authoritative_health_copy

    checks = []

    async def graph_is_clean():
        if not personal_kg._ensure_driver():
            return Check("4.1 no measured PKG_Health nodes remain").skip("Neo4j unreachable")
        with personal_kg.driver.session() as session:
            rows = session.run("""
                MATCH (n:PKG_Health) WHERE n.superseded_by IS NULL
                RETURN n.metric AS metric, n.current_value AS current_value
            """).data()
        survivors = [
            (r.get("metric"), r.get("current_value")) for r in rows
            if (r.get("metric") or r.get("current_value"))
            and is_authoritative_health_copy(r.get("metric") or "", r.get("current_value") or "")
        ]
        if survivors:
            return Check("4.1 no measured PKG_Health nodes remain").fail(
                f"{len(survivors)} still present: {survivors[:5]} — "
                "run scripts/purge_measured_health_facts.py --apply")
        return Check("4.1 no measured PKG_Health nodes remain").ok(
            f"{len(rows)} PKG_Health node(s), none a measurement")
    checks.append(await _run("4.1", graph_is_clean()))

    async def extraction_reads_only_david():
        """The loop's other half: the extractor must not be fed Sara's turns."""
        src = (Path(__file__).parent.parent / "app" / "tasks" / "autonomy.py").read_text()
        if "role IN ('user', 'assistant')" in src:
            return Check("4.2 extractor reads only David's turns").fail(
                "autonomy.py still selects assistant episodes for PKG extraction")
        dream = (Path(__file__).parent.parent / "app" / "services"
                 / "nightly_dream_service.py").read_text()
        if "conversation_text += f\"Sara: {content}\\n\"" in dream:
            return Check("4.2 extractor reads only David's turns").fail(
                "nightly_dream_service.py still feeds Sara's replies to deep_extract")
        return Check("4.2 extractor reads only David's turns").ok(
            "both extraction paths are user-only")
    checks.append(await _run("4.2", extraction_reads_only_david()))

    return checks


CHECKS = {
    "no-invention": check_no_invention,
    "no-stale": check_no_stale,
    "no-loop": check_no_loop,
    "regression": check_regression,
}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=list(CHECKS.keys()), default=None)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    selected = {args.check: CHECKS[args.check]} if args.check else CHECKS

    all_checks = []
    for name, fn in selected.items():
        print(f"\n=== {name} ===")
        checks = await (fn(args.user_id, args.days) if name == "no-invention"
                        else fn(args.user_id))
        for c in checks:
            symbol = "PASS" if c.passed is True else ("SKIP" if c.passed is None else "FAIL")
            print(f"  [{symbol}] {c.name} — {c.detail}")
            all_checks.append(c)

    failed = [c for c in all_checks if c.passed is False]
    passed = [c for c in all_checks if c.passed is True]
    skipped = [c for c in all_checks if c.passed is None]
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
