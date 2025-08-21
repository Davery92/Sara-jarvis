"""
Neo4j Knowledge Graph Service
Handles all interactions with the Neo4j graph database for Sara's knowledge graph.
"""
import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from neo4j import GraphDatabase, Driver, Session
import json
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class Neo4jService:
    """Service for managing Neo4j knowledge graph operations"""
    
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "sara-graph-secret")
        self.driver: Optional[Driver] = None
        
    async def connect(self):
        """Initialize Neo4j connection"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=300,
                max_connection_pool_size=50,
                connection_acquisition_timeout=30
            )
            
            # Verify connection
            await self.verify_connection()
            await self.initialize_schema()
            logger.info("✅ Neo4j knowledge graph connected successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neo4j: {e}")
            raise
    
    async def verify_connection(self):
        """Verify Neo4j connection is working"""
        if not self.driver:
            raise Exception("Neo4j driver not initialized")
            
        with self.driver.session() as session:
            result = session.run("RETURN 1 as test")
            record = result.single()
            if record and record["test"] == 1:
                logger.info("✅ Neo4j connection verified")
            else:
                raise Exception("Neo4j connection test failed")
    
    async def initialize_schema(self):
        """Create indexes and constraints for optimal graph performance"""
        with self.driver.session() as session:
            # Create constraints (automatically creates indexes)
            constraints = [
                "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
                "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE", 
                "CREATE CONSTRAINT episode_id_unique IF NOT EXISTS FOR (e:Episode) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
                "CREATE CONSTRAINT folder_id_unique IF NOT EXISTS FOR (f:Folder) REQUIRE f.id IS UNIQUE"
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                    logger.debug(f"✅ Created constraint: {constraint}")
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(f"⚠️ Constraint creation warning: {e}")
            
            # Create additional indexes for performance
            indexes = [
                "CREATE INDEX note_title_index IF NOT EXISTS FOR (n:Note) ON (n.title)",
                "CREATE INDEX episode_role_index IF NOT EXISTS FOR (e:Episode) ON (e.role)",
                "CREATE INDEX content_created_index IF NOT EXISTS FOR (n) ON (n.created_at)",
                "CREATE INDEX document_mime_index IF NOT EXISTS FOR (d:Document) ON (d.mime_type)"
            ]
            
            for index in indexes:
                try:
                    session.run(index)
                    logger.debug(f"✅ Created index: {index}")
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(f"⚠️ Index creation warning: {e}")
    
    def close(self):
        """Close Neo4j connection"""
        if self.driver:
            self.driver.close()
            logger.info("🔌 Neo4j connection closed")
    
    # ========================================
    # NODE CREATION METHODS
    # ========================================
    
    async def create_user(self, user_id: str, email: str, **properties) -> Dict[str, Any]:
        """Create a User node"""
        with self.driver.session() as session:
            query = """
            MERGE (u:User {id: $user_id})
            SET u.email = $email,
                u.created_at = datetime(),
                u += $properties
            RETURN u
            """
            result = session.run(query, user_id=user_id, email=email, properties=properties)
            record = result.single()
            return dict(record["u"]) if record else None
    
    async def create_note(
        self, 
        note_id: str, 
        user_id: str, 
        title: str, 
        content: str, 
        folder_id: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        **properties
    ) -> Dict[str, Any]:
        """Create a Note node with relationships"""
        with self.driver.session() as session:
            # Create note and link to user
            query = """
            MATCH (u:User {id: $user_id})
            MERGE (n:Note {id: $note_id})
            SET n.title = $title,
                n.content = $content,
                n.created_at = datetime(),
                n.updated_at = datetime(),
                n.embedding = $embedding,
                n += $properties
            MERGE (u)-[:CREATED]->(n)
            """
            
            # Add folder relationship if specified
            if folder_id:
                query += """
                WITH n
                MATCH (f:Folder {id: $folder_id, user_id: $user_id})
                MERGE (f)-[:CONTAINS]->(n)
                """
            
            query += "RETURN n"
            
            result = session.run(
                query, 
                note_id=note_id, 
                user_id=user_id, 
                title=title, 
                content=content,
                folder_id=folder_id,
                embedding=embedding,
                properties=properties
            )
            record = result.single()
            return dict(record["n"]) if record else None
    
    async def create_episode(
        self,
        episode_id: str,
        user_id: str,
        content: str,
        role: str,
        importance: float = 0.5,
        source: str = "chat",
        embedding: Optional[List[float]] = None,
        **properties
    ) -> Dict[str, Any]:
        """Create an Episode node (conversation turn)"""
        with self.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})
            MERGE (e:Episode {id: $episode_id})
            SET e.content = $content,
                e.role = $role,
                e.importance = $importance,
                e.source = $source,
                e.created_at = datetime(),
                e.embedding = $embedding,
                e += $properties
            MERGE (u)-[:PARTICIPATED_IN]->(e)
            RETURN e
            """
            result = session.run(
                query,
                episode_id=episode_id,
                user_id=user_id,
                content=content,
                role=role,
                importance=importance,
                source=source,
                embedding=embedding,
                properties=properties
            )
            record = result.single()
            return dict(record["e"]) if record else None
    
    async def create_document(
        self,
        doc_id: str,
        user_id: str,
        title: str,
        content_text: str,
        mime_type: str,
        file_path: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        **properties
    ) -> Dict[str, Any]:
        """Create a Document node"""
        with self.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})
            MERGE (d:Document {id: $doc_id})
            SET d.title = $title,
                d.content_text = $content_text,
                d.mime_type = $mime_type,
                d.file_path = $file_path,
                d.created_at = datetime(),
                d.embedding = $embedding,
                d += $properties
            MERGE (u)-[:UPLOADED]->(d)
            RETURN d
            """
            result = session.run(
                query,
                doc_id=doc_id,
                user_id=user_id,
                title=title,
                content_text=content_text,
                mime_type=mime_type,
                file_path=file_path,
                embedding=embedding,
                properties=properties
            )
            record = result.single()
            return dict(record["d"]) if record else None
    
    async def create_folder(
        self,
        folder_id: str,
        user_id: str,
        name: str,
        parent_id: Optional[str] = None,
        **properties
    ) -> Dict[str, Any]:
        """Create a Folder node with hierarchy"""
        with self.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})
            MERGE (f:Folder {id: $folder_id})
            SET f.name = $name,
                f.user_id = $user_id,
                f.created_at = datetime(),
                f += $properties
            MERGE (u)-[:CREATED]->(f)
            """
            
            # Add parent relationship if specified
            if parent_id:
                query += """
                WITH f
                MATCH (parent:Folder {id: $parent_id, user_id: $user_id})
                MERGE (parent)-[:CONTAINS]->(f)
                """
            
            query += "RETURN f"
            
            result = session.run(
                query,
                folder_id=folder_id,
                user_id=user_id,
                name=name,
                parent_id=parent_id,
                properties=properties
            )
            record = result.single()
            return dict(record["f"]) if record else None
    
    # ========================================
    # RELATIONSHIP CREATION METHODS
    # ========================================
    
    async def create_reference_link(self, source_id: str, target_id: str, link_type: str = "REFERENCES") -> bool:
        """Create a reference relationship between nodes (e.g., [[Note Title]] links)"""
        with self.driver.session() as session:
            query = f"""
            MATCH (source {{id: $source_id}})
            MATCH (target {{id: $target_id}})
            MERGE (source)-[r:{link_type}]->(target)
            SET r.created_at = datetime(),
                r.strength = 1.0
            RETURN r
            """
            result = session.run(query, source_id=source_id, target_id=target_id)
            return result.single() is not None
    
    async def create_semantic_connection(
        self, 
        node1_id: str, 
        node2_id: str, 
        similarity: float,
        connection_type: str = "SEMANTIC_SIMILAR"
    ) -> bool:
        """Create bidirectional semantic similarity relationship"""
        with self.driver.session() as session:
            query = f"""
            MATCH (n1 {{id: $node1_id}})
            MATCH (n2 {{id: $node2_id}})
            MERGE (n1)-[r1:{connection_type}]-(n2)
            SET r1.similarity = $similarity,
                r1.created_at = datetime(),
                r1.strength = $similarity
            RETURN r1
            """
            result = session.run(
                query, 
                node1_id=node1_id, 
                node2_id=node2_id, 
                similarity=similarity
            )
            return result.single() is not None
    
    async def create_temporal_connection(
        self, 
        node1_id: str, 
        node2_id: str, 
        time_proximity: float,
        connection_type: str = "TEMPORAL_NEAR"
    ) -> bool:
        """Create temporal proximity relationship"""
        with self.driver.session() as session:
            query = f"""
            MATCH (n1 {{id: $node1_id}})
            MATCH (n2 {{id: $node2_id}})
            MERGE (n1)-[r:{connection_type}]-(n2)
            SET r.time_proximity = $time_proximity,
                r.created_at = datetime(),
                r.strength = $time_proximity
            RETURN r
            """
            result = session.run(
                query,
                node1_id=node1_id,
                node2_id=node2_id,
                time_proximity=time_proximity
            )
            return result.single() is not None
    
    # ========================================
    # QUERY METHODS
    # ========================================
    
    async def get_user_knowledge_graph(self, user_id: str, depth: int = 2) -> Dict[str, Any]:
        """Get complete knowledge graph for a user"""
        with self.driver.session() as session:
            query = f"""
            MATCH (u:User {{id: $user_id}})
            MATCH (u)-[*0..{depth}]-(node)
            OPTIONAL MATCH (node)-[rel]-(connected)
            WHERE connected.id IS NOT NULL
            RETURN 
                collect(DISTINCT {{
                    id: node.id,
                    labels: labels(node),
                    properties: properties(node)
                }}) as nodes,
                collect(DISTINCT {{
                    source: startNode(rel).id,
                    target: endNode(rel).id,
                    type: type(rel),
                    properties: properties(rel)
                }}) as relationships
            """
            result = session.run(query, user_id=user_id)
            record = result.single()
            
            if record:
                return {
                    "nodes": record["nodes"],
                    "relationships": record["relationships"]
                }
            return {"nodes": [], "relationships": []}
    
    async def find_connected_content(
        self, 
        node_id: str, 
        user_id: str, 
        depth: int = 2,
        relationship_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Find all content connected to a specific node"""
        with self.driver.session() as session:
            # Build relationship filter
            rel_filter = ""
            if relationship_types:
                rel_types = "|".join(relationship_types)
                rel_filter = f":{rel_types}"
            
            query = f"""
            MATCH (start {{id: $node_id}})
            MATCH (u:User {{id: $user_id}})
            MATCH (start)-[{rel_filter}*1..{depth}]-(connected)
            WHERE (u)-[:CREATED|:UPLOADED|:PARTICIPATED_IN]-(connected)
            RETURN DISTINCT connected, 
                   length(shortestPath((start)-[*]-(connected))) as distance
            ORDER BY distance ASC
            LIMIT 50
            """
            
            result = session.run(query, node_id=node_id, user_id=user_id)
            
            connected_items = []
            for record in result:
                node = dict(record["connected"])
                node["distance"] = record["distance"]
                connected_items.append(node)
            
            return connected_items
    
    async def search_knowledge_graph(
        self,
        user_id: str,
        query: str,
        content_types: Optional[List[str]] = None,
        limit: int = 20,
        # Metadata filters
        entity_types: Optional[List[str]] = None,
        topic_types: Optional[List[str]] = None,
        tag_categories: Optional[List[str]] = None,
        min_importance: Optional[float] = None,
        max_importance: Optional[float] = None,
        min_urgency: Optional[float] = None,
        max_urgency: Optional[float] = None,
        min_confidence: Optional[float] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search across all content types in the knowledge graph with metadata filtering"""
        with self.driver.session() as session:
            # Build search conditions
            search_conditions = []
            params = {"user_id": user_id, "search_query": query, "limit": limit}
            
            # Content type filter
            if content_types:
                labels = "|".join([f":{t.title()}" for t in content_types])
                search_conditions.append(f"node{labels}")
            
            # Add text search conditions
            text_conditions = [
                "toLower(coalesce(node.title, '')) CONTAINS toLower($search_query)",
                "toLower(coalesce(node.content, '')) CONTAINS toLower($search_query)",
                "toLower(coalesce(node.content_text, '')) CONTAINS toLower($search_query)",
                "toLower(coalesce(node.name, '')) CONTAINS toLower($search_query)"
            ]
            
            # Entity type filter
            if entity_types:
                entity_conditions = []
                for i, entity_type in enumerate(entity_types):
                    param_name = f"entity_type_{i}"
                    entity_conditions.append(f"node.entity_type = ${param_name}")
                    params[param_name] = entity_type
                search_conditions.append(f"({' OR '.join(entity_conditions)})")
            
            # Topic type filter
            if topic_types:
                topic_conditions = []
                for i, topic_type in enumerate(topic_types):
                    param_name = f"topic_type_{i}"
                    topic_conditions.append(f"node.topic_type = ${param_name}")
                    params[param_name] = topic_type
                search_conditions.append(f"({' OR '.join(topic_conditions)})")
            
            # Tag category filter
            if tag_categories:
                tag_conditions = []
                for i, tag_category in enumerate(tag_categories):
                    param_name = f"tag_category_{i}"
                    tag_conditions.append(f"node.category = ${param_name}")
                    params[param_name] = tag_category
                search_conditions.append(f"({' OR '.join(tag_conditions)})")
            
            # Numeric filters
            if min_importance is not None:
                search_conditions.append("coalesce(node.importance_score, 0) >= $min_importance")
                params["min_importance"] = min_importance
            
            if max_importance is not None:
                search_conditions.append("coalesce(node.importance_score, 0) <= $max_importance")
                params["max_importance"] = max_importance
            
            if min_urgency is not None:
                search_conditions.append("coalesce(node.urgency_score, 0) >= $min_urgency")
                params["min_urgency"] = min_urgency
            
            if max_urgency is not None:
                search_conditions.append("coalesce(node.urgency_score, 0) <= $max_urgency")
                params["max_urgency"] = max_urgency
            
            if min_confidence is not None:
                search_conditions.append("coalesce(node.confidence, 0) >= $min_confidence")
                params["min_confidence"] = min_confidence
            
            # Date filters
            if date_from:
                search_conditions.append("node.created_at >= datetime($date_from)")
                params["date_from"] = date_from
            
            if date_to:
                search_conditions.append("node.created_at <= datetime($date_to)")
                params["date_to"] = date_to
            
            # Build WHERE clause
            where_clause = ""
            if search_conditions:
                where_clause = "WHERE " + " AND ".join(search_conditions)
            
            # Add text search as OR condition
            if where_clause:
                text_search = " OR ".join(text_conditions)
                where_clause += f" AND ({text_search})"
            else:
                text_search = " OR ".join(text_conditions)
                where_clause = f"WHERE ({text_search})"
            
            query_cypher = f"""
            MATCH (u:User {{id: $user_id}})
            MATCH (u)-[:CREATED|:UPLOADED|:PARTICIPATED_IN|:HAS_CONTENT]-(node)
            {where_clause}
            RETURN node, labels(node) as node_types
            ORDER BY 
                CASE 
                    WHEN toLower(coalesce(node.title, '')) CONTAINS toLower($search_query) THEN 1
                    WHEN toLower(coalesce(node.name, '')) CONTAINS toLower($search_query) THEN 2
                    ELSE 3
                END,
                coalesce(node.importance_score, node.confidence, 0) DESC,
                node.created_at DESC
            LIMIT $limit
            """
            
            result = session.run(query_cypher, **params)
            
            search_results = []
            for record in result:
                node = dict(record["node"])
                node["node_types"] = record["node_types"]
                search_results.append(node)
            
            return search_results
    
    async def get_search_filter_options(self, user_id: str) -> Dict[str, Any]:
        """Get available filter options for the user's content"""
        with self.driver.session() as session:
            # Get unique entity types
            entity_query = """
            MATCH (u:User {id: $user_id})-[:HAS_CONTENT]-(entity:Entity)
            RETURN DISTINCT entity.entity_type as type
            ORDER BY type
            """
            entity_result = session.run(entity_query, user_id=user_id)
            entity_types = [record["type"] for record in entity_result if record["type"]]
            
            # Get unique topic types
            topic_query = """
            MATCH (u:User {id: $user_id})-[:HAS_CONTENT]-(topic:Topic)
            RETURN DISTINCT topic.topic_type as type
            ORDER BY type
            """
            topic_result = session.run(topic_query, user_id=user_id)
            topic_types = [record["type"] for record in topic_result if record["type"]]
            
            # Get unique tag categories
            tag_query = """
            MATCH (u:User {id: $user_id})-[:HAS_CONTENT]-(tag:Tag)
            RETURN DISTINCT tag.category as category
            ORDER BY category
            """
            tag_result = session.run(tag_query, user_id=user_id)
            tag_categories = [record["category"] for record in tag_result if record["category"]]
            
            # Get content types
            content_query = """
            MATCH (u:User {id: $user_id})-[:HAS_CONTENT]-(content:Content)
            RETURN DISTINCT content.content_type as type
            ORDER BY type
            """
            content_result = session.run(content_query, user_id=user_id)
            content_types = [record["type"] for record in content_result if record["type"]]
            
            # Get numeric ranges
            ranges_query = """
            MATCH (u:User {id: $user_id})-[:HAS_CONTENT]-(node)
            WHERE node.importance_score IS NOT NULL OR node.urgency_score IS NOT NULL OR node.confidence IS NOT NULL
            RETURN 
                min(coalesce(node.importance_score, 0)) as min_importance,
                max(coalesce(node.importance_score, 0)) as max_importance,
                min(coalesce(node.urgency_score, 0)) as min_urgency,
                max(coalesce(node.urgency_score, 0)) as max_urgency,
                min(coalesce(node.confidence, 0)) as min_confidence,
                max(coalesce(node.confidence, 0)) as max_confidence,
                min(node.created_at) as min_date,
                max(node.created_at) as max_date
            """
            ranges_result = session.run(ranges_query, user_id=user_id)
            ranges = ranges_result.single()
            
            return {
                "entity_types": entity_types,
                "topic_types": topic_types,
                "tag_categories": tag_categories,
                "content_types": content_types,
                "importance_range": {
                    "min": float(ranges["min_importance"]) if ranges and ranges["min_importance"] is not None else 0.0,
                    "max": float(ranges["max_importance"]) if ranges and ranges["max_importance"] is not None else 1.0
                },
                "urgency_range": {
                    "min": float(ranges["min_urgency"]) if ranges and ranges["min_urgency"] is not None else 0.0,
                    "max": float(ranges["max_urgency"]) if ranges and ranges["max_urgency"] is not None else 1.0
                },
                "confidence_range": {
                    "min": float(ranges["min_confidence"]) if ranges and ranges["min_confidence"] is not None else 0.0,
                    "max": float(ranges["max_confidence"]) if ranges and ranges["max_confidence"] is not None else 1.0
                },
                "date_range": {
                    "min": ranges["min_date"].isoformat() if ranges and ranges["min_date"] else None,
                    "max": ranges["max_date"].isoformat() if ranges and ranges["max_date"] else None
                }
            }
    
    async def get_knowledge_clusters(self, user_id: str) -> List[Dict[str, Any]]:
        """Find knowledge clusters using community detection"""
        with self.driver.session() as session:
            # This requires Graph Data Science library
            query = """
            MATCH (u:User {id: $user_id})
            MATCH (u)-[:CREATED|:UPLOADED|:PARTICIPATED_IN]-(node)
            MATCH (node)-[rel]-(connected)
            WITH collect(DISTINCT node) as nodes, collect(DISTINCT rel) as relationships
            CALL gds.louvain.stream({
                nodeQuery: 'MATCH (n) WHERE n IN $nodes RETURN id(n) as id',
                relationshipQuery: 'MATCH (n)-[r]-(m) WHERE r IN $relationships RETURN id(n) as source, id(m) as target, 1.0 as weight'
            }) YIELD nodeId, communityId
            MATCH (n) WHERE id(n) = nodeId
            RETURN communityId, collect({
                id: n.id,
                title: coalesce(n.title, n.content[0..50]),
                type: labels(n)[0]
            }) as cluster_members
            ORDER BY size(cluster_members) DESC
            """
            
            try:
                result = session.run(query, user_id=user_id)
                clusters = []
                for record in result:
                    clusters.append({
                        "community_id": record["communityId"],
                        "members": record["cluster_members"],
                        "size": len(record["cluster_members"])
                    })
                return clusters
            except Exception as e:
                logger.warning(f"Community detection failed (GDS not available?): {e}")
                # Fallback to simple grouping
                return await self._simple_clustering_fallback(user_id)
    
    async def _simple_clustering_fallback(self, user_id: str) -> List[Dict[str, Any]]:
        """Simple clustering fallback when GDS is not available"""
        with self.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})
            MATCH (u)-[:CREATED|:UPLOADED|:PARTICIPATED_IN]-(node)
            OPTIONAL MATCH (node)-[rel]-(connected)
            RETURN node, count(rel) as connection_count
            ORDER BY connection_count DESC
            """
            result = session.run(query, user_id=user_id)
            
            # Simple grouping by connection density
            high_connected = []
            medium_connected = []
            low_connected = []
            
            for record in result:
                node = dict(record["node"])
                count = record["connection_count"]
                
                if count >= 5:
                    high_connected.append(node)
                elif count >= 2:
                    medium_connected.append(node)
                else:
                    low_connected.append(node)
            
            clusters = []
            if high_connected:
                clusters.append({"community_id": "high_connected", "members": high_connected, "size": len(high_connected)})
            if medium_connected:
                clusters.append({"community_id": "medium_connected", "members": medium_connected, "size": len(medium_connected)})
            if low_connected:
                clusters.append({"community_id": "low_connected", "members": low_connected, "size": len(low_connected)})
            
            return clusters
    
    # ========================================
    # UPDATE METHODS
    # ========================================
    
    async def update_document_title(self, document_id: str, title: str) -> bool:
        """Update document title in Neo4j"""
        with self.driver.session() as session:
            query = """
            MATCH (d:Document {id: $document_id})
            SET d.title = $title,
                d.updated_at = datetime()
            RETURN d
            """
            
            result = session.run(query, document_id=document_id, title=title)
            return result.single() is not None
    
    async def delete_document(self, document_id: str, user_id: str) -> bool:
        """Delete document and all its relationships from Neo4j"""
        with self.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})-[:UPLOADED]->(d:Document {id: $document_id})
            OPTIONAL MATCH (d)-[r]-()
            DELETE r, d
            RETURN count(d) as deleted_count
            """
            
            result = session.run(query, document_id=document_id, user_id=user_id)
            record = result.single()
            return record and record["deleted_count"] > 0
    
    async def delete_note(self, note_id: str, user_id: str) -> bool:
        """Delete note and all its relationships from Neo4j"""
        with self.driver.session() as session:
            query = """
            MATCH (u:User {id: $user_id})-[:CREATED]->(n:Note {id: $note_id})
            OPTIONAL MATCH (n)-[r]-()
            DELETE r, n
            RETURN count(n) as deleted_count
            """
            
            result = session.run(query, note_id=note_id, user_id=user_id)
            record = result.single()
            return record and record["deleted_count"] > 0
    
    async def update_processing_status(self, node_id: str, status: str) -> bool:
        """Update processing status of a node"""
        with self.driver.session() as session:
            query = """
            MATCH (n {id: $node_id})
            SET n.processing_status = $status,
                n.status_updated_at = datetime()
            RETURN n
            """
            
            result = session.run(query, node_id=node_id, status=status)
            return result.single() is not None
    
    async def get_node_content(self, node_id: str) -> Dict[str, Any]:
        """Get node content and metadata"""
        with self.driver.session() as session:
            query = """
            MATCH (n {id: $node_id})
            RETURN n.id as id, n.content as content, n.content_text as content_text,
                   n.title as title, n.user_id as user_id, n.created_at as created_at,
                   labels(n) as labels
            """
            
            result = session.run(query, node_id=node_id)
            record = result.single()
            return dict(record) if record else None
    
    async def update_node_embedding(self, node_id: str, embedding: List[float]) -> bool:
        """Update node with embedding vector"""
        with self.driver.session() as session:
            query = """
            MATCH (n {id: $node_id})
            SET n.embedding = $embedding,
                n.embedding_updated_at = datetime()
            RETURN n
            """
            
            result = session.run(query, node_id=node_id, embedding=embedding)
            return result.single() is not None
    
    async def find_nodes_by_title(self, title: str) -> List[Dict[str, Any]]:
        """Find nodes by title (case insensitive)"""
        with self.driver.session() as session:
            query = """
            MATCH (n)
            WHERE toLower(n.title) = toLower($title)
            RETURN n.id as id, n.title as title, labels(n) as labels
            """
            
            result = session.run(query, title=title)
            return [dict(record) for record in result]
    
    async def find_recent_nodes(self, user_id: str, hours_back: int = 24, exclude_id: str = None) -> List[Dict[str, Any]]:
        """Find nodes created recently for temporal connections"""
        with self.driver.session() as session:
            query = """
            MATCH (n)
            WHERE n.user_id = $user_id
            AND datetime() - duration({hours: $hours_back}) <= n.created_at <= datetime()
            AND ($exclude_id IS NULL OR n.id <> $exclude_id)
            RETURN n.id as id, n.title as title, n.created_at as created_at, labels(n) as labels
            ORDER BY n.created_at DESC
            LIMIT 10
            """
            
            result = session.run(query, user_id=user_id, hours_back=hours_back, exclude_id=exclude_id)
            return [dict(record) for record in result]
    
    async def create_temporal_connection(self, source_id: str, target_id: str, strength: float = 0.3) -> bool:
        """Create temporal proximity relationship"""
        with self.driver.session() as session:
            query = """
            MATCH (source {id: $source_id})
            MATCH (target {id: $target_id})
            MERGE (source)-[r:TEMPORAL_NEAR]->(target)
            SET r.strength = $strength,
                r.created_at = datetime()
            RETURN r
            """
            
            result = session.run(query, source_id=source_id, target_id=target_id, strength=strength)
            return result.single() is not None
    
    async def find_similar_nodes(self, node_id: str, similarity_threshold: float = 0.6, limit: int = 5) -> List[tuple]:
        """Find semantically similar nodes using embedding similarity"""
        with self.driver.session() as session:
            # Note: This is a simplified version. In production, you'd use vector similarity search
            # For now, we'll use a placeholder that could be enhanced with proper vector indexing
            query = """
            MATCH (source {id: $node_id})
            MATCH (target)
            WHERE target.id <> $node_id 
            AND target.embedding IS NOT NULL 
            AND source.embedding IS NOT NULL
            WITH source, target,
                 gds.similarity.cosine(source.embedding, target.embedding) as similarity
            WHERE similarity >= $similarity_threshold
            RETURN target, similarity
            ORDER BY similarity DESC
            LIMIT $limit
            """
            
            try:
                result = session.run(query, node_id=node_id, similarity_threshold=similarity_threshold, limit=limit)
                return [(dict(record["target"]), record["similarity"]) for record in result]
            except Exception as e:
                # Fallback to simple text matching if vector similarity fails
                logger.warning(f"Vector similarity failed, using fallback: {e}")
                return []
    
    async def create_or_find_entity(self, name: str, entity_type: str) -> Dict[str, Any]:
        """Create or find an entity node (Person, Organization, etc.)"""
        with self.driver.session() as session:
            query = f"""
            MERGE (e:{entity_type} {{name: $name}})
            ON CREATE SET e.id = randomUUID(),
                         e.created_at = datetime(),
                         e.entity_type = $entity_type
            RETURN e.id as id, e.name as name, e.entity_type as entity_type
            """
            
            result = session.run(query, name=name, entity_type=entity_type)
            record = result.single()
            return dict(record) if record else None
    
    async def create_entity_relationship(self, content_id: str, entity_id: str, rel_type: str) -> bool:
        """Create relationship between content and entity"""
        with self.driver.session() as session:
            query = f"""
            MATCH (content {{id: $content_id}})
            MATCH (entity {{id: $entity_id}})
            MERGE (content)-[r:{rel_type}]->(entity)
            SET r.created_at = datetime()
            RETURN r
            """
            
            result = session.run(query, content_id=content_id, entity_id=entity_id)
            return result.single() is not None
    
    async def create_or_find_topic(self, name: str, topic_type: str) -> Dict[str, Any]:
        """Create or find a topic node"""
        with self.driver.session() as session:
            query = """
            MERGE (t:Topic {name: $name})
            ON CREATE SET t.id = randomUUID(),
                         t.created_at = datetime(),
                         t.topic_type = $topic_type
            RETURN t.id as id, t.name as name, t.topic_type as topic_type
            """
            
            result = session.run(query, name=name, topic_type=topic_type)
            record = result.single()
            return dict(record) if record else None
    
    async def create_topic_relationship(self, content_id: str, topic_id: str, rel_type: str, strength: float = 0.5) -> bool:
        """Create relationship between content and topic"""
        with self.driver.session() as session:
            query = f"""
            MATCH (content {{id: $content_id}})
            MATCH (topic {{id: $topic_id}})
            MERGE (content)-[r:{rel_type}]->(topic)
            SET r.strength = $strength,
                r.created_at = datetime()
            RETURN r
            """
            
            result = session.run(query, content_id=content_id, topic_id=topic_id, strength=strength)
            return result.single() is not None
    
    async def get_node_relationships(self, node_id: str) -> List[Dict[str, Any]]:
        """Get all relationships for a node"""
        with self.driver.session() as session:
            query = """
            MATCH (n {id: $node_id})-[r]-(other)
            RETURN id(r) as id, type(r) as type, r.strength as strength,
                   startNode(r).id as source_id, endNode(r).id as target_id
            """
            
            result = session.run(query, node_id=node_id)
            return [dict(record) for record in result]
    
    async def update_relationship_strength(self, rel_id: int, strength: float) -> bool:
        """Update relationship strength"""
        with self.driver.session() as session:
            query = """
            MATCH ()-[r]-()
            WHERE id(r) = $rel_id
            SET r.strength = $strength,
                r.updated_at = datetime()
            RETURN r
            """
            
            result = session.run(query, rel_id=rel_id, strength=strength)
            return result.single() is not None
    
    async def get_connection_details(self, source_id: str, target_id: str, user_id: str) -> Dict[str, Any]:
        """Get detailed information about a connection including shared content analysis"""
        with self.driver.session() as session:
            # Get the relationship and both nodes
            query = """
            MATCH (source {id: $source_id})-[r]-(target {id: $target_id})
            RETURN source, target, r, type(r) as rel_type, properties(r) as rel_props
            """
            
            result = session.run(query, source_id=source_id, target_id=target_id)
            record = result.single()
            
            if not record:
                return {"error": "Connection not found"}
            
            source_node = dict(record["source"])
            target_node = dict(record["target"])
            relationship = record["r"]
            rel_type = record["rel_type"]
            rel_props = record["rel_props"]
            
            # Get content for analysis
            source_content = source_node.get('content', '') or source_node.get('content_text', '')
            target_content = target_node.get('content', '') or target_node.get('content_text', '')
            
            connection_details = {
                "source": source_node,
                "target": target_node,
                "relationship_type": rel_type,
                "properties": rel_props,
                "created_at": rel_props.get('created_at')
            }
            
            # Add specific analysis based on connection type
            if rel_type == "SEMANTIC_SIMILAR":
                shared_analysis = self._analyze_semantic_connection(source_content, target_content)
                connection_details["shared_content_analysis"] = shared_analysis
            elif rel_type == "REFERENCES":
                ref_analysis = self._analyze_reference_connection(source_content, target_content, source_node, target_node)
                connection_details["reference_analysis"] = ref_analysis
            elif rel_type == "TEMPORAL_NEAR":
                temporal_analysis = self._analyze_temporal_connection(source_node, target_node)
                connection_details["temporal_analysis"] = temporal_analysis
            
            return connection_details
    
    def _analyze_semantic_connection(self, content1: str, content2: str) -> Dict[str, Any]:
        """Analyze what content is shared between two semantically connected items"""
        import re
        from collections import Counter
        
        # Extract meaningful words (longer than 3 chars, not common words)
        stop_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 
            'this', 'that', 'these', 'those', 'have', 'has', 'had', 'will', 'would', 
            'could', 'should', 'can', 'may', 'might', 'must', 'shall', 'are', 'is', 'was', 
            'were', 'been', 'being', 'do', 'does', 'did', 'done', 'get', 'got', 'getting',
            'make', 'made', 'making', 'take', 'took', 'taken', 'taking', 'come', 'came',
            'coming', 'go', 'went', 'going', 'see', 'saw', 'seen', 'seeing', 'know', 
            'knew', 'known', 'knowing', 'think', 'thought', 'thinking', 'say', 'said', 
            'saying', 'tell', 'told', 'telling', 'work', 'worked', 'working', 'use', 
            'used', 'using', 'find', 'found', 'finding', 'give', 'gave', 'given', 'giving'
        }
        
        # Extract words from both contents
        words1 = re.findall(r'\b[a-zA-Z]{4,}\b', content1.lower())
        words2 = re.findall(r'\b[a-zA-Z]{4,}\b', content2.lower())
        
        # Filter out stop words
        meaningful_words1 = [w for w in words1 if w not in stop_words]
        meaningful_words2 = [w for w in words2 if w not in stop_words]
        
        # Find common words
        common_words = list(set(meaningful_words1) & set(meaningful_words2))
        
        # Get word frequencies
        freq1 = Counter(meaningful_words1)
        freq2 = Counter(meaningful_words2)
        
        # Calculate importance of shared words
        shared_word_analysis = []
        for word in common_words:
            importance = min(freq1[word], freq2[word]) * len(word)  # Basic importance scoring
            shared_word_analysis.append({
                "word": word,
                "frequency_source": freq1[word],
                "frequency_target": freq2[word],
                "importance": importance
            })
        
        # Sort by importance
        shared_word_analysis.sort(key=lambda x: x["importance"], reverse=True)
        
        # Look for shared phrases (2-3 words)
        shared_phrases = []
        for i in range(len(words1) - 1):
            phrase = " ".join(words1[i:i+2])
            if phrase in " ".join(words2) and len(phrase) > 8:
                shared_phrases.append(phrase)
        
        return {
            "shared_words": shared_word_analysis[:10],  # Top 10 most important
            "shared_phrases": list(set(shared_phrases))[:5],  # Top 5 unique phrases
            "total_shared_words": len(common_words),
            "similarity_ratio": len(common_words) / max(len(set(meaningful_words1 + meaningful_words2)), 1)
        }
    
    def _analyze_reference_connection(self, content1: str, content2: str, node1: Dict, node2: Dict) -> Dict[str, Any]:
        """Analyze reference connections to show what exactly is referenced"""
        import re
        
        # Look for [[Title]] style references
        wiki_links = re.findall(r'\[\[([^\]]+)\]\]', content1)
        title_matches = []
        
        target_title = node2.get('title', '')
        source_title = node1.get('title', '')
        
        # Check if target title is referenced in source
        for link in wiki_links:
            if link.lower() == target_title.lower():
                title_matches.append(f"[[{link}]]")
        
        # Check for direct title mentions (case insensitive)
        if target_title and target_title.lower() in content1.lower():
            title_matches.append(f"Title mention: '{target_title}'")
        
        # Check reverse direction
        reverse_wiki_links = re.findall(r'\[\[([^\]]+)\]\]', content2)
        for link in reverse_wiki_links:
            if link.lower() == source_title.lower():
                title_matches.append(f"[[{link}]] (reverse)")
                
        if source_title and source_title.lower() in content2.lower():
            title_matches.append(f"Title mention: '{source_title}' (reverse)")
        
        return {
            "reference_type": "explicit_link",
            "references_found": title_matches,
            "bidirectional": len([m for m in title_matches if "(reverse)" in m]) > 0
        }
    
    def _analyze_temporal_connection(self, node1: Dict, node2: Dict) -> Dict[str, Any]:
        """Analyze temporal connections"""
        from datetime import datetime
        
        created1 = node1.get('created_at')
        created2 = node2.get('created_at')
        
        if created1 and created2:
            # Convert to datetime if needed
            if isinstance(created1, str):
                try:
                    created1 = datetime.fromisoformat(created1.replace('Z', '+00:00'))
                except:
                    created1 = None
            if isinstance(created2, str):
                try:
                    created2 = datetime.fromisoformat(created2.replace('Z', '+00:00'))
                except:
                    created2 = None
            
            if created1 and created2:
                time_diff = abs((created1 - created2).total_seconds())
                hours_apart = time_diff / 3600
                
                return {
                    "time_difference_hours": round(hours_apart, 2),
                    "created_within": f"{round(hours_apart, 1)} hours of each other",
                    "temporal_proximity": "very_close" if hours_apart < 1 else "close" if hours_apart < 6 else "same_day"
                }
        
        return {
            "time_difference_hours": None,
            "created_within": "Unknown timing",
            "temporal_proximity": "unknown"
        }

# Global Neo4j service instance
neo4j_service = Neo4jService()