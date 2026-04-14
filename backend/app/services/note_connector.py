"""Standalone note connection detection — works with async SQLAlchemy sessions.

Used by ACS session_manager (Celery workers) and notes tools to detect
and create NoteConnection rows directly in PostgreSQL.
"""
import re
import uuid
import logging
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def process_note_connections(
    note_id: str,
    user_id: str,
    title: str,
    content: str,
    db,
    *,
    generate_embedding: bool = True,
):
    """Detect and create connections for a note. Fire-and-forget safe.

    Args:
        db: An async SQLAlchemy session (already inside a transaction).
        generate_embedding: If True, generate and store embedding for the note.
    """
    try:
        full_text = f"{title}\n{content}" if title else content
        embedding = None

        # Step 1: Generate and store embedding
        if generate_embedding:
            try:
                from app.services.embeddings import get_embedding
                embedding = await get_embedding(full_text)
                if embedding:
                    await db.execute(
                        text("UPDATE note SET embedding = CAST(:emb AS vector) WHERE id = :nid"),
                        {"emb": str(embedding), "nid": note_id},
                    )
            except Exception as e:
                logger.warning(f"note_connector: embedding failed for {note_id}: {e}")

        # Step 2: Parse [[wiki links]] and create reference connections
        await _create_reference_connections(db, note_id, user_id, content)

        # Step 3: Find semantic neighbors and create semantic connections
        if embedding:
            await _create_semantic_connections(db, note_id, user_id, embedding)

    except Exception as e:
        logger.error(f"note_connector: failed for note {note_id}: {e}", exc_info=True)


async def _create_reference_connections(
    db, note_id: str, user_id: str, content: str
):
    """Parse [[wiki links]] from content and create reference connections."""
    links = re.findall(r"\[\[([^\]]+)\]\]", content)
    if not links:
        return

    for link_title in links:
        link_title = link_title.strip()
        if not link_title:
            continue
        try:
            result = await db.execute(
                text("""
                    SELECT id FROM note
                    WHERE user_id = :uid AND LOWER(title) = LOWER(:title) AND id != :nid
                    LIMIT 1
                """),
                {"uid": user_id, "title": link_title, "nid": note_id},
            )
            row = result.fetchone()
            if not row:
                continue

            target_id = row[0]
            await _insert_connection(
                db, user_id, note_id, target_id,
                connection_type="reference", strength=80,
            )
        except Exception as e:
            logger.debug(f"note_connector: ref link '{link_title}' failed: {e}")


async def _create_semantic_connections(
    db, note_id: str, user_id: str, embedding: list,
):
    """Find semantically similar notes and create connections."""
    try:
        result = await db.execute(
            text("""
                SELECT id, title, 1 - (embedding <=> CAST(:emb AS vector)) AS sim
                FROM note
                WHERE user_id = :uid
                  AND id != :nid
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> CAST(:emb AS vector)) > 0.65
                ORDER BY sim DESC
                LIMIT 5
            """),
            {"emb": str(embedding), "uid": user_id, "nid": note_id},
        )
        rows = result.fetchall()
        for row in rows:
            target_id, target_title, sim = row[0], row[1], row[2]
            await _insert_connection(
                db, user_id, note_id, target_id,
                connection_type="semantic", strength=int(sim * 100),
            )
    except Exception as e:
        logger.warning(f"note_connector: semantic search failed: {e}")


async def _insert_connection(
    db,
    user_id: str,
    source_id: str,
    target_id: str,
    connection_type: str,
    strength: int,
):
    """Insert a NoteConnection row, skipping if duplicate exists."""
    # Normalize direction so we don't get A→B and B→A duplicates
    a, b = min(source_id, target_id), max(source_id, target_id)
    try:
        # Check for existing connection in either direction
        existing = await db.execute(
            text("""
                SELECT id FROM note_connection
                WHERE user_id = :uid
                  AND ((source_note_id = :a AND target_note_id = :b)
                    OR (source_note_id = :b AND target_note_id = :a))
                  AND connection_type = :ctype
                LIMIT 1
            """),
            {"uid": user_id, "a": a, "b": b, "ctype": connection_type},
        )
        if existing.fetchone():
            return  # Already exists

        await db.execute(
            text("""
                INSERT INTO note_connection (id, user_id, source_note_id, target_note_id,
                                             connection_type, strength, auto_generated,
                                             created_at, updated_at)
                VALUES (:id, :uid, :src, :tgt, :ctype, :strength, 'true', NOW(), NOW())
            """),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "src": source_id,
                "tgt": target_id,
                "ctype": connection_type,
                "strength": strength,
            },
        )
    except Exception as e:
        logger.debug(f"note_connector: insert connection failed: {e}")


