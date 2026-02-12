"""
Learning system Celery tasks.

Handles:
- Deep research worker (background processing of research jobs)
- Pending source fetcher (auto-fetch sources with fetch_status='pending')
- Auto-research trigger (dispatched when topics are created)
"""

import logging
import asyncio
from datetime import datetime

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Default user ID for Sara
DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@celery_app.task(
    name="app.tasks.learning.deep_research_worker",
    bind=True,
    queue="cognitive",
    max_retries=1
)
def deep_research_worker(self, job_id: str = None):
    """
    Deep research worker — processes queued ResearchJob records.

    Can be called with a specific job_id (dispatched from endpoint) or
    without one (poller mode — finds next queued job).
    """
    logger.info(f"Starting deep research worker (job_id={job_id})")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _run_deep_research_async(job_id)
        )
        logger.info(f"Deep research complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_run_deep_research_async(job_id))
        logger.info(f"Deep research complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Deep research worker failed: {e}")
        raise self.retry(countdown=120, exc=e)


async def _run_deep_research_async(job_id: str = None):
    """Async implementation of deep research."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    database_url = os.getenv("DATABASE_URL", "")

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        try:
            # Find the job to process
            if job_id:
                job_result = await db.execute(text("""
                    SELECT rj.id, rj.user_id, rj.report_id, rj.status,
                           rr.question, rr.topic_id
                    FROM research_job rj
                    JOIN research_report rr ON rj.report_id = rr.id
                    WHERE rj.id = :job_id AND rj.status IN ('queued', 'running')
                """), {"job_id": job_id})
            else:
                # Poller mode: find next queued job
                job_result = await db.execute(text("""
                    SELECT rj.id, rj.user_id, rj.report_id, rj.status,
                           rr.question, rr.topic_id
                    FROM research_job rj
                    JOIN research_report rr ON rj.report_id = rr.id
                    WHERE rj.status = 'queued'
                    ORDER BY rj.created_at ASC
                    LIMIT 1
                """))

            job_row = job_result.fetchone()
            if not job_row:
                return {"skipped": True, "reason": "no queued jobs"}

            job_id = job_row.id
            user_id = job_row.user_id
            report_id = job_row.report_id
            question = job_row.question
            topic_id = job_row.topic_id

            # Mark as running
            await db.execute(text("""
                UPDATE research_job
                SET status = 'running', started_at = NOW(),
                    current_step = 'Generating search queries'
                WHERE id = :job_id
            """), {"job_id": job_id})
            await db.execute(text("""
                UPDATE research_report SET status = 'in_progress'
                WHERE id = :report_id
            """), {"report_id": report_id})
            await db.commit()

            result = await _execute_deep_research(
                db, job_id, report_id, user_id, topic_id, question
            )
            return result

        except Exception as e:
            logger.error(f"Deep research failed for job {job_id}: {e}", exc_info=True)
            try:
                await db.execute(text("""
                    UPDATE research_job
                    SET status = 'failed', error_message = :error,
                        completed_at = NOW()
                    WHERE id = :job_id
                """), {"job_id": job_id, "error": str(e)[:500]})
                await db.execute(text("""
                    UPDATE research_report SET status = 'failed'
                    WHERE id = :report_id
                """), {"report_id": report_id})
                await db.commit()
            except Exception:
                pass
            return {"error": str(e), "job_id": job_id}

    await engine.dispose()


async def _update_progress(db, job_id: str, progress: int, step: str, sources_found: int = None):
    """Helper to update job progress."""
    params = {"job_id": job_id, "progress": progress, "step": step}
    sql = """
        UPDATE research_job
        SET progress = :progress, current_step = :step
    """
    if sources_found is not None:
        sql += ", sources_found = :sources_found"
        params["sources_found"] = sources_found
    sql += " WHERE id = :job_id"
    await db.execute(text(sql), params)
    await db.commit()


async def _execute_deep_research(
    db, job_id: str, report_id: str, user_id: str,
    topic_id: str, question: str
) -> dict:
    """Execute the multi-phase deep research pipeline."""
    import json
    import uuid
    from sqlalchemy import text

    from app.core.llm import get_background_llm_client

    llm = get_background_llm_client()

    # Load topic context if available
    topic_context = ""
    if topic_id:
        topic_result = await db.execute(text("""
            SELECT title, description FROM learning_topic
            WHERE id = :topic_id
        """), {"topic_id": topic_id})
        topic_row = topic_result.fetchone()
        if topic_row:
            topic_context = f"Topic: {topic_row.title}"
            if topic_row.description:
                topic_context += f"\nDescription: {topic_row.description}"

    # ── Phase 1: Query Generation (0-15%) ──
    await _update_progress(db, job_id, 5, "Generating search queries")

    query_prompt = f"""Generate 5-8 diverse search queries for deep research on this question.
The queries should cover different angles and aspects.

{topic_context}

Research question: {question}

Return ONLY a JSON array of search query strings. Example:
["query one", "query two", "query three"]"""

    try:
        response = await llm.chat_completion(
            messages=[
                {"role": "system", "content": "You are a research query generator. Return only valid JSON."},
                {"role": "user", "content": query_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        raw_queries = response["choices"][0]["message"]["content"].strip()
        # Parse JSON from response (handle markdown code blocks)
        if "```" in raw_queries:
            raw_queries = raw_queries.split("```")[1]
            if raw_queries.startswith("json"):
                raw_queries = raw_queries[4:]
            raw_queries = raw_queries.strip()
        search_queries = json.loads(raw_queries)
        if not isinstance(search_queries, list):
            search_queries = [question]
    except Exception as e:
        logger.warning(f"Query generation failed, using fallback: {e}")
        search_queries = [
            question,
            f"{question} tutorial",
            f"{question} explained",
        ]

    # Save queries to job
    await db.execute(text("""
        UPDATE research_job SET search_queries = CAST(:queries AS jsonb)
        WHERE id = :job_id
    """), {"job_id": job_id, "queries": json.dumps(search_queries)})
    await db.commit()
    await _update_progress(db, job_id, 15, f"Generated {len(search_queries)} search queries")

    # ── Phase 2: Discovery (15-45%) ──
    from app.services.search_service import search_service

    all_urls = set()
    discovered_sources = []

    for i, query in enumerate(search_queries[:8]):
        step_progress = 15 + int((i / min(len(search_queries), 8)) * 30)
        await _update_progress(db, job_id, step_progress, f"Searching: {query[:50]}...")

        try:
            results = await search_service.web_search(query=query, max_results=5)
            for r in results.get("results", []):
                url = r.get("url")
                if not url or url in all_urls:
                    continue
                all_urls.add(url)
                discovered_sources.append({
                    "url": url,
                    "title": r.get("title", url[:60]),
                    "snippet": r.get("snippet", ""),
                    "query": query,
                })
        except Exception as e:
            logger.warning(f"Search failed for query '{query[:50]}': {e}")
            continue

    sources_found = len(discovered_sources)
    await _update_progress(db, job_id, 45, f"Discovered {sources_found} sources", sources_found)

    # ── Phase 3: Fetching (45-75%) ──
    # Create TopicSource records and fetch top sources
    from app.services.learning_source_service import learning_source_service

    fetched_chunks = []
    processed_count = 0
    max_fetch = min(12, len(discovered_sources))

    for i, src_info in enumerate(discovered_sources[:max_fetch]):
        step_progress = 45 + int((i / max_fetch) * 30) if max_fetch > 0 else 75
        await _update_progress(db, job_id, step_progress, f"Processing: {src_info['title'][:40]}...")

        try:
            # Create TopicSource record
            source_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO topic_source (id, topic_id, user_id, source_type, url, title, fetch_status, created_at)
                VALUES (:id, :topic_id, :user_id, 'web', :url, :title, 'pending', NOW())
            """), {
                "id": source_id,
                "topic_id": topic_id,
                "user_id": user_id,
                "url": src_info["url"],
                "title": src_info["title"],
            })
            await db.commit()

            # Fetch and process via existing service
            # Need to load the ORM object for the service
            from app.models.learning import TopicSource
            from sqlalchemy import select
            source_result = await db.execute(
                select(TopicSource).where(TopicSource.id == source_id)
            )
            # Use raw SQL since we're in async context
            # Actually just update via SQL after processing
            try:
                from app.db.session import SessionLocal
                sync_db = SessionLocal()
                try:
                    source_obj = sync_db.query(TopicSource).filter(TopicSource.id == source_id).first()
                    if source_obj:
                        result = await learning_source_service.fetch_and_process_source(source_obj, sync_db)
                        if result.get("status") == "success":
                            processed_count += 1
                finally:
                    sync_db.close()
            except Exception as fetch_err:
                logger.warning(f"Failed to fetch source {src_info['url'][:60]}: {fetch_err}")

        except Exception as e:
            logger.warning(f"Failed to process source: {e}")
            continue

    await _update_progress(db, job_id, 75, f"Fetched {processed_count}/{sources_found} sources", sources_found)

    # ── Phase 4: Synthesis (75-95%) ──
    await _update_progress(db, job_id, 80, "Synthesizing research report")

    # Search for relevant chunks across all topic sources
    synthesis_context = ""
    if topic_id:
        try:
            from app.db.session import SessionLocal
            sync_db = SessionLocal()
            try:
                chunks = await learning_source_service.search_chunks(
                    topic_id=topic_id,
                    query=question,
                    db=sync_db,
                    limit=10
                )
                if chunks:
                    synthesis_context = "\n\n".join(
                        f"[{c.get('source_title', 'Source')}]: {c['text']}"
                        for c in chunks
                    )
            finally:
                sync_db.close()
        except Exception as e:
            logger.warning(f"Chunk search failed: {e}")

    # Also include snippets from discovery if no chunks available
    if not synthesis_context and discovered_sources:
        synthesis_context = "\n\n".join(
            f"[{s['title']}]: {s['snippet']}"
            for s in discovered_sources[:10]
            if s.get("snippet")
        )

    await _update_progress(db, job_id, 85, "Generating synthesis with LLM")

    # Generate synthesis
    synthesis_prompt = f"""You are a research synthesizer. Based on the sources below, write a comprehensive research report.

Research Question: {question}
{topic_context}

Sources:
{synthesis_context[:12000]}

Write a detailed report covering:
1. **Key Findings** — Main answers to the research question
2. **Supporting Evidence** — Evidence from sources with citations
3. **Nuances & Caveats** — Limitations, alternative views, areas of uncertainty
4. **Practical Implications** — How this knowledge can be applied
5. **Further Questions** — What remains unanswered

Also provide:
- A 2-3 sentence SUMMARY at the top
- A CONFIDENCE score (0.0 to 1.0) for how well the sources answer the question

Format the confidence as: CONFIDENCE: 0.X"""

    try:
        response = await llm.chat_completion(
            messages=[
                {"role": "system", "content": "You are a thorough research analyst. Write well-structured reports with citations."},
                {"role": "user", "content": synthesis_prompt},
            ],
            temperature=0.4,
            max_tokens=2000,
        )
        full_content = response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Synthesis LLM call failed: {e}")
        full_content = f"Research synthesis failed: {e}\n\nDiscovered {sources_found} sources for '{question}'."

    # Parse confidence from response
    confidence = 0.5
    for line in full_content.split("\n"):
        if "CONFIDENCE:" in line.upper():
            try:
                conf_str = line.upper().split("CONFIDENCE:")[1].strip()
                confidence = float(conf_str.split()[0])
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, IndexError):
                pass
            break

    # Extract summary (first paragraph or first 3 sentences)
    summary_lines = full_content.split("\n\n")
    summary = summary_lines[0] if summary_lines else full_content[:300]
    if len(summary) > 500:
        summary = summary[:500] + "..."

    await _update_progress(db, job_id, 95, "Finalizing report")

    # ── Phase 5: Finalization (95-100%) ──
    sources_used = [
        {"url": s["url"], "title": s["title"], "contribution": "web_discovery"}
        for s in discovered_sources[:max_fetch]
    ]

    await db.execute(text("""
        UPDATE research_report
        SET full_content = :full_content,
            summary = :summary,
            confidence = :confidence,
            sources_used = CAST(:sources_used AS jsonb),
            status = 'completed',
            completed_at = NOW()
        WHERE id = :report_id
    """), {
        "report_id": report_id,
        "full_content": full_content,
        "summary": summary,
        "confidence": confidence,
        "sources_used": json.dumps(sources_used),
    })

    await db.execute(text("""
        UPDATE research_job
        SET status = 'completed', progress = 100,
            current_step = 'Completed', completed_at = NOW(),
            sources_found = :sources_found
        WHERE id = :job_id
    """), {"job_id": job_id, "sources_found": sources_found})

    await db.commit()

    return {
        "job_id": job_id,
        "report_id": report_id,
        "status": "completed",
        "sources_found": sources_found,
        "sources_processed": processed_count,
        "confidence": confidence,
        "summary_preview": summary[:200],
    }


