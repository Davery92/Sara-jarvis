#!/usr/bin/env python3
"""
Neo4j Orphaned Data Cleanup Script

This script removes orphaned nodes from Neo4j that no longer exist in PostgreSQL.
It provides options for dry-run (preview) and actual cleanup.
"""

import os
import logging
import argparse
from typing import Set, Dict, List
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from neo4j import GraphDatabase

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Neo4jDataCleaner:
    def __init__(self):
        # PostgreSQL connection
        self.postgres_url = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
        self.postgres_engine = create_engine(self.postgres_url)
        self.postgres_session = sessionmaker(bind=self.postgres_engine)

        # Neo4j connection
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://10.185.1.180:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "sara-graph-secret")
        self.neo4j_driver = GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password)
        )

    def get_postgresql_ids(self, table_name: str) -> Set[str]:
        """Get all IDs from a PostgreSQL table"""
        with self.postgres_session() as session:
            result = session.execute(text(f"SELECT id FROM {table_name}"))
            return {str(row[0]) for row in result}

    def get_neo4j_nodes(self, node_type: str) -> List[Dict]:
        """Get all nodes of a specific type from Neo4j with details"""
        with self.neo4j_driver.session() as session:
            result = session.run(
                f"MATCH (n:{node_type}) RETURN n.id as id, n.title as title, n.user_id as user_id, n.created_at as created_at"
            )
            return [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "user_id": record["user_id"],
                    "created_at": record["created_at"]
                }
                for record in result
            ]

    def find_orphaned_nodes(self) -> Dict:
        """Find all orphaned nodes in Neo4j"""
        logger.info("Finding orphaned nodes...")
        
        # Get valid IDs from PostgreSQL
        postgres_notes = self.get_postgresql_ids("note")
        postgres_documents = self.get_postgresql_ids("document")
        
        # Get all nodes from Neo4j
        neo4j_notes = self.get_neo4j_nodes("Note")
        neo4j_documents = self.get_neo4j_nodes("Document")
        
        # Find orphaned nodes
        orphaned_notes = [note for note in neo4j_notes if note["id"] not in postgres_notes]
        orphaned_documents = [doc for doc in neo4j_documents if doc["id"] not in postgres_documents]
        
        return {
            "notes": orphaned_notes,
            "documents": orphaned_documents,
            "total_orphaned": len(orphaned_notes) + len(orphaned_documents)
        }

    def preview_cleanup(self, orphaned_data: Dict):
        """Preview what would be cleaned up"""
        print("\n" + "="*80)
        print("CLEANUP PREVIEW")
        print("="*80)
        
        total = orphaned_data["total_orphaned"]
        print(f"\nTotal orphaned nodes to be removed: {total}")
        
        if orphaned_data["notes"]:
            print(f"\n📝 ORPHANED NOTES TO BE REMOVED ({len(orphaned_data['notes'])}):")
            for note in orphaned_data["notes"]:
                print(f"  - ID: {note['id']}")
                print(f"    Title: {note['title']}")
                print(f"    User ID: {note['user_id']}")
                print(f"    Created: {note['created_at']}")
                print()
        
        if orphaned_data["documents"]:
            print(f"\n📄 ORPHANED DOCUMENTS TO BE REMOVED ({len(orphaned_data['documents'])}):")
            for doc in orphaned_data["documents"]:
                print(f"  - ID: {doc['id']}")
                print(f"    Title: {doc['title']}")
                print(f"    User ID: {doc['user_id']}")
                print(f"    Created: {doc['created_at']}")
                print()
        
        if total == 0:
            print("\n✅ No orphaned nodes found. Database is consistent!")
        
        print("="*80)

    def cleanup_orphaned_node(self, node_id: str, node_type: str) -> bool:
        """Remove a single orphaned node and all its relationships"""
        with self.neo4j_driver.session() as session:
            try:
                # Delete the node and all its relationships
                result = session.run(
                    f"""
                    MATCH (n:{node_type} {{id: $node_id}})
                    OPTIONAL MATCH (n)-[r]-()
                    DELETE r, n
                    RETURN count(n) as deleted_count
                    """,
                    node_id=node_id
                )
                record = result.single()
                return record and record["deleted_count"] > 0
            except Exception as e:
                logger.error(f"Failed to delete {node_type} node {node_id}: {e}")
                return False

    def perform_cleanup(self, orphaned_data: Dict) -> Dict:
        """Perform the actual cleanup of orphaned nodes"""
        logger.info("Starting cleanup of orphaned nodes...")
        
        results = {
            "notes_deleted": 0,
            "documents_deleted": 0,
            "failed_deletions": []
        }
        
        # Clean up orphaned notes
        for note in orphaned_data["notes"]:
            logger.info(f"Deleting orphaned note: {note['id']} - {note['title']}")
            if self.cleanup_orphaned_node(note["id"], "Note"):
                results["notes_deleted"] += 1
                logger.info(f"✅ Successfully deleted note {note['id']}")
            else:
                results["failed_deletions"].append(("Note", note["id"], note["title"]))
                logger.error(f"❌ Failed to delete note {note['id']}")
        
        # Clean up orphaned documents
        for doc in orphaned_data["documents"]:
            logger.info(f"Deleting orphaned document: {doc['id']} - {doc['title']}")
            if self.cleanup_orphaned_node(doc["id"], "Document"):
                results["documents_deleted"] += 1
                logger.info(f"✅ Successfully deleted document {doc['id']}")
            else:
                results["failed_deletions"].append(("Document", doc["id"], doc["title"]))
                logger.error(f"❌ Failed to delete document {doc['id']}")
        
        return results

    def print_cleanup_results(self, results: Dict):
        """Print the results of the cleanup operation"""
        print("\n" + "="*80)
        print("CLEANUP RESULTS")
        print("="*80)
        
        total_deleted = results["notes_deleted"] + results["documents_deleted"]
        print(f"\nSuccessfully deleted: {total_deleted} orphaned nodes")
        print(f"  - Notes deleted: {results['notes_deleted']}")
        print(f"  - Documents deleted: {results['documents_deleted']}")
        
        if results["failed_deletions"]:
            print(f"\nFailed deletions: {len(results['failed_deletions'])}")
            for node_type, node_id, title in results["failed_deletions"]:
                print(f"  - {node_type}: {node_id} - {title}")
        else:
            print(f"\n✅ All orphaned nodes were successfully removed!")
        
        print("\n" + "="*80)

    def close_connections(self):
        """Close database connections"""
        self.postgres_engine.dispose()
        self.neo4j_driver.close()

