#!/usr/bin/env python3
"""Ban naive datetime construction across the backend.

`datetime.now()` (no tz) and `datetime.utcnow()` both produce *naive* datetimes.
In this ET-configured container `datetime.now()` silently yields ET wall-clock,
which — when stored into a timestamptz column or subtracted from an aware
datetime — has bitten us repeatedly ("can't subtract offset-naive and
offset-aware datetimes", values landing 4–5h early).

The only sanctioned ways to get "now":
    app.core.timezone.now()             -> aware ET
    app.core.timezone.now_utc()         -> aware UTC
    app.core.timezone.naive_local_now() -> naive ET   (for legacy naive-ET columns)
    app.core.timezone.naive_utc_now()   -> naive UTC  (for legacy naive-UTC columns)
    datetime.now(timezone.utc) / datetime.now(tz)      (explicit tz is fine)

This script fails (exit 1) if any banned form appears in app/ outside
app/core/timezone.py. Occurrences inside comments are ignored. Run from
backend/ (or pass a root dir).

Usage:  python scripts/check_naive_datetime.py [backend/app]
"""
import re
import sys
import pathlib

BANNED = [
    (re.compile(r"\bdatetime\.now\(\s*\)"), "datetime.now()  -> use timezone.now()/now_utc()/naive_local_now()"),
    (re.compile(r"\bdatetime\.utcnow\(\s*\)"), "datetime.utcnow()  -> use timezone.now_utc()/naive_utc_now()"),
]


def strip_comment(line: str) -> str:
    in_s = None
    for i, ch in enumerate(line):
        if in_s:
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
        elif ch == "#":
            return line[:i]
    return line


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "app")
    allow = {root / "core" / "timezone.py"}
    violations = []
    for p in root.rglob("*.py"):
        if p in allow or "__pycache__" in str(p):
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            code = strip_comment(line)
            for rx, msg in BANNED:
                if rx.search(code):
                    violations.append(f"{p}:{n}: {msg}")
    if violations:
        print("Naive datetime ban — %d violation(s):" % len(violations))
        for v in violations:
            print("  " + v)
        print("\nSee app/core/timezone.py for the sanctioned helpers.")
        return 1
    print("Naive datetime ban: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
