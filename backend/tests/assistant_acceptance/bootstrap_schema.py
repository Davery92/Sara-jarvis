"""Provision a disposable Postgres with every ORM table this app declares.

Why this exists: `alembic upgrade head` cannot build this database from
nothing — the chain contains migrations that ALTER tables no earlier
migration creates (`ALTER TABLE episode ADD COLUMN emotion_metadata` fails on
an empty database), because the schema was originally created by
`Base.metadata.create_all` and migrated from there. And `create_all` alone
does not work either, for two reasons this script handles:

  1. There are TWO declarative registries — `app.db.base.Base` (the model
     files) and a second `Base` local to `main_simple` — with foreign keys
     pointing across the boundary. `metadata.sorted_tables` raises
     NoReferencedTableError while topologically sorting either one alone.
  2. Because of that, table creation has to be attempted repeatedly: each
     pass creates whatever table's dependencies now exist, until a pass
     makes no further progress.

Disposable stacks only — refuses to run unless SARA_TEST_ENV=disposable, so
this can never be pointed at production by accident.
"""
import os
import sys

if os.environ.get("SARA_TEST_ENV") != "disposable":
    sys.exit("refusing to run: SARA_TEST_ENV must be 'disposable'")

import logging

logging.disable(logging.ERROR)

from sqlalchemy import text  # noqa: E402

import app.db.base  # noqa: F401,E402  — registers every model
from app.db.base import Base as ModelBase  # noqa: E402
from app.db.session import engine  # noqa: E402

metadatas = [ModelBase.metadata]
try:
    import app.main_simple as ms  # noqa: E402

    ms_base = getattr(ms, "Base", None)
    if ms_base is not None and ms_base.metadata is not ModelBase.metadata:
        metadatas.append(ms_base.metadata)
except Exception as exc:  # pragma: no cover - diagnostic only
    print(f"note: main_simple models unavailable ({type(exc).__name__}: {exc})")


def table_count() -> int:
    with engine.connect() as conn:
        return conn.execute(text(
            "select count(*) from information_schema.tables where table_schema='public'"
        )).scalar()


with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

before = table_count()
errors = {}
for pass_no in range(1, 9):
    made_progress = False
    for meta in metadatas:
        # Deliberately NOT sorted_tables: sorting raises on the cross-registry
        # foreign keys. Unordered + repeated passes gets there instead.
        for table in list(meta.tables.values()):
            try:
                table.create(bind=engine, checkfirst=True)
                errors.pop(table.name, None)
            except Exception as exc:
                errors[table.name] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"
    now = table_count()
    print(f"pass {pass_no}: {now} tables")
    if now == before and pass_no > 1:
        break
    made_progress = now != before
    before = now
    if not made_progress and pass_no > 1:
        break

print(f"\nfinal table count: {table_count()}")
if errors:
    print(f"{len(errors)} table(s) could not be created:")
    for name, err in sorted(errors.items())[:25]:
        print(f"  {name}: {err}")

# Stamp alembic so the app's own startup checks see a migrated database.
with engine.connect() as conn:
    conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
    conn.execute(text("DELETE FROM alembic_version"))
    conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                 {"v": sys.argv[1] if len(sys.argv) > 1 else "158_reminder_delivery_state"})
    conn.commit()
    print("alembic_version stamped:", conn.execute(text("select version_num from alembic_version")).scalar())
