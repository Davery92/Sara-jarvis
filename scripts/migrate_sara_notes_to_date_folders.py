"""One-shot migration: move all notes inside Sara's Notes into date folders.

For every note whose folder ancestor is "Sara's Notes" (`36ca18ea-...`),
compute the creation date in ET and move it into the corresponding day folder
under the new `YYYY / MM - Month / DD` hierarchy. Idempotent — re-running
leaves already-migrated notes in place.

Usage (inside the backend container):
    docker compose -f docker-compose.dev.yml exec -T backend \
        python scripts/migrate_sara_notes_to_date_folders.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

# Add /app to path when run from inside the container
sys.path.insert(0, "/app")

SARA_NOTES_ROOT = "36ca18ea-7b4b-4b48-ac60-95e1b720ec57"
SOLO_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
ET = ZoneInfo("America/New_York")


async def main():
    from app.db.session import get_async_session_factory
    from app.services.acs.session_manager import _ensure_date_folder

    async_session = get_async_session_factory()

    print(f"Migration: Sara's Notes → date folders")
    print(f"  user:  {SOLO_USER_ID}")
    print(f"  root:  {SARA_NOTES_ROOT}")
    print()

    # Step 1: collect every folder under Sara's Notes (recursive)
    async with async_session() as db:
        result = await db.execute(text("""
            WITH RECURSIVE tree AS (
                SELECT id, parent_id, name FROM folder WHERE id = :root
                UNION ALL
                SELECT f.id, f.parent_id, f.name
                FROM folder f
                JOIN tree t ON f.parent_id = t.id
                WHERE f.user_id = :uid
            )
            SELECT id, parent_id, name FROM tree
        """), {"root": SARA_NOTES_ROOT, "uid": SOLO_USER_ID})
        all_folders = result.fetchall()
        folder_ids = {row[0] for row in all_folders}
        print(f"Found {len(folder_ids)} folders under Sara's Notes")

    # Step 2: collect every note in those folders
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT n.id, n.title, n.folder_id, n.created_at
            FROM note n
            WHERE n.user_id = :uid AND n.folder_id = ANY(:fids)
            ORDER BY n.created_at
        """), {"uid": SOLO_USER_ID, "fids": list(folder_ids)})
        notes = result.fetchall()
        print(f"Found {len(notes)} notes to consider")
        print()

    if not notes:
        print("Nothing to migrate.")
        return

    # Step 3: for each note, compute its date folder (ET) and queue the move
    moves: dict[str, list[str]] = defaultdict(list)  # date_folder_id → [note_id]
    skipped_no_date = 0
    skipped_already_in_date_folder = 0

    # Pre-create folders sequentially to avoid races; cache by date string
    date_folder_cache: dict[str, str] = {}

    for note_id, title, current_folder_id, created_at in notes:
        if created_at is None:
            skipped_no_date += 1
            continue

        # Convert created_at to ET. created_at is timestamptz so it's tz-aware.
        if created_at.tzinfo is None:
            # Defensive — treat as UTC
            from datetime import timezone as _tz
            created_at = created_at.replace(tzinfo=_tz.utc)
        et_dt = created_at.astimezone(ET)
        date_key = et_dt.strftime("%Y-%m-%d")

        # Get or create the day folder via the same helper the new code uses
        if date_key not in date_folder_cache:
            day_folder_id = await _ensure_date_folder(SOLO_USER_ID, et_dt)
            date_folder_cache[date_key] = day_folder_id
        else:
            day_folder_id = date_folder_cache[date_key]

        if current_folder_id == day_folder_id:
            skipped_already_in_date_folder += 1
            continue

        moves[day_folder_id].append(note_id)

    total_to_move = sum(len(ids) for ids in moves.values())
    print(f"Planned moves:")
    print(f"  date folders touched:        {len(moves)}")
    print(f"  notes to move:               {total_to_move}")
    print(f"  notes already in date folder: {skipped_already_in_date_folder}")
    print(f"  notes skipped (no created_at): {skipped_no_date}")
    print()

    if not total_to_move:
        print("Nothing to move. Done.")
        return

    # Step 4: bulk-update folder_id per destination
    async with async_session() as db:
        for day_folder_id, note_ids in sorted(moves.items()):
            await db.execute(text("""
                UPDATE note SET folder_id = :fid, updated_at = updated_at
                WHERE id = ANY(:nids)
            """), {"fid": day_folder_id, "nids": note_ids})
        await db.commit()
    print(f"Moved {total_to_move} notes into {len(moves)} date folders.")

    # Step 5: report on now-empty topic folders (don't delete — just inform)
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT f.id, f.name, COUNT(n.id) AS note_count
            FROM folder f
            LEFT JOIN note n ON n.folder_id = f.id
            WHERE f.parent_id = :root
              AND f.user_id = :uid
              AND f.name NOT SIMILAR TO '[0-9]{4}'  -- skip year folders
            GROUP BY f.id, f.name
            ORDER BY note_count, f.name
        """), {"root": SARA_NOTES_ROOT, "uid": SOLO_USER_ID})
        rows = result.fetchall()

    if rows:
        print()
        print("Old topic folders directly under Sara's Notes (preserved, not deleted):")
        for fid, name, count in rows:
            marker = " (now empty)" if count == 0 else f" ({count} notes still inside)"
            print(f"  - {name}{marker}")
        print()
        print("Re-run this script after manual review to clean up empty topic folders,")
        print("or pass --delete-empty as a follow-up.")


if __name__ == "__main__":
    asyncio.run(main())
