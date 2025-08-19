#!/usr/bin/env python3
"""
Migration script to populate Neo4j knowledge graph from existing PostgreSQL data.
Run this after setting up Neo4j to migrate existing notes, episodes, and documents.
"""
import os
import sys
import asyncio
import logging
from typing import List, Dict, Any
import json
import numpy as np
from datetime import datetime, timezone

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.services.neo4j_service import neo4j_service

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Create PostgreSQL connection
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class DataMigrator:
    """Handles migration from PostgreSQL to Neo4j"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.stats = {
            "users_migrated": 0,
            "notes_migrated": 0,
            "episodes_migrated": 0,
            "documents_migrated": 0,
            "folders_migrated": 0,
            "connections_created": 0,
            "errors": 0
        }
    
    async def run_migration(self):
        """Run complete data migration"""
        logger.info("🚀 Starting Neo4j knowledge graph migration...")
        
        try:
            # Connect to Neo4j
            await neo4j_service.connect()
            
            # Migrate data in order (users first, then content, then relationships)
            await self.migrate_users()
            await self.migrate_folders()
            await self.migrate_notes()
            await self.migrate_episodes()
            await self.migrate_documents()
            await self.create_relationships()
            
            # Print migration summary
            self.print_migration_summary()
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            raise
        finally:
            self.db.close()
            neo4j_service.close()
    
    async def migrate_users(self):
        """Migrate users from PostgreSQL to Neo4j"""
        logger.info("👥 Migrating users...")
        
        try:
            # Get all users
            result = self.db.execute(text("""
                SELECT id, email, created_at 
                FROM app_user 
                ORDER BY created_at
            """))
            
            for row in result:
                try:
                    await neo4j_service.create_user(
                        user_id=row.id,
                        email=row.email,
                        migrated_at=datetime.now(timezone.utc).isoformat(),
                        original_created_at=row.created_at.isoformat() if row.created_at else None
                    )
                    self.stats["users_migrated"] += 1
                    logger.debug(f"✅ Migrated user: {row.email}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to migrate user {row.email}: {e}")
                    self.stats["errors"] += 1
            
            logger.info(f"✅ Migrated {self.stats['users_migrated']} users")
            
        except Exception as e:
            logger.error(f"❌ User migration failed: {e}")
            raise
    
    async def migrate_folders(self):
        """Migrate folders to Neo4j"""
        logger.info("📁 Migrating folders...")
        
        try:
            result = self.db.execute(text("""
                SELECT id, user_id, name, parent_id, sort_order, created_at
                FROM folder
                ORDER BY created_at
            """))
            
            for row in result:
                try:
                    await neo4j_service.create_folder(
                        folder_id=row.id,
                        user_id=row.user_id,
                        name=row.name,
                        parent_id=row.parent_id,
                        sort_order=row.sort_order or 0,
                        migrated_at=datetime.now(timezone.utc).isoformat(),
                        original_created_at=row.created_at.isoformat() if row.created_at else None
                    )
                    self.stats["folders_migrated"] += 1
                    logger.debug(f"✅ Migrated folder: {row.name}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to migrate folder {row.name}: {e}")
                    self.stats["errors"] += 1
            
            logger.info(f"✅ Migrated {self.stats['folders_migrated']} folders")
            
        except Exception as e:
            logger.error(f"❌ Folder migration failed: {e}")
            raise
    
    async def migrate_notes(self):
        """Migrate notes from PostgreSQL to Neo4j"""
        logger.info("📝 Migrating notes...")
        
        try:
            # Try to get notes with embeddings, fall back if embedding column doesn't exist
            try:
                result = self.db.execute(text("""
                    SELECT id, user_id, folder_id, title, content, created_at, updated_at, embedding
                    FROM note 
                    ORDER BY created_at
                """))
            except Exception as e:
                if "embedding" in str(e) and "does not exist" in str(e):
                    logger.info("📝 Note: embedding column not found, proceeding without embeddings")
                    # Rollback the failed transaction
                    self.db.rollback()
                    result = self.db.execute(text("""
                        SELECT id, user_id, folder_id, title, content, created_at, updated_at
                        FROM note 
                        ORDER BY created_at
                    """))
                else:
                    raise
            
            for row in result:
                try:
                    # Process embedding if available
                    embedding = None
                    if hasattr(row, 'embedding') and row.embedding:
                        try:
                            if isinstance(row.embedding, str):
                                embedding = json.loads(row.embedding)
                            elif hasattr(row.embedding, '__iter__'):
                                embedding = list(row.embedding)
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(f"⚠️ Invalid embedding for note {row.id}: {e}")
                    
                    await neo4j_service.create_note(
                        note_id=row.id,
                        user_id=row.user_id,
                        title=row.title or "",
                        content=row.content or "",
                        folder_id=row.folder_id,
                        embedding=embedding,
                        migrated_at=datetime.now(timezone.utc).isoformat(),
                        original_created_at=row.created_at.isoformat() if row.created_at else None,
                        original_updated_at=row.updated_at.isoformat() if row.updated_at else None
                    )
                    self.stats["notes_migrated"] += 1
                    logger.debug(f"✅ Migrated note: {row.title or 'Untitled'}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to migrate note {row.id}: {e}")
                    self.stats["errors"] += 1
            
            logger.info(f"✅ Migrated {self.stats['notes_migrated']} notes")
            
        except Exception as e:
            logger.error(f"❌ Note migration failed: {e}")
            raise
    
    async def migrate_episodes(self):
        """Migrate conversation episodes to Neo4j"""
        logger.info("💭 Migrating conversation episodes...")
        
        try:
            # Try conversation_turn table first (newer schema)
            try:
                try:
                    result = self.db.execute(text("""
                        SELECT id, user_id, content, role, message_index, created_at, embedding
                        FROM conversation_turn 
                        ORDER BY created_at
                    """))
                except Exception as e:
                    if "embedding" in str(e) and "does not exist" in str(e):
                        result = self.db.execute(text("""
                            SELECT id, user_id, content, role, message_index, created_at, NULL as embedding
                            FROM conversation_turn 
                            ORDER BY created_at
                        """))
                    else:
                        raise
                
                for row in result:
                    try:
                        # Process embedding
                        embedding = None
                        if row.embedding:
                            try:
                                if isinstance(row.embedding, str):
                                    embedding = json.loads(row.embedding)
                                elif hasattr(row.embedding, '__iter__'):
                                    embedding = list(row.embedding)
                            except (json.JSONDecodeError, TypeError) as e:
                                logger.warning(f"⚠️ Invalid embedding for episode {row.id}: {e}")
                        
                        # Calculate importance based on role and content length
                        importance = 0.5  # Default
                        if row.role == "assistant":
                            importance = 0.7  # Sara's responses are important
                        elif len(row.content or "") > 100:
                            importance = 0.6  # Longer messages are more important
                        
                        await neo4j_service.create_episode(
                            episode_id=row.id,
                            user_id=row.user_id,
                            content=row.content or "",
                            role=row.role or "user",
                            importance=importance,
                            source="conversation",
                            embedding=embedding,
                            message_index=row.message_index,
                            migrated_at=datetime.now(timezone.utc).isoformat(),
                            original_created_at=row.created_at.isoformat() if row.created_at else None
                        )
                        self.stats["episodes_migrated"] += 1
                        logger.debug(f"✅ Migrated episode: {row.role} - {(row.content or '')[:50]}...")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to migrate episode {row.id}: {e}")
                        self.stats["errors"] += 1
                        
            except Exception:
                # Fallback to episode table (older schema)
                logger.info("💭 Trying fallback episode table...")
                try:
                    result = self.db.execute(text("""
                        SELECT id, user_id, content, role, importance, source, created_at, embedding
                        FROM episode 
                        ORDER BY created_at
                    """))
                except Exception as e:
                    if "embedding" in str(e) and "does not exist" in str(e):
                        result = self.db.execute(text("""
                            SELECT id, user_id, content, role, importance, source, created_at, NULL as embedding
                            FROM episode 
                            ORDER BY created_at
                        """))
                    else:
                        # Episode table might not exist at all
                        logger.info("💭 No episode tables found, skipping episode migration")
                        return
                
                for row in result:
                    try:
                        # Process embedding
                        embedding = None
                        if row.embedding:
                            try:
                                embedding = json.loads(row.embedding) if isinstance(row.embedding, str) else list(row.embedding)
                            except (json.JSONDecodeError, TypeError) as e:
                                logger.warning(f"⚠️ Invalid embedding for episode {row.id}: {e}")
                        
                        await neo4j_service.create_episode(
                            episode_id=row.id,
                            user_id=row.user_id,
                            content=row.content or "",
                            role=row.role or "user",
                            importance=float(row.importance or 0.5),
                            source=row.source or "conversation",
                            embedding=embedding,
                            migrated_at=datetime.now(timezone.utc).isoformat(),
                            original_created_at=row.created_at.isoformat() if row.created_at else None
                        )
                        self.stats["episodes_migrated"] += 1
                        logger.debug(f"✅ Migrated episode: {row.role} - {(row.content or '')[:50]}...")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to migrate episode {row.id}: {e}")
                        self.stats["errors"] += 1
            
            logger.info(f"✅ Migrated {self.stats['episodes_migrated']} episodes")
            
        except Exception as e:
            logger.error(f"❌ Episode migration failed: {e}")
            raise
    
    async def migrate_documents(self):
        """Migrate documents to Neo4j"""
        logger.info("📄 Migrating documents...")
        
        try:
            try:
                result = self.db.execute(text("""
                    SELECT id, user_id, title, content_text, mime_type, file_path, created_at, embedding
                    FROM document 
                    ORDER BY created_at
                """))
            except Exception as e:
                if "embedding" in str(e) and "does not exist" in str(e):
                    # Rollback the failed transaction
                    self.db.rollback()
                    result = self.db.execute(text("""
                        SELECT id, user_id, title, content_text, mime_type, file_path, created_at, NULL as embedding
                        FROM document 
                        ORDER BY created_at
                    """))
                elif "document" in str(e) and "does not exist" in str(e):
                    logger.info("📄 Document table not found, skipping document migration")
                    return
                else:
                    raise
            
            for row in result:
                try:
                    # Process embedding
                    embedding = None
                    if row.embedding:
                        try:
                            embedding = json.loads(row.embedding) if isinstance(row.embedding, str) else list(row.embedding)
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(f"⚠️ Invalid embedding for document {row.id}: {e}")
                    
                    await neo4j_service.create_document(
                        doc_id=row.id,
                        user_id=row.user_id,
                        title=row.title or "Untitled Document",
                        content_text=row.content_text or "",
                        mime_type=row.mime_type or "unknown",
                        file_path=row.file_path,
                        embedding=embedding,
                        migrated_at=datetime.now(timezone.utc).isoformat(),
                        original_created_at=row.created_at.isoformat() if row.created_at else None
                    )
                    self.stats["documents_migrated"] += 1
                    logger.debug(f"✅ Migrated document: {row.title or 'Untitled'}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to migrate document {row.id}: {e}")
                    self.stats["errors"] += 1
            
            logger.info(f"✅ Migrated {self.stats['documents_migrated']} documents")
            
        except Exception as e:
            logger.error(f"❌ Document migration failed: {e}")
            raise
    
    async def create_relationships(self):
        """Create relationships between migrated content"""
        logger.info("🔗 Creating knowledge graph relationships...")
        
        try:
            # Migrate existing note connections if they exist
            await self.migrate_note_connections()
            
            # Create semantic relationships based on embeddings
            await self.create_semantic_relationships()
            
            # Create temporal relationships
            await self.create_temporal_relationships()
            
            logger.info(f"✅ Created {self.stats['connections_created']} relationships")
            
        except Exception as e:
            logger.error(f"❌ Relationship creation failed: {e}")
            raise
    
    async def migrate_note_connections(self):
        """Migrate existing note connections if they exist"""
        try:
            result = self.db.execute(text("""
                SELECT source_note_id, target_note_id, connection_type, strength
                FROM note_connection
                WHERE auto_generated = 'true'
            """))
            
            for row in result:
                try:
                    connection_type = "REFERENCES" if row.connection_type == "reference" else "SEMANTIC_SIMILAR"
                    
                    if connection_type == "REFERENCES":
                        await neo4j_service.create_reference_link(
                            source_id=row.source_note_id,
                            target_id=row.target_note_id,
                            link_type="REFERENCES"
                        )
                    else:
                        await neo4j_service.create_semantic_connection(
                            node1_id=row.source_note_id,
                            node2_id=row.target_note_id,
                            similarity=float(row.strength or 0.5)
                        )
                    
                    self.stats["connections_created"] += 1
                    
                except Exception as e:
                    logger.error(f"❌ Failed to migrate connection {row.source_note_id}->{row.target_note_id}: {e}")
                    self.stats["errors"] += 1
                    
        except Exception as e:
            logger.debug(f"No existing note connections to migrate: {e}")
    
    async def create_semantic_relationships(self):
        """Create semantic relationships based on content similarity"""
        logger.info("🧠 Creating semantic relationships...")
        
        # This is a simplified version - in production you'd want more sophisticated similarity calculation
        try:
            # Get all nodes with content for similarity comparison
            graph_data = await neo4j_service.get_user_knowledge_graph("", depth=1)  # All users for now
            
            # Simple keyword-based similarity for now
            # In production, you'd use proper embedding similarity
            nodes_with_content = [
                node for node in graph_data.get("nodes", [])
                if any(prop in node.get("properties", {}) for prop in ["content", "content_text"])
            ]
            
            similarity_threshold = 0.3
            for i, node1 in enumerate(nodes_with_content):
                for node2 in nodes_with_content[i+1:]:
                    similarity = self._calculate_simple_similarity(node1, node2)
                    
                    if similarity > similarity_threshold:
                        await neo4j_service.create_semantic_connection(
                            node1_id=node1["properties"]["id"],
                            node2_id=node2["properties"]["id"],
                            similarity=similarity
                        )
                        self.stats["connections_created"] += 1
                        
        except Exception as e:
            logger.warning(f"⚠️ Semantic relationship creation had issues: {e}")
    
    async def create_temporal_relationships(self):
        """Create temporal relationships for content created around the same time"""
        logger.info("⏰ Creating temporal relationships...")
        
        # Create temporal connections for items created within 24 hours of each other
        # This is handled by the Neo4j service based on created_at timestamps
        pass  # Implementation would go here if needed
    
    def _calculate_simple_similarity(self, node1: Dict, node2: Dict) -> float:
        """Simple keyword-based similarity calculation"""
        try:
            props1 = node1.get("properties", {})
            props2 = node2.get("properties", {})
            
            text1 = (props1.get("content", "") + " " + props1.get("content_text", "") + " " + props1.get("title", "")).lower()
            text2 = (props2.get("content", "") + " " + props2.get("content_text", "") + " " + props2.get("title", "")).lower()
            
            if not text1.strip() or not text2.strip():
                return 0.0
            
            words1 = set(text1.split())
            words2 = set(text2.split())
            
            if not words1 or not words2:
                return 0.0
            
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            
            return len(intersection) / len(union) if union else 0.0
            
        except Exception:
            return 0.0
    
    def print_migration_summary(self):
        """Print migration statistics"""
        logger.info("📊 Migration Summary:")
        logger.info(f"  👥 Users migrated: {self.stats['users_migrated']}")
        logger.info(f"  📁 Folders migrated: {self.stats['folders_migrated']}")
        logger.info(f"  📝 Notes migrated: {self.stats['notes_migrated']}")
        logger.info(f"  💭 Episodes migrated: {self.stats['episodes_migrated']}")
        logger.info(f"  📄 Documents migrated: {self.stats['documents_migrated']}")
        logger.info(f"  🔗 Connections created: {self.stats['connections_created']}")
        logger.info(f"  ❌ Errors encountered: {self.stats['errors']}")
        
        total_items = (self.stats['users_migrated'] + self.stats['folders_migrated'] + 
                      self.stats['notes_migrated'] + self.stats['episodes_migrated'] + 
                      self.stats['documents_migrated'])
        
        if total_items > 0:
            success_rate = ((total_items - self.stats['errors']) / total_items) * 100
            logger.info(f"  📈 Success rate: {success_rate:.1f}%")
        
        if self.stats['errors'] == 0:
            logger.info("🎉 Migration completed successfully!")
        else:
            logger.warning(f"⚠️ Migration completed with {self.stats['errors']} errors")

async def main():
    """Main migration function"""
    migrator = DataMigrator()
    await migrator.run_migration()

if __name__ == "__main__":
    asyncio.run(main())