def main():
    parser = argparse.ArgumentParser(description="Cleanup orphaned data in Neo4j")
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Preview what would be cleaned up without actually deleting anything"
    )
    parser.add_argument(
        "--confirm", 
        action="store_true", 
        help="Confirm that you want to perform the actual cleanup"
    )
    parser.add_argument(
        "--force", 
        action="store_true", 
        help="Force cleanup without interactive confirmation"
    )
    
    args = parser.parse_args()
    
    cleaner = Neo4jDataCleaner()
    
    try:
        # Find orphaned nodes
        orphaned_data = cleaner.find_orphaned_nodes()
        
        if args.dry_run or not args.confirm:
            # Show preview
            cleaner.preview_cleanup(orphaned_data)
            
            if not args.dry_run and orphaned_data["total_orphaned"] > 0:
                print("\n⚠️  To actually perform the cleanup, run with --confirm flag:")
                print("python3 cleanup_orphaned_neo4j_data.py --confirm")
        
        elif args.confirm:
            # Show preview first
            cleaner.preview_cleanup(orphaned_data)
            
            if orphaned_data["total_orphaned"] > 0:
                # Ask for final confirmation (unless force flag is used)
                if args.force:
                    print(f"\n🚀 Force flag detected - proceeding with cleanup of {orphaned_data['total_orphaned']} orphaned nodes...")
                    # Perform cleanup
                    results = cleaner.perform_cleanup(orphaned_data)
                    cleaner.print_cleanup_results(results)
                else:
                    response = input(f"\n⚠️  Are you sure you want to delete {orphaned_data['total_orphaned']} orphaned nodes? (yes/no): ")
                    if response.lower() == 'yes':
                        # Perform cleanup
                        results = cleaner.perform_cleanup(orphaned_data)
                        cleaner.print_cleanup_results(results)
                    else:
                        print("Cleanup cancelled.")
            else:
                print("\n✅ No cleanup needed - database is already consistent!")
        
    except Exception as e:
        logger.error(f"Error during cleanup operation: {e}")
        raise
    finally:
        cleaner.close_connections()

if __name__ == "__main__":
    main()