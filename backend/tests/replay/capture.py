#!/usr/bin/env python3
"""Capture the 2026-09-09/10 conversation and the world it happened in.

Phase 0 of docs/plans/SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md: the
eight exchanges that plan was written from are still in the live database,
so the evidence does not have to be reconstructed from memory or from
Sara's own later description of them. This script freezes them — the turns,
and the canonical rows that were true at the time — into a fixture the
replay harness can rebuild a whole world from.

READ-ONLY BY CONSTRUCTION. Every statement runs against the live database
in a session with `default_transaction_read_only=on`, so the server itself
refuses a write; the only writes this script performs are to files under
fixtures/.

Runs on the HOST (stdlib only), because the schema dump needs `pg_dump`,
which lives in the db container and not in the backend image:

    python3 backend/tests/replay/capture.py

Re-running overwrites the fixture. Don't, unless you mean to: the point of
the file is that it is the state of the world on 2026-09-10, not the state
of the world today.
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "2026_09_09"

DB_SERVICE = "db"
DB_USER = "sara"
DB_NAME = "sara_hub"

# David. Every capture below is scoped to this id; no other user's rows are
# read, let alone committed.
USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# The two conversations the plan reviewed.
CONVERSATIONS = (
    "0c01dd0e-9f07-4a25-bf11-c863346ce2cc",  # Sept 9 — workout, food, dinner, correction
    "f882bce8-58cb-4541-8669-2435917a4623",  # Sept 10 — greeting, Everett/open house
)

WINDOW_START = "2026-09-08"
WINDOW_END = "2026-09-11"

# Three minutes after the last captured turn (10:57 UTC). Anything recorded
# after this could not have been in front of Sara during any of the eight
# exchanges, and a replay that shows it is showing her the future: the first
# capture ran at 14:20 UTC and put a weight reading "measured in 3h 11m" into
# a 6:54 AM prompt. Time-series tables are cut here.
#
# STATE tables cannot be: world_brief, world_thread, world_fact, life_fact,
# behavioral_pattern, daily_rhythm, standing_order, directive, reminder,
# timer, scratchpad_entry, user_profile and user_settings hold current state
# with no history to rewind, so the fixture carries them as they were at
# capture time. That is a real limitation of this fixture and it is written
# into the manifest rather than left for someone to discover.
CUTOFF = "2026-09-10 11:00:00+00"

# (table, where-clause, columns-to-drop). Columns are dropped for size
# (embeddings) or for privacy (password hashes) — never to make the replay
# look better than the day did.
SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("app_user", f"id = '{USER_ID}'", ()),
    ("episode",
     f"user_id = '{USER_ID}' AND created_at >= '{WINDOW_START}' AND created_at < '{CUTOFF}'",
     ("embedding",)),
    ("conversation_turn",
     "conversation_id IN (" + ",".join(f"'{c}'" for c in CONVERSATIONS) + ")",
     ("embedding",)),
    # A generous calendar window: the failure was about *ownership*, and the
    # renderer looks 14 days out, so the fixture has to hold more than the
    # two events that went wrong.
    ("calendar_event", "start_time >= '2026-09-01' AND start_time < '2026-10-01'", ()),
    ("food_log", f"user_id = '{USER_ID}' AND logged_at >= '{WINDOW_START}' AND logged_at < '{CUTOFF}'", ()),
    ("food_log_item",
     f"food_log_id IN (SELECT id FROM food_log WHERE user_id = '{USER_ID}'"
     f" AND logged_at >= '{WINDOW_START}' AND logged_at < '{CUTOFF}')", ()),
    ("workout_log", f"user_id = '{USER_ID}' AND created_at >= '2026-08-25' AND created_at < '{CUTOFF}'", ()),
    ("workout_session", f"user_id = '{USER_ID}' AND created_at < '{CUTOFF}'", ()),
    ("active_workout_session", f"user_id = '{USER_ID}' AND created_at < '{CUTOFF}'", ()),
    ("health_metric",
     f"user_id = '{USER_ID}' AND recorded_at >= '2026-08-15'"
     " AND metric_type IN ('hrv_morning','hrv','sleep_hours','sleep_deep_min','sleep_rem_min',"
     "'sleep_core_min','sleep_awake_min','resting_hr','steps','weight','active_energy',"
     "'exercise_minutes','stand_minutes','flights_climbed')"
     f" AND recorded_at < '{CUTOFF}'", ()),
    ("life_fact", f"user_id = '{USER_ID}'", ()),
    # Only the entries that could still have been read on the 10th — the
    # narrative failure is about a document that keeps folding itself
    # forward, so the last fortnight of it is the evidence, not the year.
    ("sara_journal",
     f"user_id = '{USER_ID}' AND created_at >= '2026-08-25' AND created_at < '{CUTOFF}'"
     " AND entry_type IN ('theory_of_david','self_story','daily_reflection')", ()),
    ("world_brief", f"user_id = '{USER_ID}'", ()),
    ("world_thread", f"user_id = '{USER_ID}'", ()),
    # Active facts only. The superseded half of world_fact is 2,700 rows of
    # history that no reader in the replay path queries.
    ("world_fact", f"user_id = '{USER_ID}' AND status = 'active'", ()),
    ("standing_order", f"user_id = '{USER_ID}'", ()),
    ("directive", f"user_id = '{USER_ID}'", ()),
    ("scratchpad_entry", f"user_id = '{USER_ID}'", ()),
    ("correction", f"user_id = '{USER_ID}'", ()),
    ("reminder", f"user_id = '{USER_ID}'", ()),
    ("timer", f"user_id = '{USER_ID}'", ()),
    ("behavioral_pattern", f"user_id = '{USER_ID}'", ()),
    ("daily_rhythm", f"user_id = '{USER_ID}'", ()),
    ("attention_item", f"created_at >= '2026-09-01' AND created_at < '{CUTOFF}'", ()),
    ("world_attention_item",
     f"user_id = '{USER_ID}' AND first_seen_at >= '2026-09-01' AND first_seen_at < '{CUTOFF}'", ()),
    ("day_replay_cache",
     f"user_id = '{USER_ID}' AND replay_date >= '2026-09-01' AND created_at < '{CUTOFF}'", ()),
    ("user_profile", f"user_id = '{USER_ID}'", ()),
    ("user_settings", f"user_id = '{USER_ID}'", ()),
    ("note", f"user_id = '{USER_ID}' AND updated_at >= '2026-08-25' AND updated_at < '{CUTOFF}'",
     ("embedding",)),
]

# Columns kept (a NOT NULL column that is simply dropped makes the fixture
# unloadable) but overwritten with a constant.
SCRUBBED: dict[tuple[str, str], str] = {
    ("app_user", "password_hash"): "[redacted — replay never authenticates]",
}

# Redaction. The fixture is committed, so anything that identifies a third
# party by contact detail — not by first name, which the ownership failure
# is literally about — comes out.
REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "redacted@example.invalid"),
    # The lookarounds matter: without them this pattern eats the tail of
    # every UUID in the fixture and the load fails on "invalid input syntax
    # for type uuid".
    (re.compile(r"(?<![\w-])\+?\d{0,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?![\w-])"),
     "555-000-0000"),
    (re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Court|Ct)\b"),
     "[street address redacted]"),
    (re.compile(r"(?i)\b(bearer|api[_-]?key|token|password)\b\s*[:=]\s*\S+"), r"\1: [redacted]"),
]


def psql(sql: str, dbname: str = DB_NAME) -> str:
    """Run one statement read-only against the live database.

    Read-only is enforced by the session's own `default_transaction_read_only`
    rather than by a hand-written BEGIN/COMMIT wrapper — the server rejects a
    write regardless of what this file asks it to do, and psql's status lines
    for the extra statements stay out of the captured output.
    """
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T",
         "-e", "PGOPTIONS=-c default_transaction_read_only=on", DB_SERVICE,
         "psql", "-U", DB_USER, "-d", dbname, "-tA", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=REPO, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed for: {sql[:120]}...\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def columns(table: str) -> list[str]:
    return list(column_types(table).keys())


def column_types(table: str) -> dict[str, str]:
    """{column: udt_name} in ordinal order. The loader needs the types back:
    `json_agg` renders a Postgres text[] as a JSON list, which is not a
    literal Postgres will accept on the way back in."""
    raw = psql(
        "SELECT COALESCE(json_agg(json_build_array(column_name, udt_name) "
        "ORDER BY ordinal_position)::text, '[]') FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name='{table}'"
    )
    return {name: udt for name, udt in json.loads(raw or "[]")}


def redact(value):
    if isinstance(value, str):
        for pattern, replacement in REDACTIONS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


def capture_rows(types: dict[str, dict[str, str]]) -> dict[str, list[dict]]:
    captured: dict[str, list[dict]] = {}
    for table, where, drop in SPECS:
        types[table] = column_types(table)
        cols = list(types[table].keys())
        if not cols:
            print(f"  ! {table}: no such table, skipped")
            continue
        keep = [c for c in cols if c not in drop]
        select = ", ".join(f'"{c}"' for c in keep)
        raw = psql(
            f"SELECT COALESCE(json_agg(t)::text, '[]') FROM "
            f"(SELECT {select} FROM {table} WHERE {where}) t"
        )
        rows = [redact(r) for r in json.loads(raw or "[]")]
        for (scrub_table, scrub_col), placeholder in SCRUBBED.items():
            if scrub_table == table:
                for row in rows:
                    if scrub_col in row:
                        row[scrub_col] = placeholder
        captured[table] = rows
        print(f"  · {table}: {len(rows)} row(s)")
    return captured


def capture_turns(rows: dict[str, list[dict]]) -> list[dict]:
    """The eight exchanges, in order, paired user->assistant.

    `expectations` is deliberately prose, not a golden sentence: the plan
    asks for recorded expected *behavior*, because there is no single ideal
    reply and pinning one would make the suite a style test.
    """
    episodes = sorted(
        (e for e in rows.get("episode", []) if e.get("conversation_id") in CONVERSATIONS),
        key=lambda e: e["created_at"],
    )
    turns, pending = [], None
    for ep in episodes:
        if ep["role"] == "user":
            pending = ep
        elif ep["role"] == "assistant" and pending is not None:
            turns.append({
                "index": len(turns),
                "conversation_id": ep["conversation_id"],
                "at": pending["created_at"],
                "user_episode_id": pending["id"],
                "assistant_episode_id": ep["id"],
                "user_text": pending["content"],
                "observed_assistant_text": ep["content"],
            })
            pending = None
    return turns


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    print("Capturing schema (pg_dump --schema-only)...")
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", DB_SERVICE, "pg_dump", "-U", DB_USER, "-d", DB_NAME,
         "--schema-only", "--no-owner", "--no-acl", "--no-comments"],
        cwd=REPO, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr[-2000:], file=sys.stderr)
        return 1
    (FIXTURE_DIR / "schema.sql.gz").write_bytes(gzip.compress(proc.stdout.encode(), 9))
    print(f"  · schema.sql.gz ({len(proc.stdout)} bytes -> "
          f"{(FIXTURE_DIR / 'schema.sql.gz').stat().st_size} compressed)")

    print("Capturing daily-brief layers...")
    # The four brief layers are FILES, not rows — /home/david/jarvis/data/
    # briefs/<user>/layers/*.md, mounted into the backend container at the
    # same path. A replay that doesn't carry them reads the live files and
    # is not a replay at all; it is today's narrative wearing Wednesday's
    # timestamp. (Captured now, so they are as of `captured_at`: day.md and
    # moment.md happen to have last been written during the final two
    # exchanges, which is as close as this can get.)
    briefs_src = REPO / "data" / "briefs" / USER_ID / "layers"
    briefs_dst = FIXTURE_DIR / "briefs" / USER_ID / "layers"
    if briefs_src.is_dir():
        shutil.rmtree(briefs_dst, ignore_errors=True)
        briefs_dst.mkdir(parents=True, exist_ok=True)
        for layer in sorted(briefs_src.glob("*.md")):
            (briefs_dst / layer.name).write_text(redact(layer.read_text()))
            print(f"  · {layer.name}: {layer.stat().st_size} bytes "
                  f"(mtime {datetime.fromtimestamp(layer.stat().st_mtime).isoformat(timespec='seconds')})")
    else:
        print(f"  ! {briefs_src} missing — replays will read live layers")

    print("Capturing rows...")
    types: dict[str, dict[str, str]] = {}
    rows = capture_rows(types)

    print("Pairing turns...")
    turns = capture_turns(rows)
    print(f"  · {len(turns)} exchange(s)")

    # gzipped: the honest world here is ~6MB of JSON, most of it the 2,300
    # active world_fact rows, and trimming it to fit a diff would mean
    # replaying a smaller world than the one Sara actually had.
    (FIXTURE_DIR / "rows.json.gz").write_bytes(
        gzip.compress(json.dumps(rows, indent=1, sort_keys=True).encode(), 9))
    (FIXTURE_DIR / "turns.json").write_text(json.dumps(turns, indent=1))
    (FIXTURE_DIR / "column_types.json").write_text(json.dumps(types, indent=1, sort_keys=True))
    (FIXTURE_DIR / "manifest.json").write_text(json.dumps({
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_database": DB_NAME,
        "user_id": USER_ID,
        "conversations": list(CONVERSATIONS),
        "window": [WINDOW_START, WINDOW_END],
        "cutoff": CUTOFF,
        "as_of_capture_tables": [
            "world_brief", "world_thread", "world_fact", "life_fact",
            "behavioral_pattern", "daily_rhythm", "standing_order", "directive",
            "reminder", "timer", "scratchpad_entry", "user_profile",
            "user_settings", "calendar_event", "correction",
        ],
        "tables": {t: len(r) for t, r in rows.items()},
        "turns": len(turns),
        "brief_layers": sorted(p.name for p in (FIXTURE_DIR / "briefs" / USER_ID / "layers").glob("*.md")),
        "redactions": [p.pattern for p, _ in REDACTIONS],
        "notes": [
            "Captured read-only from the live database; no row here was edited by hand.",
            "Embeddings are dropped: they are large, and nothing in the replay reads them "
            "back (recall is exercised against the same text through the live embedder).",
            "First names of family members are kept deliberately — the calendar-ownership "
            "failure is about a first name being read as a place.",
            "Time-series tables are cut at `cutoff`, just after the last exchange, so a "
            "replay is never shown a row that did not exist yet. The tables in "
            "`as_of_capture_tables` hold current state with no history to rewind and are "
            "therefore as of `captured_at`, not as of the turn.",
        ],
    }, indent=1))
    print(f"Wrote fixture to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
