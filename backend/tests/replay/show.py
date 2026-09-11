"""Print what Sara would be shown for one captured turn, today's code.

    backend/tests/replay/run_replay.sh --help      # (pytest)
    docker compose exec -T -e DATABASE_URL=.../sara_replay -e SARA_REPLAY=1 \
        backend python -m tests.replay.show 3

Reading the assembled prompt is how you tell a fixed failure from a
rephrased one, and the size account underneath it is the honest answer to
"what is actually in the 6k budget".
"""
import asyncio
import sys

from tests.replay import harness


async def main(index: int, full: bool) -> int:
    t = harness.turn(index)
    print(f"=== turn {t.index}: {t.at_et:%a %Y-%m-%d %H:%M %Z} ===")
    print(f"David: {t.user_text}\n")

    with harness.write_ledger() as ledger:
        assembled = await harness.assemble(t.user_text, t.at_et)

    print(assembled.account())
    print(f"\nwrites during assembly: {len(ledger)}")
    for verb, sql in ledger.statements[:10]:
        print(f"  {verb}: {sql[:120]}")
    if full:
        print("\n" + "=" * 70)
        print(assembled.text)
    else:
        print("\n(pass --full for the assembled text)")
    print("\n=== what Sara actually said that day ===")
    print(t.observed_assistant_text[:1500])
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    raise SystemExit(asyncio.run(main(int(args[0]) if args else 0, "--full" in sys.argv)))
