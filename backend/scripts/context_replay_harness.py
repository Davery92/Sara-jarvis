"""SINGULAR_CONTEXT replay harness (work-order item 3, 2026-07-30).

Runs the new 4-source kernel context assembly (get_context_snapshot +
memory_recall + get_extended_signals + render_engaged_context — the exact
same calls main_simple.py's live [context-diet-compare] path makes) against
a broad sample of REAL historical user turns, and reports whether it builds
successfully and what it covers.

Scope, stated plainly: this is real regression/robustness evidence, not a
byte-for-byte "new == old at the time" comparison. The old ~19-source
assembly's construction is inline in the /chat/stream request handler,
built from request-time state (world_state, calendar, recent chat) that has
moved on since a historical message was actually sent — pairing old TEXT
with TODAY's state and calling it a replay of "what the old assembly would
have produced back then" would be a false equivalence, not evidence. What
this DOES honestly establish: does the new assembly handle a wide, real
sample of David's actual phrasing without erroring, and does its coverage
(world slices / extended signals / recall traces) look sane across that
sample. The organic clean-turn count (app/services/context_diet_usage.py,
bar=200) remains the actual deletion gate — this harness doesn't touch it
and isn't meant to.
"""
import asyncio
import json
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
SAMPLE_SIZE = 200


async def _fetch_sample(db, user_id: str, n: int):
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT id, content, created_at
        FROM episode
        WHERE user_id = :uid AND role = 'user'
          AND content IS NOT NULL AND length(content) > 0
        ORDER BY random()
        LIMIT :n
    """), {"uid": user_id, "n": n}).fetchall()
    return [(r.id, r.content, r.created_at) for r in rows]


async def run(n: int = SAMPLE_SIZE, user_id: str = DEFAULT_USER_ID) -> dict:
    from app.db.session import get_db
    from app.services.context_snapshot import get_context_snapshot, get_extended_signals, render_engaged_context
    from app.services.memory_recall import recall as memory_recall
    from app.services.intent_graph_projection import get_intent_graph

    db_gen = get_db()
    db = next(db_gen)
    try:
        sample = await _fetch_sample(db, user_id, n)
    finally:
        db.close()

    print(f"Sampled {len(sample)} real historical user turns for user {user_id}")

    results = []
    errors = []

    for i, (ep_id, text_, created_at) in enumerate(sample, 1):
        db_gen = get_db()
        db = next(db_gen)
        try:
            snapshot = await get_context_snapshot(db, user_id)
            open_intents = get_intent_graph(db, user_id)["total"]
            recalled = await memory_recall(user_id=user_id, query=text_ or "", k=5)
            extended = await get_extended_signals(db, user_id, text_ or "")
            rendered = render_engaged_context(
                snapshot, open_intents, recalled.get("traces") or [], extended=extended,
            )
            world_slices = sum(
                1 for k in ("david", "home", "calendar_horizon", "health_today", "work", "fleet")
                if (snapshot.get("world_state") or {}).get(k)
            )
            results.append({
                "episode_id": str(ep_id),
                "original_at": created_at.isoformat() if created_at else None,
                "chars": len(rendered),
                "world_slices": world_slices,
                "extended_keys": sorted(k for k, v in extended.items() if v),
                "recall_traces": len(recalled.get("traces") or []),
                "open_intents": open_intents,
            })
        except Exception as e:
            errors.append({
                "episode_id": str(ep_id),
                "text_preview": (text_ or "")[:120],
                "error": f"{type(e).__name__}: {e}",
            })
        finally:
            db.close()

        if i % 25 == 0:
            print(f"  {i}/{len(sample)} processed ({len(errors)} errors so far)")

    char_counts = [r["chars"] for r in results]
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(sample),
        "succeeded": len(results),
        "errored": len(errors),
        "error_rate": round(len(errors) / len(sample), 4) if sample else None,
        "chars": {
            "min": min(char_counts) if char_counts else None,
            "p10": statistics.quantiles(char_counts, n=10)[0] if len(char_counts) >= 10 else None,
            "median": statistics.median(char_counts) if char_counts else None,
            "p90": statistics.quantiles(char_counts, n=10)[-1] if len(char_counts) >= 10 else None,
            "max": max(char_counts) if char_counts else None,
        },
        "zero_length_count": sum(1 for c in char_counts if c == 0),
        "world_slice_coverage": {
            str(n): sum(1 for r in results if r["world_slices"] == n) for n in range(7)
        },
        "extended_key_frequency": {},
        "errors": errors,
    }
    freq: dict = {}
    for r in results:
        for k in r["extended_keys"]:
            freq[k] = freq.get(k, 0) + 1
    report["extended_key_frequency"] = freq

    return report


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE_SIZE
    report = asyncio.run(run(n))
    print("\n=== SINGULAR_CONTEXT replay harness report ===")
    print(json.dumps(report, indent=2, default=str))

    out_path = "/app/context_replay_report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWritten to {out_path}")
