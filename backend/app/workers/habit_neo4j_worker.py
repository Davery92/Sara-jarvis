"""
Habit Neo4j Worker - Sync habit data to knowledge graph using outbox pattern
"""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json
import os

logger = logging.getLogger(__name__)


class HabitNeo4jWorker:
    """Worker that syncs habit data to Neo4j using outbox pattern for reliability"""
    
    def __init__(self, database_url: str, neo4j_uri: str = None, neo4j_user: str = None, neo4j_password: str = None):
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Neo4j connection details
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI")
        self.neo4j_user = neo4j_user or os.getenv("NEO4J_USER")
        self.neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD")
        
        self.neo4j_driver = None
        if self.neo4j_uri:
            try:
                from neo4j import GraphDatabase
                self.neo4j_driver = GraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(self.neo4j_user, self.neo4j_password)
                )
                logger.info("✅ Neo4j driver initialized")
            except Exception as e:
                logger.warning(f"⚠️ Neo4j not available: {e}")
    
    async def process_outbox_events(self) -> Dict[str, Any]:
        """
        Process pending outbox events to sync habit data to Neo4j
        
        Uses outbox pattern for reliable event processing
        """
        logger.info("🔄 Processing habit outbox events for Neo4j sync...")
        
        start_time = datetime.now()
        results = {
            "events_processed": 0,
            "events_failed": 0,
            "events_skipped": 0,
            "errors": [],
            "execution_time_seconds": 0
        }
        
        if not self.neo4j_driver:
            logger.warning("⚠️ Neo4j not available, skipping sync")
            results["events_skipped"] = "neo4j_unavailable"
            return results
        
        db = self.SessionLocal()
        try:
            # Get pending outbox events for habits
            events = db.execute(text("""
                SELECT id, event_type, entity_type, entity_id, payload, created_at, processed_at
                FROM outbox_events
                WHERE entity_type IN ('habit', 'habit_instance', 'habit_log', 'habit_link')
                    AND processed_at IS NULL
                ORDER BY created_at ASC
                LIMIT 100
            """)).fetchall()
            
            for event in events:
                try:
                    success = await self._process_single_event(db, event)
                    if success:
                        # Mark event as processed
                        db.execute(text("""
                            UPDATE outbox_events 
                            SET processed_at = :now
                            WHERE id = :event_id
                        """), {"now": datetime.now(), "event_id": event.id})
                        results["events_processed"] += 1
                    else:
                        results["events_failed"] += 1
                
                except Exception as e:
                    error_msg = f"Failed to process event {event.id}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                    results["events_failed"] += 1
            
            db.commit()
            results["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"🎉 Outbox processing complete: {results['events_processed']} processed, {results['events_failed']} failed")
            
        except Exception as e:
            logger.error(f"❌ Outbox processing failed: {e}")
            results["errors"].append(f"Critical error: {str(e)}")
            db.rollback()
        finally:
            db.close()
        
        return results
    
    async def _process_single_event(self, db: Session, event) -> bool:
        """Process a single outbox event"""
        try:
            payload = json.loads(event.payload) if event.payload else {}
            
            if event.entity_type == "habit":
                return await self._sync_habit(event.event_type, event.entity_id, payload)
            elif event.entity_type == "habit_instance":
                return await self._sync_habit_instance(event.event_type, event.entity_id, payload)
            elif event.entity_type == "habit_log":
                return await self._sync_habit_log(event.event_type, event.entity_id, payload)
            elif event.entity_type == "habit_link":
                return await self._sync_habit_link(event.event_type, event.entity_id, payload)
            else:
                logger.warning(f"Unknown entity type: {event.entity_type}")
                return True  # Mark as processed to avoid reprocessing
        
        except Exception as e:
            logger.error(f"Failed to process event {event.id}: {e}")
            return False
    
    async def _sync_habit(self, event_type: str, habit_id: str, payload: Dict) -> bool:
        """Sync habit node to Neo4j"""
        try:
            with self.neo4j_driver.session() as session:
                if event_type in ["created", "updated"]:
                    # Create or update habit node
                    cypher = """
                    MERGE (h:Habit {id: $habit_id})
                    SET h.title = $title,
                        h.type = $type,
                        h.rrule = $rrule,
                        h.target_numeric = $target_numeric,
                        h.unit = $unit,
                        h.grace_days = $grace_days,
                        h.current_streak = $current_streak,
                        h.best_streak = $best_streak,
                        h.created_at = $created_at,
                        h.updated_at = $updated_at,
                        h.paused = $paused
                    """
                    
                    session.run(cypher, {
                        "habit_id": habit_id,
                        "title": payload.get("title"),
                        "type": payload.get("type"),
                        "rrule": payload.get("rrule"),
                        "target_numeric": payload.get("target_numeric"),
                        "unit": payload.get("unit"),
                        "grace_days": payload.get("grace_days", 0),
                        "current_streak": payload.get("current_streak", 0),
                        "best_streak": payload.get("best_streak", 0),
                        "created_at": payload.get("created_at"),
                        "updated_at": payload.get("updated_at"),
                        "paused": payload.get("paused", False)
                    })
                    
                    # Link to user
                    if payload.get("user_id"):
                        session.run("""
                            MATCH (u:User {id: $user_id})
                            MATCH (h:Habit {id: $habit_id})
                            MERGE (u)-[:HAS_HABIT]->(h)
                        """, {"user_id": payload["user_id"], "habit_id": habit_id})
                
                elif event_type == "deleted":
                    # Remove habit and all relationships
                    session.run("""
                        MATCH (h:Habit {id: $habit_id})
                        DETACH DELETE h
                    """, {"habit_id": habit_id})
                
                logger.debug(f"✓ Synced habit {habit_id} ({event_type})")
                return True
        
        except Exception as e:
            logger.error(f"Failed to sync habit {habit_id}: {e}")
            return False
    
    async def _sync_habit_instance(self, event_type: str, instance_id: str, payload: Dict) -> bool:
        """Sync habit instance (daily tracking) to Neo4j"""
        try:
            with self.neo4j_driver.session() as session:
                if event_type in ["created", "updated"]:
                    # Create or update instance node
                    cypher = """
                    MERGE (hi:HabitInstance {id: $instance_id})
                    SET hi.date = $date,
                        hi.status = $status,
                        hi.progress = $progress,
                        hi.total_amount = $total_amount,
                        hi.target = $target,
                        hi.window = $window,
                        hi.expected = $expected,
                        hi.created_at = $created_at,
                        hi.updated_at = $updated_at
                    """
                    
                    session.run(cypher, {
                        "instance_id": instance_id,
                        "date": payload.get("date"),
                        "status": payload.get("status"),
                        "progress": payload.get("progress", 0.0),
                        "total_amount": payload.get("total_amount"),
                        "target": payload.get("target"),
                        "window": payload.get("window"),
                        "expected": payload.get("expected", True),
                        "created_at": payload.get("created_at"),
                        "updated_at": payload.get("updated_at")
                    })
                    
                    # Link to habit
                    if payload.get("habit_id"):
                        session.run("""
                            MATCH (h:Habit {id: $habit_id})
                            MATCH (hi:HabitInstance {id: $instance_id})
                            MERGE (h)-[:HAS_INSTANCE]->(hi)
                        """, {"habit_id": payload["habit_id"], "instance_id": instance_id})
                
                elif event_type == "deleted":
                    session.run("""
                        MATCH (hi:HabitInstance {id: $instance_id})
                        DETACH DELETE hi
                    """, {"instance_id": instance_id})
                
                logger.debug(f"✓ Synced habit instance {instance_id} ({event_type})")
                return True
        
        except Exception as e:
            logger.error(f"Failed to sync habit instance {instance_id}: {e}")
            return False
    
    async def _sync_habit_log(self, event_type: str, log_id: str, payload: Dict) -> bool:
        """Sync habit log (completion events) to Neo4j"""
        try:
            with self.neo4j_driver.session() as session:
                if event_type in ["created", "updated"]:
                    # Create completion event node
                    cypher = """
                    MERGE (hl:HabitLog {id: $log_id})
                    SET hl.amount = $amount,
                        hl.notes = $notes,
                        hl.source = $source,
                        hl.created_at = $created_at,
                        hl.logged_at = $logged_at
                    """
                    
                    session.run(cypher, {
                        "log_id": log_id,
                        "amount": payload.get("amount"),
                        "notes": payload.get("notes"),
                        "source": payload.get("source"),
                        "created_at": payload.get("created_at"),
                        "logged_at": payload.get("logged_at")
                    })
                    
                    # Link to habit instance
                    if payload.get("instance_id"):
                        session.run("""
                            MATCH (hi:HabitInstance {id: $instance_id})
                            MATCH (hl:HabitLog {id: $log_id})
                            MERGE (hi)-[:HAS_LOG]->(hl)
                        """, {"instance_id": payload["instance_id"], "log_id": log_id})
                
                elif event_type == "deleted":
                    session.run("""
                        MATCH (hl:HabitLog {id: $log_id})
                        DETACH DELETE hl
                    """, {"log_id": log_id})
                
                logger.debug(f"✓ Synced habit log {log_id} ({event_type})")
                return True
        
        except Exception as e:
            logger.error(f"Failed to sync habit log {log_id}: {e}")
            return False
    
    async def _sync_habit_link(self, event_type: str, link_id: str, payload: Dict) -> bool:
        """Sync habit-note/document links to Neo4j"""
        try:
            with self.neo4j_driver.session() as session:
                if event_type in ["created", "updated"]:
                    # Create relationship between habit and linked entity
                    link_type = payload.get("link_type")
                    entity_type = payload.get("entity_type")
                    entity_id = payload.get("entity_id")
                    habit_id = payload.get("habit_id")
                    
                    if entity_type == "note":
                        cypher = """
                        MATCH (h:Habit {id: $habit_id})
                        MATCH (n:Note {id: $entity_id})
                        MERGE (h)-[r:LINKED_TO_NOTE]->(n)
                        SET r.link_type = $link_type,
                            r.created_at = $created_at
                        """
                    elif entity_type == "document":
                        cypher = """
                        MATCH (h:Habit {id: $habit_id})
                        MATCH (d:Document {id: $entity_id})
                        MERGE (h)-[r:LINKED_TO_DOCUMENT]->(d)
                        SET r.link_type = $link_type,
                            r.created_at = $created_at
                        """
                    else:
                        logger.warning(f"Unknown link entity type: {entity_type}")
                        return True
                    
                    session.run(cypher, {
                        "habit_id": habit_id,
                        "entity_id": entity_id,
                        "link_type": link_type,
                        "created_at": payload.get("created_at")
                    })
                
                elif event_type == "deleted":
                    # Remove specific relationship
                    habit_id = payload.get("habit_id")
                    entity_id = payload.get("entity_id")
                    entity_type = payload.get("entity_type")
                    
                    if entity_type == "note":
                        session.run("""
                            MATCH (h:Habit {id: $habit_id})-[r:LINKED_TO_NOTE]->(n:Note {id: $entity_id})
                            DELETE r
                        """, {"habit_id": habit_id, "entity_id": entity_id})
                    elif entity_type == "document":
                        session.run("""
                            MATCH (h:Habit {id: $habit_id})-[r:LINKED_TO_DOCUMENT]->(d:Document {id: $entity_id})
                            DELETE r
                        """, {"habit_id": habit_id, "entity_id": entity_id})
                
                logger.debug(f"✓ Synced habit link {link_id} ({event_type})")
                return True
        
        except Exception as e:
            logger.error(f"Failed to sync habit link {link_id}: {e}")
            return False
    
    async def create_habit_graph_insights(self, user_id: str) -> Dict[str, Any]:
        """Create graph-based insights for habit patterns"""
        if not self.neo4j_driver:
            return {"error": "Neo4j not available"}
        
        try:
            with self.neo4j_driver.session() as session:
                # Find habit patterns and connections
                insights = {}
                
                # Habit completion patterns
                result = session.run("""
                    MATCH (u:User {id: $user_id})-[:HAS_HABIT]->(h:Habit)-[:HAS_INSTANCE]->(hi:HabitInstance)
                    WHERE hi.status = 'complete'
                    RETURN h.title, COUNT(hi) as completions, h.current_streak, h.best_streak
                    ORDER BY completions DESC
                """, {"user_id": user_id})
                
                insights["completion_patterns"] = [
                    {
                        "habit": record["h.title"],
                        "completions": record["completions"],
                        "current_streak": record["h.current_streak"],
                        "best_streak": record["h.best_streak"]
                    }
                    for record in result
                ]
                
                # Connected notes/documents
                result = session.run("""
                    MATCH (u:User {id: $user_id})-[:HAS_HABIT]->(h:Habit)
                    OPTIONAL MATCH (h)-[:LINKED_TO_NOTE]->(n:Note)
                    OPTIONAL MATCH (h)-[:LINKED_TO_DOCUMENT]->(d:Document)
                    RETURN h.title, 
                           COLLECT(DISTINCT n.title) as linked_notes,
                           COLLECT(DISTINCT d.filename) as linked_documents
                """, {"user_id": user_id})
                
                insights["knowledge_connections"] = [
                    {
                        "habit": record["h.title"],
                        "linked_notes": [n for n in record["linked_notes"] if n],
                        "linked_documents": [d for d in record["linked_documents"] if d]
                    }
                    for record in result
                ]
                
                return insights
        
        except Exception as e:
            logger.error(f"Failed to create habit graph insights: {e}")
            return {"error": str(e)}
    
    def close(self):
        """Close Neo4j driver"""
        if self.neo4j_driver:
            self.neo4j_driver.close()


async def main():
    """Test runner for development"""
    logging.basicConfig(level=logging.INFO)
    
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
    worker = HabitNeo4jWorker(database_url)
    
    print("🧪 Testing Habit Neo4j Worker...")
    
    try:
        # Test outbox processing
        results = await worker.process_outbox_events()
        print(f"✅ Outbox processing: {results}")
        
    finally:
        worker.close()


if __name__ == "__main__":
    asyncio.run(main())