"""Cognitive tool dispatcher for ACS sessions.

Handles tool calls that mutate Sara's cognitive state — interest graph,
self-model, notes, journal, show-david buffer, research threads, directives,
and plan-item state transitions.

Kept out of session_manager.py so the turn loop stays readable. Dependencies
on session_manager helpers (`_save_note`, `_append_journal`, `_ensure_subfolder`,
`_handle_hitl_request`) are imported lazily inside the function body to avoid
a circular import.
"""

import json
import logging
import os
import uuid
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
OPEN_THREADS_KEY = "sara:acs:open_threads:{user_id}"


# Tool names dispatched by this module. Imported by session_manager._llm_turn
# to decide whether to route a tool call here vs. to VM shell / infra tools.
COGNITIVE_TOOL_NAMES = {
    "create_interest_node", "update_interest_node", "create_interest_edge",
    "update_self_model", "signal_engagement",
    "write_note", "write_journal", "show_david",
    "find_similar_notes", "merge_notes",
    "archive_note", "find_notes_by_topic",
    "create_topic_folder", "move_note_to_folder",
    "archive_interest",
    "request_human_input",
    "open_thread", "update_thread", "resolve_thread",
    "acknowledge_directive",
    "complete_plan_item", "block_plan_item", "defer_plan_item", "park_plan_item",
}


async def _close_redis(r):
    if hasattr(r, 'aclose'):
        await r.aclose()
    else:
        await r.close()


