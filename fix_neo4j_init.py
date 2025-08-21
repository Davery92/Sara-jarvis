#!/usr/bin/env python3
"""
Fix Neo4j initialization issue
"""
import sys
import os
import asyncio
sys.path.insert(0, '/home/david/jarvis/backend')

# Set environment variables
os.environ["NEO4J_URI"] = "bolt://10.185.1.180:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "sara-graph-secret"

async def initialize_neo4j_service():
    print("🔧 Initializing Neo4j Service")
    print("=" * 40)
    
    try:
        from app.services.neo4j_service import neo4j_service
        
        print("📋 Current state:")
        print(f"   Driver: {neo4j_service.driver}")
        print(f"   URI: {neo4j_service.uri}")
        print(f"   User: {neo4j_service.user}")
        
        print("\n🔌 Attempting to connect...")
        await neo4j_service.connect()
        
        print("✅ Neo4j service connected!")
        print(f"   Driver: {neo4j_service.driver}")
        
        # Test the connection
        print("\n🧪 Testing connection...")
        with neo4j_service.driver.session() as session:
            result = session.run("RETURN 'Neo4j service works!' as message")
            record = result.single()
            print(f"   {record['message']}")
            
            # Check node counts
            result = session.run("MATCH (n) RETURN labels(n) as labels, count(n) as count")
            print("\n📊 Database contents:")
            for record in result:
                labels = record["labels"]
                count = record["count"]
                print(f"   {labels}: {count}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to initialize Neo4j service: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_search_with_neo4j():
    print("\n🔍 Testing Search with Neo4j")
    print("=" * 40)
    
    try:
        from app.services.neo4j_service import neo4j_service
        
        if not neo4j_service.driver:
            print("❌ Neo4j driver not available")
            return False
            
        # Test the search function that was failing
        search_results = await neo4j_service.search_knowledge_graph(
            user_id="64f37c56-85cb-4590-8de9-adfc17d343ed",  # The user ID from our notes
            query="web search feature",
            content_types=["Note"],
            limit=10
        )
        
        print(f"✅ Search successful! Found {len(search_results)} results")
        for result in search_results[:3]:
            title = result.get('title', 'No title')
            content = (result.get('content', '') or '')[:100]
            print(f"   - {title}: {content}...")
            
        return True
        
    except Exception as e:
        print(f"❌ Search test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    async def main():
        init_ok = await initialize_neo4j_service()
        
        if init_ok:
            search_ok = await test_search_with_neo4j()
            
            if search_ok:
                print("\n🎉 Neo4j is fully working!")
            else:
                print("\n⚠️  Neo4j connected but search has issues")
        else:
            print("\n❌ Neo4j initialization failed")
    
    asyncio.run(main())