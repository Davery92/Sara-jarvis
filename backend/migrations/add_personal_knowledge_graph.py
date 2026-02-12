"""
Migration: Initialize Personal Knowledge Graph (PKG) schema in Neo4j

Creates constraints and indexes for PKG node types:
- PKG_Person, PKG_Preference, PKG_Routine, PKG_Goal
- PKG_Interest, PKG_Health, PKG_Place, PKG_Fact

No PostgreSQL changes needed — PKG lives entirely in Neo4j.
"""

import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Initialize PKG schema in Neo4j"""
    # Set Neo4j env vars if not set
    if not os.getenv("NEO4J_URI"):
        os.environ["NEO4J_URI"] = "bolt://10.185.1.180:7687"
        os.environ["NEO4J_USER"] = "neo4j"
        os.environ["NEO4J_PASSWORD"] = "sara-graph-secret"

    from app.services.personal_knowledge_graph import personal_kg

    logger.info("Initializing Personal Knowledge Graph schema in Neo4j...")
    success = personal_kg.initialize_schema()

    if success:
        logger.info("PKG schema initialized successfully!")

        # Verify by getting stats
        stats = personal_kg.get_stats()
        logger.info(f"PKG stats: {stats}")
    else:
        logger.error("PKG schema initialization failed!")
        sys.exit(1)


if __name__ == "__main__":
    run_migration()
