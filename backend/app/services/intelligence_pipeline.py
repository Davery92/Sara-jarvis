"""
Intelligent content processing pipeline for Neo4j-first architecture.
Handles progressive enhancement of content with semantic analysis and relationship detection.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import json
from enum import Enum

from app.services.neo4j_service import neo4j_service
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

class ProcessingStage(Enum):
    CREATED = "created"
    FAST_PROCESSING = "fast_processing"
    FAST_READY = "fast_ready"
    DEEP_PROCESSING = "deep_processing"
    FULLY_PROCESSED = "fully_processed"
    ERROR = "error"

class ContentType(Enum):
    NOTE = "note"
    DOCUMENT = "document"
    EPISODE = "episode"

class IntelligenceTask:
    def __init__(self, content_id: str, content_type: ContentType, stage: ProcessingStage, 
                 priority: int = 1, metadata: Dict = None):
        self.content_id = content_id
        self.content_type = content_type
        self.stage = stage
        self.priority = priority
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)
        
class IntelligencePipeline:
    """Main intelligence processing pipeline for content enhancement"""
    
    def __init__(self):
        self.fast_queue = asyncio.Queue()
        self.deep_queue = asyncio.Queue()
        self.is_running = False
        
    async def start_workers(self):
        """Start background processing workers"""
        if self.is_running:
            return
            
        self.is_running = True
        logger.info("🧠 Starting intelligence pipeline workers...")
        
        # Start fast processing workers (2-5 second tasks)
        asyncio.create_task(self.fast_worker("fast-worker-1"))
        asyncio.create_task(self.fast_worker("fast-worker-2"))
        
        # Start deep processing worker (30+ second tasks)
        asyncio.create_task(self.deep_worker("deep-worker-1"))
        
        logger.info("✅ Intelligence pipeline workers started")
    
    async def queue_fast_processing(self, content_id: str, content_type: ContentType, 
                                  metadata: Dict = None):
        """Queue content for fast intelligence processing"""
        task = IntelligenceTask(
            content_id=content_id,
            content_type=content_type,
            stage=ProcessingStage.FAST_PROCESSING,
            priority=1,
            metadata=metadata
        )
        await self.fast_queue.put(task)
        logger.info(f"🚀 Queued {content_type.value} {content_id} for fast processing")
        
    async def queue_deep_processing(self, content_id: str, content_type: ContentType,
                                  metadata: Dict = None):
        """Queue content for deep intelligence processing"""
        task = IntelligenceTask(
            content_id=content_id,
            content_type=content_type,
            stage=ProcessingStage.DEEP_PROCESSING,
            priority=2,
            metadata=metadata
        )
        await self.deep_queue.put(task)
        logger.info(f"🧠 Queued {content_type.value} {content_id} for deep processing")
    
    async def fast_worker(self, worker_id: str):
        """Fast processing worker - handles 2-5 second intelligence tasks"""
        logger.info(f"⚡ Fast worker {worker_id} started")
        
        while self.is_running:
            try:
                # Wait for tasks with timeout
                task = await asyncio.wait_for(self.fast_queue.get(), timeout=1.0)
                logger.info(f"⚡ {worker_id} processing {task.content_type.value} {task.content_id}")
                
                # Update status to processing
                await neo4j_service.update_processing_status(
                    task.content_id, ProcessingStage.FAST_PROCESSING.value
                )
                
                # Perform fast analysis
                await self.perform_fast_analysis(task)
                
                # Update status to fast ready
                await neo4j_service.update_processing_status(
                    task.content_id, ProcessingStage.FAST_READY.value
                )
                
                # Queue for deep processing
                await self.queue_deep_processing(
                    task.content_id, task.content_type, task.metadata
                )
                
                logger.info(f"✅ {worker_id} completed fast processing for {task.content_id}")
                
            except asyncio.TimeoutError:
                # No tasks available, continue loop
                continue
            except Exception as e:
                logger.error(f"❌ {worker_id} fast processing error: {e}")
                if 'task' in locals():
                    await neo4j_service.update_processing_status(
                        task.content_id, ProcessingStage.ERROR.value
                    )
    
    async def deep_worker(self, worker_id: str):
        """Deep processing worker - handles 30+ second intelligence tasks"""
        logger.info(f"🧠 Deep worker {worker_id} started")
        
        while self.is_running:
            try:
                # Wait for tasks with timeout
                task = await asyncio.wait_for(self.deep_queue.get(), timeout=1.0)
                logger.info(f"🧠 {worker_id} deep processing {task.content_type.value} {task.content_id}")
                
                # Update status to deep processing
                await neo4j_service.update_processing_status(
                    task.content_id, ProcessingStage.DEEP_PROCESSING.value
                )
                
                # Perform deep analysis
                await self.perform_deep_analysis(task)
                
                # Update status to fully processed
                await neo4j_service.update_processing_status(
                    task.content_id, ProcessingStage.FULLY_PROCESSED.value
                )
                
                logger.info(f"✅ {worker_id} completed deep processing for {task.content_id}")
                
            except asyncio.TimeoutError:
                # No tasks available, continue loop  
                continue
            except Exception as e:
                logger.error(f"❌ {worker_id} deep processing error: {e}")
                if 'task' in locals():
                    await neo4j_service.update_processing_status(
                        task.content_id, ProcessingStage.ERROR.value
                    )
    
    async def perform_fast_analysis(self, task: IntelligenceTask):
        """Perform fast intelligence analysis (2-5 seconds)"""
        try:
            # Get content from Neo4j
            content_data = await neo4j_service.get_node_content(task.content_id)
            if not content_data:
                logger.warning(f"No content found for {task.content_id}")
                return
            
            content_text = content_data.get('content', '') or content_data.get('content_text', '')
            
            # 1. Generate embedding (fast)
            logger.info(f"⚡ Generating embedding for {task.content_id}")
            embedding = await embedding_service.generate_embedding(content_text)
            
            # 2. Update Neo4j with embedding
            await neo4j_service.update_node_embedding(task.content_id, embedding)
            
            # 3. Find obvious connections (title matches, explicit links)
            await self.find_obvious_connections(task.content_id, content_data)
            
            # 4. Temporal clustering (connect to recent content)
            await self.create_temporal_connections(task.content_id, content_data)
            
            logger.info(f"✅ Fast analysis completed for {task.content_id}")
            
        except Exception as e:
            logger.error(f"❌ Fast analysis failed for {task.content_id}: {e}")
            raise
    
    async def perform_deep_analysis(self, task: IntelligenceTask):
        """Perform deep intelligence analysis (30+ seconds)"""
        try:
            # Get content and existing data from Neo4j
            content_data = await neo4j_service.get_node_content(task.content_id)
            if not content_data:
                logger.warning(f"No content found for {task.content_id}")
                return
            
            content_text = content_data.get('content', '') or content_data.get('content_text', '')
            
            # 1. Semantic similarity analysis
            logger.info(f"🧠 Finding semantic connections for {task.content_id}")
            await self.find_semantic_connections(task.content_id, content_data)
            
            # 2. Entity extraction and linking
            logger.info(f"🧠 Extracting entities for {task.content_id}")
            await self.extract_and_link_entities(task.content_id, content_text)
            
            # 3. Topic modeling and clustering  
            logger.info(f"🧠 Analyzing topics for {task.content_id}")
            await self.analyze_topics(task.content_id, content_text)
            
            # 4. Cross-content relationship scoring
            logger.info(f"🧠 Scoring relationships for {task.content_id}")
            await self.score_relationships(task.content_id)
            
            logger.info(f"✅ Deep analysis completed for {task.content_id}")
            
        except Exception as e:
            logger.error(f"❌ Deep analysis failed for {task.content_id}: {e}")
            raise
    
    async def find_obvious_connections(self, content_id: str, content_data: Dict):
        """Find obvious connections like title matches and explicit links"""
        try:
            content_text = content_data.get('content', '') or content_data.get('content_text', '')
            
            # Find [[Note Title]] style references
            import re
            wiki_links = re.findall(r'\[\[([^\]]+)\]\]', content_text)
            
            for link_title in wiki_links:
                # Find target node by title
                target_nodes = await neo4j_service.find_nodes_by_title(link_title.strip())
                for target_node in target_nodes:
                    if target_node['id'] != content_id:
                        await neo4j_service.create_reference_link(
                            content_id, target_node['id'], "REFERENCES"
                        )
                        logger.info(f"🔗 Created reference link: {content_id} -> {target_node['id']}")
            
        except Exception as e:
            logger.error(f"❌ Error finding obvious connections: {e}")
    
    async def create_temporal_connections(self, content_id: str, content_data: Dict):
        """Connect to content created in similar timeframes"""
        try:
            # Find content created within 24 hours
            recent_nodes = await neo4j_service.find_recent_nodes(
                user_id=content_data.get('user_id'),
                hours_back=24,
                exclude_id=content_id
            )
            
            for node in recent_nodes[:3]:  # Limit to 3 most recent
                await neo4j_service.create_temporal_connection(
                    content_id, node['id'], strength=0.3
                )
                logger.info(f"⏰ Created temporal connection: {content_id} -> {node['id']}")
                
        except Exception as e:
            logger.error(f"❌ Error creating temporal connections: {e}")
    
    async def find_semantic_connections(self, content_id: str, content_data: Dict):
        """Find semantically similar content using embeddings"""
        try:
            # Get similar nodes by embedding similarity
            similar_nodes = await neo4j_service.find_similar_nodes(
                content_id, similarity_threshold=0.6, limit=5
            )
            
            for node, similarity in similar_nodes:
                if similarity > 0.6:
                    await neo4j_service.create_semantic_connection(
                        content_id, node['id'], similarity=similarity
                    )
                    logger.info(f"🧠 Created semantic connection: {content_id} -> {node['id']} (similarity: {similarity:.3f})")
                    
        except Exception as e:
            logger.error(f"❌ Error finding semantic connections: {e}")
    
    async def extract_and_link_entities(self, content_id: str, content_text: str):
        """Extract entities and create entity nodes/relationships"""
        try:
            # Simple entity extraction (could be enhanced with NLP libraries)
            import re
            
            # Extract potential people names (capitalized words)
            people_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
            people = list(set(re.findall(people_pattern, content_text)))
            
            for person in people[:5]:  # Limit to avoid noise
                # Create or find person entity
                person_node = await neo4j_service.create_or_find_entity(
                    name=person, entity_type="Person"
                )
                
                # Link content to person
                await neo4j_service.create_entity_relationship(
                    content_id, person_node['id'], "MENTIONS"
                )
                logger.info(f"👤 Linked {content_id} to person entity: {person}")
                
        except Exception as e:
            logger.error(f"❌ Error extracting entities: {e}")
    
    async def analyze_topics(self, content_id: str, content_text: str):
        """Analyze topics and create topic clusters"""
        try:
            # Simple keyword extraction (could be enhanced with topic modeling)
            import re
            from collections import Counter
            
            # Extract meaningful words (longer than 3 chars, not common words)
            stop_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'this', 'that', 'these', 'those'}
            words = re.findall(r'\b[a-zA-Z]{4,}\b', content_text.lower())
            meaningful_words = [w for w in words if w not in stop_words]
            
            # Get top keywords
            top_keywords = Counter(meaningful_words).most_common(5)
            
            for keyword, frequency in top_keywords:
                if frequency >= 2:  # Only frequent keywords
                    # Create or find topic node
                    topic_node = await neo4j_service.create_or_find_topic(
                        name=keyword, topic_type="Keyword"
                    )
                    
                    # Link content to topic
                    await neo4j_service.create_topic_relationship(
                        content_id, topic_node['id'], "RELATES_TO", strength=frequency/len(words)
                    )
                    logger.info(f"📚 Linked {content_id} to topic: {keyword} (frequency: {frequency})")
                    
        except Exception as e:
            logger.error(f"❌ Error analyzing topics: {e}")
    
    async def score_relationships(self, content_id: str):
        """Score and optimize relationship strengths"""
        try:
            # Get all relationships for this node
            relationships = await neo4j_service.get_node_relationships(content_id)
            
            # Apply scoring based on relationship type and usage
            for rel in relationships:
                current_strength = rel.get('strength', 0.5)
                rel_type = rel.get('type', '')
                
                # Boost reference links
                if rel_type == 'REFERENCES':
                    new_strength = min(current_strength * 1.5, 1.0)
                # Moderate semantic connections
                elif rel_type == 'SEMANTIC_SIMILAR':
                    new_strength = current_strength * 0.9
                else:
                    new_strength = current_strength
                
                # Update relationship strength
                if new_strength != current_strength:
                    await neo4j_service.update_relationship_strength(
                        rel['id'], new_strength
                    )
                    
        except Exception as e:
            logger.error(f"❌ Error scoring relationships: {e}")

# Global intelligence pipeline instance
intelligence_pipeline = IntelligencePipeline()