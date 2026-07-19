"""
Autonomy system Celery tasks (Phase 4).

Handles:
- Heartbeat agent (HEARTBEAT.md rule evaluation every 30 min)
- Proactive checks (consider if action is needed)
- Anticipation (morning/evening preparation)
- Memory consolidation (nightly processing)
- Learning digest (weekly summary)
- Idle processing (productive quiet time)
"""

import logging
import asyncio
from datetime import datetime, timedelta


def _run_async(coro):
    """Run an async coroutine from a sync Celery task.

    Always uses asyncio.run() to get a fresh event loop, avoiding the
    'Event loop is closed' / 'Future attached to a different loop' errors
    that plague get_event_loop().run_until_complete() in forked workers.
    """
    return asyncio.run(coro)

from app.celery_app import celery_app
from sqlalchemy import text
from app.core.timezone import USER_TIMEZONE, now as local_now, to_naive_local, to_naive_utc

logger = logging.getLogger(__name__)

# Default user ID for Sara
DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"



# unified_heartbeat and unified_agent tasks removed — replaced by event-driven
# deliberation system (salience subscriber + periodic deliberation fallback)



# ─── Standing Order Time Check ─────────────────────────────────────

@celery_app.task(
    name="app.tasks.autonomy.standing_order_time_check",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def standing_order_time_check(self):
    """
    Lightweight periodic evaluator for time-based standing orders.

    This keeps critical time automations (e.g., "all lights off at 11 PM")
    running even when unified_agent is not scheduled.
    """
    try:
        result = _run_async(
            _standing_order_time_check_async()
        )
        return result
    except Exception as e:
        logger.error(f"Standing order time check failed: {e}")
        raise self.retry(countdown=30, exc=e)


async def _standing_order_time_check_async():
    """Async implementation for standing order time checks."""
    from app.db.session import SessionLocal
    from app.services.standing_order_service import standing_order_service

    now = datetime.now(USER_TIMEZONE)
    sync_db = SessionLocal()
    try:
        results = await standing_order_service.evaluate_time_orders(sync_db, now)
        return {
            "status": "ok",
            "checked_at": now.isoformat(),
            "executed": len(results),
        }
    finally:
        sync_db.close()


# ─── Proxmox Container Cleanup ──────────────────────────────────────

@celery_app.task(
    name="app.tasks.autonomy.cleanup_stale_containers",
    bind=True,
    queue="maintenance",
    max_retries=1,
)
def cleanup_stale_containers(self):
    """Destroy ephemeral Proxmox containers idle for >24 hours."""
    try:
        result = _run_async(
            _cleanup_stale_containers_async()
        )
        return result
    except Exception as e:
        logger.error(f"Container cleanup failed: {e}")
        raise self.retry(countdown=60, exc=e)


async def _cleanup_stale_containers_async():
    from app.services.container_provisioner import ContainerProvisioner
    provisioner = ContainerProvisioner()
    destroyed = await provisioner.cleanup_stale(max_idle_hours=24)
    return {"status": "ok", "destroyed": destroyed}


# ─── Mission Worker (Phase 2 — Cortana Evolution) ───────────────────


@celery_app.task(
    name="app.tasks.autonomy.mission_worker",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def mission_worker(self):
    """
    Advance runnable missions every 30 seconds.
    Behind AUTONOMY_MISSIONS_ENABLED flag.
    """
    try:
        from app.core.config import settings
        if not getattr(settings, 'autonomy_missions_enabled', False):
            return {"skipped": "missions_disabled"}
    except Exception:
        return {"skipped": "config_unavailable"}

    try:
        result = _run_async(
            _mission_worker_async()
        )
        if result.get("advanced", 0) > 0:
            logger.info(f"Mission worker: {result}")
        return result
    except Exception as e:
        logger.error(f"Mission worker failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _mission_worker_async():
    """Async implementation of mission worker."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.autonomy.mission_engine import mission_engine
    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()
    if not await coordinator.acquire_exclusive("mission-worker", "mission_processing"):
        return {"skipped": "exclusive_lock_busy"}

    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            runnable = await mission_engine.get_runnable_missions(db)
            advanced = 0
            for mission_id in runnable:
                result = await mission_engine.advance_mission(db, mission_id)
                await db.commit()
                if result.get("status") in ("step_completed", "completed"):
                    advanced += 1
            return {"runnable": len(runnable), "advanced": advanced}
    finally:
        await coordinator.release_exclusive("mission_processing", "mission-worker")


@celery_app.task(
    name="app.tasks.autonomy.morning_anticipation",
    bind=True,
    queue="cognitive"
)
def morning_anticipation(self):
    """
    Morning anticipation - prepare for the day ahead.

    Runs at 7 AM daily.
    """
    logger.info("Starting morning anticipation")

    try:
        result = _run_async(
            _anticipation_async("morning")
        )
        logger.info(f"Morning anticipation complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Morning anticipation failed: {e}")
        raise


@celery_app.task(
    name="app.tasks.autonomy.evening_anticipation",
    bind=True,
    queue="cognitive"
)
def evening_anticipation(self):
    """
    Evening anticipation - prepare for tomorrow.

    Runs at 9 PM daily.
    """
    logger.info("Starting evening anticipation")

    try:
        result = _run_async(
            _anticipation_async("evening")
        )
        logger.info(f"Evening anticipation complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Evening anticipation failed: {e}")
        raise


async def _anticipation_async(time_of_day: str):
    """Async implementation of anticipation."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.autonomy.anticipation import get_anticipation_service
    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()
    task_name = f"{time_of_day}-anticipation"

    if not await coordinator.acquire_exclusive(task_name, "heavy_llm"):
        return {"skipped": "exclusive_group_busy"}

    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            service = await get_anticipation_service(db)

            if time_of_day == "morning":
                preparations = await service.run_morning_anticipation()
            else:
                preparations = await service.run_evening_anticipation()

            prep_types = [p.prep_type.value for p in preparations]

            # Log to agent_run_log so the unified heartbeat knows what was prepared
            try:
                import json
                await db.execute(text("""
                    INSERT INTO agent_run_log
                    (user_id, run_at, context_summary, actions_taken, handoff_note, source)
                    VALUES
                    (:user_id, NOW(), :ctx, CAST(:actions AS jsonb),
                     :note, :source)
                """), {
                    "user_id": DEFAULT_USER_ID,
                    "ctx": f"{time_of_day} anticipation: {len(preparations)} preparations ({', '.join(prep_types)})",
                    "actions": json.dumps([{"prep_type": pt} for pt in prep_types]),
                    "note": f"{time_of_day.title()} anticipation ran — prepared {len(preparations)} items. Types: {', '.join(prep_types)}",
                    "source": f"{time_of_day}_anticipation",
                })
                await db.commit()
            except Exception as log_err:
                logger.warning(f"Failed to log anticipation to agent_run_log: {log_err}")

            # Write anticipation handoff to unified context snapshot
            try:
                from app.services.context_writer import update_fields, append_change
                note = f"{time_of_day.title()} anticipation: prepared {', '.join(prep_types)}" if prep_types else None
                await update_fields(
                    DEFAULT_USER_ID, source=f"{time_of_day}_anticipation",
                    last_anticipation_note=note,
                )
                if prep_types:
                    await append_change(
                        DEFAULT_USER_ID,
                        f"{time_of_day.title()} prep done: {', '.join(prep_types)}"
                    )
            except Exception:
                pass

            return {
                "timestamp": local_now().isoformat(),
                "time_of_day": time_of_day,
                "preparations": len(preparations),
                "prep_types": prep_types,
            }
    finally:
        await coordinator.release_exclusive("heavy_llm", task_name)


@celery_app.task(
    name="app.tasks.autonomy.nightly_memory_consolidation",
    bind=True,
    queue="maintenance"
)
def nightly_memory_consolidation(self):
    """
    Nightly memory consolidation - process the day's experiences.

    Runs at 3 AM daily.
    """
    logger.info("Starting nightly memory consolidation")

    try:
        result = _run_async(
            _memory_consolidation_async()
        )
        logger.info(f"Memory consolidation complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Memory consolidation failed: {e}")
        raise


def _rescore_importance_sync(max_batches: int = 50) -> dict:
    """Bulk-rescore episode importance using the synchronous ImportanceScorer.

    Runs in a worker thread via asyncio.to_thread — the scorer uses a sync
    Session internally, so we open one from SessionLocal here. Driving the
    service's async API from inside the thread via asyncio.run() keeps the
    scoring logic in one place instead of duplicating it inline.
    """
    import asyncio as _asyncio
    try:
        from app.db.session import SessionLocal
        from app.services.importance_scorer import ImportanceScorer
    except Exception as exc:  # pragma: no cover
        return {"skipped": f"import_error:{exc}"}

    try:
        with SessionLocal() as db:
            scorer = ImportanceScorer(db)
            return _asyncio.run(scorer.rescore_all_episodes(max_batches=max_batches))
    except Exception as exc:
        logger.warning(f"Importance rescoring failed: {exc}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


def _consolidate_ratings_sync() -> dict:
    """Run rating consolidation (Redis→DB, Wilson boosts, Thompson exploration).

    Same thread-pool pattern as _rescore_importance_sync — the consolidation
    job takes a sync Session even though its orchestration is async.
    """
    import asyncio as _asyncio
    try:
        from app.db.session import SessionLocal
        from app.services.rating_consolidation_job import run_rating_consolidation_job
    except Exception as exc:  # pragma: no cover
        return {"skipped": f"import_error:{exc}"}

    try:
        with SessionLocal() as db:
            return _asyncio.run(run_rating_consolidation_job(db))
    except Exception as exc:
        logger.warning(f"Rating consolidation failed: {exc}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _memory_consolidation_async():
    """Async implementation of memory consolidation."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()

    if not await coordinator.acquire_exclusive("nightly-consolidation", "reflection"):
        return {"skipped": "exclusive_group_busy"}

    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            today_start = local_now().replace(hour=0, minute=0, second=0)

            # Count today's episodes
            episode_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM episode
                    WHERE created_at >= :today
                """),
                {"today": today_start}
            )
            episode_count = episode_result.fetchone()[0] or 0

            # Mark low-importance episodes for decay (simplified)
            decay_result = await db.execute(
                text("""
                    UPDATE episode
                    SET importance = importance * 0.95
                    WHERE created_at < :today
                    AND importance < 0.3
                """),
                {"today": today_start}
            )
            decayed = decay_result.rowcount

            # Clean up old working memory
            cleanup_result = await db.execute(
                text("""
                    DELETE FROM working_memory_actions
                    WHERE status = 'completed'
                    AND completed_at < NOW() - INTERVAL '7 days'
                """)
            )
            cleaned = cleanup_result.rowcount

            await db.commit()

        # Rescore importance for all episodes (sync scorer in thread pool).
        # This updates base_importance/importance/importance_last_updated so
        # retrieval ranking reflects recency+frequency+rating signals, not
        # just the value written at ingestion time.
        rescore_stats = await asyncio.to_thread(_rescore_importance_sync, 50)

        # Consolidate ratings from Redis into DB and recompute rating_boost /
        # exploration_bonus. Without this, the retrieval composite score's
        # rating and exploration terms stay at 0 forever.
        rating_stats = await asyncio.to_thread(_consolidate_ratings_sync)

        # H4 (Brain Alignment): forgetting. Compress old, low-importance,
        # never-retrieved episodes into semantic summaries + PKG facts.
        # Deletion is gated behind memory.forgetting_delete_enabled (dry-run
        # until the golden retrieval set proves recall holds).
        try:
            from app.services.memory_compaction import compact_old_memories
            compaction_stats = await compact_old_memories()
        except Exception as e:
            logger.warning(f"Memory compaction failed: {e}")
            compaction_stats = {"error": str(e)}

        # H7 (Brain Alignment): the persona evolves. Revive the reflection loop
        # and relationship arc, graduate well-evidenced PKG facts into soul
        # proposals, and auto-approve stale style proposals.
        persona_stats = {}
        try:
            from app.services.persona_evolution import (
                run_reflection_and_relationship, graduate_facts_to_proposals,
                auto_approve_style_proposals,
            )
            persona_stats["reflection"] = await run_reflection_and_relationship()
            persona_stats["graduation"] = await graduate_facts_to_proposals()
            from app.db.session import SessionLocal as _SL
            with _SL() as _sdb:
                persona_stats["style_auto_approved"] = auto_approve_style_proposals(_sdb)
        except Exception as e:
            logger.warning(f"Persona evolution failed: {e}")
            persona_stats["error"] = str(e)

        return {
            "timestamp": local_now().isoformat(),
            "episodes_today": episode_count,
            "episodes_decayed": decayed,
            "actions_cleaned": cleaned,
            "importance_rescoring": rescore_stats,
            "rating_consolidation": rating_stats,
            "memory_compaction": compaction_stats,
            "persona_evolution": persona_stats,
        }
    finally:
        await coordinator.release_exclusive("reflection", "nightly-consolidation")


@celery_app.task(
    name="app.tasks.autonomy.weekly_learning_digest",
    bind=True,
    queue="reflection"
)
def weekly_learning_digest(self):
    """
    Weekly learning digest - comprehensive self-assessment.

    Runs Sunday at 10 AM.
    """
    logger.info("Starting weekly learning digest")

    try:
        result = _run_async(
            _learning_digest_async()
        )
        # H7.6 (Brain Alignment): Sara's weekly self-narrative — what she learned,
        # what she changed about herself, what she got wrong.
        try:
            from app.services.persona_evolution import write_self_narrative
            _run_async(write_self_narrative())
        except Exception as e:
            logger.warning(f"Weekly self-narrative failed: {e}")
        logger.info(f"Learning digest complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Learning digest failed: {e}")
        raise


async def _learning_digest_async():
    """
    Async implementation of learning digest.

    PHASE 4: Now invokes Sara to generate a thoughtful weekly digest
    reflecting on growth, learnings, and intentions.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.autonomy.sara_invocation import get_sara_invocation_service
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        week_start = local_now() - timedelta(days=7)

        # Count interactions
        interaction_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM episode
                WHERE created_at >= :week_start
            """),
            {"week_start": week_start}
        )
        interaction_count = interaction_result.fetchone()[0] or 0

        # Count actions and outcomes
        action_result = await db.execute(
            text("""
                SELECT outcome_status, COUNT(*)
                FROM action_log
                WHERE created_at >= :week_start
                GROUP BY outcome_status
            """),
            {"week_start": week_start}
        )
        action_stats = dict(action_result.fetchall())

        # Count proposals
        proposal_result = await db.execute(
            text("""
                SELECT status, COUNT(*)
                FROM prompt_proposals
                WHERE created_at >= :week_start
                GROUP BY status
            """),
            {"week_start": week_start}
        )
        proposal_stats = dict(proposal_result.fetchall())

        # Build data summary
        raw_data = {
            "timestamp": local_now().isoformat(),
            "week_start": week_start.isoformat(),
            "interactions": interaction_count,
            "action_outcomes": action_stats,
            "proposals": proposal_stats,
        }

        # Invoke Sara to generate a thoughtful digest
        try:
            sara = await get_sara_invocation_service(db)

            context_summary = f"""This week's data:
- Total interactions with David: {interaction_count}
- Actions taken: {action_stats}
- Proposals: {proposal_stats}"""

            generation_result = await sara.invoke_for_generation(
                context=context_summary,
                prompt="""Generate a thoughtful weekly digest reflecting on your week.
Include:
1. What went well this week
2. Areas where you struggled or could improve
3. Notable interactions or learnings
4. Intentions for next week

Write in first person as Sara. Be genuine and reflective.""",
                max_tokens=800
            )

            digest_content = generation_result.content

            logger.info(f"Weekly digest generated: {interaction_count} interactions")

            return {
                "digest": digest_content,
                "raw_data": raw_data,
                "generated_at": local_now().isoformat(),
                "invocation_id": generation_result.invocation_id
            }

        except Exception as e:
            logger.warning(f"Sara digest generation failed, returning raw data: {e}")
            return raw_data


@celery_app.task(
    name="app.tasks.autonomy.pkg_deep_extract",
    bind=True,
    queue="cognitive",
    max_retries=1
)
def pkg_deep_extract(self, user_id: str = None, since_hours: int = 6):
    """
    PKG deep extraction — mines recent conversations for personal knowledge.

    Runs at midday (12 PM) and evening (6 PM) to catch facts between
    the nightly dream cycle without adding latency to the chat path.
    """
    user_id = user_id or DEFAULT_USER_ID
    logger.info(f"Starting PKG deep extraction (last {since_hours}h)")

    try:
        result = _run_async(
            _pkg_deep_extract_async(user_id, since_hours)
        )
        logger.info(f"PKG deep extraction complete: {result}")
        return result
    except Exception as e:
        logger.error(f"PKG deep extraction failed: {e}")
        raise self.retry(countdown=120, exc=e)


async def _pkg_deep_extract_async(user_id: str, since_hours: int):
    """Async implementation of PKG deep extraction."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.pkg_extractor import pkg_extractor
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        # episode.created_at is a naive `timestamp` column storing UTC; bind naive UTC.
        since = to_naive_utc(local_now() - timedelta(hours=since_hours))

        # Load recent episodes (regular chat)
        result = await db.execute(text("""
            SELECT role, content FROM episode
            WHERE user_id = :user_id
            AND created_at >= :since
            AND role IN ('user', 'assistant')
            AND (source IS NULL OR source != 'learning_chat')
            ORDER BY created_at ASC
        """), {"user_id": user_id, "since": since})
        rows = result.fetchall()

        # Also load learning_chat episodes
        learning_result = await db.execute(text("""
            SELECT role, content, meta->>'topic_id' as topic_id
            FROM episode
            WHERE user_id = :user_id
            AND created_at >= :since
            AND role IN ('user', 'assistant')
            AND source = 'learning_chat'
            ORDER BY created_at ASC
        """), {"user_id": user_id, "since": since})
        learning_rows = learning_result.fetchall()

        # Skip if fewer than 3 user messages across both sources
        user_messages = [r for r in rows if r.role == "user"]
        learning_user_messages = [r for r in learning_rows if r.role == "user"]
        total_user_messages = len(user_messages) + len(learning_user_messages)

        if total_user_messages < 3:
            logger.info(f"PKG: Skipping extraction — only {total_user_messages} user messages in window")
            return {
                "timestamp": local_now().isoformat(),
                "skipped": True,
                "reason": f"only {total_user_messages} user messages",
            }

        # Build conversation text
        conversation_text = "\n".join(
            f"{r.role.upper()}: {r.content}" for r in rows if r.content
        )

        # Append learning session conversations
        if learning_rows:
            conversation_text += "\n\n[Learning Session]\n"
            conversation_text += "\n".join(
                f"{r.role.upper()}: {r.content}" for r in learning_rows if r.content
            )

        # Cap at 15,000 chars
        if len(conversation_text) > 15000:
            conversation_text = conversation_text[:15000] + "\n...(truncated)"

        extraction = await pkg_extractor.deep_extract(conversation_text, user_id)

        stats = extraction.get("stats", {})
        logger.info(
            f"PKG deep extraction: {stats.get('total', 0)} facts found, "
            f"{len(extraction.get('contradictions', []))} contradictions, "
            f"avg confidence {stats.get('avg_confidence', 0):.2f}"
        )

        return {
            "timestamp": local_now().isoformat(),
            "since_hours": since_hours,
            "episodes_processed": len(rows) + len(learning_rows),
            "user_messages": total_user_messages,
            "learning_messages": len(learning_user_messages),
            "facts_extracted": stats.get("total", 0),
            "by_type": stats.get("by_type", {}),
            "contradictions": len(extraction.get("contradictions", [])),
        }


@celery_app.task(
    name="app.tasks.autonomy.learning_pkg_sync",
    bind=True,
    queue="cognitive",
    max_retries=1
)
def learning_pkg_sync(self, user_id: str, topic_id: str):
    """
    Sync a learning topic's knowledge into the Personal Knowledge Graph.

    Creates/updates PKG_Interest, PKG_Goal, and PKG_Fact nodes based on
    the learning topic's mastery level and recent session content.
    """
    logger.info(f"Starting learning PKG sync for topic {topic_id}")

    try:
        result = _run_async(
            _learning_pkg_sync_async(user_id, topic_id)
        )
        logger.info(f"Learning PKG sync complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Learning PKG sync failed: {e}")
        raise self.retry(countdown=60, exc=e)


async def _learning_pkg_sync_async(user_id: str, topic_id: str):
    """Async implementation of learning PKG sync."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os
    import re

    from app.services.personal_knowledge_graph import personal_kg
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Load the topic
        topic_result = await db.execute(text("""
            SELECT title, description, mastery_level, status
            FROM learning_topic
            WHERE id = :topic_id AND user_id = :user_id
        """), {"topic_id": topic_id, "user_id": user_id})
        topic = topic_result.fetchone()

        if not topic:
            return {"skipped": True, "reason": "topic not found"}

        title = topic.title
        mastery = topic.mastery_level or 0.0
        status = topic.status or "active"

        # Compute depth label from mastery
        if mastery < 0.3:
            depth = "surface"
        elif mastery < 0.7:
            depth = "moderate"
        else:
            depth = "deep"

        # Slug for dedup key
        title_slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
        nodes_created = 0

        # 1. Upsert PKG_Interest
        try:
            pkg_id = personal_kg.upsert_fact(
                fact_type="Interest",
                properties={
                    "topic": title,
                    "depth": depth,
                    "category": "learning",
                    "description": topic.description or f"Studying {title}",
                },
                confidence=0.85,
                source="learning_extraction",
                dedup_key=f"interest:{title_slug}",
            )
            if pkg_id:
                nodes_created += 1
                logger.info(f"PKG: Upserted Interest node for '{title}' (depth={depth})")
        except Exception as e:
            logger.warning(f"PKG Interest upsert failed for '{title}': {e}")

        # 2. Upsert PKG_Goal if actively studying and not yet mastered
        if mastery < 0.8 and status == "active":
            try:
                pkg_id = personal_kg.upsert_fact(
                    fact_type="Goal",
                    properties={
                        "description": f"Learn {title}",
                        "status": "in_progress",
                        "progress": f"{mastery:.0%}",
                        "category": "learning",
                    },
                    confidence=0.85,
                    source="learning_extraction",
                    dedup_key=f"goal:learn_{title_slug}",
                )
                if pkg_id:
                    nodes_created += 1
                    logger.info(f"PKG: Upserted Goal node for 'Learn {title}'")
            except Exception as e:
                logger.warning(f"PKG Goal upsert failed for '{title}': {e}")

        # 3. Extract key concepts from recent learning session as PKG_Fact nodes
        try:
            session_result = await db.execute(text("""
                SELECT content FROM episode
                WHERE user_id = :user_id AND source = 'learning_chat'
                  AND meta->>'topic_id' = :topic_id
                  AND role = 'assistant'
                  AND created_at >= NOW() - INTERVAL '3 hours'
                ORDER BY created_at DESC LIMIT 5
            """), {"user_id": user_id, "topic_id": topic_id})
            session_rows = session_result.fetchall()

            if session_rows:
                # Use lightweight LLM call to extract key concepts
                from app.core.llm import get_background_llm_client
                llm = get_background_llm_client()

                session_text = "\n".join(r.content[:500] for r in session_rows if r.content)

                import json
                try:
                    response = await llm.chat_completion(
                        messages=[
                            {"role": "system", "content": "Extract 2-3 key factual concepts David learned. Return ONLY a JSON array of short strings. Example: [\"Rust ownership transfers value on assignment\", \"Borrow checker prevents data races\"]"},
                            {"role": "user", "content": f"From this learning session about '{title}':\n{session_text[:3000]}"},
                        ],
                        temperature=0.3,
                        max_tokens=300,
                    )
                    raw = response["choices"][0]["message"]["content"].strip()
                    if "```" in raw:
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                        raw = raw.strip()
                    concepts = json.loads(raw)
                    if isinstance(concepts, list):
                        for i, concept in enumerate(concepts[:3]):
                            concept_slug = re.sub(r'[^a-z0-9]+', '_', concept.lower()[:60]).strip('_')
                            try:
                                pkg_id = personal_kg.upsert_fact(
                                    fact_type="Fact",
                                    properties={
                                        "description": concept,
                                        "domain": title,
                                        "category": "learning",
                                    },
                                    confidence=0.75,
                                    source="learning_extraction",
                                    dedup_key=f"fact:learning:{concept_slug}",
                                )
                                if pkg_id:
                                    nodes_created += 1
                            except Exception:
                                pass
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    logger.debug(f"PKG concept extraction parse failed: {e}")
        except Exception as e:
            logger.debug(f"PKG Fact extraction failed for '{title}': {e}")

        return {
            "topic": title,
            "mastery": mastery,
            "depth": depth,
            "nodes_created": nodes_created,
        }


@celery_app.task(
    name="app.tasks.autonomy.idle_processing",
    bind=True,
    queue="low_priority"
)
def idle_processing(self):
    """
    Idle processing - productive use of quiet time.

    Runs every 10 minutes when system is idle.
    """
    logger.info("Starting idle processing")

    try:
        result = _run_async(
            _idle_processing_async()
        )
        return result
    except Exception as e:
        logger.error(f"Idle processing failed: {e}")
        raise


async def _idle_processing_async():
    """Async implementation of idle processing."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()

    # Check if system is actually idle
    if not await coordinator.should_run_worker("idle-processing"):
        return {"skipped": "not_idle"}
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        tasks_done = []

        # Task 1: Clean up old consolidation discards
        cleanup_result = await db.execute(
            text("""
                DELETE FROM consolidation_discards
                WHERE created_at < NOW() - INTERVAL '30 days'
            """)
        )
        if cleanup_result.rowcount:
            tasks_done.append(f"Cleaned {cleanup_result.rowcount} old discards")

        # Task 2: Prune expired raw buffer stats
        stats_result = await db.execute(
            text("""
                DELETE FROM raw_buffer_stats
                WHERE window_end < NOW() - INTERVAL '7 days'
            """)
        )
        if stats_result.rowcount:
            tasks_done.append(f"Cleaned {stats_result.rowcount} old stats")

        await db.commit()

        return {
            "timestamp": local_now().isoformat(),
            "tasks_done": tasks_done,
        }


# ── Weather Context Refresh ──────────────────────────────────────
@celery_app.task(
    name="app.tasks.autonomy.weather_context_refresh",
    bind=True,
    queue="low_priority",
    max_retries=1,
)
def weather_context_refresh(self):
    """
    Refresh weather data in the unified context snapshot.
    Runs every 30 minutes. Reuses existing WeatherService (OpenWeatherMap).
    """
    try:
        result = _run_async(
            _weather_refresh_async()
        )
        return result
    except Exception as e:
        logger.warning(f"Weather refresh failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _weather_refresh_async():
    """Fetch weather and write to unified context snapshot."""
    try:
        from app.services.weather_service import weather_service
        from app.services.context_writer import update_fields

        weather = await weather_service.get_weather()
        if weather and weather.current:
            await update_fields(
                DEFAULT_USER_ID,
                source="weather_refresh",
                temperature_outside=weather.current.temperature,
                weather_condition=weather.current.description,
            )
            return {
                "temperature": weather.current.temperature,
                "condition": weather.current.description,
            }
        return {"skipped": "no_weather_data"}
    except Exception as e:
        logger.warning(f"Weather refresh async failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


# ── Home State Hourly Summary ────────────────────────────────────
@celery_app.task(
    name="app.tasks.autonomy.home_state_hourly_summary",
    bind=True,
    queue="low_priority",
    max_retries=1,
)
def home_state_hourly_summary(self):
    """
    Aggregate HA events from the last hour into home_state_summary.
    Runs 5 minutes past each hour.
    """
    try:
        result = _run_async(
            _home_state_summary_async()
        )
        return result
    except Exception as e:
        logger.error(f"Home state summary failed: {e}", exc_info=True)
        raise self.retry(countdown=60, exc=e)


async def _home_state_summary_async():
    """Aggregate HA events from Redis event replay buffer into DB."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    try:
        from app.services.event_bus import event_bus
        now = local_now()
        hour_bucket = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

        # Replay events from the last hour
        events = await event_bus.replay_events(
            start_time=hour_bucket,
            end_time=hour_bucket + timedelta(hours=1),
        )

        rooms_active = set()
        temp_readings = []
        motion_count = 0
        door_count = 0
        lights_on = 0

        for evt in events:
            payload = evt.payload if hasattr(evt, 'payload') else {}
            etype = evt.event_type.value if hasattr(evt.event_type, 'value') else str(evt.event_type)

            if "motion" in etype:
                motion_count += 1
                room = payload.get("room")
                if room:
                    rooms_active.add(room)
            elif "door" in etype:
                door_count += 1
            elif "light" in etype:
                lights_on += 1
            elif "climate" in etype:
                temp = payload.get("current_temperature")
                if temp is not None:
                    temp_readings.append(float(temp))

        async with async_session() as db:
            import json
            await db.execute(text("""
                INSERT INTO home_state_summary
                (user_id, hour_bucket, rooms_active, temperature_avg,
                 lights_on_count, motion_events, door_events)
                VALUES (:uid, :bucket, CAST(:rooms AS jsonb), :temp_avg,
                        :lights, :motion, :doors)
                ON CONFLICT (user_id, hour_bucket) DO UPDATE SET
                    rooms_active = EXCLUDED.rooms_active,
                    temperature_avg = EXCLUDED.temperature_avg,
                    lights_on_count = EXCLUDED.lights_on_count,
                    motion_events = EXCLUDED.motion_events,
                    door_events = EXCLUDED.door_events
            """), {
                "uid": DEFAULT_USER_ID,
                # hour_bucket column is `timestamp without time zone` (naive ET);
                # asyncpg cannot encode an aware datetime into it.
                "bucket": to_naive_local(hour_bucket),
                "rooms": json.dumps(list(rooms_active)),
                "temp_avg": sum(temp_readings) / len(temp_readings) if temp_readings else None,
                "lights": lights_on,
                "motion": motion_count,
                "doors": door_count,
            })
            await db.commit()

        return {
            "hour_bucket": hour_bucket.isoformat(),
            "motion_events": motion_count,
            "door_events": door_count,
            "rooms": list(rooms_active),
        }
    except Exception as e:
        logger.error(f"Home state summary async failed: {e}", exc_info=True)
        raise


# ── Daily Autonomy Digest ──

@celery_app.task(
    name="app.tasks.autonomy.daily_autonomy_digest",
    bind=True,
    queue="low_priority",
)
def daily_autonomy_digest(self):
    """
    Daily summary of autonomous actions — runs at 9 PM.
    Queries last 24h of agent_run_log and notification_log, sends a single digest.
    """
    logger.info("Starting daily autonomy digest")
    try:
        result = _run_async(
            _daily_digest_async()
        )
        return result
    except Exception as e:
        logger.error(f"Daily digest failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _daily_digest_async():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os
    import json
    from app.services.unified_notification import send_notification
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        from sqlalchemy import text
        user_id = DEFAULT_USER_ID
        today = local_now().strftime("%Y-%m-%d")

        # Count runs
        run_result = await db.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN error_message IS NOT NULL THEN 1 END) as errors,
                   SUM(jsonb_array_length(
                       CASE WHEN jsonb_typeof(actions_taken) = 'array'
                       THEN actions_taken ELSE '[]'::jsonb END
                   )) as total_actions
            FROM agent_run_log
            WHERE user_id = :uid AND run_at >= NOW() - INTERVAL '24 hours'
        """), {"uid": user_id})
        run_stats = run_result.fetchone()

        # Count notifications
        notif_result = await db.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN sent = TRUE THEN 1 END) as sent,
                   COUNT(CASE WHEN outcome = 'dismissed' THEN 1 END) as dismissed
            FROM notification_log
            WHERE user_id = :uid AND sent_at >= NOW() - INTERVAL '24 hours'
        """), {"uid": user_id})
        notif_stats = notif_result.fetchone()

        runs = run_stats.total if run_stats else 0
        errors = run_stats.errors if run_stats else 0
        notifs_sent = notif_stats.sent if notif_stats else 0
        notifs_dismissed = notif_stats.dismissed if notif_stats else 0

        if runs == 0 and notifs_sent == 0:
            return {"skipped": "no_activity"}

        lines = [f"Autonomy Digest for {today}:"]
        lines.append(f"- {runs} agent runs ({errors} errors)")
        lines.append(f"- {notifs_sent} notifications sent ({notifs_dismissed} dismissed)")

        message = "\n".join(lines)

        await send_notification(
            user_id=user_id,
            title="Daily Autonomy Digest",
            message=message,
            topic=f"digest:daily_{today}",
            category="general",
            priority="low",
            source="daily_digest",
            db=db,
        )
        await db.commit()

        return {"runs": runs, "errors": errors, "notifications": notifs_sent}


