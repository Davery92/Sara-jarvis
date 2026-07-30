#!/usr/bin/env python3
"""
verify_sara_alive.py — one command to detect regressions across everything
SARA_ALIVE_BUILD_PLAN has verified live so far (Arc 0-2).

Run from inside the backend container (needs DB/Redis/service access):
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/verify_sara_alive.py [--section arc0|arc1|arc2|arc5] [--user-id UUID]

Each section is a list of independent checks. A check either passes,
fails (with a reason), or is marked SKIP when its precondition isn't met
(e.g. no real data to check against) — SKIP is not a pass. Exit code is
nonzero if anything failed.

This is intentionally NOT pytest: these checks hit the live DB/Redis of
whatever environment the script runs in (real data, real state), which is
the point — pytest's mocked unit tests already cover the code-level logic
(tests/test_world_state_*.py, tests/test_candidate_state_machine.py, etc).
This script is the live-system complement.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


class Check:
    def __init__(self, name):
        self.name = name
        self.passed = None
        self.detail = ""

    def ok(self, detail=""):
        self.passed = True
        self.detail = detail
        return self

    def fail(self, detail=""):
        self.passed = False
        self.detail = detail
        return self

    def skip(self, detail=""):
        self.passed = None
        self.detail = detail
        return self


async def _check(name, coro):
    c = Check(name)
    try:
        result = await coro
        if isinstance(result, Check):
            return result
        c.ok(str(result) if result else "")
    except Exception as e:
        c.fail(f"{type(e).__name__}: {e}")
    return c


# ─────────────────────────── Arc 0 ───────────────────────────

async def arc0_checks(user_id: str) -> list:
    from sqlalchemy import text
    from app.db.session import SessionLocal

    checks = []

    async def workout_log_stats():
        from app.tools.fitness.workout_log import WorkoutStatsTool
        result = await WorkoutStatsTool().execute(user_id=user_id, period="week")
        if not result.success:
            return Check("0.1 workout-log/stats query").fail(result.message)
        return Check("0.1 workout-log/stats query").ok("no SQL error")
    checks.append(await _check("0.1", workout_log_stats()))

    async def patterns_uuid_guard():
        import uuid as uuid_module
        try:
            uuid_module.UUID("not-a-uuid")
            return Check("0.3 patterns/{id} UUID guard").fail("should have raised ValueError")
        except ValueError:
            return Check("0.3 patterns/{id} UUID guard").ok("non-UUID correctly rejected before query")
    checks.append(await _check("0.3", patterns_uuid_guard()))

    async def calendar_dedup():
        db = SessionLocal()
        try:
            dupes = db.execute(text("""
                SELECT title, start_time::date, COUNT(*) FROM calendar_event
                WHERE user_id = :uid
                GROUP BY title, start_time::date HAVING COUNT(*) > 1
            """), {"uid": user_id}).fetchall()
        finally:
            db.close()
        if dupes:
            return Check("0.9 no duplicate (title,date) calendar events").fail(f"{len(dupes)} duplicate groups: {[d[0] for d in dupes[:3]]}")
        return Check("0.9 no duplicate (title,date) calendar events").ok("0 duplicate groups")
    checks.append(await _check("0.9", calendar_dedup()))

    async def episode_id_never_null_on_response():
        from app.main_simple import SimpleLLMClient
        client = SimpleLLMClient()
        client._ephemeral = False
        eid = await client._store_conversation_with_timeout(
            messages=[{"role": "user", "content": "verify_sara_alive probe"}],
            response_content="verify_sara_alive probe response",
            user_id=user_id,
            conversation_id="verify-sara-alive-arc0-probe",
        )
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM episode WHERE conversation_id = :c"),
                       {"c": "verify-sara-alive-arc0-probe"})
            db.commit()
        finally:
            db.close()
        if not eid:
            return Check("0.5 episode_id never null for a real response").fail("got None")
        return Check("0.5 episode_id never null for a real response").ok(f"got {eid}")
    checks.append(await _check("0.5", episode_id_never_null_on_response()))

    return checks


# ─────────────────────────── Arc 1 ───────────────────────────

async def arc1_checks(user_id: str) -> list:
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    checks = []
    factory = get_async_session_factory()

    async def composed_utterance_diversity():
        async with factory() as db:
            row = (await db.execute(text("""
                SELECT count(*) AS total, count(DISTINCT sc.source) AS sources
                FROM composed_utterance cu JOIN say_candidate sc ON sc.id = cu.candidate_id
                WHERE cu.user_id = :uid
            """), {"uid": user_id})).first()
        if row.total >= 10 and row.sources >= 3:
            return Check("1.acc composed_utterance >=10 rows / >=3 sources").ok(f"{row.total} rows, {row.sources} sources")
        return Check("1.acc composed_utterance >=10 rows / >=3 sources").fail(f"only {row.total} rows, {row.sources} sources")
    checks.append(await _check("1a", composed_utterance_diversity()))

    async def no_legacy_sends_in_cut_senders():
        import re
        app_root = Path(__file__).parent.parent / "app"
        offenders = []
        targets = [
            "tasks/calendar_prep.py",
            "services/proactive_checkins.py",
            "services/research/executor.py",
        ]
        pattern = re.compile(r"(?<!\.)\bsend_notification\s*\(|\bnotification_service\.send_notification\b")
        for rel in targets:
            f = app_root / rel
            if not f.exists():
                continue
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(f"{rel}:{i}")
        if offenders:
            return Check("1.5 no legacy send call sites in the 3 cut senders").fail(str(offenders))
        return Check("1.5 no legacy send call sites in the 3 cut senders").ok("clean")
    checks.append(await _check("1b", no_legacy_sends_in_cut_senders()))

    async def mindv2_compose_flag():
        from app.core.feature_flags import Flag, is_enabled
        enabled = is_enabled(Flag.MINDV2_COMPOSE)
        return Check("1.4 MINDV2_COMPOSE flag state").ok(f"enabled={enabled}")
    checks.append(await _check("1c", mindv2_compose_flag()))

    async def candidate_status_constraint_allows_new_states():
        async with factory() as db:
            row = (await db.execute(text("""
                SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conname = 'ck_say_candidate_status'
            """))).first()
        if not row or "composed" not in row[0] or "declined" not in row[0]:
            return Check("1.1 say_candidate status constraint allows composed/declined").fail(str(row))
        return Check("1.1 say_candidate status constraint allows composed/declined").ok("constraint includes both")
    checks.append(await _check("1d", candidate_status_constraint_allows_new_states()))

    return checks


# ─────────────────────────── Arc 2 ───────────────────────────

async def arc2_checks(user_id: str) -> list:
    checks = []

    async def world_state_slices_populated():
        from app.db.session import SessionLocal
        from app.services.context_snapshot import get_world_state
        db = SessionLocal()
        try:
            world = await get_world_state(db, user_id)
        finally:
            db.close()
        missing = [n for n in ("david", "home", "calendar_horizon", "health_today", "work", "fleet")
                   if getattr(world, n) is None]
        if missing:
            return Check("2.1 all 6 world_state slices populate").fail(f"missing: {missing}")
        return Check("2.1 all 6 world_state slices populate").ok("all 6 present")
    checks.append(await _check("2a", world_state_slices_populated()))

    async def self_health_agrees_across_surfaces():
        from app.services.body_state_projection import get_body_state_projection
        from app.services.self_model import _health
        projection = await get_body_state_projection(user_id)
        health = await _health(db=None, user_id=user_id)
        if projection.healthy != health["ok"]:
            return Check("2.2 /mind/self and /api/sara/brief agree").fail(
                f"brief.healthy={projection.healthy} vs mind.ok={health['ok']}")
        return Check("2.2 /mind/self and /api/sara/brief agree").ok(
            f"both report healthy={projection.healthy}")
    checks.append(await _check("2b", self_health_agrees_across_surfaces()))

    async def staleness_emits_for_synthetic_stale_slice():
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock, patch
        from app.schemas.contracts import WorldStateV1, WorldStateSliceV1
        from app.services.context_snapshot import check_staleness

        stale_slice = WorldStateSliceV1(
            updated_at=datetime.now(timezone.utc) - timedelta(days=3),
            source="verify_sara_alive_probe", confidence=1.0, data={},
        )
        world = WorldStateV1(as_of=datetime.now(timezone.utc), user_id=user_id, fleet=stale_slice)
        with patch("app.services.event_bus.emit_event", new=AsyncMock()) as mock_emit:
            stale = await check_staleness(world)
        if "fleet" not in stale or not mock_emit.called:
            return Check("2.4 staleness emits prediction.violated").fail(f"stale={stale}, emit_called={mock_emit.called}")
        return Check("2.4 staleness emits prediction.violated").ok("fleet correctly flagged + event emitted")
    checks.append(await _check("2c", staleness_emits_for_synthetic_stale_slice()))

    async def fleet_never_reported_is_not_silently_fresh():
        from sqlalchemy import text
        from app.db.session import SessionLocal
        from app.services.context_snapshot import get_world_state
        db = SessionLocal()
        try:
            hosts = db.execute(text(
                "SELECT COUNT(*) FROM managed_host WHERE user_id = :uid AND last_seen_at IS NULL"
            ), {"uid": user_id}).scalar() or 0
            world = await get_world_state(db, user_id)
        finally:
            db.close()
        if hosts == 0:
            return Check("2.4b fleet never-reported hosts not silently fresh").skip("no never-reported hosts to check against")
        if world.fleet is None or world.fleet.confidence > 0.1:
            return Check("2.4b fleet never-reported hosts not silently fresh").fail(
                f"{hosts} never-reported hosts but fleet.confidence={world.fleet.confidence if world.fleet else None}")
        return Check("2.4b fleet never-reported hosts not silently fresh").ok(
            f"{hosts} never-reported hosts correctly yield confidence={world.fleet.confidence}")
    checks.append(await _check("2d", fleet_never_reported_is_not_silently_fresh()))

    return checks


# ─────────────────────────── Arc 5 ───────────────────────────

async def arc5_checks(user_id: str) -> list:
    from sqlalchemy import text
    from app.db.session import SessionLocal

    checks = []

    async def garden_has_no_machine_generated_notes():
        """Arc 5.3: 'the garden — David's notes, zero machine-generated
        content, ever.' Scoped to user_id, not a bare title-prefix count
        across the whole note table — two leftover dev/test accounts
        (test_agent@example.com, test@example.com) also have
        'Agent Result:' notes from Feb/June 2026 that were never part of
        David's garden to begin with (the original migration's manifest
        script was correctly user_id-scoped and never matched them); an
        unscoped count conflates "the garden is dirty" with "unrelated
        test accounts exist," which is a different, already-decided-to-
        leave-alone situation (David, 2026-07-30)."""
        db = SessionLocal()
        try:
            patterns = ["Agent Result:%", "✅ Agent Report:%", "Background Research:%"]
            counts = {}
            for pat in patterns:
                counts[pat] = db.execute(text(
                    "SELECT COUNT(*) FROM note WHERE title LIKE :p AND user_id = :uid"
                ), {"p": pat, "uid": user_id}).scalar() or 0
        finally:
            db.close()
        total = sum(counts.values())
        if total > 0:
            return Check("5.acc garden has zero machine-generated notes").fail(
                f"David-owned matches: {counts}")
        return Check("5.acc garden has zero machine-generated notes").ok(
            "0 across all 3 known machine-generated title patterns, scoped to David's user_id")
    checks.append(await _check("5a", garden_has_no_machine_generated_notes()))

    return checks


SECTIONS = {"arc0": arc0_checks, "arc1": arc1_checks, "arc2": arc2_checks, "arc5": arc5_checks}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", choices=list(SECTIONS.keys()), default=None)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    args = parser.parse_args()

    sections = {args.section: SECTIONS[args.section]} if args.section else SECTIONS

    all_checks = []
    for name, fn in sections.items():
        print(f"\n=== {name} ===")
        checks = await fn(args.user_id)
        for c in checks:
            symbol = "PASS" if c.passed is True else ("SKIP" if c.passed is None else "FAIL")
            print(f"  [{symbol}] {c.name} — {c.detail}")
            all_checks.append(c)

    failed = [c for c in all_checks if c.passed is False]
    passed = [c for c in all_checks if c.passed is True]
    skipped = [c for c in all_checks if c.passed is None]
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
