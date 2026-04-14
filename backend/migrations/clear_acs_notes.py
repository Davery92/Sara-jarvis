"""
Clear all ACS-generated notes, interest graph, self-model, and session state.
Gives Sara a fresh start. Notes are archived (moved to Archived/ folder), not deleted.

Usage: python3 backend/migrations/clear_acs_notes.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


def clear():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        user_id = DEFAULT_USER_ID

        # 1. Find Sara's Notes root folder
        result = conn.execute(text("""
            SELECT id FROM folder
            WHERE user_id = :uid AND name = 'Sara''s Notes'
            LIMIT 1
        """), {"uid": user_id})
        root_row = result.fetchone()

        notes_archived = 0
        if root_row:
            root_id = root_row[0]

            # Find all subfolders under Sara's Notes
            result = conn.execute(text("""
                SELECT id FROM folder
                WHERE user_id = :uid AND (id = :root OR parent_id = :root)
            """), {"uid": user_id, "root": root_id})
            folder_ids = [r[0] for r in result.fetchall()]

            if folder_ids:
                # Get or create Archived subfolder
                result = conn.execute(text("""
                    SELECT id FROM folder
                    WHERE user_id = :uid AND name = 'Archived' AND parent_id = :root
                    LIMIT 1
                """), {"uid": user_id, "root": root_id})
                archive_row = result.fetchone()

                if archive_row:
                    archive_id = archive_row[0]
                else:
                    import uuid
                    archive_id = str(uuid.uuid4())
                    conn.execute(text("""
                        INSERT INTO folder (id, user_id, name, parent_id, created_at, updated_at)
                        VALUES (:id, :uid, 'Archived', :parent, NOW(), NOW())
                    """), {"id": archive_id, "uid": user_id, "parent": root_id})
                    print(f"Created 'Archived' subfolder: {archive_id[:8]}")

                # Move all notes from Sara's Notes folders to Archived
                # (except notes already in Archived)
                non_archive_folders = [fid for fid in folder_ids if fid != archive_id]
                if non_archive_folders:
                    result = conn.execute(text("""
                        UPDATE note SET folder_id = :archive
                        WHERE user_id = :uid AND folder_id = ANY(:fids)
                        RETURNING id
                    """), {"archive": archive_id, "uid": user_id, "fids": non_archive_folders})
                    notes_archived = result.rowcount
                    print(f"Archived {notes_archived} notes to Archived/ folder")

                # Delete empty subfolders (except root and Archived)
                cleanup_ids = [fid for fid in non_archive_folders if fid != root_id]
                if cleanup_ids:
                    # Only delete folders with no remaining notes
                    for fid in cleanup_ids:
                        check = conn.execute(text(
                            "SELECT COUNT(*) FROM note WHERE folder_id = :fid"
                        ), {"fid": fid})
                        if (check.scalar() or 0) == 0:
                            conn.execute(text("DELETE FROM folder WHERE id = :fid"), {"fid": fid})
                    print(f"Cleaned up empty subfolders")
        else:
            print("No 'Sara's Notes' folder found — skipping note archival")

        # 2. Clear interest graph
        result = conn.execute(text(
            "DELETE FROM acs_interest_edge WHERE user_id = :uid RETURNING id"
        ), {"uid": user_id})
        edges_deleted = result.rowcount
        print(f"Deleted {edges_deleted} interest edges")

        result = conn.execute(text(
            "DELETE FROM acs_interest_node WHERE user_id = :uid RETURNING id"
        ), {"uid": user_id})
        nodes_deleted = result.rowcount
        print(f"Deleted {nodes_deleted} interest nodes")

        # 3. Clear self-model
        result = conn.execute(text(
            "DELETE FROM acs_self_model WHERE user_id = :uid RETURNING id"
        ), {"uid": user_id})
        sm_deleted = result.rowcount
        print(f"Deleted {sm_deleted} self-model versions")

        # 4. Clear show-david buffer
        result = conn.execute(text(
            "DELETE FROM acs_show_david_buffer WHERE user_id = :uid RETURNING id"
        ), {"uid": user_id})
        sd_deleted = result.rowcount
        print(f"Deleted {sd_deleted} show-david items")

        # 5. Clear curiosity queue
        result = conn.execute(text(
            "DELETE FROM acs_curiosity_queue WHERE user_id = :uid RETURNING id"
        ), {"uid": user_id})
        cq_deleted = result.rowcount
        print(f"Deleted {cq_deleted} curiosity queue items")

        # 6. Clear directives
        result = conn.execute(text(
            "DELETE FROM acs_directive WHERE user_id = :uid RETURNING id"
        ), {"uid": user_id})
        dir_deleted = result.rowcount
        print(f"Deleted {dir_deleted} directives")

    # 7. Clear Redis keys
    try:
        import redis
        r = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        cleared = 0
        for pattern in [
            f"sara:acs:last_handoff:{DEFAULT_USER_ID}",
            f"sara:acs:open_threads:{DEFAULT_USER_ID}",
            f"sara:acs:daily_plan:{DEFAULT_USER_ID}",
            f"sara:acs:audit_feedback:{DEFAULT_USER_ID}",
            f"sara:acs:session_mode:{DEFAULT_USER_ID}",
        ]:
            if r.delete(pattern):
                cleared += 1
        # Also clear transcript keys
        for key in r.scan_iter("sara:acs:transcript:*"):
            r.delete(key)
            cleared += 1
        for key in r.scan_iter(f"sara:acs:transcripts_today:{DEFAULT_USER_ID}:*"):
            r.delete(key)
            cleared += 1
        for key in r.scan_iter("sara:acs:audit_pending:*"):
            r.delete(key)
            cleared += 1
        r.close()
        print(f"Cleared {cleared} Redis keys")
    except Exception as e:
        print(f"Redis cleanup failed (non-critical): {e}")

    print("\n--- ACS Cleanup Summary ---")
    print(f"Notes archived: {notes_archived}")
    print(f"Interest nodes deleted: {nodes_deleted}")
    print(f"Interest edges deleted: {edges_deleted}")
    print(f"Self-model versions deleted: {sm_deleted}")
    print("ACS is ready for a fresh start.")


if __name__ == "__main__":
    clear()
