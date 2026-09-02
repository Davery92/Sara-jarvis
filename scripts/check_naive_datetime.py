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

# Heuristic for the B2 shape: an aware "now" helper subtracted against a bare
# variable that is very likely a naive value straight from the DB, e.g.
#   hours_away = local_now() - last_message_time   # naive episode.created_at
# Python raises "can't subtract offset-naive and offset-aware datetimes".
# We exclude `- timedelta(...)` (legitimate and extremely common) and allow an
# inline `# tz-ok` escape hatch for verified-aware operands.
_AWARE_NOW = r"(?:local_now|now_utc|now)\(\s*\)"
MIXED_SUB = [
    # aware_now() - <bare name that is not timedelta / not a call>
    (re.compile(_AWARE_NOW + r"\s*-\s*(?!timedelta\b)([A-Za-z_]\w*)(?!\s*\()"),
     "aware now() minus a bare variable — confirm the variable is timezone-aware (naive DB value?) or add `# tz-ok`"),
    # <bare name> - aware_now()
    (re.compile(r"(?<![.\w])([A-Za-z_]\w*)\s*-\s*" + _AWARE_NOW),
     "bare variable minus aware now() — confirm the variable is timezone-aware or add `# tz-ok`"),
]


# ── Raw timestamps in prompt builders (ground truth plan, invariant 4) ──────
#
# "One clock: no timestamp reaches a prompt or message except through one ET
# renderer. Raw ISO in prompt builders is a lint failure."
#
# Sara ran three conventions at once — world_thread.due_at in UTC handed straight
# to a prompt, calendar_event.start_time naive ET, notification_ack formatting UTC
# with %a %H:%M — so a thread due 1:00 PM ET was announced as "your 5:00 AM EDT
# call" and a 5:38 AM journal line said 9:38 AM. Everything below builds text a
# model or David reads, and must go through app.core.timezone.render_when.
PROMPT_PATH_PATTERNS = [
    "services/world_state/",
    "services/notification_ack.py",
    "services/compose.py",
    "services/judge.py",
    "services/appraisal.py",
    "services/context_snapshot.py",
    "services/world_brief.py",
]
PROMPT_NAME_SUBSTRING = "prompt"

RAW_TIMESTAMP = [
    (re.compile(r"\.isoformat\(\s*\)"),
     "raw .isoformat() in a prompt builder — render it with app.core.timezone.render_when()"),
    (re.compile(r"\.strftime\("),
     "raw .strftime() in a prompt builder — render it with app.core.timezone.render_when()"),
]


def is_prompt_path(path: pathlib.Path) -> bool:
    text = str(path).replace("\\", "/")
    if any(fragment in text for fragment in PROMPT_PATH_PATTERNS):
        return True
    return PROMPT_NAME_SUBSTRING in path.name and path.parts[-2:-1] == ("services",)


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
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    strict = "--strict" in sys.argv  # treat mixed-subtraction warnings as errors too
    root = pathlib.Path(argv[0] if argv else "app")
    allow = {root / "core" / "timezone.py"}
    violations = []   # hard errors (fail CI)
    warnings = []     # advisory mixed-subtraction heuristic (review, not fail)
    for p in root.rglob("*.py"):
        if p in allow or "__pycache__" in str(p):
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            code = strip_comment(line)
            for rx, msg in BANNED:
                if rx.search(code):
                    violations.append(f"{p}:{n}: {msg}")
            if is_prompt_path(p) and "# time-ok" not in line:
                for rx, msg in RAW_TIMESTAMP:
                    if rx.search(code):
                        violations.append(f"{p}:{n}: {msg}")
            if "# tz-ok" in line:
                continue
            for rx, msg in MIXED_SUB:
                m = rx.search(code)
                if not m:
                    continue
                # Skip the false-positive where the "bare name" is actually the
                # left side of a timedelta subtraction captured on the right.
                if m.group(1) in ("timedelta",):
                    continue
                warnings.append(f"{p}:{n}: {msg}")

    rc = 0
    if violations:
        print("Naive datetime ban — %d violation(s):" % len(violations))
        for v in violations:
            print("  " + v)
        print("\nSee app/core/timezone.py for the sanctioned helpers.")
        rc = 1
    else:
        print("Naive datetime ban: clean.")

    if warnings:
        label = "ERROR" if strict else "REVIEW"
        print(f"\nMixed-subtraction heuristic — {len(warnings)} site(s) to {label} "
              f"(naive/aware subtraction is the B2/B4 bug class; add `# tz-ok` once verified):")
        for w in warnings:
            print("  " + w)
        if strict:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
