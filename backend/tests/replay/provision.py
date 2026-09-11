#!/usr/bin/env python3
"""Build the throwaway `sara_replay` database from the captured fixture.

The replay harness runs the real assembly code — raw Postgres SQL, pgvector
casts, `percentile_cont`, naive-ET wall-clock comparisons — so it needs a
real Postgres, not a stubbed session. It gets its own database instead: the
live one is never opened by a replay, and the isolation is structural
rather than a promise in a comment.

    python3 backend/tests/replay/provision.py            # rebuild sara_replay
    python3 backend/tests/replay/provision.py --check    # is it there and loaded?

Everything is dropped and rebuilt each time; the replay database holds
nothing that isn't in the fixture, so there is nothing in it to lose.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "2026_09_09"

DB_SERVICE = "db"
DB_USER = "sara"
LIVE_DB = "sara_hub"
REPLAY_DB = "sara_replay"

# app_user first (everything references it); the rest follow in fixture
# order. FK triggers are off during the load anyway — see load_rows.
PRIORITY_TABLES = ("app_user",)

# Tables a replay rewinds, and the column (plus the convention that column
# is stored in — this database has three) that says when a row came into
# existence. Copied into a `fixture` schema at provision time so
# harness.rewind_to() can restore the exact set of rows that existed at any
# moment in the window, over and over, without reprovisioning.
#
# Without this, replaying the Wednesday afternoon turns shows Sara Thursday
# morning's sleep data — "measured Thu Sep 10, 6:00 AM (in 16h)".
# A table may name more than one column: a row is only visible at time T if
# every one of them is at or before T. health_metric needs both — a sleep
# sample RECORDED at 6:00 AM but only SYNCED from the watch at 9:28 was not
# knowable at 6:54, and rewinding on recorded_at alone put a reading "synced
# in 2h 34m" into the morning greeting.
REWINDABLE: dict[str, tuple[tuple[str, ...], str]] = {
    "episode": (("created_at",), "utc"),
    "conversation_turn": (("created_at",), "utc"),
    "food_log": (("logged_at",), "et"),
    "day_replay_cache": (("created_at",), "utc"),
    "note": (("updated_at",), "utc"),
    "workout_log": (("created_at",), "aware"),
    "workout_session": (("created_at",), "aware"),
    "active_workout_session": (("created_at",), "aware"),
    "health_metric": (("recorded_at", "created_at"), "aware"),
    "sara_journal": (("created_at",), "aware"),
    "attention_item": (("created_at",), "aware"),
    "world_attention_item": (("first_seen_at",), "aware"),
}


def psql(args: list[str], stdin: bytes | None = None, dbname: str = REPLAY_DB):
    return subprocess.run(
        ["docker", "compose", "exec", "-T", DB_SERVICE,
         "psql", "-U", DB_USER, "-d", dbname, *args],
        cwd=REPO, input=stdin, capture_output=True,
    )


def fail_if(proc, what: str):
    if proc.returncode != 0:
        sys.stderr.write(f"{what} failed:\n{proc.stderr.decode()[-3000:]}\n")
        raise SystemExit(1)


def array_literal(values: list) -> str:
    """A Postgres array literal for a column json_agg gave us as a JSON list."""
    parts = []
    for v in values:
        if v is None:
            parts.append("NULL")
        elif isinstance(v, (dict, list)):
            v = json.dumps(v)
            parts.append('"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"')
        else:
            parts.append('"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"')
    return "'{" + ",".join(parts) + "}'"


def sql_literal(value, udt: str | None = None) -> str:
    if value is None:
        return "NULL"
    if udt in ("json", "jsonb"):
        # Column type wins over Python type here: a json column holding the
        # scalar `true` or the string "3 of 3" comes back from json_agg as a
        # Python bool/str, and Postgres rejects either on the way in unless
        # it is re-serialized as JSON first.
        value = json.dumps(value)
    elif isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    elif isinstance(value, (int, float)):
        return repr(value)
    elif isinstance(value, list) and (udt or "").startswith("_"):
        return array_literal(value)
    elif isinstance(value, (dict, list)):
        value = json.dumps(value)
    # standard_conforming_strings is on, so doubling the quote is the whole
    # of the escaping; backslashes are literal.
    return "'" + str(value).replace("'", "''") + "'"


def recreate_database():
    print(f"Recreating {REPLAY_DB}...")
    proc = psql(["-v", "ON_ERROR_STOP=1", "-c",
                 f"DROP DATABASE IF EXISTS {REPLAY_DB} WITH (FORCE)"], dbname="postgres")
    fail_if(proc, "DROP DATABASE")
    proc = psql(["-v", "ON_ERROR_STOP=1", "-c", f"CREATE DATABASE {REPLAY_DB}"], dbname="postgres")
    fail_if(proc, "CREATE DATABASE")


def load_schema():
    schema = gzip.decompress((FIXTURE_DIR / "schema.sql.gz").read_bytes())
    print(f"Loading schema ({len(schema)} bytes)...")
    # ON_ERROR_STOP stays OFF: the dump carries a few objects the replay role
    # cannot recreate (extension comments, event triggers). Coverage is
    # verified by the table count below, not by a clean exit code.
    proc = psql(["-q", "-f", "-"], stdin=schema)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode()[-2000:] + "\n")
    count = psql(["-tAc", "SELECT count(*) FROM information_schema.tables "
                          "WHERE table_schema='public'"])
    fail_if(count, "table count")
    n = int(count.stdout.decode().strip() or 0)
    print(f"  · {n} tables")
    if n < 100:
        sys.stderr.write("Schema load looks incomplete; aborting.\n")
        raise SystemExit(1)


def load_rows():
    rows: dict[str, list[dict]] = json.loads(
        gzip.decompress((FIXTURE_DIR / "rows.json.gz").read_bytes()).decode())
    types: dict[str, dict[str, str]] = json.loads(
        (FIXTURE_DIR / "column_types.json").read_text())
    order = [t for t in PRIORITY_TABLES if t in rows] + \
            [t for t in rows if t not in PRIORITY_TABLES]

    statements = [
        # The fixture is a slice of the world, not the whole of it: rows point
        # at events, entities and sessions outside the captured window. Loading
        # with FK triggers live would mean either dragging in the transitive
        # closure of the database or silently dropping the rows that matter.
        "SET session_replication_role = replica;",
    ]
    total = 0
    for table in order:
        table_rows = rows[table]
        if not table_rows:
            continue
        cols = list(table_rows[0].keys())
        collist = ", ".join(f'"{c}"' for c in cols)
        coltypes = types.get(table, {})
        for row in table_rows:
            values = ", ".join(sql_literal(row.get(c), coltypes.get(c)) for c in cols)
            statements.append(f'INSERT INTO "{table}" ({collist}) VALUES ({values});')
        total += len(table_rows)
        print(f"  · {table}: {len(table_rows)}")
    statements.append("SET session_replication_role = DEFAULT;")

    print(f"Loading {total} rows...")
    proc = psql(["-q", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                stdin="\n".join(statements).encode())
    fail_if(proc, "row load")


def snapshot_rewindable():
    """Keep a pristine copy of every rewindable table in schema `fixture`."""
    statements = ["CREATE SCHEMA IF NOT EXISTS fixture;"]
    for table in REWINDABLE:
        statements.append(f'CREATE TABLE fixture."{table}" AS TABLE public."{table}";')
    print(f"Snapshotting {len(REWINDABLE)} rewindable tables...")
    proc = psql(["-q", "-v", "ON_ERROR_STOP=1", "-f", "-"], stdin="\n".join(statements).encode())
    fail_if(proc, "snapshot")


def check() -> int:
    exists = psql(["-tAc", "SELECT 1"], dbname=REPLAY_DB)
    if exists.returncode != 0:
        print(f"{REPLAY_DB}: not present (run without --check to build it)")
        return 1
    episodes = psql(["-tAc", "SELECT count(*) FROM fixture.episode"])
    events = psql(["-tAc", "SELECT count(*) FROM calendar_event"])
    if episodes.returncode != 0:
        print(f"{REPLAY_DB}: present but not snapshotted (rebuild it)")
        return 1
    print(f"{REPLAY_DB}: episode={episodes.stdout.decode().strip()} "
          f"calendar_event={events.stdout.decode().strip()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()

    recreate_database()
    load_schema()
    load_rows()
    snapshot_rewindable()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
