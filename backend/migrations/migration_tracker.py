"""
Lightweight migration version tracker.

Tracks which migration scripts have been applied via a `schema_migrations` table.
Each migration file must have an `upgrade()` function.

Usage:
    python -m migrations.migration_tracker status   # Show applied vs pending
    python -m migrations.migration_tracker run      # Run pending migrations
"""

import importlib
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
).replace("+asyncpg", "").replace("+psycopg", "")


def _get_engine():
    return create_engine(DATABASE_URL)


def _ensure_tracking_table(engine):
    """Create schema_migrations table if it doesn't exist."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT NOW()
            )
        """))


def _get_applied(engine) -> set:
    """Get set of already-applied migration names."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM schema_migrations ORDER BY name"))
        return {row[0] for row in result.fetchall()}


def _get_migration_files() -> list:
    """Get all migration files sorted alphabetically."""
    migrations_dir = Path(__file__).parent
    files = []
    for f in sorted(migrations_dir.glob("*.py")):
        name = f.stem
        # Skip non-migration files
        if name in ("migration_tracker", "__init__", "__pycache__"):
            continue
        files.append((name, f))
    return files


def status():
    """Show migration status."""
    engine = _get_engine()
    _ensure_tracking_table(engine)
    applied = _get_applied(engine)
    files = _get_migration_files()

    print(f"\nMigration Status ({len(applied)} applied, {len(files)} total)\n")
    print(f"{'Status':<10} {'Migration'}")
    print("-" * 60)

    pending = 0
    for name, _ in files:
        if name in applied:
            print(f"{'APPLIED':<10} {name}")
        else:
            print(f"{'PENDING':<10} {name}")
            pending += 1

    print(f"\n{pending} pending migration(s)")
    return pending


def run():
    """Run all pending migrations."""
    engine = _get_engine()
    _ensure_tracking_table(engine)
    applied = _get_applied(engine)
    files = _get_migration_files()

    pending = [(name, path) for name, path in files if name not in applied]
    if not pending:
        print("No pending migrations.")
        return 0

    print(f"\nRunning {len(pending)} pending migration(s)...\n")

    success = 0
    for name, path in pending:
        print(f"  Running: {name}...", end=" ", flush=True)
        try:
            # Import and run the upgrade function
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "upgrade"):
                module.upgrade()
            else:
                print(f"SKIP (no upgrade() function)")
                continue

            # Mark as applied
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO schema_migrations (name) VALUES (:name) ON CONFLICT DO NOTHING"),
                    {"name": name}
                )
            print("OK")
            success += 1
        except Exception as e:
            print(f"FAILED: {e}")
            logger.error(f"Migration {name} failed: {e}", exc_info=True)

    print(f"\n{success}/{len(pending)} migrations applied successfully.")
    return len(pending) - success


def mark_applied():
    """Mark all existing migrations as applied (for bootstrapping existing databases)."""
    engine = _get_engine()
    _ensure_tracking_table(engine)
    files = _get_migration_files()
    applied = _get_applied(engine)

    new = 0
    with engine.begin() as conn:
        for name, _ in files:
            if name not in applied:
                conn.execute(
                    text("INSERT INTO schema_migrations (name) VALUES (:name) ON CONFLICT DO NOTHING"),
                    {"name": name}
                )
                new += 1

    print(f"Marked {new} migration(s) as applied.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "run":
        run()
    elif cmd == "mark-applied":
        mark_applied()
    else:
        print(f"Usage: python -m migrations.migration_tracker [status|run|mark-applied]")