async def process_note_connections_sync(
    note_id: str,
    user_id: str,
    title: str,
    content: str,
    db_sync,
):
    """Wrapper for synchronous SQLAlchemy sessions (used by tools/notes.py).

    Generates embedding and creates connections using the sync session.
    """
    try:
        full_text = f"{title}\n{content}" if title else content
        embedding = None

        # Generate embedding
        try:
            from app.services.embeddings import get_embedding
            embedding = await get_embedding(full_text)
        except Exception as e:
            logger.warning(f"note_connector_sync: embedding failed: {e}")

        # Parse [[wiki links]]
        links = re.findall(r"\[\[([^\]]+)\]\]", content)
        for link_title in links:
            link_title = link_title.strip()
            if not link_title:
                continue
            try:
                result = db_sync.execute(
                    text("""
                        SELECT id FROM note
                        WHERE user_id = :uid AND LOWER(title) = LOWER(:title) AND id != :nid
                        LIMIT 1
                    """),
                    {"uid": user_id, "title": link_title, "nid": note_id},
                )
                row = result.fetchone()
                if not row:
                    continue
                target_id = row[0]
                _insert_connection_sync(db_sync, user_id, note_id, target_id, "reference", 80)
            except Exception as e:
                logger.debug(f"note_connector_sync: ref link failed: {e}")

        # Semantic neighbors
        if embedding:
            try:
                result = db_sync.execute(
                    text("""
                        SELECT id, title, 1 - (embedding <=> CAST(:emb AS vector)) AS sim
                        FROM note
                        WHERE user_id = :uid AND id != :nid AND embedding IS NOT NULL
                          AND 1 - (embedding <=> CAST(:emb AS vector)) > 0.65
                        ORDER BY sim DESC LIMIT 5
                    """),
                    {"emb": str(embedding), "uid": user_id, "nid": note_id},
                )
                for row in result.fetchall():
                    _insert_connection_sync(
                        db_sync, user_id, note_id, row[0], "semantic", int(row[2] * 100)
                    )
            except Exception as e:
                logger.warning(f"note_connector_sync: semantic search failed: {e}")

        db_sync.commit()
    except Exception as e:
        logger.error(f"note_connector_sync: failed for note {note_id}: {e}", exc_info=True)


def _insert_connection_sync(db_sync, user_id, source_id, target_id, connection_type, strength):
    """Insert connection using sync session, skip duplicates."""
    a, b = min(source_id, target_id), max(source_id, target_id)
    try:
        existing = db_sync.execute(
            text("""
                SELECT id FROM note_connection
                WHERE user_id = :uid
                  AND ((source_note_id = :a AND target_note_id = :b)
                    OR (source_note_id = :b AND target_note_id = :a))
                  AND connection_type = :ctype
                LIMIT 1
            """),
            {"uid": user_id, "a": a, "b": b, "ctype": connection_type},
        )
        if existing.fetchone():
            return
        db_sync.execute(
            text("""
                INSERT INTO note_connection (id, user_id, source_note_id, target_note_id,
                                             connection_type, strength, auto_generated,
                                             created_at, updated_at)
                VALUES (:id, :uid, :src, :tgt, :ctype, :strength, 'true', NOW(), NOW())
            """),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "src": source_id,
                "tgt": target_id,
                "ctype": connection_type,
                "strength": strength,
            },
        )
    except Exception as e:
        logger.debug(f"note_connector_sync: insert failed: {e}")
