#!/usr/bin/env python3
"""
Test Neo4j connection directly
"""
import sys
import os
sys.path.insert(0, '/home/david/jarvis/backend')

# Set environment variables
os.environ["NEO4J_URI"] = "bolt://10.185.1.180:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "sara-graph-secret"

def test_neo4j_direct():
    print("🔍 Testing Neo4j Connection")
    print("=" * 40)
    
    try:
        from neo4j import GraphDatabase
        
        uri = "bolt://10.185.1.180:7687"
        user = "neo4j"
        password = "sara-graph-secret"
        
        print(f"Connecting to: {uri}")
        print(f"User: {user}")
        
        driver = GraphDatabase.driver(uri, auth=(user, password))
        
        # Test connection
        with driver.session() as session:
            result = session.run("RETURN 'Hello Neo4j!' as message")
            record = result.single()
            print(f"✅ Connection successful: {record['message']}")
            
            # Check what's in the database
            result = session.run("MATCH (n) RETURN labels(n) as labels, count(n) as count")
            print("\n📊 Current database contents:")
            for record in result:
                labels = record["labels"]
                count = record["count"]
                print(f"   {labels}: {count} nodes")
                
            # Check for any Note nodes
            result = session.run("MATCH (n:Note) RETURN count(n) as note_count")
            note_count = result.single()["note_count"]
            print(f"\n📝 Note nodes: {note_count}")
            
            # Check for User nodes
            result = session.run("MATCH (n:User) RETURN count(n) as user_count")
            user_count = result.single()["user_count"]
            print(f"👤 User nodes: {user_count}")
            
        driver.close()
        return True
        
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_app_neo4j_service():
    print("\n🔍 Testing App Neo4j Service")
    print("=" * 40)
    
    try:
        from app.services.neo4j_service import neo4j_service
        
        if neo4j_service.driver:
            print("✅ Neo4j service has driver")
            
            # Test basic operation
            with neo4j_service.driver.session() as session:
                result = session.run("RETURN 'App service works!' as message")
                record = result.single()
                print(f"✅ App service test: {record['message']}")
                
        else:
            print("❌ Neo4j service driver is None")
            
        return neo4j_service.driver is not None
        
    except Exception as e:
        print(f"❌ App Neo4j service failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Neo4j Connection Diagnostics")
    
    direct_ok = test_neo4j_direct()
    app_ok = test_app_neo4j_service()
    
    if direct_ok and app_ok:
        print("\n🎉 Neo4j is working properly!")
    elif direct_ok:
        print("\n⚠️  Neo4j works directly but app service has issues")
    else:
        print("\n❌ Neo4j connection problems")