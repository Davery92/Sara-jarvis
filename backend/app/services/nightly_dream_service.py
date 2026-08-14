"""
Nightly Dream Sequence Service
Processes daily conversations using content intelligence pipeline.
Runs once per night to consolidate the day's interactions into meaningful knowledge.
"""
import asyncio
import logging
import os
import uuid as _uuid
from datetime import datetime, timedelta, time
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
import pytz
from app.core.redis import get_redis

from app.core.timezone import now as local_now
from app.core.config import get_owner_id

from app.db.session import SessionLocal
from app.models.episode import Episode
from app.services.content_intelligence import content_intelligence, ContentType
from app.services.metadata_extractor import metadata_extractor
from app.services.tagging_system import smart_tagger
from app.services.enhanced_neo4j_schema import enhanced_neo4j

logger = logging.getLogger(__name__)

DREAM_LOCK_KEY = "sara:dream_scheduler_lock"
DREAM_LOCK_TTL = 120  # seconds
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SOLO_USER_ID = get_owner_id()

RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class NightlyDreamService:
    """Intelligent nightly processing of daily conversations and content"""

    def __init__(self):
        self.eastern_tz = pytz.timezone('America/New_York')
        self.dream_time = time(2, 0)  # 2:00 AM Eastern
        self.is_dreaming = False
        self.last_dream_date = None
        self._owner_token: str = ""
        logger.info("NightlyDreamService initialized - dreams at 2:00 AM Eastern time")

    async def start_dream_scheduler(self):
        """Start the nightly dream scheduler with Redis distributed lock."""
        self._owner_token = str(_uuid.uuid4())
        r = await get_redis()

        # Acquire lock
        acquired = await r.set(DREAM_LOCK_KEY, self._owner_token, nx=True, ex=DREAM_LOCK_TTL)
        if not acquired:
            logger.warning("Dream scheduler already running (lock held by another instance)")
            return

        logger.info("Starting nightly dream scheduler (lock acquired)...")
        try:
            while True:
                try:
                    # Refresh lock ownership
                    current = await r.get(DREAM_LOCK_KEY)
                    if current != self._owner_token:
                        logger.error("Dream scheduler lost lock - another instance took over")
                        return
                    await r.expire(DREAM_LOCK_KEY, DREAM_LOCK_TTL)

                    # Get current time in Eastern timezone
                    utc_now = datetime.now(pytz.UTC)
                    eastern_now = utc_now.astimezone(self.eastern_tz)

                    # Check if it's time to dream and we haven't dreamed today
                    if self._should_dream(eastern_now):
                        logger.info(f"Time to dream! It's {eastern_now.strftime('%I:%M %p')} Eastern")
                        await self._run_nightly_dream_cycle()
                        self.last_dream_date = eastern_now.date()

                    # Sleep for 60 seconds (must refresh faster than TTL)
                    await asyncio.sleep(60)

                except Exception as e:
                    logger.error(f"Dream scheduler error: {e}")
                    await asyncio.sleep(60)
        finally:
            # Compare-and-delete via Lua to avoid race release
            try:
                await r.eval(RELEASE_SCRIPT, 1, DREAM_LOCK_KEY, self._owner_token)
            except Exception:
                pass
    
    def _should_dream(self, eastern_now: datetime) -> bool:
        """Check if we should run the dream sequence (Eastern time)"""
        current_time = eastern_now.time()
        current_date = eastern_now.date()

        # Dream window: 2:00 AM - 3:00 AM Eastern only
        dream_start = time(2, 0)
        dream_end = time(3, 0)
        is_dream_time = dream_start <= current_time < dream_end
        havent_dreamed_today = (self.last_dream_date is None or self.last_dream_date < current_date)
        not_currently_dreaming = not self.is_dreaming

        if is_dream_time and havent_dreamed_today and not_currently_dreaming:
            logger.info(f"🌙 Dream conditions met: {eastern_now.strftime('%I:%M %p')} Eastern on {current_date}")
            return True

        return False
    
    async def _run_nightly_dream_cycle(self):
        """Run the complete nightly dream cycle"""
        if self.is_dreaming:
            logger.info("🌙 Already dreaming, skipping cycle")
            return
        
        try:
            self.is_dreaming = True
            logger.info("🌙 Starting nightly dream cycle...")
            
            # Solo-user deployment: HA/workout/location events aren't user-scoped,
            # so looping all app_user rows (including test accounts) cloned David's
            # home patterns onto every test account. Scope to the real user only.
            eastern_yesterday = (
                datetime.now(pytz.UTC).astimezone(self.eastern_tz) - timedelta(days=1)
            ).date()

            await self._process_user_daily_conversations(SOLO_USER_ID)
            await self._consolidate_inbox_items(SOLO_USER_ID)
            # Pattern detection learns from HA/workout/meal data, so it must
            # run even on days with no chat — _process_user_daily_conversations
            # returns early when there were no conversations yesterday.
            await self._run_full_day_replay_and_pattern_detection(
                SOLO_USER_ID, eastern_yesterday
            )

            logger.info("🌙 Nightly dream cycle complete!")
            
        except Exception as e:
            logger.error(f"❌ Nightly dream cycle failed: {e}")
        finally:
            self.is_dreaming = False
    
    async def _process_user_daily_conversations(self, user_id: str):
        """Process one user's daily conversations using content intelligence"""
        logger.info(f"🌙 Processing conversations for user {user_id}")
        
        try:
            # Get yesterday's conversations (episodes) in Eastern time
            utc_now = datetime.now(pytz.UTC)
            eastern_now = utc_now.astimezone(self.eastern_tz)
            eastern_yesterday = eastern_now - timedelta(days=1)
            daily_episodes = await self._get_daily_episodes(user_id, eastern_yesterday)
            
            if not daily_episodes:
                logger.info(f"   No conversations from yesterday for user {user_id}")
                return
            
            logger.info(f"   Found {len(daily_episodes)} conversations to process")
            
            # Group episodes into conversation sessions
            conversation_sessions = self._group_episodes_into_sessions(daily_episodes)
            
            # Process each conversation session with content intelligence
            for session_id, session_episodes in conversation_sessions.items():
                await self._process_conversation_session(user_id, session_id, session_episodes)
            
            # Generate daily summary and insights
            await self._generate_daily_summary(user_id, daily_episodes)
            
            # Also run the dreaming service to generate PostgreSQL insights
            from app.main_simple import dreaming_service
            if len(daily_episodes) >= 3:  # Only run if there are enough episodes
                logger.info(f"   💭 Running dream cycle to generate insights...")
                await dreaming_service.dream_cycle(user_id, min_episodes=3)

            # Run cognitive enhancement processing
            await self._run_cognitive_processing(user_id, conversation_sessions)

            # Extract personal knowledge for the PKG
            await self._extract_personal_knowledge(user_id, conversation_sessions, daily_episodes)

            # (Day replay + pattern detection moved to _run_nightly_dream_cycle so
            # it runs even when there were no conversations yesterday.)

            logger.info(f"✅ Processed {len(conversation_sessions)} conversation sessions for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to process conversations for user {user_id}: {e}")
    
    async def _get_daily_episodes(self, user_id: str, target_date: datetime) -> List[Episode]:
        """Get all episodes from a specific day"""
        db = SessionLocal()
        try:
            # Ensure user_id is a string to avoid UUID casting issues
            user_id_str = str(user_id)
            
            start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            # Query only existing columns to avoid meta column error
            episodes = db.query(
                Episode.id,
                Episode.user_id, 
                Episode.source,
                Episode.role,
                Episode.content,
                Episode.importance,
                Episode.created_at
            ).filter(
                Episode.user_id == user_id_str,
                Episode.created_at >= start_of_day,
                Episode.created_at < end_of_day
            ).order_by(Episode.created_at).all()
            
            return episodes
            
        finally:
            db.close()
    
    def _group_episodes_into_sessions(self, episodes: List[Episode]) -> Dict[str, List[Episode]]:
        """Group episodes into conversation sessions based on time gaps"""
        sessions = {}
        current_session = []
        session_id = 1
        
        for i, episode in enumerate(episodes):
            if current_session:
                # If more than 30 minutes gap, start new session
                time_gap = (episode.created_at - current_session[-1].created_at).total_seconds()
                if time_gap > 1800:  # 30 minutes
                    sessions[f"session_{session_id}"] = current_session
                    session_id += 1
                    current_session = [episode]
                else:
                    current_session.append(episode)
            else:
                current_session = [episode]
        
        # Add final session
        if current_session:
            sessions[f"session_{session_id}"] = current_session
        
        return sessions
    
    async def _process_conversation_session(self, user_id: str, session_id: str, episodes: List[Episode]):
        """Process a conversation session using content intelligence pipeline"""
        logger.info(f"   🧠 Processing {session_id} with {len(episodes)} messages")
        
        try:
            # Combine session episodes into conversation text
            conversation_content = self._combine_episodes_to_conversation(episodes)
            
            # Create session title and ID
            session_title = f"Conversation Session - {episodes[0].created_at.strftime('%Y-%m-%d %H:%M')}"
            session_content_id = f"{user_id}_conversation_{session_id}_{episodes[0].created_at.strftime('%Y%m%d_%H%M')}"
            
            # Step 1: Content Intelligence - detect type and chunk
            content_type, chunks = content_intelligence.process_content(
                conversation_content, 
                session_title
            )
            logger.info(f"     ✅ Detected as {content_type.value}, {len(chunks)} chunks")
            
            # Step 2: Extract metadata (entities, topics, urgency, etc.)
            metadata = metadata_extractor.extract_metadata(
                conversation_content,
                content_type,
                session_title
            )
            logger.info(f"     ✅ Extracted {len(metadata.entities)} entities, {len(metadata.topics)} topics")
            
            # Step 3: Generate smart tags
            tags = smart_tagger.generate_tags(
                conversation_content,
                metadata,
                content_type,
                session_title
            )
            logger.info(f"     ✅ Generated {len(tags)} smart tags")
            
            # Step 4: Store in Neo4j with full intelligence
            # Note: store_intelligent_content is now synchronous, so we run it in a thread pool
            success = await asyncio.to_thread(
                enhanced_neo4j.store_intelligent_content,
                content_id=session_content_id,
                user_id=user_id,
                title=session_title,
                content=conversation_content,
                content_type=content_type,
                chunks=chunks,
                metadata=metadata,
                tags=tags
            )
            
            if success:
                logger.info(f"     ✅ Stored intelligent conversation session: {session_id}")
                
                # Create meaningful connections with existing content
                await self._create_meaningful_connections(session_content_id, metadata, tags)
            else:
                logger.error(f"     ❌ Failed to store session: {session_id}")
                
        except Exception as e:
            logger.error(f"❌ Failed to process session {session_id}: {e}")
    
    def _combine_episodes_to_conversation(self, episodes: List[Episode]) -> str:
        """Combine episodes into a readable conversation format"""
        conversation_parts = []
        
        for episode in episodes:
            timestamp = episode.created_at.strftime("%H:%M")
            role = episode.role or "user"
            content = episode.content or ""
            
            # Format as conversation
            if role == "user":
                conversation_parts.append(f"[{timestamp}] User: {content}")
            else:
                conversation_parts.append(f"[{timestamp}] Sara: {content}")
        
        return "\n\n".join(conversation_parts)
    
    async def _create_meaningful_connections(self, session_id: str, metadata, tags):
        """Create meaningful connections based on shared content, not random similarity"""
        try:
            # Find related content by shared entities
            if metadata.entities:
                entity_names = [e.name for e in metadata.entities if e.confidence > 0.7]
                if entity_names:
                    await self._connect_by_shared_entities(session_id, entity_names)
            
            # Find related content by shared topics
            if metadata.topics:
                topic_names = [t.name for t in metadata.topics if t.confidence > 0.5]
                if topic_names:
                    await self._connect_by_shared_topics(session_id, topic_names)
            
            # Find related content by shared high-priority tags
            if tags:
                priority_tags = [t.name for t in tags if t.priority.value in ['critical', 'high']]
                if priority_tags:
                    await self._connect_by_shared_tags(session_id, priority_tags)
            
            logger.info(f"     ✅ Created meaningful connections for {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to create connections for {session_id}: {e}")
    
    async def _connect_by_shared_entities(self, session_id: str, entity_names: List[str]):
        """Connect content that shares significant entities"""
        try:
            from app.services.neo4j_service import neo4j_service
            with neo4j_service.driver.session() as session:
                # Find other content that shares these entities
                query = """
                MATCH (source:Content {id: $session_id})
                MATCH (other:Content)-[:CONTAINS_ENTITY]->(entity:Entity)
                WHERE entity.name IN $entity_names 
                  AND other.id <> $session_id
                
                // Count shared entities and calculate connection strength
                WITH source, other, collect(entity.name) as shared_entities, 
                     count(entity) as shared_count
                WHERE shared_count >= 2  // Require at least 2 shared entities
                
                // Create meaningful connection
                MERGE (source)-[r:SHARES_ENTITIES]->(other)
                SET r.shared_entities = shared_entities,
                    r.connection_strength = shared_count * 0.2,
                    r.connection_type = 'entity_based',
                    r.created_at = datetime(),
                    r.auto_generated = true
                
                RETURN other.title as connected_title, shared_entities, shared_count
                """
                
                result = session.run(query, session_id=session_id, entity_names=entity_names)
                connections = list(result)
                
                if connections:
                    logger.info(f"     ✅ Created {len(connections)} entity-based connections")
                
        except Exception as e:
            logger.error(f"❌ Entity connection failed: {e}")
    
    async def _connect_by_shared_topics(self, session_id: str, topic_names: List[str]):
        """Connect content that shares topics"""
        try:
            from app.services.neo4j_service import neo4j_service
            with neo4j_service.driver.session() as session:
                # Find content sharing significant topics
                query = """
                MATCH (source:Content {id: $session_id})
                MATCH (other:Content)-[:HAS_TOPIC]->(topic:Topic)
                WHERE topic.name IN $topic_names 
                  AND other.id <> $session_id
                
                // Group by other content and calculate topic overlap
                WITH source, other, collect(topic.name) as shared_topics,
                     avg(topic.confidence) as avg_confidence
                WHERE size(shared_topics) >= 1 
                  AND avg_confidence > 0.4
                
                // Create topic-based connection
                MERGE (source)-[r:SHARES_TOPICS]->(other) 
                SET r.shared_topics = shared_topics,
                    r.connection_strength = avg_confidence,
                    r.connection_type = 'topic_based',
                    r.created_at = datetime(),
                    r.auto_generated = true
                
                RETURN other.title as connected_title, shared_topics, avg_confidence
                """
                
                result = session.run(query, session_id=session_id, topic_names=topic_names)
                connections = list(result)
                
                if connections:
                    logger.info(f"     ✅ Created {len(connections)} topic-based connections")
                    
        except Exception as e:
            logger.error(f"❌ Topic connection failed: {e}")
    
    async def _connect_by_shared_tags(self, session_id: str, tag_names: List[str]):
        """Connect content that shares high-priority tags"""
        try:
            from app.services.neo4j_service import neo4j_service
            with neo4j_service.driver.session() as session:
                # Find content sharing high-priority tags
                query = """
                MATCH (source:Content {id: $session_id})
                MATCH (other:Content)-[:HAS_TAG]->(tag:Tag)
                WHERE tag.name IN $tag_names 
                  AND tag.priority IN ['critical', 'high']
                  AND other.id <> $session_id
                
                // Group by content and count shared priority tags
                WITH source, other, collect(tag.name) as shared_tags,
                     count(tag) as priority_tag_count,
                     avg(tag.confidence) as avg_confidence
                WHERE priority_tag_count >= 1
                
                // Create context-based connection
                MERGE (source)-[r:SHARES_CONTEXT]->(other)
                SET r.shared_tags = shared_tags,
                    r.connection_strength = priority_tag_count * avg_confidence,
                    r.connection_type = 'context_based', 
                    r.created_at = datetime(),
                    r.auto_generated = true
                
                RETURN other.title as connected_title, shared_tags, priority_tag_count
                """
                
                result = session.run(query, session_id=session_id, tag_names=tag_names)
                connections = list(result)
                
                if connections:
                    logger.info(f"     ✅ Created {len(connections)} context-based connections")
                    
        except Exception as e:
            logger.error(f"❌ Context connection failed: {e}")
    
    async def _generate_daily_summary(self, user_id: str, daily_episodes: List[Episode]):
        """Generate intelligent daily summary and insights"""
        logger.info(f"   📊 Generating daily summary for user {user_id}")
        
        try:
            # Analyze conversation themes
            themes = await self._extract_daily_themes(daily_episodes)
            
            # Detect mood patterns  
            mood_patterns = await self._analyze_daily_mood(daily_episodes)
            
            # Identify key decisions or commitments
            key_outcomes = await self._identify_key_outcomes(daily_episodes)
            
            # Track progress on ongoing topics
            progress_updates = await self._track_topic_progress(user_id, daily_episodes)
            
            # Generate summary content
            summary_content = self._format_daily_summary(
                themes, mood_patterns, key_outcomes, progress_updates
            )
            
            # Store as special summary content
            summary_id = f"{user_id}_daily_summary_{local_now().strftime('%Y%m%d')}"
            
            # Process summary through intelligence pipeline
            content_type, chunks = content_intelligence.process_content(
                summary_content, 
                f"Daily Summary - {local_now().strftime('%Y-%m-%d')}"
            )
            
            metadata = metadata_extractor.extract_metadata(
                summary_content, content_type
            )
            
            tags = smart_tagger.generate_tags(
                summary_content, metadata, content_type
            )
            
            # Add special summary tags
            from app.services.tagging_system import Tag, TagCategory, TagPriority
            summary_tag = Tag(
                name="daily_summary",
                category=TagCategory.CONTEXT,
                priority=TagPriority.HIGH,
                confidence=1.0,
                description="Automatically generated daily summary"
            )
            tags.append(summary_tag)
            
            # Store intelligent summary
            # Note: store_intelligent_content is now synchronous, so we run it in a thread pool
            await asyncio.to_thread(
                enhanced_neo4j.store_intelligent_content,
                content_id=summary_id,
                user_id=user_id,
                title=f"Daily Summary - {local_now().strftime('%Y-%m-%d')}",
                content=summary_content,
                content_type=content_type,
                chunks=chunks,
                metadata=metadata,
                tags=tags
            )
            
            logger.info(f"   ✅ Generated and stored daily summary")

            # Update Daily Brief context layer with dream insights
            try:
                from app.services.daily_brief import context_layer
                await context_layer.update_from_dream_insights(
                    user_id=user_id,
                    daily_summary=summary_content,
                    themes=themes,
                    key_outcomes=key_outcomes
                )
                logger.info(f"   📋 Updated Daily Brief context layer with dream insights")
            except ImportError:
                logger.debug("Daily Brief service not available, skipping context layer update")
            except Exception as brief_error:
                logger.warning(f"   ⚠️ Failed to update Daily Brief context layer: {brief_error}")

        except Exception as e:
            logger.error(f"❌ Failed to generate daily summary: {e}")
    
    async def _extract_daily_themes(self, episodes: List[Episode]) -> List[str]:
        """Extract main themes from daily conversations"""
        # Analyze episode content for recurring topics and themes
        all_content = " ".join([ep.content for ep in episodes if ep.content])
        
        # Use content intelligence to identify themes
        if all_content:
            content_type, _ = content_intelligence.process_content(all_content)
            metadata = metadata_extractor.extract_metadata(all_content, content_type)
            return [topic.name for topic in metadata.topics if topic.confidence > 0.4]
        
        return []
    
    async def _analyze_daily_mood(self, episodes: List[Episode]) -> Dict[str, float]:
        """Analyze mood patterns throughout the day"""
        # Simple mood detection based on content
        mood_keywords = {
            'positive': ['happy', 'excited', 'great', 'awesome', 'love', 'good', 'wonderful'],
            'negative': ['sad', 'frustrated', 'angry', 'difficult', 'problem', 'issue'],
            'neutral': ['okay', 'fine', 'normal'],
            'energetic': ['motivated', 'ready', 'energetic', 'pumped']
        }
        
        mood_scores = {mood: 0 for mood in mood_keywords.keys()}
        total_content = ""
        
        for episode in episodes:
            if episode.content and episode.role == "user":
                total_content += " " + episode.content.lower()
        
        # Count mood indicators
        for mood, keywords in mood_keywords.items():
            score = sum(1 for keyword in keywords if keyword in total_content)
            mood_scores[mood] = score
        
        return mood_scores
    
    async def _identify_key_outcomes(self, episodes: List[Episode]) -> List[str]:
        """Identify key decisions, commitments, or outcomes from conversations"""
        outcomes = []
        
        for episode in episodes:
            if episode.content:
                content_lower = episode.content.lower()
                
                # Look for decision indicators
                if any(word in content_lower for word in ['decided', 'will do', 'commit to', 'plan to']):
                    outcomes.append(episode.content[:100] + "...")
                
                # Look for completion indicators  
                if any(word in content_lower for word in ['completed', 'finished', 'done with']):
                    outcomes.append(episode.content[:100] + "...")
        
        return outcomes[:5]  # Limit to top 5
    
    async def _track_topic_progress(self, user_id: str, episodes: List[Episode]) -> Dict[str, str]:
        """Track progress on ongoing topics and projects"""
        # This would connect with existing content to see topic evolution
        # For now, return empty dict - full implementation would analyze
        # topic progression over time using Neo4j queries
        return {}
    
    def _format_daily_summary(self, themes: List[str], moods: Dict[str, float], 
                             outcomes: List[str], progress: Dict[str, str]) -> str:
        """Format all daily insights into a comprehensive summary"""
        summary_parts = []
        
        summary_parts.append(f"# Daily Summary - {local_now().strftime('%Y-%m-%d')}")
        summary_parts.append("")
        
        if themes:
            summary_parts.append("## Main Topics Discussed")
            for theme in themes:
                summary_parts.append(f"- {theme.title()}")
            summary_parts.append("")
        
        if any(score > 0 for score in moods.values()):
            summary_parts.append("## Mood Patterns")
            for mood, score in moods.items():
                if score > 0:
                    summary_parts.append(f"- {mood.title()}: {score} indicators")
            summary_parts.append("")
        
        if outcomes:
            summary_parts.append("## Key Outcomes & Decisions")
            for outcome in outcomes:
                summary_parts.append(f"- {outcome}")
            summary_parts.append("")
        
        if progress:
            summary_parts.append("## Progress Updates")
            for topic, update in progress.items():
                summary_parts.append(f"- {topic}: {update}")
            summary_parts.append("")
        
        summary_parts.append("---")
        summary_parts.append("*Generated by Sara's nightly dream sequence*")

        return "\n".join(summary_parts)

    async def _run_cognitive_processing(self, user_id: str, conversation_sessions: Dict[str, List[Episode]]):
        """Run cognitive enhancement processing (self-reflection, hypothesis analysis)"""
        logger.info(f"   🧠 Running cognitive enhancement processing...")

        try:
            from app.services.sara_identity_service import sara_identity_service
            from app.services.hypothesis_service import hypothesis_service
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                # Process each conversation session for reflections and hypotheses
                for session_id, episodes in conversation_sessions.items():
                    # Convert episodes to dict format for analysis
                    conversation_episodes = []
                    for ep in episodes:
                        conversation_episodes.append({
                            "id": str(ep.id),
                            "role": ep.role,
                            "content": ep.content,
                            "created_at": ep.created_at
                        })

                    # Skip very short conversations
                    if len(conversation_episodes) < 2:
                        continue

                    # Analyze for self-reflections
                    reflections = await sara_identity_service.analyze_conversation_for_reflections(
                        db=db,
                        conversation_episodes=conversation_episodes
                    )
                    if reflections:
                        logger.info(f"     💭 Created {len(reflections)} reflections from {session_id}")

                    # Extract hypotheses
                    hypotheses = await hypothesis_service.extract_hypotheses_from_conversation(
                        db=db,
                        conversation_episodes=conversation_episodes
                    )
                    if hypotheses:
                        logger.info(f"     💡 Extracted {len(hypotheses)} hypotheses from {session_id}")

                # Decay stale hypotheses
                await hypothesis_service.decay_stale_hypotheses(db)
                logger.info(f"     🧹 Cleaned up stale hypotheses")

            finally:
                db.close()

            logger.info(f"   ✅ Cognitive enhancement processing complete")

        except Exception as e:
            logger.error(f"❌ Cognitive enhancement processing failed: {e}")

    async def _extract_personal_knowledge(self, user_id: str, conversation_sessions: Dict[str, List[Episode]], daily_episodes: List[Episode]):
        """Extract personal knowledge about David into the PKG from the day's conversations"""
        try:
            from app.services.pkg_extractor import pkg_extractor
            from app.services.personal_knowledge_graph import personal_kg

            # Combine all conversation sessions into text
            conversation_text = ""
            for session_id, episodes in conversation_sessions.items():
                conversation_text += f"\n--- Session {session_id} ---\n"
                for ep in episodes:
                    role = getattr(ep, 'role', 'unknown')
                    content = getattr(ep, 'content', '')
                    if role == 'user':
                        conversation_text += f"David: {content}\n"
                    elif role == 'assistant':
                        conversation_text += f"Sara: {content}\n"

            if len(conversation_text.strip()) < 100:
                logger.info(f"   PKG: Skipping extraction - too little conversation text")
                return

            # Run deep extraction
            logger.info(f"   🧠 PKG: Starting deep knowledge extraction ({len(conversation_text)} chars)...")
            result = await pkg_extractor.deep_extract(conversation_text, user_id)

            extracted = result.get("extracted", [])
            contradictions = result.get("contradictions", [])
            stats = result.get("stats", {})

            # Run stale knowledge decay as maintenance, then propagate the
            # new Neo4j confidence values to the pgvector shadow — decay
            # only ever touches Neo4j, and query_semantic()'s merge fallback
            # reads the shadow, so without this the shadow keeps serving
            # pre-decay confidence indefinitely.
            personal_kg.decay_stale_knowledge(days_threshold=90)
            reconcile_stats = personal_kg.reconcile_embedding_confidence()
            logger.info(f"   PKG: shadow reconcile — {reconcile_stats}")

            logger.info(f"   🧠 PKG: Extracted {stats.get('total', 0)} facts "
                       f"(types: {stats.get('by_type', {})}), "
                       f"{len(contradictions)} contradictions found")

        except Exception as e:
            logger.error(f"❌ PKG extraction failed (non-critical): {e}")

    async def _consolidate_inbox_items(self, user_id: str):
        """Consolidate kept inbox items into episodic memory."""
        logger.info(f"   📥 Consolidating kept inbox items for user {user_id}")

        try:
            from app.models.shared_content import SharedContent
            from app.models.episode import Episode
            from app.services.embedding_service import embedding_service
            import uuid
            import json

            db = SessionLocal()
            try:
                # Find kept, unconsolidated items
                items = db.query(SharedContent).filter(
                    SharedContent.user_id == user_id,
                    SharedContent.status == "kept",
                    SharedContent.consolidated == False,
                    SharedContent.extraction_status == "extracted",
                ).all()

                if not items:
                    logger.info(f"   📥 No inbox items to consolidate for user {user_id}")
                    return

                logger.info(f"   📥 Consolidating {len(items)} kept inbox items...")

                for item in items:
                    try:
                        # Summarize using LLM
                        summary = await self._summarize_inbox_item(item)
                        if not summary:
                            summary = (item.description or item.title or "Shared content")[:300]

                        # Create episode
                        episode_id = str(uuid.uuid4())
                        episode = Episode(
                            id=episode_id,
                            user_id=user_id,
                            source="content_inbox",
                            role="system",
                            content=summary,
                            importance=0.6,
                            base_importance=0.6,
                        )

                        # Generate embedding for the episode. Background
                        # dreaming — presence-latency ruling 1 (2026-07-31):
                        # routes to the CPU fallback host, never the GPU
                        # host a real chat turn needs.
                        emb = await embedding_service.generate_embedding(summary, capability="embedding_cognition")
                        if emb:
                            episode.embedding = emb

                        db.add(episode)

                        # Mark item as consolidated
                        item.consolidated = True
                        item.consolidated_at = datetime.now(pytz.UTC)
                        item.episode_id = episode_id

                        db.commit()
                        logger.info(f"   📥 Consolidated: {item.title} -> episode {episode_id}")

                    except Exception as e:
                        logger.error(f"   ❌ Failed to consolidate item {item.id}: {e}")
                        db.rollback()
                        continue

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Inbox consolidation failed: {e}")

    async def _summarize_inbox_item(self, item) -> Optional[str]:
        """Use LLM to summarize an inbox item for memory consolidation."""
        try:
            from app.main_simple import call_llm_simple

            text_content = (item.extracted_text or "")[:4000]
            if not text_content:
                return None

            prompt = (
                f"Summarize this {item.content_type} that David shared and decided to keep.\n"
                f"Title: {item.title} | Source: {item.original_url or 'shared file'}\n\n"
                f"{text_content}\n\n"
                f"Write 2-4 sentences capturing the key points David would want to remember. "
                f"Include what it's about, why it might matter to him, and any actionable takeaways."
            )

            summary = await call_llm_simple(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            return summary.strip() if summary else None

        except Exception as e:
            logger.warning(f"LLM summarization failed for inbox item: {e}")
            return None

    async def _run_full_day_replay_and_pattern_detection(self, user_id: str, replay_date):
        """
        Run FULL day replay and pattern detection.

        This is like the human brain's memory consolidation during sleep -
        replaying ALL events from the day (not just conversations) and
        detecting behavioral patterns that can be used for proactive suggestions.
        """
        logger.info(f"   🧠 Running full day replay and pattern detection...")

        try:
            from app.services.day_replay_builder import day_replay_builder
            from app.services.pattern_detector import pattern_detector
            from app.services.weather_service import weather_service
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                # Step 1: Build full day replay from ALL data sources
                logger.info(f"   📼 Building full day replay for {replay_date}...")
                replay = await day_replay_builder.build_replay(db, user_id, replay_date)

                if replay.total_events == 0:
                    logger.info(f"   ℹ️ No events to replay for {replay_date}")
                    return

                logger.info(
                    f"   ✅ Day replay built: {replay.total_events} events from "
                    f"{len(replay.data_sources_included)} sources: {', '.join(replay.data_sources_included)}"
                )

                # Step 2: Get weather data for context
                weather_history = {}
                try:
                    weather = await weather_service.get_weather()
                    if weather:
                        weather_history[replay_date] = {
                            "current_temp": weather.current.temperature,
                            "temp_high": weather.forecast[0].temp_high if weather.forecast else None,
                            "temp_low": weather.forecast[0].temp_low if weather.forecast else None,
                            "description": weather.current.description
                        }
                except Exception as we:
                    logger.warning(f"   ⚠️ Failed to get weather for pattern detection: {we}")

                # Step 3: Cache the replay for future analysis
                await day_replay_builder.cache_replay(db, replay)

                # Step 4: Run pattern detection across recent days
                logger.info(f"   🔍 Running pattern detection...")
                detection_result = await pattern_detector.run_detection_cycle(db, user_id)

                if detection_result.get("patterns_detected", 0) > 0:
                    logger.info(
                        f"   ✅ Pattern detection complete: {detection_result['patterns_detected']} patterns "
                        f"detected from {detection_result.get('days_analyzed', 0)} days of data"
                    )
                else:
                    logger.info(f"   ℹ️ No new patterns detected")

            finally:
                db.close()

        except ImportError as ie:
            logger.warning(f"   ⚠️ Day replay/pattern detection not available: {ie}")
        except Exception as e:
            logger.error(f"   ❌ Full day replay failed: {e}")


# Global service instance
nightly_dream_service = NightlyDreamService()