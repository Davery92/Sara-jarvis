#!/usr/bin/env python3
"""
Data Consistency Checker between PostgreSQL and Neo4j

This script compares data between PostgreSQL and Neo4j to identify:
1. Notes that exist in PostgreSQL but not in Neo4j
2. Notes that exist in Neo4j but not in PostgreSQL (orphaned)
3. Documents that exist in PostgreSQL but not in Neo4j
4. Documents that exist in Neo4j but not in PostgreSQL (orphaned)
"""

import os
import asyncio
import logging
from typing import Set, Dict, List, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from neo4j import GraphDatabase
import uuid

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataConsistencyChecker:
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

    def get_postgresql_notes(self) -> Set[str]:
        """Get all note IDs from PostgreSQL"""
        with self.postgres_session() as session:
            result = session.execute(text("SELECT id FROM note"))
            return {str(row[0]) for row in result}

    def get_postgresql_documents(self) -> Set[str]:
        """Get all document IDs from PostgreSQL"""
        with self.postgres_session() as session:
            result = session.execute(text("SELECT id FROM document"))
            return {str(row[0]) for row in result}

    def get_neo4j_notes(self) -> Set[str]:
        """Get all Note node IDs from Neo4j"""
        with self.neo4j_driver.session() as session:
            result = session.run("MATCH (n:Note) RETURN n.id as id")
            return {record["id"] for record in result}

    def get_neo4j_documents(self) -> Set[str]:
        """Get all Document node IDs from Neo4j"""
        with self.neo4j_driver.session() as session:
            result = session.run("MATCH (d:Document) RETURN d.id as id")
            return {record["id"] for record in result}

    def get_postgresql_note_details(self, note_ids: Set[str]) -> List[Dict]:
        """Get detailed information about specific notes from PostgreSQL"""
        if not note_ids:
            return []
        
        # Convert UUIDs to string format for the query
        id_list = "', '".join(note_ids)
        with self.postgres_session() as session:
            query = f"""
            SELECT n.id, n.title, n.created_at, n.updated_at, u.email as user_email
            FROM note n
            JOIN app_user u ON n.user_id = u.id
            WHERE n.id::text IN ('{id_list}')
            """
            result = session.execute(text(query))
            return [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "created_at": row[2],
                    "updated_at": row[3],
                    "user_email": row[4]
                }
                for row in result
            ]

    def get_postgresql_document_details(self, doc_ids: Set[str]) -> List[Dict]:
        """Get detailed information about specific documents from PostgreSQL"""
        if not doc_ids:
            return []
        
        id_list = "', '".join(doc_ids)
        with self.postgres_session() as session:
            query = f"""
            SELECT d.id, d.title, d.mime_type, d.created_at, u.email as user_email
            FROM document d
            JOIN app_user u ON d.user_id = u.id
            WHERE d.id::text IN ('{id_list}')
            """
            result = session.execute(text(query))
            return [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "mime_type": row[2],
                    "created_at": row[3],
                    "user_email": row[4]
                }
                for row in result
            ]

    def get_neo4j_node_details(self, node_ids: Set[str], node_type: str) -> List[Dict]:
        """Get detailed information about specific nodes from Neo4j"""
        if not node_ids:
            return []
        
        with self.neo4j_driver.session() as session:
            result = session.run(
                f"MATCH (n:{node_type}) WHERE n.id IN $ids RETURN n.id as id, n.title as title, n.created_at as created_at, n.user_id as user_id",
                ids=list(node_ids)
            )
            return [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "created_at": record["created_at"],
                    "user_id": record["user_id"]
                }
                for record in result
            ]

    def run_consistency_check(self) -> Dict:
        """Run the full consistency check"""
        logger.info("Starting data consistency check between PostgreSQL and Neo4j...")

        # Get all IDs from both databases
        logger.info("Fetching note IDs from PostgreSQL...")
        postgres_notes = self.get_postgresql_notes()
        logger.info(f"Found {len(postgres_notes)} notes in PostgreSQL")

        logger.info("Fetching note IDs from Neo4j...")
        neo4j_notes = self.get_neo4j_notes()
        logger.info(f"Found {len(neo4j_notes)} notes in Neo4j")

        logger.info("Fetching document IDs from PostgreSQL...")
        postgres_documents = self.get_postgresql_documents()
        logger.info(f"Found {len(postgres_documents)} documents in PostgreSQL")

        logger.info("Fetching document IDs from Neo4j...")
        neo4j_documents = self.get_neo4j_documents()
        logger.info(f"Found {len(neo4j_documents)} documents in Neo4j")

        # Find inconsistencies
        # Notes only in PostgreSQL (missing from Neo4j)
        notes_missing_in_neo4j = postgres_notes - neo4j_notes
        # Notes only in Neo4j (orphaned - deleted from PostgreSQL)
        notes_orphaned_in_neo4j = neo4j_notes - postgres_notes

        # Documents only in PostgreSQL (missing from Neo4j)
        docs_missing_in_neo4j = postgres_documents - neo4j_documents
        # Documents only in Neo4j (orphaned - deleted from PostgreSQL)
        docs_orphaned_in_neo4j = neo4j_documents - postgres_documents

        # Get detailed information about inconsistencies
        logger.info("Getting detailed information about inconsistencies...")
        
        missing_notes_details = self.get_postgresql_note_details(notes_missing_in_neo4j)
        orphaned_notes_details = self.get_neo4j_node_details(notes_orphaned_in_neo4j, "Note")
        
        missing_docs_details = self.get_postgresql_document_details(docs_missing_in_neo4j)
        orphaned_docs_details = self.get_neo4j_node_details(docs_orphaned_in_neo4j, "Document")

        results = {
            "summary": {
                "postgres_notes_count": len(postgres_notes),
                "neo4j_notes_count": len(neo4j_notes),
                "postgres_documents_count": len(postgres_documents),
                "neo4j_documents_count": len(neo4j_documents),
                "notes_missing_in_neo4j": len(notes_missing_in_neo4j),
                "notes_orphaned_in_neo4j": len(notes_orphaned_in_neo4j),
                "docs_missing_in_neo4j": len(docs_missing_in_neo4j),
                "docs_orphaned_in_neo4j": len(docs_orphaned_in_neo4j)
            },
            "inconsistencies": {
                "notes_missing_in_neo4j": {
                    "ids": list(notes_missing_in_neo4j),
                    "details": missing_notes_details
                },
                "notes_orphaned_in_neo4j": {
                    "ids": list(notes_orphaned_in_neo4j),
                    "details": orphaned_notes_details
                },
                "documents_missing_in_neo4j": {
                    "ids": list(docs_missing_in_neo4j),
                    "details": missing_docs_details
                },
                "documents_orphaned_in_neo4j": {
                    "ids": list(docs_orphaned_in_neo4j),
                    "details": orphaned_docs_details
                }
            }
        }

        return results

    def print_report(self, results: Dict):
        """Print a formatted report of the consistency check results"""
        print("\n" + "="*80)
        print("DATA CONSISTENCY REPORT")
        print("="*80)
        
        summary = results["summary"]
        print(f"\nDATABASE COUNTS:")
        print(f"  PostgreSQL Notes:    {summary['postgres_notes_count']}")
        print(f"  Neo4j Notes:         {summary['neo4j_notes_count']}")
        print(f"  PostgreSQL Documents: {summary['postgres_documents_count']}")
        print(f"  Neo4j Documents:     {summary['neo4j_documents_count']}")
        
        print(f"\nINCONSISTENCIES FOUND:")
        print(f"  Notes missing in Neo4j:     {summary['notes_missing_in_neo4j']}")
        print(f"  Notes orphaned in Neo4j:    {summary['notes_orphaned_in_neo4j']}")
        print(f"  Documents missing in Neo4j: {summary['docs_missing_in_neo4j']}")
        print(f"  Documents orphaned in Neo4j: {summary['docs_orphaned_in_neo4j']}")

        inconsistencies = results["inconsistencies"]

        # Notes missing in Neo4j
        if inconsistencies["notes_missing_in_neo4j"]["ids"]:
            print(f"\n📝 NOTES MISSING IN NEO4J ({len(inconsistencies['notes_missing_in_neo4j']['ids'])}):")
            for note in inconsistencies["notes_missing_in_neo4j"]["details"]:
                print(f"  - ID: {note['id']}")
                print(f"    Title: {note['title']}")
                print(f"    User: {note['user_email']}")
                print(f"    Created: {note['created_at']}")
                print()

        # Notes orphaned in Neo4j (deleted from PostgreSQL)
        if inconsistencies["notes_orphaned_in_neo4j"]["ids"]:
            print(f"\n🗑️  NOTES ORPHANED IN NEO4J ({len(inconsistencies['notes_orphaned_in_neo4j']['ids'])}):")
            print("These notes exist in Neo4j but have been deleted from PostgreSQL:")
            for note in inconsistencies["notes_orphaned_in_neo4j"]["details"]:
                print(f"  - ID: {note['id']}")
                print(f"    Title: {note['title']}")
                print(f"    User ID: {note['user_id']}")
                print()

        # Documents missing in Neo4j
        if inconsistencies["documents_missing_in_neo4j"]["ids"]:
            print(f"\n📄 DOCUMENTS MISSING IN NEO4J ({len(inconsistencies['documents_missing_in_neo4j']['ids'])}):")
            for doc in inconsistencies["documents_missing_in_neo4j"]["details"]:
                print(f"  - ID: {doc['id']}")
                print(f"    Title: {doc['title']}")
                print(f"    Type: {doc['mime_type']}")
                print(f"    User: {doc['user_email']}")
                print(f"    Created: {doc['created_at']}")
                print()

        # Documents orphaned in Neo4j
        if inconsistencies["documents_orphaned_in_neo4j"]["ids"]:
            print(f"\n🗑️  DOCUMENTS ORPHANED IN NEO4J ({len(inconsistencies['documents_orphaned_in_neo4j']['ids'])}):")
            print("These documents exist in Neo4j but have been deleted from PostgreSQL:")
            for doc in inconsistencies["documents_orphaned_in_neo4j"]["details"]:
                print(f"  - ID: {doc['id']}")
                print(f"    Title: {doc['title']}")
                print(f"    User ID: {doc['user_id']}")
                print()

        # Cleanup recommendations
        total_orphaned = summary['notes_orphaned_in_neo4j'] + summary['docs_orphaned_in_neo4j']
        if total_orphaned > 0:
            print(f"\n🧹 CLEANUP RECOMMENDATIONS:")
            print(f"  Total orphaned nodes in Neo4j: {total_orphaned}")
            print(f"  Consider running cleanup script to remove orphaned nodes.")
            print(f"  This will help maintain data consistency and improve performance.")

        print("\n" + "="*80)

    def close_connections(self):
        """Close database connections"""
        self.postgres_engine.dispose()
        self.neo4j_driver.close()

def main():
    checker = DataConsistencyChecker()
    
    try:
        results = checker.run_consistency_check()
        checker.print_report(results)
        
        # Return results for potential use in cleanup scripts
        return results
        
    except Exception as e:
        logger.error(f"Error during consistency check: {e}")
        raise
    finally:
        checker.close_connections()

if __name__ == "__main__":
    main()