"""
Outbox Processor Service

Guarantees eventual consistency between Postgres and Neo4j using the transactional outbox pattern.
Polls the event_outbox table and processes events with retry logic and exponential backoff.

Architecture:
- Postgres is the source of truth for existence queries (consistent reads)
- Neo4j is the enriched view for relationship traversal (eventually consistent)
- This processor bridges the gap with guaranteed delivery semantics
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Callable, Any, Optional
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class OutboxProcessor:
    """
    Processes events from the outbox table with polling and retry logic.

    Events flow through this processor to sync Postgres writes to Neo4j,
    with chained events for deep processing (e.g., episode_created -> episode_deep_analysis).
    """

    def __init__(self, poll_interval: int = 5, batch_size: int = 50, metrics_interval: int = 12):
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.metrics_interval = metrics_interval  # Emit metrics every N polls (12 * 5s = 1 min)
        self.is_running = False
        self.handlers: Dict[str, Callable] = {}
        self._poll_count = 0
        self._register_handlers()

    def _register_handlers(self):
        """Register event type handlers"""
        self.handlers = {
            # Neo4j sync events (fast path)
            "episode_created": self._handle_episode_sync,
            "episode_updated": self._handle_episode_sync,
            "note_created": self._handle_note_sync,
            "note_updated": self._handle_note_sync,
            "document_uploaded": self._handle_document_sync,
            "document_updated": self._handle_document_sync,

            # Deep processing events (slow path)
            "episode_deep_analysis": self._handle_episode_deep_analysis,
            "note_deep_analysis": self._handle_note_deep_analysis,

            # Insight and feedback events
            "insight_generated": self._handle_insight_backprop,
            "importance_decay": self._handle_importance_decay,
        }

    async def start(self):
        """Start the outbox processor worker"""
        if self.is_running:
            logger.warning("OutboxProcessor already running")
            return

        self.is_running = True
        logger.info(f"📬 OutboxProcessor started (poll_interval={self.poll_interval}s, batch_size={self.batch_size})")

        while self.is_running:
            try:
                processed_count = await self._process_batch()
                if processed_count > 0:
                    logger.info(f"📬 Processed {processed_count} outbox events")

                # Emit metrics periodically
                self._poll_count += 1
                if self._poll_count >= self.metrics_interval:
                    await self._emit_metrics()
                    self._poll_count = 0

            except Exception as e:
                logger.error(f"❌ OutboxProcessor batch error: {e}")

            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop the outbox processor"""
        self.is_running = False
        logger.info("📬 OutboxProcessor stopped")

    async def _emit_metrics(self):
        """Emit queue metrics for monitoring"""
        from app.main_simple import SessionLocal, EventOutbox

        db = SessionLocal()
        try:
            # Get counts by status and event_type
            stats = db.query(
                EventOutbox.status,
                EventOutbox.event_type,
                func.count(EventOutbox.id).label('count')
            ).group_by(
                EventOutbox.status,
                EventOutbox.event_type
            ).all()

            # Aggregate metrics
            pending_total = 0
            failed_total = 0
            pending_by_type = {}
            failed_by_type = {}

            for status, event_type, count in stats:
                if status == 'pending':
                    pending_total += count
                    pending_by_type[event_type] = count
                elif status == 'failed':
                    failed_total += count
                    failed_by_type[event_type] = count

            # Get average processing latency for recently completed events
            latency_result = db.query(
                func.avg(
                    func.extract('epoch', EventOutbox.processed_at) -
                    func.extract('epoch', EventOutbox.created_at)
                ).label('avg_latency')
            ).filter(
                EventOutbox.status == 'completed',
                EventOutbox.processed_at >= datetime.utcnow() - timedelta(minutes=5)
            ).first()

            avg_latency = latency_result.avg_latency if latency_result and latency_result.avg_latency else 0

            # Log metrics
            if pending_total > 0 or failed_total > 0:
                logger.info(
                    f"📊 Outbox metrics: pending={pending_total}, failed={failed_total}, "
                    f"avg_latency={avg_latency:.2f}s"
                )
                if pending_by_type:
                    logger.info(f"   Pending by type: {pending_by_type}")
                if failed_by_type:
                    logger.warning(f"   Failed by type: {failed_by_type}")
            else:
                logger.debug("📊 Outbox metrics: queue empty, no failures")

        except Exception as e:
            logger.error(f"❌ Failed to emit metrics: {e}")
        finally:
            db.close()

    async def _process_batch(self) -> int:
        """Process a batch of pending events"""
        from app.main_simple import SessionLocal, EventOutbox

        db = SessionLocal()
        processed = 0

        try:
            # Get pending events that are ready for processing
            # - status is pending or failed (for retry)
            # - retry_count < max_retries
            # - next_retry_at is null or in the past
            now = datetime.utcnow()

            events = db.query(EventOutbox).filter(
                and_(
                    EventOutbox.status.in_(["pending", "failed"]),
                    EventOutbox.retry_count < EventOutbox.max_retries,
                    or_(
                        EventOutbox.next_retry_at.is_(None),
                        EventOutbox.next_retry_at <= now
                    )
                )
            ).order_by(
                EventOutbox.created_at.asc()
            ).limit(self.batch_size).with_for_update(skip_locked=True).all()

            for event in events:
                await self._process_event(event, db)
                processed += 1

            db.commit()

        except Exception as e:
            logger.error(f"❌ Batch processing error: {e}")
            db.rollback()
        finally:
            db.close()

        return processed

    async def _process_event(self, event, db: Session):
        """Process a single event with error handling"""
        from app.main_simple import EventOutbox

        event.status = "processing"
        db.flush()

        handler = self.handlers.get(event.event_type)
        if not handler:
            logger.warning(f"⚠️ No handler for event type: {event.event_type}")
            event.status = "failed"
            event.last_error = f"Unknown event type: {event.event_type}"
            return

        try:
            payload = json.loads(event.payload)

            # Execute handler - may create chained events
            chained_events = await handler(payload, db)

            # Mark as completed
            event.status = "completed"
            event.processed_at = datetime.utcnow()
            event.last_error = None

            # Add any chained events
            if chained_events:
                for chained in chained_events:
                    db.add(chained)
                logger.info(f"📬 Event {event.event_type} created {len(chained_events)} chained events")

            logger.debug(f"✅ Processed event {event.id}: {event.event_type}")

        except Exception as e:
            logger.error(f"❌ Event {event.id} ({event.event_type}) failed: {e}")
            event.status = "failed"
            event.retry_count += 1
            event.last_error = str(e)[:1000]  # Truncate long errors

            # Exponential backoff: 30s, 1m, 2m, 4m, 8m
            backoff_seconds = 30 * (2 ** event.retry_count)
            event.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)

            if event.retry_count >= event.max_retries:
                logger.error(f"💀 Event {event.id} exhausted retries, will not retry")

    # ========================================
    # EVENT HANDLERS - Neo4j Sync (Fast Path)
    # ========================================

    async def _handle_episode_sync(self, payload: Dict[str, Any], db: Session) -> list:
        """Sync episode to Neo4j, then queue for deep analysis"""
        from app.services.neo4j_service import neo4j_service
        from app.main_simple import EventOutbox

        episode_id = payload.get("episode_id")
        user_id = payload.get("user_id")
        content = payload.get("content", "")
        role = payload.get("role", "user")
        importance = payload.get("importance", 0.5)
        source = payload.get("source", "chat")
        embedding = payload.get("embedding")
        conversation_id = payload.get("conversation_id")

        # Sync to Neo4j
        await neo4j_service.create_episode(
            episode_id=str(episode_id),
            user_id=str(user_id),
            content=content,
            role=role,
            importance=importance,
            source=source,
            embedding=embedding,
            conversation_id=conversation_id
        )

        logger.info(f"📊 Synced episode {episode_id} to Neo4j")

        # Chain: queue for deep analysis (only for user messages with substantial content)
        chained = []
        if role == "user" and len(content) > 50:
            deep_event = EventOutbox(
                event_type="episode_deep_analysis",
                aggregate_type="Episode",
                aggregate_id=str(episode_id),
                op="PROCESS",
                payload=json.dumps({
                    "episode_id": str(episode_id),
                    "user_id": str(user_id),
                    "content": content,
                    "conversation_id": conversation_id
                }),
                status="pending"
            )
            chained.append(deep_event)

        return chained

    async def _handle_note_sync(self, payload: Dict[str, Any], db: Session) -> list:
        """Sync note to Neo4j"""
        from app.services.neo4j_service import neo4j_service

        note_id = payload.get("note_id")
        user_id = payload.get("user_id")
        title = payload.get("title", "")
        content = payload.get("content", "")
        folder_id = payload.get("folder_id")
        embedding = payload.get("embedding")

        await neo4j_service.create_note(
            note_id=str(note_id),
            user_id=str(user_id),
            title=title,
            content=content,
            folder_id=folder_id,
            embedding=embedding
        )

        logger.info(f"📝 Synced note {note_id} to Neo4j")

        # Chain: queue for deep analysis if substantial content
        chained = []
        if len(content) > 100:
            from app.main_simple import EventOutbox
            deep_event = EventOutbox(
                event_type="note_deep_analysis",
                aggregate_type="Note",
                aggregate_id=str(note_id),
                op="PROCESS",
                payload=json.dumps({
                    "note_id": str(note_id),
                    "user_id": str(user_id),
                    "title": title,
                    "content": content
                }),
                status="pending"
            )
            chained.append(deep_event)

        return chained

    async def _handle_document_sync(self, payload: Dict[str, Any], db: Session) -> list:
        """Sync document to Neo4j"""
        from app.services.neo4j_service import neo4j_service

        doc_id = payload.get("document_id")
        user_id = payload.get("user_id")
        title = payload.get("title", "")
        content_text = payload.get("content_text", "")
        mime_type = payload.get("mime_type", "")
        file_path = payload.get("file_path")
        embedding = payload.get("embedding")

        await neo4j_service.create_document(
            doc_id=str(doc_id),
            user_id=str(user_id),
            title=title,
            content_text=content_text,
            mime_type=mime_type,
            file_path=file_path,
            embedding=embedding
        )

        logger.info(f"📄 Synced document {doc_id} to Neo4j")
        return []

    # ========================================
    # EVENT HANDLERS - Deep Processing (Slow Path)
    # ========================================

    async def _handle_episode_deep_analysis(self, payload: Dict[str, Any], db: Session) -> list:
        """Run LLM-based entity/topic extraction on episode"""
        from app.services.neo4j_service import neo4j_service

        episode_id = payload.get("episode_id")
        user_id = payload.get("user_id")
        content = payload.get("content", "")

        logger.info(f"🧠 Starting deep analysis for episode {episode_id}")

        # Extract entities and topics using LLM
        extracted = await self._llm_extract_entities(content, user_id)

        # Store entities in Neo4j and link to episode
        for entity in extracted.get("people", []):
            entity_node = await neo4j_service.create_or_find_entity(
                name=entity.get("name"),
                entity_type="Person"
            )
            if entity_node:
                await neo4j_service.create_entity_relationship(
                    content_id=str(episode_id),
                    entity_id=entity_node["id"],
                    rel_type="MENTIONS_PERSON"
                )

        for project in extracted.get("projects", []):
            entity_node = await neo4j_service.create_or_find_entity(
                name=project.get("name"),
                entity_type="Project"
            )
            if entity_node:
                await neo4j_service.create_entity_relationship(
                    content_id=str(episode_id),
                    entity_id=entity_node["id"],
                    rel_type="MENTIONS_PROJECT"
                )

        for topic in extracted.get("topics", []):
            topic_node = await neo4j_service.create_or_find_topic(
                name=topic.get("name"),
                topic_type=topic.get("type", "general")
            )
            if topic_node:
                await neo4j_service.create_topic_relationship(
                    content_id=str(episode_id),
                    topic_id=topic_node["id"],
                    rel_type="DISCUSSES",
                    strength=topic.get("confidence", 0.5)
                )

        logger.info(f"🧠 Deep analysis complete for episode {episode_id}: "
                   f"{len(extracted.get('people', []))} people, "
                   f"{len(extracted.get('projects', []))} projects, "
                   f"{len(extracted.get('topics', []))} topics")

        return []

    async def _handle_note_deep_analysis(self, payload: Dict[str, Any], db: Session) -> list:
        """Run LLM-based entity/topic extraction on note"""
        from app.services.neo4j_service import neo4j_service

        note_id = payload.get("note_id")
        user_id = payload.get("user_id")
        content = payload.get("content", "")

        logger.info(f"🧠 Starting deep analysis for note {note_id}")

        # Same extraction logic as episodes
        extracted = await self._llm_extract_entities(content, user_id)

        for entity in extracted.get("people", []):
            entity_node = await neo4j_service.create_or_find_entity(
                name=entity.get("name"),
                entity_type="Person"
            )
            if entity_node:
                await neo4j_service.create_entity_relationship(
                    content_id=str(note_id),
                    entity_id=entity_node["id"],
                    rel_type="MENTIONS_PERSON"
                )

        for project in extracted.get("projects", []):
            entity_node = await neo4j_service.create_or_find_entity(
                name=project.get("name"),
                entity_type="Project"
            )
            if entity_node:
                await neo4j_service.create_entity_relationship(
                    content_id=str(note_id),
                    entity_id=entity_node["id"],
                    rel_type="MENTIONS_PROJECT"
                )

        logger.info(f"🧠 Deep analysis complete for note {note_id}")
        return []

    async def _llm_extract_entities(self, content: str, user_id: str) -> Dict[str, Any]:
        """Use LLM to extract personal entities from content"""
        import httpx
        import os

        OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
        OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:120b")

        prompt = f"""Extract personal entities from this text. Include:
- People (with relationship to user if mentioned: "brother", "coworker", "friend")
- Projects (personal or work projects mentioned)
- Topics (main themes or subjects discussed)

Text:
{content[:2000]}

Return ONLY valid JSON in this exact format, no other text:
{{"people": [{{"name": "Mike", "relationship": "brother"}}], "projects": [{{"name": "Riverside project"}}], "topics": [{{"name": "fitness", "type": "health", "confidence": 0.8}}]}}
"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OPENAI_BASE_URL}/chat/completions",
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 500
                    }
                )
                response.raise_for_status()
                result = response.json()

                content_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not content_text or not content_text.strip():
                    logger.warning("LLM returned empty content for entity extraction")
                    return {"people": [], "projects": [], "topics": []}

                # Parse JSON from response
                # Try to extract JSON from response (handle markdown code blocks)
                if "```json" in content_text:
                    content_text = content_text.split("```json")[1].split("```")[0]
                elif "```" in content_text:
                    content_text = content_text.split("```")[1].split("```")[0]

                # Try to find JSON object in the response
                content_text = content_text.strip()
                if not content_text.startswith("{"):
                    # Try to find the first { in the response
                    start_idx = content_text.find("{")
                    if start_idx != -1:
                        content_text = content_text[start_idx:]

                parsed = json.loads(content_text)
                logger.debug(f"LLM extracted: {len(parsed.get('people', []))} people, {len(parsed.get('projects', []))} projects, {len(parsed.get('topics', []))} topics")
                return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"LLM entity extraction JSON parse failed: {e}, content was: {content_text[:200] if content_text else 'empty'}")
            return {"people": [], "projects": [], "topics": []}
        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}")
            return {"people": [], "projects": [], "topics": []}

    # ========================================
    # EVENT HANDLERS - Feedback Loop
    # ========================================

    async def _handle_insight_backprop(self, payload: Dict[str, Any], db: Session) -> list:
        """Backpropagate importance to episodes that generated an insight"""
        from app.main_simple import Episode

        insight_id = payload.get("insight_id")
        source_episode_ids = payload.get("source_episode_ids", [])
        importance_boost = payload.get("importance_boost", 0.1)

        logger.info(f"📈 Backpropagating importance from insight {insight_id} to {len(source_episode_ids)} episodes")

        for episode_id in source_episode_ids:
            episode = db.query(Episode).filter(Episode.id == episode_id).first()
            if episode:
                # Boost importance, cap at 1.0
                new_importance = min(1.0, (episode.importance or 0.5) + importance_boost)
                episode.importance = new_importance
                logger.debug(f"  Episode {episode_id}: importance {episode.importance:.2f} -> {new_importance:.2f}")

        return []

    async def _handle_importance_decay(self, payload: Dict[str, Any], db: Session) -> list:
        """Decay importance for episodes that haven't contributed to insights"""
        from app.main_simple import Episode
        from datetime import datetime, timedelta

        user_id = payload.get("user_id")
        decay_amount = payload.get("decay_amount", 0.05)
        min_importance = payload.get("min_importance", 0.1)
        days_threshold = payload.get("days_threshold", 30)

        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)

        # Find episodes that:
        # - Are older than threshold
        # - Have importance above floor
        # - Haven't been referenced recently (last_accessed or similar)
        fading_episodes = db.query(Episode).filter(
            Episode.user_id == user_id,
            Episode.importance > min_importance,
            Episode.created_at < cutoff_date
        ).all()

        decayed_count = 0
        for episode in fading_episodes:
            new_importance = max(min_importance, (episode.importance or 0.5) - decay_amount)
            if new_importance < episode.importance:
                episode.importance = new_importance
                decayed_count += 1

        logger.info(f"📉 Decayed importance for {decayed_count} episodes (user {user_id})")
        return []


# Global instance
outbox_processor = OutboxProcessor()
