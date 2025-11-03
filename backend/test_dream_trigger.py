"""
Manual trigger for nightly dream service
This script runs the dream consolidation process to test Neo4j storage.
"""
import asyncio
import logging
import sys
import os

# Add backend to path
sys.path.insert(0, '/home/david/jarvis/backend')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set environment variables
os.environ['DATABASE_URL'] = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
os.environ['NEO4J_URI'] = "bolt://10.185.1.180:7687"
os.environ['NEO4J_USER'] = "neo4j"
os.environ['NEO4J_PASSWORD'] = "sara-graph-secret"
os.environ['OPENAI_BASE_URL'] = "http://100.104.68.115:8080/v1"
os.environ['OPENAI_MODEL'] = "GLM-4.5-Air-Q5_K_M"
os.environ['OPENAI_API_KEY'] = "dummy"
os.environ['EMBEDDING_BASE_URL'] = "http://100.104.68.115:11434"
os.environ['EMBEDDING_MODEL'] = "bge-m3"
os.environ['EMBEDDING_DIM'] = "1024"
os.environ['ASSISTANT_NAME'] = "Sara"

async def main():
    """Main test function"""
    try:
        logger.info("🧪 Starting manual dream service test...")

        # Import after environment is set
        from app.services.nightly_dream_service import NightlyDreamService
        from app.services.neo4j_service import neo4j_service

        # Initialize Neo4j connection
        logger.info("📊 Connecting to Neo4j...")
        await neo4j_service.connect()

        # Initialize enhanced Neo4j schema
        from app.services.enhanced_neo4j_schema import enhanced_neo4j
        logger.info("🔧 Initializing enhanced Neo4j schema...")
        enhanced_neo4j.initialize_enhanced_schema()

        # Initialize dream service
        logger.info("🌙 Initializing NightlyDreamService...")
        dream_service = NightlyDreamService()

        # Force the dream cycle to run
        logger.info("🚀 Triggering dream cycle manually...")
        dream_service.is_dreaming = False  # Reset flag in case it was stuck
        await dream_service._run_nightly_dream_cycle()

        logger.info("✅ Dream cycle completed successfully!")
        logger.info("💡 Now query Neo4j to verify data was stored:")
        logger.info("   MATCH (n) RETURN labels(n), count(n)")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Close connections
        try:
            neo4j_service.close()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(main())
