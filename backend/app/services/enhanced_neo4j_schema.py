"""
Enhanced Neo4j Schema for Intelligent Content Storage
Stores rich metadata, tags, entities, and relationships from content intelligence.
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from .neo4j_service import neo4j_service
from .content_intelligence import ContentType, ContentChunk, ChunkType
from .metadata_extractor import ContentMetadata, Entity, Topic, TemporalInfo
from .tagging_system import Tag, TagCategory, TagPriority

logger = logging.getLogger(__name__)

class EnhancedNeo4jService:
    """Enhanced Neo4j service with intelligent content storage"""
    
    def __init__(self):
        self.base_service = neo4j_service
    
    async def initialize_enhanced_schema(self):
        """Initialize the enhanced schema with new node types and relationships"""
        logger.info("🔧 Initializing enhanced Neo4j schema...")
        
        if not self.base_service.driver:
            await self.base_service.connect()
        
        with self.base_service.driver.session() as session:
            # Create enhanced constraints
            enhanced_constraints = [
                "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT topic_id_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
                "CREATE CONSTRAINT tag_id_unique IF NOT EXISTS FOR (tag:Tag) REQUIRE tag.id IS UNIQUE",
                "CREATE CONSTRAINT context_id_unique IF NOT EXISTS FOR (ctx:Context) REQUIRE ctx.id IS UNIQUE",
                "CREATE CONSTRAINT priority_id_unique IF NOT EXISTS FOR (p:Priority) REQUIRE p.id IS UNIQUE"
            ]
            
            for constraint in enhanced_constraints:
                try:
                    session.run(constraint)
                    logger.debug(f"✅ Created constraint: {constraint}")
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(f"⚠️ Constraint creation warning: {e}")
            
            # Create enhanced indexes
            enhanced_indexes = [
                "CREATE INDEX chunk_parent_index IF NOT EXISTS FOR (c:Chunk) ON (c.parent_content_id)",
                "CREATE INDEX chunk_type_index IF NOT EXISTS FOR (c:Chunk) ON (c.chunk_type)",
                "CREATE INDEX entity_type_index IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
                "CREATE INDEX entity_confidence_index IF NOT EXISTS FOR (e:Entity) ON (e.confidence)",
                "CREATE INDEX topic_confidence_index IF NOT EXISTS FOR (t:Topic) ON (t.confidence)",
                "CREATE INDEX tag_category_index IF NOT EXISTS FOR (tag:Tag) ON (tag.category)",
                "CREATE INDEX tag_priority_index IF NOT EXISTS FOR (tag:Tag) ON (tag.priority)",
                "CREATE INDEX content_urgency_index IF NOT EXISTS FOR (n) ON (n.urgency_score)",
                "CREATE INDEX content_importance_index IF NOT EXISTS FOR (n) ON (n.importance_score)",
                "CREATE TEXT INDEX content_search_index IF NOT EXISTS FOR (n) ON (n.content)",
                "CREATE TEXT INDEX entity_name_search IF NOT EXISTS FOR (e:Entity) ON (e.name)"
            ]
            
            for index in enhanced_indexes:
                try:
                    session.run(index)
                    logger.debug(f"✅ Created index: {index}")
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(f"⚠️ Index creation warning: {e}")
        
        logger.info("✅ Enhanced Neo4j schema initialized")
    
    async def store_intelligent_content(
        self,
        content_id: str,
        user_id: str,
        title: str,
        content: str,
        content_type: ContentType,
        chunks: List[ContentChunk],
        metadata: ContentMetadata,
        tags: List[Tag]
    ) -> bool:
        """Store content with full intelligence data in Neo4j"""
        
        logger.info(f"💾 Storing intelligent content: {title} ({content_type.value})")
        
        with self.base_service.driver.session() as session:
            try:
                # Start transaction
                with session.begin_transaction() as tx:
                    
                    # 1. Create/update main content node with enhanced metadata
                    content_query = """
                    MATCH (u:User {id: $user_id})
                    MERGE (c:Content {id: $content_id})
                    SET c.title = $title,
                        c.content = $content,
                        c.content_type = $content_type,
                        c.urgency_score = $urgency_score,
                        c.importance_score = $importance_score,
                        c.intent = $intent,
                        c.created_at = datetime(),
                        c.updated_at = datetime(),
                        c.chunk_count = $chunk_count
                    MERGE (u)-[:CREATED]->(c)
                    RETURN c
                    """
                    
                    tx.run(content_query,
                        user_id=user_id,
                        content_id=content_id,
                        title=title,
                        content=content,
                        content_type=content_type.value,
                        urgency_score=metadata.urgency_score,
                        importance_score=metadata.importance_score,
                        intent=metadata.intent,
                        chunk_count=len(chunks)
                    )
                    
                    # 2. Store content chunks
                    await self._store_chunks(tx, content_id, chunks)
                    
                    # 3. Store entities and create relationships
                    await self._store_entities(tx, content_id, metadata.entities)
                    
                    # 4. Store topics and create relationships
                    await self._store_topics(tx, content_id, metadata.topics)
                    
                    # 5. Store tags and create relationships
                    await self._store_tags(tx, content_id, tags)
                    
                    # 6. Store temporal information
                    await self._store_temporal_info(tx, content_id, metadata.temporal_info)
                    
                    # 7. Store actionable items as separate nodes
                    await self._store_actionable_items(tx, content_id, metadata.actionable_items)
                
                logger.info(f"✅ Stored intelligent content: {content_id}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Failed to store intelligent content: {e}")
                return False
    
    async def _store_chunks(self, tx, parent_content_id: str, chunks: List[ContentChunk]):
        """Store content chunks as separate nodes"""
        chunk_query = """
        MATCH (parent:Content {id: $parent_id})
        CREATE (chunk:Chunk {
            id: $chunk_id,
            content: $content,
            chunk_type: $chunk_type,
            order: $order,
            parent_content_id: $parent_id,
            parent_section: $parent_section,
            metadata: $metadata,
            created_at: datetime()
        })
        CREATE (parent)-[:HAS_CHUNK {order: $order}]->(chunk)
        """
        
        for chunk in chunks:
            chunk_id = f"{parent_content_id}_chunk_{chunk.order}"
            tx.run(chunk_query,
                parent_id=parent_content_id,
                chunk_id=chunk_id,
                content=chunk.content,
                chunk_type=chunk.chunk_type.value,
                order=chunk.order,
                parent_section=chunk.parent_section,
                metadata=chunk.metadata
            )
    
    async def _store_entities(self, tx, content_id: str, entities: List[Entity]):
        """Store entities and link to content"""
        entity_query = """
        MATCH (content:Content {id: $content_id})
        MERGE (entity:Entity {name: $name, entity_type: $entity_type})
        ON CREATE SET entity.id = randomUUID(),
                     entity.created_at = datetime()
        SET entity.confidence = $confidence,
            entity.mentions = coalesce(entity.mentions, 0) + $mentions,
            entity.last_seen = datetime(),
            entity.context = $context
        
        MERGE (content)-[r:CONTAINS_ENTITY]->(entity)
        SET r.confidence = $confidence,
            r.mentions = $mentions,
            r.context = $context
        """
        
        for entity in entities:
            tx.run(entity_query,
                content_id=content_id,
                name=entity.name,
                entity_type=entity.entity_type,
                confidence=entity.confidence,
                mentions=entity.mentions,
                context=entity.context
            )
    
    async def _store_topics(self, tx, content_id: str, topics: List[Topic]):
        """Store topics and link to content"""
        topic_query = """
        MATCH (content:Content {id: $content_id})
        MERGE (topic:Topic {name: $name})
        ON CREATE SET topic.id = randomUUID(),
                     topic.created_at = datetime()
        SET topic.confidence = $confidence,
            topic.keywords = $keywords,
            topic.relevance = $relevance,
            topic.last_seen = datetime()
        
        MERGE (content)-[r:HAS_TOPIC]->(topic)
        SET r.confidence = $confidence,
            r.relevance = $relevance,
            r.keywords = $keywords
        """
        
        for topic in topics:
            tx.run(topic_query,
                content_id=content_id,
                name=topic.name,
                confidence=topic.confidence,
                keywords=topic.keywords,
                relevance=topic.relevance
            )
    
    async def _store_tags(self, tx, content_id: str, tags: List[Tag]):
        """Store tags and link to content"""
        tag_query = """
        MATCH (content:Content {id: $content_id})
        MERGE (tag:Tag {name: $name, category: $category})
        ON CREATE SET tag.id = randomUUID(),
                     tag.created_at = datetime()
        SET tag.priority = $priority,
            tag.confidence = $confidence,
            tag.description = $description,
            tag.auto_generated = $auto_generated,
            tag.parent_tag = $parent_tag,
            tag.aliases = $aliases,
            tag.last_used = datetime()
        
        MERGE (content)-[r:HAS_TAG]->(tag)
        SET r.confidence = $confidence,
            r.assigned_at = datetime(),
            r.auto_generated = $auto_generated
        """
        
        for tag in tags:
            tx.run(tag_query,
                content_id=content_id,
                name=tag.name,
                category=tag.category.value,
                priority=tag.priority.value,
                confidence=tag.confidence,
                description=tag.description,
                auto_generated=tag.auto_generated,
                parent_tag=tag.parent_tag,
                aliases=tag.aliases
            )
    
    async def _store_temporal_info(self, tx, content_id: str, temporal_info: TemporalInfo):
        """Store temporal information"""
        if temporal_info.durations or temporal_info.schedules:
            temporal_query = """
            MATCH (content:Content {id: $content_id})
            CREATE (temporal:TemporalInfo {
                id: randomUUID(),
                content_id: $content_id,
                durations: $durations,
                schedules: $schedules,
                created_at: datetime()
            })
            CREATE (content)-[:HAS_TEMPORAL_INFO]->(temporal)
            """
            
            tx.run(temporal_query,
                content_id=content_id,
                durations=temporal_info.durations,
                schedules=temporal_info.schedules
            )
    
    async def _store_actionable_items(self, tx, content_id: str, actionable_items: List[str]):
        """Store actionable items as separate nodes"""
        if actionable_items:
            action_query = """
            MATCH (content:Content {id: $content_id})
            CREATE (action:ActionItem {
                id: randomUUID(),
                content_id: $content_id,
                description: $description,
                status: 'pending',
                priority: 'normal',
                created_at: datetime()
            })
            CREATE (content)-[:HAS_ACTION_ITEM]->(action)
            """
            
            for item in actionable_items:
                tx.run(action_query,
                    content_id=content_id,
                    description=item
                )
    
    # Enhanced query methods
    async def find_content_by_tags(self, user_id: str, tag_names: List[str], limit: int = 20) -> List[Dict]:
        """Find content by tags"""
        with self.base_service.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})-[:CREATED]->(content:Content)
            MATCH (content)-[:HAS_TAG]->(tag:Tag)
            WHERE tag.name IN $tag_names
            WITH content, collect(tag.name) as matched_tags, count(tag) as tag_matches
            RETURN content, matched_tags, tag_matches
            ORDER BY tag_matches DESC, content.importance_score DESC
            LIMIT $limit
            """
            
            result = session.run(query, user_id=user_id, tag_names=tag_names, limit=limit)
            return [dict(record) for record in result]
    
    async def find_content_by_urgency(self, user_id: str, min_urgency: float = 0.5, limit: int = 10) -> List[Dict]:
        """Find urgent content"""
        with self.base_service.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})-[:CREATED]->(content:Content)
            WHERE content.urgency_score >= $min_urgency
            OPTIONAL MATCH (content)-[:HAS_TAG]->(tag:Tag {category: 'priority'})
            RETURN content, collect(tag.name) as priority_tags
            ORDER BY content.urgency_score DESC, content.importance_score DESC
            LIMIT $limit
            """
            
            result = session.run(query, user_id=user_id, min_urgency=min_urgency, limit=limit)
            return [dict(record) for record in result]
    
    async def find_related_content(self, content_id: str, similarity_threshold: float = 0.3) -> List[Dict]:
        """Find content related by shared entities, topics, or tags"""
        with self.base_service.driver.session() as session:
            query = """
            MATCH (source:Content {id: $content_id})
            
            // Find content sharing entities
            OPTIONAL MATCH (source)-[:CONTAINS_ENTITY]->(entity:Entity)<-[:CONTAINS_ENTITY]-(related1:Content)
            WHERE related1.id <> $content_id
            
            // Find content sharing topics  
            OPTIONAL MATCH (source)-[:HAS_TOPIC]->(topic:Topic)<-[:HAS_TOPIC]-(related2:Content)
            WHERE related2.id <> $content_id
            
            // Find content sharing tags
            OPTIONAL MATCH (source)-[:HAS_TAG]->(tag:Tag)<-[:HAS_TAG]-(related3:Content)
            WHERE related3.id <> $content_id
            
            WITH [related1, related2, related3] as related_list
            UNWIND related_list as related
            WHERE related IS NOT NULL
            
            WITH related, count(*) as connection_strength
            WHERE connection_strength >= $similarity_threshold
            
            RETURN related, connection_strength
            ORDER BY connection_strength DESC
            LIMIT 10
            """
            
            result = session.run(query, content_id=content_id, similarity_threshold=similarity_threshold)
            return [dict(record) for record in result]
    
    async def get_content_analytics(self, user_id: str) -> Dict[str, Any]:
        """Get analytics about user's content"""
        with self.base_service.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})-[:CREATED]->(content:Content)
            
            // Content type distribution
            WITH collect(content.content_type) as content_types,
                 collect(content.urgency_score) as urgency_scores,
                 collect(content.importance_score) as importance_scores,
                 count(content) as total_content
            
            // Tag usage
            OPTIONAL MATCH (u)-[:CREATED]->(content2:Content)-[:HAS_TAG]->(tag:Tag)
            WITH content_types, urgency_scores, importance_scores, total_content,
                 collect(tag.name) as all_tags
            
            // Entity counts
            OPTIONAL MATCH (u)-[:CREATED]->(content3:Content)-[:CONTAINS_ENTITY]->(entity:Entity)
            WITH content_types, urgency_scores, importance_scores, total_content, all_tags,
                 collect(entity.entity_type) as entity_types
            
            RETURN {
                total_content: total_content,
                content_types: content_types,
                avg_urgency: reduce(sum = 0.0, score IN urgency_scores | sum + score) / size(urgency_scores),
                avg_importance: reduce(sum = 0.0, score IN importance_scores | sum + score) / size(importance_scores),
                tag_count: size(all_tags),
                unique_tags: size(apoc.coll.toSet(all_tags)),
                entity_types: apoc.coll.frequencies(entity_types)
            } as analytics
            """
            
            result = session.run(query, user_id=user_id)
            record = result.single()
            return record["analytics"] if record else {}

# Global enhanced service instance
enhanced_neo4j = EnhancedNeo4jService()