async def execute_cognitive_tool(
    user_id: str, session_id: str, name: str, args: dict
) -> tuple[str, Optional[dict]]:
    """Execute a cognitive tool call. Returns (result_text, stats_update_or_None)."""
    stats: dict = {}
    try:
        if name == "create_interest_node":
            from app.services.acs.interest_graph import InterestGraph
            graph = InterestGraph()
            result = await graph.add_node(
                user_id=user_id,
                label=args.get("label", ""),
                description=args.get("description", ""),
                source=args.get("source", "self_discovery"),
                fascination=args.get("fascination", 0.5),
            )
            if result and not result.get("merged"):
                stats["nodes_created"] = 1
                return f"Created interest node: {args.get('label')}", stats
            elif result and result.get("merged"):
                stats["nodes_updated"] = 1
                return f"Merged with existing node: {args.get('label')} (fascination boosted)", stats
            return "Failed to create node (empty label?)", stats

        elif name == "update_interest_node":
            from app.services.acs.interest_graph import InterestGraph
            graph = InterestGraph()
            label = args.get("label", "")
            node = await graph.find_by_label(user_id, label)
            if not node:
                return f"No interest node found with label: {label}", stats
            updates = {k: v for k, v in args.items()
                       if k in ("description", "fascination", "depth", "confidence") and v is not None}
            if updates:
                await graph.update_node(node["id"], **updates)
            await graph.engage_node(node["id"], meaningful=("depth" in updates))
            stats["nodes_updated"] = 1
            return f"Updated interest node: {label}", stats

        elif name == "create_interest_edge":
            from app.services.acs.interest_graph import InterestGraph
            graph = InterestGraph()
            src = await graph.find_by_label(user_id, args.get("source_label", ""))
            tgt = await graph.find_by_label(user_id, args.get("target_label", ""))
            if not src:
                return f"Source node not found: {args.get('source_label')}", stats
            if not tgt:
                return f"Target node not found: {args.get('target_label')}", stats
            await graph.add_edge(
                user_id=user_id,
                source_node_id=src["id"],
                target_node_id=tgt["id"],
                relationship=args.get("relationship", "relates_to"),
                description=args.get("description", ""),
                strength=args.get("strength", 0.5),
            )
            stats["edges_created"] = 1
            return f"Connected '{args.get('source_label')}' → '{args.get('target_label')}' ({args.get('relationship')})", stats

        elif name == "update_self_model":
            from app.services.acs.self_model import SelfModel
            sm = SelfModel()
            updates = args.get("updates", {})
            if not updates:
                return "No updates provided", stats
            await sm.update(user_id, updates, session_id=session_id)
            stats["self_model_updated"] = True
            return "Self-model updated", stats

        elif name == "signal_engagement":
            score = args.get("score", 0.5)
            reason = args.get("reason", "")
            stats["engagement_score"] = float(score)
            return f"Engagement recorded: {score} ({reason})", stats

        elif name == "write_note":
            from app.db.session import get_async_session_factory
            from app.services.acs import session_manager as _sm
            async_session = get_async_session_factory()
            async with async_session() as db:
                await _sm._save_note(db, user_id, session_id, {
                    "title": args.get("title", "Untitled"),
                    "content": args.get("content", ""),
                    "tags": args.get("tags", []),
                })
                await db.commit()
            stats["notes_written"] = 1
            logger.info(f"ACS note written: {args.get('title')}")
            return f"Note saved: {args.get('title')}", stats

        elif name == "write_journal":
            from app.db.session import get_async_session_factory
            from app.services.acs import session_manager as _sm
            async_session = get_async_session_factory()
            async with async_session() as db:
                await _sm._append_journal(db, user_id, args.get("content", ""))
                await db.commit()
            stats["notes_written"] = 1
            return "Journal entry added", stats

        elif name == "show_david":
            from app.db.session import get_async_session_factory
            from app.services.acs.communication_policy import queue_show_david
            async_session = get_async_session_factory()
            show_title = args.get("title", "")
            show_content = args.get("content", "")
            show_category = args.get("category", "insight")
            show_priority = args.get("priority", 0.5)
            shared_reason = args.get("shared_reason", "interesting_discovery")
            async with async_session() as db:
                try:
                    queued = await queue_show_david(
                        db,
                        user_id=user_id,
                        session_id=session_id,
                        title=show_title,
                        content=show_content,
                        category=show_category,
                        priority=float(show_priority or 0.5),
                        shared_reason=shared_reason,
                    )
                except Exception:
                    await db.rollback()
                    show_id = str(uuid.uuid4())
                    await db.execute(text("""
                        INSERT INTO acs_show_david_buffer (id, user_id, session_id, title, content, category, created_at)
                        VALUES (:id, :uid, :sid, :title, :content, :cat, NOW())
                    """), {
                        "id": show_id, "uid": user_id, "sid": session_id,
                        "title": show_title,
                        "content": show_content,
                        "cat": show_category,
                    })
                    queued = {"status": "queued", "reason": "legacy_fallback"}
                await db.commit()
            status = queued.get("status", "queued")
            reason = queued.get("reason", "queued")
            if status == "queued":
                logger.info(f"ACS show_david queued: {show_title}")
                return f"Queued for David: {show_title}", stats
            logger.info(f"ACS show_david {status}: {show_title} ({reason})")
            stats["suppressed_messages"] = stats.get("suppressed_messages", 0) + 1
            return f"Share suppressed ({reason})", stats

        elif name == "find_similar_notes":
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                note_id = args.get("note_id")
                threshold = args.get("threshold", 0.78)
                limit = args.get("limit", 10)

                if note_id:
                    result = await db.execute(text("""
                        SELECT n2.id, n2.title, LEFT(n2.content, 200) AS preview,
                               1 - (n1.embedding <=> n2.embedding) AS similarity
                        FROM note n1
                        JOIN note n2 ON n2.user_id = n1.user_id
                            AND n2.id != n1.id
                            AND n2.embedding IS NOT NULL
                            AND n2.title NOT LIKE 'Sara''s Journal%'
                        WHERE n1.id = :nid AND n1.embedding IS NOT NULL
                          AND 1 - (n1.embedding <=> n2.embedding) > :threshold
                        ORDER BY similarity DESC
                        LIMIT :lim
                    """), {"nid": note_id, "threshold": threshold, "lim": limit})
                else:
                    result = await db.execute(text("""
                        SELECT n1.id AS id1, n1.title AS title1, LEFT(n1.content, 200) AS preview1,
                               n2.id AS id2, n2.title AS title2, LEFT(n2.content, 200) AS preview2,
                               1 - (n1.embedding <=> n2.embedding) AS similarity
                        FROM note n1
                        JOIN note n2 ON n2.user_id = n1.user_id
                            AND n2.id > n1.id
                            AND n2.embedding IS NOT NULL
                            AND n2.title NOT LIKE 'Sara''s Journal%'
                        WHERE n1.user_id = :uid
                          AND n1.embedding IS NOT NULL
                          AND n1.title NOT LIKE 'Sara''s Journal%'
                          AND 1 - (n1.embedding <=> n2.embedding) > :threshold
                        ORDER BY similarity DESC
                        LIMIT :lim
                    """), {"uid": user_id, "threshold": threshold, "lim": limit})

                rows = result.fetchall()
                if note_id:
                    pairs = [
                        {"note_id": r[0], "title": r[1], "preview": r[2],
                         "similarity": round(float(r[3]), 3)}
                        for r in rows
                    ]
                    return f"Found {len(pairs)} similar notes:\n" + "\n".join(
                        f"- [{p['similarity']}] {p['title']} ({p['note_id'][:8]}): {p['preview'][:80]}"
                        for p in pairs
                    ), stats
                else:
                    pairs = [
                        {"id1": r[0], "title1": r[1], "preview1": r[2],
                         "id2": r[3], "title2": r[4], "preview2": r[5],
                         "similarity": round(float(r[6]), 3)}
                        for r in rows
                    ]
                    return f"Found {len(pairs)} similar pairs:\n" + "\n".join(
                        f"- [{p['similarity']}] \"{p['title1']}\" ({p['id1'][:8]}) ↔ \"{p['title2']}\" ({p['id2'][:8]})"
                        for p in pairs
                    ), stats

        elif name == "merge_notes":
            from app.db.session import get_async_session_factory
            from app.services.note_connector import process_note_connections
            async_session = get_async_session_factory()
            target_id = args.get("target_note_id", "")
            source_id = args.get("source_note_id", "")
            merged_title = args.get("merged_title")
            merged_content = args.get("merged_content", "")

            if not target_id or not source_id or not merged_content:
                return "merge_notes requires target_note_id, source_note_id, and merged_content", stats

            async with async_session() as db:
                for nid, label in [(target_id, "target"), (source_id, "source")]:
                    r = await db.execute(text(
                        "SELECT id FROM note WHERE id = :nid AND user_id = :uid"
                    ), {"nid": nid, "uid": user_id})
                    if not r.fetchone():
                        return f"merge_notes: {label} note {nid} not found", stats

                await db.execute(text("""
                    UPDATE note_connection
                    SET source_note_id = :tid, updated_at = NOW()
                    WHERE source_note_id = :sid AND user_id = :uid
                      AND target_note_id != :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM note_connection nc2
                          WHERE nc2.source_note_id = :tid
                            AND nc2.target_note_id = note_connection.target_note_id
                            AND nc2.connection_type = note_connection.connection_type
                      )
                """), {"tid": target_id, "sid": source_id, "uid": user_id})

                await db.execute(text("""
                    UPDATE note_connection
                    SET target_note_id = :tid, updated_at = NOW()
                    WHERE target_note_id = :sid AND user_id = :uid
                      AND source_note_id != :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM note_connection nc2
                          WHERE nc2.target_note_id = :tid
                            AND nc2.source_note_id = note_connection.source_note_id
                            AND nc2.connection_type = note_connection.connection_type
                      )
                """), {"tid": target_id, "sid": source_id, "uid": user_id})

                await db.execute(text(
                    "DELETE FROM note WHERE id = :sid AND user_id = :uid"
                ), {"sid": source_id, "uid": user_id})

                update_params = {"content": merged_content, "nid": target_id}
                if merged_title:
                    await db.execute(text(
                        "UPDATE note SET title = :title, content = :content, updated_at = NOW() WHERE id = :nid"
                    ), {**update_params, "title": merged_title})
                else:
                    await db.execute(text(
                        "UPDATE note SET content = :content, updated_at = NOW() WHERE id = :nid"
                    ), update_params)

                await db.commit()

                final_title = merged_title or target_id
                r = await db.execute(text("SELECT title FROM note WHERE id = :nid"), {"nid": target_id})
                row = r.fetchone()
                if row:
                    final_title = row[0]

            async with async_session() as db:
                await process_note_connections(target_id, user_id, final_title, merged_content, db)
                await db.commit()

            logger.info(f"ACS merged note {source_id[:8]} into {target_id[:8]}")
            return f"Merged notes. Source {source_id[:8]} deleted, target {target_id[:8]} updated.", stats

        elif name == "archive_note":
            from app.db.session import get_async_session_factory
            from app.services.acs import session_manager as _sm
            async_session = get_async_session_factory()
            note_id = args.get("note_id", "")
            reason = args.get("reason", "")
            if not note_id or not reason:
                return "archive_note requires note_id and reason", stats

            archived_folder_id = await _sm._ensure_subfolder(user_id, "Archived")
            async with async_session() as db:
                r = await db.execute(text(
                    "SELECT id, title, content FROM note WHERE id = :nid AND user_id = :uid"
                ), {"nid": note_id, "uid": user_id})
                row = r.fetchone()
                if not row:
                    return f"Note {note_id} not found", stats

                title = row[1]
                content = row[2] or ""
                archived_content = f"[ARCHIVED: {reason}]\n\n{content}"
                await db.execute(text("""
                    UPDATE note SET folder_id = :fid, content = :content, updated_at = NOW()
                    WHERE id = :nid
                """), {"fid": archived_folder_id, "content": archived_content, "nid": note_id})
                await db.commit()

            logger.info(f"ACS archived note: {title} ({note_id[:8]})")
            return f"Archived note '{title}' — reason: {reason}", stats

        elif name == "find_notes_by_topic":
            from app.db.session import get_async_session_factory
            from app.services.acs import state_machine
            async_session = get_async_session_factory()
            query = args.get("query", "")
            limit = args.get("limit", 10)
            if not query:
                return "find_notes_by_topic requires a query", stats

            try:
                from app.services.embeddings import get_embedding
                query_embedding = await get_embedding(query)
            except Exception as e:
                return f"Embedding generation failed: {e}", stats

            root_id = await state_machine.get_notes_folder_id(user_id)
            if not root_id:
                return "Sara's Notes folder not found", stats

            async with async_session() as db:
                result = await db.execute(text("""
                    WITH sara_folders AS (
                        SELECT id, name FROM folder
                        WHERE user_id = :uid AND (id = :root OR parent_id = :root)
                    )
                    SELECT n.id, n.title, LEFT(n.content, 200) AS preview,
                           f.name AS folder_name,
                           1 - (n.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM note n
                    JOIN sara_folders f ON n.folder_id = f.id
                    WHERE n.user_id = :uid
                      AND n.embedding IS NOT NULL
                      AND n.title NOT LIKE 'Sara''s Journal%'
                    ORDER BY similarity DESC
                    LIMIT :lim
                """), {
                    "uid": user_id, "root": root_id,
                    "emb": str(query_embedding), "lim": limit,
                })
                rows = result.fetchall()

            if not rows:
                return f"No notes found matching '{query}'", stats

            results = []
            for r in rows:
                folder = r[3] if r[3] != "Sara's Notes" else "(root)"
                results.append(
                    f"- [{round(float(r[4]), 3)}] {r[1]} ({r[0][:8]}) [{folder}]: {(r[2] or '')[:80]}"
                )
            return f"Found {len(rows)} notes for '{query}':\n" + "\n".join(results), stats

        elif name == "create_topic_folder":
            from app.services.acs import session_manager as _sm
            folder_name = args.get("name", "")
            if not folder_name:
                return "create_topic_folder requires a name", stats
            folder_id = await _sm._ensure_subfolder(user_id, folder_name)
            return f"Topic folder '{folder_name}' ready (id: {folder_id[:8]})", stats

        elif name == "move_note_to_folder":
            from app.db.session import get_async_session_factory
            from app.services.acs import session_manager as _sm
            async_session = get_async_session_factory()
            note_id = args.get("note_id", "")
            folder_name = args.get("folder_name", "")
            if not note_id or not folder_name:
                return "move_note_to_folder requires note_id and folder_name", stats

            target_folder_id = await _sm._ensure_subfolder(user_id, folder_name)
            async with async_session() as db:
                r = await db.execute(text(
                    "SELECT title FROM note WHERE id = :nid AND user_id = :uid"
                ), {"nid": note_id, "uid": user_id})
                row = r.fetchone()
                if not row:
                    return f"Note {note_id} not found", stats

                await db.execute(text(
                    "UPDATE note SET folder_id = :fid, updated_at = NOW() WHERE id = :nid"
                ), {"fid": target_folder_id, "nid": note_id})
                await db.commit()

            return f"Moved '{row[0]}' to {folder_name}/", stats

        elif name == "archive_interest":
            from app.services.acs.interest_graph import InterestGraph
            from app.services.acs.communication_policy import queue_show_david
            graph = InterestGraph()
            label = args.get("label", "")
            reason = args.get("reason", "")
            if not label or not reason:
                return "archive_interest requires label and reason", stats

            node = await graph.find_by_label(user_id, label)
            if not node:
                return f"No active interest node found with label: {label}", stats

            await graph.archive_node(node["id"])
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_interest_node
                    SET cooldown_until = NOW() + INTERVAL '7 days',
                        revisit_count = COALESCE(revisit_count, 0) + 1
                    WHERE id = :id
                """), {"id": node["id"]})
                await db.commit()

            async with async_session() as db:
                try:
                    await queue_show_david(
                        db,
                        user_id=user_id,
                        session_id=session_id,
                        title=f"Archived interest: {label}",
                        content=f"I've decided to archive my interest in '{label}'. {reason}",
                        category="insight",
                        priority=0.7,
                        shared_reason="needs_attention",
                    )
                except Exception:
                    await db.rollback()
                await db.commit()

            logger.info(f"ACS archived interest node: {label}")
            return f"Archived interest '{label}' — reason recorded and David notified.", stats

        elif name == "request_human_input":
            from app.services.acs import session_manager as _sm
            result_text = await _sm._handle_hitl_request(
                user_id=user_id,
                session_id=session_id,
                question=args.get("question", ""),
                context=args.get("context", ""),
                alternatives=args.get("alternatives", ""),
            )
            return result_text, stats

        elif name == "open_thread":
            thread_id = str(uuid.uuid4())[:8]
            thread = {
                "id": thread_id,
                "title": args.get("title", ""),
                "description": args.get("description", ""),
                "priority": args.get("priority", "medium"),
                "status": "active",
                "progress": [],
                "opened_at": local_now().isoformat(),
                "updated_at": local_now().isoformat(),
                "source_session": session_id,
            }
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                await r.hset(OPEN_THREADS_KEY.format(user_id=user_id), thread_id, json.dumps(thread))
            finally:
                await _close_redis(r)
            logger.info(f"ACS thread opened: {thread_id} — {args.get('title')}")
            return f"Thread opened: {thread_id} — {args.get('title')}", stats

        elif name == "update_thread":
            thread_id = args.get("thread_id", "")
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                raw = await r.hget(OPEN_THREADS_KEY.format(user_id=user_id), thread_id)
                if not raw:
                    return f"Thread not found: {thread_id}", stats
                thread = json.loads(raw)
                if args.get("progress"):
                    thread.setdefault("progress", []).append({
                        "text": args["progress"],
                        "next_steps": args.get("next_steps", ""),
                        "session": session_id,
                        "at": local_now().isoformat(),
                    })
                if args.get("priority"):
                    thread["priority"] = args["priority"]
                if args.get("next_steps"):
                    thread["next_steps"] = args["next_steps"]
                thread["updated_at"] = local_now().isoformat()
                await r.hset(OPEN_THREADS_KEY.format(user_id=user_id), thread_id, json.dumps(thread))
            finally:
                await _close_redis(r)
            logger.info(f"ACS thread updated: {thread_id}")
            return f"Thread {thread_id} updated", stats

        elif name == "resolve_thread":
            thread_id = args.get("thread_id", "")
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                raw = await r.hget(OPEN_THREADS_KEY.format(user_id=user_id), thread_id)
                if not raw:
                    return f"Thread not found: {thread_id}", stats
                thread = json.loads(raw)
                thread["status"] = "resolved"
                thread["resolution"] = args.get("resolution", "completed")
                thread["resolution_summary"] = args.get("summary", "")
                thread["resolved_at"] = local_now().isoformat()
                await r.hset(OPEN_THREADS_KEY.format(user_id=user_id), thread_id, json.dumps(thread))
            finally:
                await _close_redis(r)
            logger.info(f"ACS thread resolved: {thread_id} ({args.get('resolution')})")
            return f"Thread {thread_id} resolved: {args.get('resolution')}", stats

        elif name == "acknowledge_directive":
            directive_id = args.get("directive_id", "")
            response_text = args.get("response", "")
            if not directive_id:
                return "Error: directive_id is required", stats
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                result = await db.execute(text("""
                    UPDATE acs_directive
                    SET status = 'acknowledged', acknowledged_at = NOW(),
                        response = :response
                    WHERE id = :id AND user_id = :uid AND status = 'pending'
                    RETURNING directive_type, content
                """), {"id": directive_id, "uid": user_id, "response": response_text or None})
                row = result.fetchone()
                if not row:
                    return f"Directive not found or already acknowledged: {directive_id[:8]}", stats
                await db.commit()
            logger.info(f"ACS directive acknowledged: {directive_id[:8]} [{row[0]}]")
            return f"Acknowledged [{row[0]}] directive: {row[1][:80]}", stats

        elif name == "complete_plan_item":
            result_summary = args.get("result_summary", "")
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                try:
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'completed',
                            result_summary = :summary,
                            completed_at = NOW(),
                            last_meaningful_progress_at = NOW(),
                            closure_reason = 'completed',
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title
                    """), {"summary": result_summary[:5000], "sid": session_id})
                except Exception:
                    await db.rollback()
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'completed',
                            result_summary = :summary,
                            completed_at = NOW(),
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title
                    """), {"summary": result_summary[:5000], "sid": session_id})
                updated = row.fetchone()
                if updated:
                    await db.commit()
                    return f"Plan item '{updated[1]}' marked as completed.", {"plan_item_completed": 1}
                else:
                    await db.commit()
                    return "No active plan item found for this session.", {}

        elif name == "block_plan_item":
            reason = args.get("reason", "")
            progress = args.get("progress_so_far", "")
            from app.db.session import get_async_session_factory
            from app.services.acs.communication_policy import queue_show_david
            async_session = get_async_session_factory()
            async with async_session() as db:
                try:
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'blocked',
                            blocker_reason = :reason,
                            result_summary = :progress,
                            last_meaningful_progress_at = CASE WHEN :progress != '' THEN NOW() ELSE last_meaningful_progress_at END,
                            closure_reason = 'blocked',
                            reopen_after = NOW() + INTERVAL '12 hours',
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title, success_criteria
                    """), {"reason": reason[:2000], "progress": progress[:5000], "sid": session_id})
                except Exception:
                    await db.rollback()
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'blocked',
                            blocker_reason = :reason,
                            result_summary = :progress,
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title, success_criteria
                    """), {"reason": reason[:2000], "progress": progress[:5000], "sid": session_id})
                updated = row.fetchone()
                if updated:
                    try:
                        await queue_show_david(
                            db,
                            user_id=user_id,
                            session_id=session_id,
                            title=f"Blocked: {updated[1]}",
                            content=f"I'm blocked on '{updated[1]}'. Reason: {reason[:500]}. Progress so far: {progress[:1000]}",
                            category="question",
                            priority=0.9,
                            shared_reason="blocked",
                        )
                    except Exception:
                        await db.rollback()
                    await db.commit()
                    return f"Plan item '{updated[1]}' marked as blocked: {reason[:200]}", {"plan_item_blocked": 1}
                else:
                    await db.commit()
                    return "No active plan item found for this session.", {}

        elif name == "defer_plan_item":
            reason = args.get("reason", "")
            progress = args.get("progress_so_far", "")
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                try:
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'deferred',
                            blocker_reason = :reason,
                            result_summary = :progress,
                            last_meaningful_progress_at = CASE WHEN :progress != '' THEN NOW() ELSE last_meaningful_progress_at END,
                            closure_reason = 'deferred',
                            reopen_after = NOW() + INTERVAL '18 hours',
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title
                    """), {"reason": reason[:2000], "progress": progress[:5000], "sid": session_id})
                except Exception:
                    await db.rollback()
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'deferred',
                            blocker_reason = :reason,
                            result_summary = :progress,
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title
                    """), {"reason": reason[:2000], "progress": progress[:5000], "sid": session_id})
                updated = row.fetchone()
                if updated:
                    await db.commit()
                    return f"Plan item '{updated[1]}' deferred: {reason[:200]}", {"plan_item_deferred": 1}
                else:
                    await db.commit()
                    return "No active plan item found for this session.", {}

        elif name == "park_plan_item":
            reason = args.get("reason", "")
            progress = args.get("progress_so_far", "")
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                try:
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'parked',
                            blocker_reason = :reason,
                            result_summary = :progress,
                            last_meaningful_progress_at = CASE WHEN :progress != '' THEN NOW() ELSE last_meaningful_progress_at END,
                            closure_reason = 'parked',
                            reopen_after = NOW() + INTERVAL '3 days',
                            parked_at = NOW(),
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title
                    """), {"reason": reason[:2000], "progress": progress[:5000], "sid": session_id})
                except Exception:
                    await db.rollback()
                    row = await db.execute(text("""
                        UPDATE acs_plan_item
                        SET status = 'deferred',
                            blocker_reason = :reason,
                            result_summary = :progress,
                            assigned_session_id = NULL,
                            updated_at = NOW()
                        WHERE assigned_session_id = :sid AND status = 'in_progress'
                        RETURNING id, title
                    """), {"reason": reason[:2000], "progress": progress[:5000], "sid": session_id})
                updated = row.fetchone()
                if updated:
                    await db.commit()
                    return f"Plan item '{updated[1]}' parked: {reason[:200]}", {"plan_item_parked": 1}
                await db.commit()
                return "No active plan item found for this session.", {}

        return f"Unknown cognitive tool: {name}", stats

    except Exception as e:
        logger.warning(f"Cognitive tool {name} failed: {e}")
        return f"Error: {e}", stats
