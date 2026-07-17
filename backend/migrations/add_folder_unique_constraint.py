"""Add unique constraint on folder (user_id, name, parent_id) to prevent duplicates.

Also deduplicates existing folders first.
"""
import asyncio
import sys
sys.path.insert(0, "/home/david/jarvis/backend")

from sqlalchemy import text
from app.db.session import get_async_session_factory


async def migrate():
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Step 1: Find and merge duplicate folders (keep the oldest)
        dupes = await db.execute(text("""
            SELECT user_id, name, COALESCE(parent_id::text, 'NULL') as pid,
                   array_agg(id::text ORDER BY created_at) as ids,
                   count(*) as cnt
            FROM folder
            GROUP BY user_id, name, COALESCE(parent_id::text, 'NULL')
            HAVING count(*) > 1
        """))

        for row in dupes.fetchall():
            ids = row[3]  # array of folder ids
            keep_id = ids[0]  # keep the oldest
            remove_ids = ids[1:]

            print(f"Deduplicating folder '{row[1]}': keeping {keep_id[:8]}, removing {len(remove_ids)} duplicates")

            for dup_id in remove_ids:
                # Move notes from duplicate to the keeper
                await db.execute(text(
                    "UPDATE note SET folder_id = :keep WHERE folder_id = :dup"
                ), {"keep": keep_id, "dup": dup_id})

                # Move subfolders from duplicate to the keeper
                await db.execute(text(
                    "UPDATE folder SET parent_id = :keep WHERE parent_id = :dup"
                ), {"keep": keep_id, "dup": dup_id})

                # Delete the duplicate folder
                await db.execute(text(
                    "DELETE FROM folder WHERE id = :dup"
                ), {"dup": dup_id})

        await db.commit()
        print("Deduplication complete.")

        # Step 2: Add unique index (using COALESCE to handle NULL parent_id)
        await db.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_folder_user_name_parent
            ON folder (user_id, name, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'))
        """))
        await db.commit()
        print("Unique constraint added successfully.")


if __name__ == "__main__":
    asyncio.run(migrate())
