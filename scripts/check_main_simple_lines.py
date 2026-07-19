#!/usr/bin/env python3
"""main_simple.py line-count freeze (Phase 8.2).

main_simple.py is the monolith we're trying to shrink. This check fails if it
grows past a ceiling that only ever ratchets DOWN — new endpoints must go in
app/routes/, and any PR that touches the monolith should extract at least what
it adds. When you legitimately shrink it, lower CEILING to the new count.

Usage:  python scripts/check_main_simple_lines.py [backend/app/main_simple.py]
"""
import sys
import pathlib

# Ratchet: lower this whenever main_simple.py legitimately shrinks. Never raise it.
CEILING = 10982


def main() -> int:
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "app/main_simple.py")
    if not path.exists():
        path = pathlib.Path("backend/app/main_simple.py")
    n = sum(1 for _ in path.open())
    if n > CEILING:
        print(f"main_simple.py grew to {n} lines (ceiling {CEILING}). "
              f"Put new code in app/routes/ and extract at least what you add.")
        return 1
    if n < CEILING:
        print(f"main_simple.py is {n} lines (ceiling {CEILING}). "
              f"Nice — lower CEILING to {n} in this script to lock in the shrink.")
    else:
        print(f"main_simple.py at ceiling ({n} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