# ─── Retention Cleanup (Phase 0 — Cortana Evolution) ───────────────────


@celery_app.task(
    name="app.tasks.autonomy.autonomy_retention_cleanup",
    bind=True,
    queue="maintenance",
    max_retries=1,
)
def autonomy_retention_cleanup(self):
    """
    Daily retention cleanup for autonomy tables.

    Retention policy:
    - autonomy_action_trace: 90 days
    - autonomy_attention_item: 30 days archived/dropped, 7 days stale new/sent
    - autonomy_mission: 180 days terminal states
    - autonomy_policy_candidate: auto-expire new after 14 days, delete decided after 30 days
    """
    logger.info("Running autonomy retention cleanup...")
    try:
        result = _run_async(
            _autonomy_retention_async()
        )
        logger.info(f"Retention cleanup complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}")
        raise self.retry(countdown=300, exc=e)


async def _autonomy_retention_async():
    """Async implementation of retention cleanup."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        results = {}

        # Action traces: delete older than 90 days
        try:
            r = await db.execute(text("""
                DELETE FROM autonomy_action_trace
                WHERE created_at < NOW() - INTERVAL '90 days'
            """))
            results["action_traces_deleted"] = r.rowcount
            await db.commit()
        except Exception as e:
            results["action_traces_error"] = str(e)
            await db.rollback()

        # Append-only tables that had no retention (Phase 8.4). promotion_event is
        # the biggest table in the DB (~32k rows, 4x episodes); cap it hard.
        _RETENTION = [
            ("promotion_event", "created_at", 30),
            ("sara_activity_log", "created_at", 90),
            ("home_activity_log", "created_at", 90),
            ("location_event", "created_at", 90),
            ("token_usage", "created_at", 90),
            ("system_event", "created_at", 30),
        ]
        for table, col, days in _RETENTION:
            try:
                r = await db.execute(text(
                    f"DELETE FROM {table} WHERE {col} < NOW() - INTERVAL '{days} days'"))
                results[f"{table}_deleted"] = r.rowcount
                await db.commit()
            except Exception as e:
                results[f"{table}_error"] = str(e)[:80]
                await db.rollback()

        # Attention items: delete archived older than 30 days (Phase 2)
        try:
            r = await db.execute(text("""
                DELETE FROM autonomy_attention_item
                WHERE status IN ('archived', 'dropped')
                  AND updated_at < NOW() - INTERVAL '30 days'
            """))
            results["attention_archived_deleted"] = r.rowcount

            # Auto-archive stale new/sent items after 7 days
            r = await db.execute(text("""
                UPDATE autonomy_attention_item
                SET status = 'archived', updated_at = NOW()
                WHERE status IN ('new', 'sent')
                  AND created_at < NOW() - INTERVAL '7 days'
            """))
            results["attention_stale_archived"] = r.rowcount
            await db.commit()
        except Exception:
            await db.rollback()  # Table may not exist yet (Phase 2)

        # Missions: delete terminal states older than 180 days (Phase 2)
        try:
            r = await db.execute(text("""
                DELETE FROM autonomy_mission
                WHERE state IN ('done', 'failed', 'cancelled')
                  AND completed_at < NOW() - INTERVAL '180 days'
            """))
            results["missions_deleted"] = r.rowcount
            await db.commit()
        except Exception:
            await db.rollback()  # Table may not exist yet

        # Policy candidates: auto-expire new after 14 days, delete decided after 30 days (Phase 3)
        try:
            r = await db.execute(text("""
                UPDATE autonomy_policy_candidate
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'new'
                  AND created_at < NOW() - INTERVAL '14 days'
            """))
            results["candidates_expired"] = r.rowcount

            r = await db.execute(text("""
                DELETE FROM autonomy_policy_candidate
                WHERE status IN ('accepted', 'rejected', 'expired')
                  AND updated_at < NOW() - INTERVAL '30 days'
            """))
            results["candidates_deleted"] = r.rowcount
            await db.commit()
        except Exception:
            await db.rollback()  # Table may not exist yet

        # Standing-order action_ledger: retain 90 days so pattern promotion
        # can see a reasonable history, drop older rows so the table doesn't
        # grow indefinitely. Audit flagged this as a slow leak because the
        # 5-minute undo window is the only time these rows are accessed, but
        # nothing ever cleaned up once undo expired.
        try:
            r = await db.execute(text("""
                DELETE FROM action_ledger
                WHERE executed_at < NOW() - INTERVAL '90 days'
            """))
            results["action_ledger_deleted"] = r.rowcount
            await db.commit()
        except Exception as e:
            # Table may not exist yet on a very old DB.
            results["action_ledger_error"] = str(e)
            await db.rollback()

    # Episode embedding backfill — several ingestion paths (fitness_food,
    # pi_dashboard_voice, api, learning_chat) insert rows with NULL
    # embeddings, making them unreachable by semantic search. Catch them
    # up here. Capped per run so we don't DOS the embedding service on a
    # database that's been running for a year.
    try:
        filled = await _backfill_episode_embeddings(limit=500)
        results["episode_embeddings_filled"] = filled
    except Exception as e:
        results["episode_embeddings_error"] = str(e)

    return results


async def _backfill_episode_embeddings(limit: int = 500) -> int:
    """Embed episodes whose ``embedding`` column is NULL.

    Returns the count written. Safe to run repeatedly: idempotent because
    we only touch rows where ``embedding IS NULL``. Bounded by ``limit``
    per call so one bad day's worth of gaps doesn't saturate the GPU.
    """
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.embedding_service import EmbeddingService

    factory = get_async_session_factory()
    svc = EmbeddingService()
    filled = 0

    async with factory() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, content
                    FROM episode
                    WHERE embedding IS NULL
                      AND content IS NOT NULL
                      AND LENGTH(content) > 0
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).fetchall()

    # Each row gets its own session/transaction so one embedding-service
    # timeout or write failure doesn't roll back everything already filled
    # in this batch.
    for row in rows:
        try:
            vec = await svc.generate_embedding(row.content)
        except Exception:
            continue
        if not vec:
            continue
        try:
            async with factory() as db:
                await db.execute(
                    text(
                        """
                        UPDATE episode
                        SET embedding = CAST(:qvec AS vector)
                        WHERE id = :id
                        """
                    ),
                    {"id": row.id, "qvec": str(vec)},
                )
                await db.commit()
            filled += 1
        except Exception as e:
            logger.warning(f"Failed to write backfilled embedding for episode {row.id}: {e}")
            continue

    return filled


# ─── Derived Signal Refresh (Phase 1: Working Memory) ───────────

@celery_app.task(
    name="app.tasks.autonomy.derived_signal_refresh",
    bind=True,
    queue="low_priority",
    max_retries=1,
)
def derived_signal_refresh(self):
    """Refresh DB-dependent working memory signals every 5 minutes."""
    try:
        result = _run_async(
            _derived_signal_refresh_async()
        )
        return result
    except Exception as e:
        logger.error(f"Derived signal refresh failed: {e}")
        raise self.retry(countdown=30, exc=e)


async def _derived_signal_refresh_async():
    from app.services.memory_subscribers import refresh_derived_signals
    return await refresh_derived_signals(DEFAULT_USER_ID)


# ─── Deliberation Tasks (Phase 3: Event-Driven Deliberation) ────

@celery_app.task(
    name="app.tasks.autonomy.trigger_deliberation",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def trigger_deliberation(self, user_id: str = None):
    """
    Run a deliberation cycle. Called by salience subscriber when threshold crossed,
    or by periodic fallback.
    """
    uid = user_id or DEFAULT_USER_ID
    try:
        result = _run_async(
            _deliberation_async(uid)
        )
        return result
    except Exception as e:
        logger.error(f"Deliberation failed: {e}")
        raise self.retry(countdown=60, exc=e)


async def _deliberation_async(user_id: str):
    # ONE_MIND §3.3: ambient cognition now flows through the one kernel entry
    # point (state + wake-reason), which delegates to this same deliberation
    # engine + gate. Behaviour is unchanged; the kernel is where later phases
    # fold the check-in / anticipation / idle / daemon loops in as wake-reasons
    # instead of parallel selves.
    from app.services.kernel import ambient_turn, WakeReason

    return await ambient_turn(user_id, wake_reason=WakeReason.PROMOTED_EVENT)


@celery_app.task(
    name="app.tasks.autonomy.periodic_deliberation_fallback",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def periodic_deliberation_fallback(self):
    """
    Safety net: check should_deliberate every 30 min in case event-driven triggers missed something.
    Also prunes old observations.
    """
    try:
        result = _run_async(
            _deliberation_fallback_async()
        )
        return result
    except Exception as e:
        logger.error(f"Deliberation fallback failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _deliberation_fallback_async():
    from app.services.salience import salience_scorer
    from app.services.observation_log import prune_old

    user_id = DEFAULT_USER_ID

    # Prune old observations
    pruned = await prune_old(user_id, max_age_hours=24)

    # Check if deliberation is needed
    if await salience_scorer.should_deliberate(user_id):
        from app.services.deliberation import deliberation_engine
        from app.services.deliberation_gate import process_deliberation_result
        from app.services.autonomy.coordination import get_coordinator

        coordinator = get_coordinator()
        if not await coordinator.acquire_exclusive("deliberation-fallback", "heavy_llm"):
            return {"skipped": "exclusive_group_busy", "pruned": pruned}

        try:
            result = await deliberation_engine.run(user_id)
            summary = await process_deliberation_result(result, user_id)
            return {
                "status": "deliberated",
                "pruned": pruned,
                "notifications": summary["notifications_sent"],
                "duration": result.duration_seconds,
            }
        finally:
            await coordinator.release_exclusive("heavy_llm", "deliberation-fallback")

    return {"status": "no_deliberation_needed", "pruned": pruned}


# ─── Proactive Check-ins ────────────────────────────────────────

@celery_app.task(
    name="app.tasks.autonomy.proactive_checkin_sweep",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def proactive_checkin_sweep(self):
    """
    Follow-up sweep: delivers the single ripest open thread (post-meeting
    recap or commitment), gated by interruptibility and anti-nag caps. Runs
    every ~15 min during waking hours. Template/ambient check-in pings were
    removed in SARA_UNLEASHED Phase A — occasional contextual check-ins are
    now proposed by the deliberation engine itself, subject to the same gate
    and payload lint as every other proactive notification.
    """
    try:
        from app.services.proactive_checkins import run_followup_sweep
        return _run_async(run_followup_sweep(DEFAULT_USER_ID))
    except Exception as e:
        logger.error(f"Follow-up sweep failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


@celery_app.task(
    name="app.tasks.autonomy.deep_deliberation",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def deep_deliberation(self):
    """SARA_UNLEASHED Phase C.3: 2x/day deep deliberation on the strong model
    (post-consolidation, 2 PM / 9 PM ET). Sees a 50-observation window (vs 15
    hourly) and may propose up to 4 tasks (vs 2) — meant to catch backlog the
    hourly qwen pass missed, not to replace it."""
    try:
        return _run_async(_deep_deliberation_async(DEFAULT_USER_ID))
    except Exception as e:
        logger.error(f"Deep deliberation failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _deep_deliberation_async(user_id: str):
    from app.services.autonomy.coordination import get_coordinator
    from app.services.deliberation import deliberation_engine
    from app.services.deliberation_gate import process_deliberation_result

    coordinator = get_coordinator()
    if not await coordinator.acquire_exclusive("deep-deliberation", "heavy_llm"):
        return {"skipped": "exclusive_group_busy"}

    try:
        result = await deliberation_engine.run(user_id, deep=True)
        summary = await process_deliberation_result(result, user_id)
        return {
            "status": "completed",
            "deep": True,
            "notifications": summary["notifications_sent"],
            "tasks_dispatched": summary["tasks_dispatched"],
            "tasks_proposed": summary["tasks_proposed"],
            "duration": result.duration_seconds,
        }
    finally:
        await coordinator.release_exclusive("heavy_llm", "deep-deliberation")


@celery_app.task(
    name="app.tasks.autonomy.scan_ended_meetings",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def scan_ended_meetings(self):
    """
    Open a one-shot follow-up thread for any real meeting that just ended.
    The check-in sweep delivers it once David is interruptible.
    """
    try:
        from app.services.proactive_checkins import scan_ended_meetings as _scan
        return _run_async(_scan(DEFAULT_USER_ID))
    except Exception as e:
        logger.error(f"Ended-meeting scan failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


# ─── Consolidation Task (Phase 4: Deep Reflection) ──────────────

@celery_app.task(
    name="app.tasks.autonomy.run_consolidation",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def run_consolidation(self):
    """
    Run consolidation — deep reflection on patterns and calibration.
    Scheduled 2x daily: 2 PM and 9 PM.
    """
    try:
        result = _run_async(
            _consolidation_async()
        )
        return result
    except Exception as e:
        logger.error(f"Consolidation failed: {e}")
        raise self.retry(countdown=120, exc=e)


async def _consolidation_async():
    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()
    if not await coordinator.acquire_exclusive("consolidation", "heavy_llm"):
        return {"skipped": "exclusive_group_busy"}

    try:
        from app.services.consolidation import consolidation_engine
        result = await consolidation_engine.run(DEFAULT_USER_ID)

        # Cross-domain correlation discovery (health x behavior x productivity)
        # has a fully-built producer in pattern_correlation_service but nothing
        # ever called it — it was written for a standalone worker process that
        # was never deployed, so correlation_pattern sat at 0 rows even though
        # routes/patterns.py and tools/patterns.py were built to read from it.
        # Piggyback on this same 2x-daily slot rather than stand up a new job.
        correlation_result = {"error": "not_run"}
        try:
            from app.db.session import SessionLocal
            from app.services.pattern_correlation_service import pattern_correlation_service
            sync_db = SessionLocal()
            try:
                correlation_result = await pattern_correlation_service.run_discovery(
                    sync_db, DEFAULT_USER_ID, lookback_days=30
                )
            finally:
                sync_db.close()
        except Exception as e:
            logger.warning(f"Correlation pattern discovery failed: {e}")
            correlation_result = {"error": str(e)}

        return {
            "status": "completed",
            "patterns": len(result.patterns_noticed),
            "pkg_extractions": len(result.pkg_extractions),
            "journal_written": bool(result.journal_entry),
            "duration": result.duration_seconds,
            "correlation_discovery": correlation_result,
        }
    finally:
        await coordinator.release_exclusive("heavy_llm", "consolidation")
