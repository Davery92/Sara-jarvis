#!/usr/bin/env python3
"""
Arc 5 note migration — execute the manifest (SARA_ALIVE_BUILD_PLAN Arc 5.3).

David approved ARC5_NOTES_MANIFEST_2026_07_29.md (53 machine-generated
notes) on 2026-07-29. This script executes the plan's own migration
discipline for destructive steps:

  1. COPY  — each matched note becomes an Episode (the record store;
     memory_recall.py already fans out over "episode" kind, so this lands
     the content behind the one recall door instead of a private notes
     table), preserving the original note id (Episode.id is an unconstrained
     string PK, so this is safe) and created_at. note.embedding is reused
     when present (23 of 53 rows) rather than recomputed.
  2. VERIFY — every copied id is re-read back from `episode` and content-
     compared against the source `note` row before anything is removed.
  3. DELETE — garden (note table) rows are removed ONLY for ids that passed
     verification. Any row that fails verification is left in the garden
     and reported, not deleted.

Idempotent: re-running skips notes that no longer exist (already migrated).

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/arc5_migrate_notes.py [--dry-run] [--user-id UUID]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

PATTERNS = ["Agent Result:%", "✅ Agent Report:%", "Background Research:%"]


def migrate(user_id: str, dry_run: bool) -> dict:
    from sqlalchemy import text
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        where_clause = " OR ".join(["title LIKE :p%d" % i for i in range(len(PATTERNS))])
        params = {"uid": user_id, **{f"p{i}": p for i, p in enumerate(PATTERNS)}}
        notes = db.execute(text(f"""
            SELECT id, title, content, created_at, embedding, tags
            FROM note WHERE user_id = :uid AND ({where_clause})
        """), params).fetchall()

        if not notes:
            return {"candidates": 0, "copied": 0, "verified": 0, "deleted": 0, "failed": []}

        print(f"Found {len(notes)} candidate notes.")
        if dry_run:
            print("--dry-run: stopping before COPY.")
            return {"candidates": len(notes), "copied": 0, "verified": 0, "deleted": 0, "failed": []}

        # ── COPY ──
        copied_ids = []
        for n in notes:
            existing = db.execute(text(
                "SELECT id FROM episode WHERE id = :id"
            ), {"id": n.id}).first()
            if existing:
                print(f"  {n.id} already migrated (episode exists) — skipping copy")
                copied_ids.append(n.id)
                continue
            has_embedding = n.embedding is not None
            db.execute(text(f"""
                INSERT INTO episode (
                    id, user_id, role, content, importance, memory_type, source,
                    created_at, embedding, meta
                ) VALUES (
                    :id, :uid, 'assistant', :content, 0.2, 'agent_result', 'agent_dispatch_migrated',
                    :created_at, {"CAST(:embedding AS vector)" if has_embedding else "NULL"}, CAST(:meta AS jsonb)
                )
            """), {
                "id": n.id, "uid": user_id, "content": n.content,
                "created_at": n.created_at,
                **({"embedding": n.embedding} if has_embedding else {}),
                "meta": __import__("json").dumps({
                    "migrated_from": "note", "original_title": n.title,
                    "migration": "arc5_notes_manifest_2026_07_29",
                }),
            })
            copied_ids.append(n.id)
        db.commit()
        print(f"Copied {len(copied_ids)} rows into episode.")

        # ── VERIFY ──
        verified_ids = []
        failed = []
        for n in notes:
            row = db.execute(text(
                "SELECT content FROM episode WHERE id = :id"
            ), {"id": n.id}).first()
            if row and row.content == n.content:
                verified_ids.append(n.id)
            else:
                failed.append(n.id)
        print(f"Verified {len(verified_ids)} / {len(notes)}.")
        if failed:
            print(f"FAILED verification (left in garden, NOT deleted): {failed}")

        # ── DELETE (garden rows, verified only) ──
        deleted = 0
        if verified_ids:
            result = db.execute(text(
                "DELETE FROM note WHERE id = ANY(:ids)"
            ), {"ids": verified_ids})
            deleted = result.rowcount
            db.commit()
        print(f"Deleted {deleted} verified garden rows.")

        return {
            "candidates": len(notes), "copied": len(copied_ids),
            "verified": len(verified_ids), "deleted": deleted, "failed": failed,
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    args = parser.parse_args()
    result = migrate(args.user_id, args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