# ─── Pending Source Fetcher ────────────────────────────────────────────


@celery_app.task(
    name="app.tasks.learning.fetch_pending_sources",
    bind=True,
    queue="cognitive",
    max_retries=0
)
def fetch_pending_sources(self, batch_size: int = 5):
    """
    Background fetcher for sources with fetch_status='pending'.

    Catches manually added sources, leftover auto-research sources,
    and any sources that failed to be fetched inline.
    Runs as a poller (every 2 minutes via beat) and processes a batch at a time.
    """
    logger.info("Starting pending source fetcher")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _fetch_pending_sources_async(batch_size)
        )
        if result.get("fetched", 0) > 0:
            logger.info(f"Pending source fetcher: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_fetch_pending_sources_async(batch_size))
        if result.get("fetched", 0) > 0:
            logger.info(f"Pending source fetcher: {result}")
        return result
    except Exception as e:
        logger.error(f"Pending source fetcher failed: {e}")
        return {"error": str(e)}


async def _fetch_pending_sources_async(batch_size: int):
    """Async implementation of pending source fetcher."""
    from sqlalchemy import text
    import os

    from app.db.session import SessionLocal
    from app.models.learning import TopicSource
    from app.services.learning_source_service import learning_source_service

    sync_db = SessionLocal()
    try:
        # Find pending sources (oldest first, skip sources less than 30s old to avoid racing
        # with inline fetch from the add_source / auto_research endpoints)
        pending = sync_db.execute(text("""
            SELECT id, url, title, source_type
            FROM topic_source
            WHERE fetch_status = 'pending'
              AND created_at < NOW() - INTERVAL '30 seconds'
            ORDER BY created_at ASC
            LIMIT :batch_size
        """), {"batch_size": batch_size})
        rows = pending.fetchall()

        if not rows:
            return {"skipped": True, "reason": "no pending sources"}

        fetched = 0
        failed = 0

        for row in rows:
            try:
                source_obj = sync_db.query(TopicSource).filter(
                    TopicSource.id == row.id
                ).first()
                if not source_obj:
                    continue

                # Double-check still pending (another worker could have grabbed it)
                if source_obj.fetch_status != "pending":
                    continue

                result = await learning_source_service.fetch_and_process_source(
                    source_obj, sync_db
                )
                if result.get("status") == "success":
                    fetched += 1
                    logger.info(
                        f"Auto-fetched source: {source_obj.title or source_obj.url} "
                        f"({result.get('chunk_count', 0)} chunks)"
                    )
                else:
                    failed += 1
                    logger.warning(
                        f"Auto-fetch failed for {source_obj.url}: {result.get('error', 'unknown')}"
                    )
            except Exception as e:
                failed += 1
                logger.warning(f"Auto-fetch error for source {row.id}: {e}")

        return {
            "checked": len(rows),
            "fetched": fetched,
            "failed": failed,
        }
    finally:
        sync_db.close()


# ─── Auto-Research on Topic Create ─────────────────────────────────────


@celery_app.task(
    name="app.tasks.learning.auto_research_topic",
    bind=True,
    queue="cognitive",
    max_retries=1
)
def auto_research_topic_task(self, user_id: str, topic_id: str):
    """
    Auto-discover and fetch sources for a newly created topic.

    Dispatched automatically when a new topic is created.
    Runs the same logic as the /topics/{id}/auto-research endpoint
    but in the background so topic creation is instant.
    """
    logger.info(f"Starting auto-research for topic {topic_id}")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _auto_research_topic_async(user_id, topic_id)
        )
        logger.info(f"Auto-research complete for topic {topic_id}: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_auto_research_topic_async(user_id, topic_id))
        logger.info(f"Auto-research complete for topic {topic_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Auto-research failed for topic {topic_id}: {e}")
        raise self.retry(countdown=60, exc=e)


async def _auto_research_topic_async(user_id: str, topic_id: str):
    """Async implementation of auto-research for a topic."""
    import uuid as uuid_mod
    from app.db.session import SessionLocal
    from app.models.learning import LearningTopic, TopicSource
    from app.services.search_service import search_service
    from app.services.learning_source_service import learning_source_service

    sync_db = SessionLocal()
    try:
        topic = sync_db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            return {"skipped": True, "reason": "topic not found"}

        # Build search queries
        search_queries = [
            f"{topic.title} tutorial",
            f"{topic.title} guide",
            f"{topic.title} explained",
            f"{topic.title} introduction",
        ]
        if topic.description:
            search_queries.append(f"{topic.title} {topic.description[:50]}")

        # Discover sources
        existing_urls = set()
        added_sources = []

        for query in search_queries[:4]:
            try:
                search_result = await search_service.web_search(
                    query=query, max_results=4
                )
                for r in search_result.get("results", [])[:3]:
                    url = r.get("url")
                    if not url or url in existing_urls:
                        continue

                    title = r.get("title", url[:60])
                    source = TopicSource(
                        id=str(uuid_mod.uuid4()),
                        topic_id=topic_id,
                        user_id=user_id,
                        source_type="web",
                        url=url,
                        title=title,
                        fetch_status="pending"
                    )
                    sync_db.add(source)
                    existing_urls.add(url)
                    added_sources.append({
                        "source_id": source.id,
                        "url": url,
                        "title": title,
                    })

                    if len(added_sources) >= 8:
                        break
            except Exception as e:
                logger.warning(f"Search failed for '{query}': {e}")
                continue

            if len(added_sources) >= 8:
                break

        sync_db.commit()

        # Fetch and process the top sources immediately (up to 5)
        fetched_count = 0
        for src_info in added_sources[:5]:
            source_obj = sync_db.query(TopicSource).filter(
                TopicSource.id == src_info["source_id"]
            ).first()
            if source_obj:
                try:
                    result = await learning_source_service.fetch_and_process_source(
                        source_obj, sync_db
                    )
                    if result.get("status") == "success":
                        fetched_count += 1
                        src_info["fetched"] = True
                        src_info["chunk_count"] = result.get("chunk_count", 0)
                except Exception as e:
                    logger.warning(f"Failed to fetch source {src_info['url'][:60]}: {e}")

        # Remaining sources stay as pending — the pending source fetcher will pick them up

        return {
            "topic_id": topic_id,
            "topic_title": topic.title,
            "sources_added": len(added_sources),
            "sources_fetched": fetched_count,
        }
    finally:
        sync_db.close()


# ─── Analogy-First Content Transformation ────────────────────────────────


@celery_app.task(
    name="app.tasks.learning.transform_topic_chunks",
    bind=True,
    queue="cognitive",
    max_retries=1
)
def transform_topic_chunks_task(self, user_id: str, topic_id: str):
    """
    Transform source chunks into analogy-based versions using anchor points.

    Dispatched when a user triggers /topics/{id}/transform or when
    anchors are validated. Rewrites chunks using the user's known domains
    so content is presented through familiar analogies.
    """
    logger.info(f"Starting analogy transformation for topic {topic_id}")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _transform_topic_chunks_async(user_id, topic_id)
        )
        logger.info(f"Analogy transformation complete for topic {topic_id}: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_transform_topic_chunks_async(user_id, topic_id))
        logger.info(f"Analogy transformation complete for topic {topic_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Analogy transformation failed for topic {topic_id}: {e}")
        raise self.retry(countdown=60, exc=e)


async def _transform_topic_chunks_async(user_id: str, topic_id: str):
    """Async implementation of analogy transformation for a topic."""
    from app.db.session import SessionLocal
    from app.services.learning_source_service import learning_source_service

    sync_db = SessionLocal()
    try:
        result = await learning_source_service.transform_topic_chunks(
            topic_id=topic_id,
            user_id=user_id,
            db=sync_db
        )
        return result
    finally:
        sync_db.close()
