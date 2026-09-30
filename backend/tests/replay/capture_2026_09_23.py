#!/usr/bin/env python3
"""Capture the two 2026-09-22/23 conversations
docs/plans/SARA_PERSONAL_CONVERSATION_REMEDIATION_PLAN_2026_09_23.md's
evidence table was written from: "Good evening" / "Just relaxing lol I'm
tired" (23:29-23:38 UTC) and the ER-visit turn the next morning
(11:12-11:13 UTC).

Same pattern as capture_2026_09_16.py (see that file's docstring for the
full rationale) re-pointed at these two conversations. Two conversations,
not one, because the plan's evidence spans an evening/morning pair — the
world state the second turn saw (the previous evening's exchange, the
overnight ER visit having happened, the workout/health rows from the day
before) is part of what this fixture needs to reproduce.

READ-ONLY BY CONSTRUCTION — see capture_2026_09_16.py. Runs on the HOST
(stdlib only):

    python3 backend/tests/replay/capture_2026_09_23.py

Re-running overwrites the fixture. Don't, unless the point is a different
capture — the value of this one is that it is the state of the world across
those two turns, not the state of the world today.
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
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "2026_09_23"

DB_SERVICE = "db"
DB_USER = "sara"
DB_NAME = "sara_hub"

# David. Every capture below is scoped to this id; no other user's rows are
# read, let alone committed.
USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# The evening conversation ("Good evening" -> "Just relaxing lol I'm tired")
# and the next-morning conversation (the ER-visit turn).
CONVERSATIONS = (
    "d30a68bf-0973-48c9-810f-3d80508a435c",  # 2026-09-22 23:29-23:38 UTC
    "27ba7e0b-42b0-4630-88b4-02e8d6d8d3d2",  # 2026-09-23 11:12-11:13 UTC
)

WINDOW_START = "2026-09-18"
WINDOW_END = "2026-09-24"

# A few minutes after the last captured turn (11:13:07 UTC). Anything
# recorded after this could not have been in front of Sara during either
# exchange. Time-series tables are cut here; STATE tables (world_brief,
# world_thread, world_fact, life_fact, behavioral_pattern, daily_rhythm,
# standing_order, directive, reminder, timer, scratchpad_entry,
# user_profile, user_settings) hold current state with no history to
# rewind and so carry it as of capture time instead — written into the
# manifest, not left for someone to discover.
CUTOFF = "2026-09-23 11:20:00+00"

# (table, where-clause, columns-to-drop). Columns dropped for size
# (embeddings) or privacy (password hashes) — never to make the replay look
# better than the day did.
SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("app_user", f"id = '{USER_ID}'", ()),
    ("episode",
     f"user_id = '{USER_ID}' AND created_at >= '{WINDOW_START}' AND created_at < '{CUTOFF}'",
     ("embedding",)),
    ("calendar_event", "start_time >= '2026-09-10' AND start_time < '2026-10-10'", ()),
    ("food_log", f"user_id = '{USER_ID}' AND logged_at >= '{WINDOW_START}' AND logged_at < '{CUTOFF}'", ()),
    ("food_log_item",
     f"food_log_id IN (SELECT id FROM food_log WHERE user_id = '{USER_ID}'"
     f" AND logged_at >= '{WINDOW_START}' AND logged_at < '{CUTOFF}')", ()),
    ("workout_log", f"user_id = '{USER_ID}' AND created_at >= '{WINDOW_START}' AND created_at < '{CUTOFF}'", ()),
    ("workout_session", f"user_id = '{USER_ID}' AND created_at < '{CUTOFF}'", ()),
    ("active_workout_session", f"user_id = '{USER_ID}' AND created_at < '{CUTOFF}'", ()),
    ("health_metric",
     f"user_id = '{USER_ID}' AND recorded_at >= '2026-09-10'"
     " AND metric_type IN ('hrv_morning','hrv','sleep_hours','sleep_deep_min','sleep_rem_min',"
     "'sleep_core_min','sleep_awake_min','resting_hr','steps','weight','active_energy',"
     "'exercise_minutes','stand_minutes','flights_climbed')"
     f" AND recorded_at < '{CUTOFF}'", ()),
    ("life_fact", f"user_id = '{USER_ID}'", ()),
    ("sara_journal",
     f"user_id = '{USER_ID}' AND created_at >= '2026-09-15' AND created_at < '{CUTOFF}'"
     " AND entry_type IN ('theory_of_david','self_story','daily_reflection')", ()),
    ("world_brief", f"user_id = '{USER_ID}'", ()),
    ("world_thread", f"user_id = '{USER_ID}'", ()),
    ("world_fact", f"user_id = '{USER_ID}' AND status = 'active'", ()),
    ("standing_order", f"user_id = '{USER_ID}'", ()),
    ("directive", f"user_id = '{USER_ID}'", ()),
    ("scratchpad_entry", f"user_id = '{USER_ID}'", ()),
    ("correction", f"user_id = '{USER_ID}'", ()),
    ("reminder", f"user_id = '{USER_ID}'", ()),
    ("timer", f"user_id = '{USER_ID}'", ()),
    ("behavioral_pattern", f"user_id = '{USER_ID}'", ()),
    ("daily_rhythm", f"user_id = '{USER_ID}'", ()),
    ("attention_item", f"created_at >= '{WINDOW_START}' AND created_at < '{CUTOFF}'", ()),
    ("world_attention_item",
     f"user_id = '{USER_ID}' AND first_seen_at >= '{WINDOW_START}' AND first_seen_at < '{CUTOFF}'", ()),
    ("outbox_item",
     f"user_id = '{USER_ID}' AND created_at >= '{WINDOW_START}' AND created_at < '{CUTOFF}'", ()),
    ("day_replay_cache",
     f"user_id = '{USER_ID}' AND replay_date >= '{WINDOW_START}' AND created_at < '{CUTOFF}'", ()),
    ("user_profile", f"user_id = '{USER_ID}'", ()),
    ("user_settings", f"user_id = '{USER_ID}'", ()),
    ("note", f"user_id = '{USER_ID}' AND updated_at >= '2026-09-15' AND updated_at < '{CUTOFF}'",
     ("embedding",)),
]

SCRUBBED: dict[tuple[str, str], str] = {
    ("app_user", "password_hash"): "[redacted — replay never authenticates]",
}

# Redaction. The fixture is committed, so anything that identifies a third
# party by contact detail — not by first name/relation, which the plan's
# evidence is literally about (his dad, the ER visit) — comes out. Health
# VALUES themselves (HRV 32, etc.) are kept: the plan's whole point is that
# Sara surfaced them unprompted, and a replay that scrubs the number can't
# reproduce or verify the fix.
REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "redacted@example.invalid"),
    (re.compile(r"(?<![\w-])\+?\d{0,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?![\w-])"),
     "555-000-0000"),
    (re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Court|Ct)\b"),
     "[street address redacted]"),
    (re.compile(r"(?i)\b(bearer|api[_-]?key|token|password)\b\s*[:=]\s*\S+"), r"\1: [redacted]"),
]


def psql(sql: str, dbname: str = DB_NAME) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T",
         "-e", "PGOPTIONS=-c default_transaction_read_only=on", DB_SERVICE,
         "psql", "-U", DB_USER, "-d", dbname, "-tA", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=REPO, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed for: {sql[:120]}...\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def column_types(table: str) -> dict[str, str]:
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
    """Each conversation's exchanges, in order, paired user->assistant.
    Sorted by created_at across both conversations so `index` reflects real
    chronology (evening turns first, then the next-morning turn)."""
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
            "user_settings", "calendar_event", "correction", "outbox_item",
        ],
        "tables": {t: len(r) for t, r in rows.items()},
        "turns": len(turns),
        "brief_layers": sorted(p.name for p in (FIXTURE_DIR / "briefs" / USER_ID / "layers").glob("*.md")),
        "redactions": [p.pattern for p, _ in REDACTIONS],
        "notes": [
            "Captured read-only from the live database; no row here was edited by hand.",
            "Embeddings are dropped: they are large, and nothing in the replay reads them "
            "back (recall is exercised against the same text through the live embedder).",
            "Captured for docs/plans/SARA_PERSONAL_CONVERSATION_REMEDIATION_PLAN_2026_09_23.md's "
            "evidence table: 'Good evening' -> unsolicited day recap, 'Just relaxing lol "
            "I'm tired' -> unsolicited HRV interpretation, the ER-visit turn -> proposed "
            "email/SSL/ACORD work and an invented wake time.",
            "Health VALUES (HRV, etc.) are kept unredacted on purpose — the plan's failure "
            "is that Sara surfaced them unprompted, and a replay that scrubs the number "
            "cannot verify the fix. Third-party contact details and street addresses are "
            "still redacted.",
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
