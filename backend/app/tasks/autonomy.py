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
from app.core.timezone import USER_TIMEZONE, now as local_now

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
        return {"error": str(e)}


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
        return {"error": str(exc)}


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
        return {"error": str(exc)}


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

        return {
            "timestamp": local_now().isoformat(),
            "episodes_today": episode_count,
            "episodes_decayed": decayed,
            "actions_cleaned": cleaned,
            "importance_rescoring": rescore_stats,
            "rating_consolidation": rating_stats,
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
        since = local_now() - timedelta(hours=since_hours)

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
        return {"error": str(e)}


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
        return {"error": str(e)}


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
        logger.warning(f"Home state summary failed: {e}")
        return {"error": str(e)}


async def _home_state_summary_async():
    """Aggregate HA events from Redis event replay buffer into DB."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os
    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
                "bucket": hour_bucket,
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
        logger.warning(f"Home state summary async failed: {e}")
        return {"error": str(e)}
    finally:
        await engine.dispose()


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
        return {"error": str(e)}


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
        except Exception as e:
            results["action_traces_error"] = str(e)

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
        except Exception:
            pass  # Table may not exist yet (Phase 2)

        # Missions: delete terminal states older than 180 days (Phase 2)
        try:
            r = await db.execute(text("""
                DELETE FROM autonomy_mission
                WHERE state IN ('done', 'failed', 'cancelled')
                  AND completed_at < NOW() - INTERVAL '180 days'
            """))
            results["missions_deleted"] = r.rowcount
        except Exception:
            pass  # Table may not exist yet

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
        except Exception:
            pass  # Table may not exist yet

        await db.commit()
        return results


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
    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()
    if not await coordinator.acquire_exclusive("deliberation", "heavy_llm"):
        return {"skipped": "exclusive_group_busy"}

    try:
        from app.services.salience import salience_scorer
        # Double-check should_deliberate (may have been consumed since trigger)
        if not await salience_scorer.should_deliberate(user_id):
            return {"skipped": "below_threshold"}

        from app.services.deliberation import deliberation_engine
        from app.services.deliberation_gate import process_deliberation_result

        result = await deliberation_engine.run(user_id)
        summary = await process_deliberation_result(result, user_id)
        return {
            "status": "completed",
            "thought": result.thought[:200],
            "notifications": summary["notifications_sent"],
            "home_actions": summary["home_actions_executed"],
            "observations_consumed": summary["observations_consumed"],
            "duration": result.duration_seconds,
        }
    finally:
        await coordinator.release_exclusive("heavy_llm", "deliberation")


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
        return {"error": str(e)}


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
        return {
            "status": "completed",
            "patterns": len(result.patterns_noticed),
            "pkg_extractions": len(result.pkg_extractions),
            "journal_written": bool(result.journal_entry),
            "duration": result.duration_seconds,
        }
    finally:
        await coordinator.release_exclusive("heavy_llm", "consolidation")
