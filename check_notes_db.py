#!/usr/bin/env python3
"""
Check where notes are stored - PostgreSQL vs Neo4j
"""
import sys
import os
sys.path.insert(0, '/home/david/jarvis/backend')

# Set up environment
os.environ["DATABASE_URL"] = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
os.environ["NEO4J_URI"] = "bolt://10.185.1.180:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "sara-graph-secret"

from app.main_simple import SessionLocal, Note
from sqlalchemy import text
import asyncio

async def check_notes_storage():
    print("🔍 Checking Notes Storage Locations")
    print("=" * 50)
    
    # Check PostgreSQL first
    print("\n1. Checking PostgreSQL...")
    db = SessionLocal()
    try:
        # Count all notes
        count = db.query(Note).count()
        print(f"   PostgreSQL notes count: {count}")
        
        if count > 0:
            print("   Recent notes in PostgreSQL:")
            notes = db.query(Note).order_by(Note.created_at.desc()).limit(5).all()
            for note in notes:
                title = note.title or "Untitled"
                content_preview = (note.content or "")[:50]
                user_id = note.user_id
                print(f"   - '{title}' (User: {user_id}) - {content_preview}...")
        
        # Check specific user
        print("\n   Checking for user david@avery.cloud...")
        result = db.execute(text("SELECT id, email FROM users WHERE email = 'david@avery.cloud'"))
        user_row = result.fetchone()
        if user_row:
            user_id = user_row[0]
            print(f"   Found user: {user_row[1]} (ID: {user_id})")
            
            user_notes = db.query(Note).filter(Note.user_id == user_id).all()
            print(f"   Notes for this user: {len(user_notes)}")
            for note in user_notes:
                print(f"   - '{note.title}' - {(note.content or '')[:50]}...")
        else:
            print("   User not found!")
            
    except Exception as e:
        print(f"   ❌ PostgreSQL error: {e}")
    finally:
        db.close()
    
    # Check Neo4j
    print("\n2. Checking Neo4j...")
    try:
        from app.services.neo4j_service import neo4j_service
        
        if neo4j_service.driver:
            print("   Neo4j connection available")
            
            # Try to count notes in Neo4j
            with neo4j_service.driver.session() as session:
                # Count all Note nodes
                result = session.run("MATCH (n:Note) RETURN count(n) as count")
                count_record = result.single()
                note_count = count_record["count"] if count_record else 0
                print(f"   Neo4j notes count: {note_count}")
                
                if note_count > 0:
                    print("   Recent notes in Neo4j:")
                    result = session.run("""
                        MATCH (n:Note) 
                        RETURN n.title as title, n.content as content, n.user_id as user_id, n.created_at as created_at
                        ORDER BY n.created_at DESC 
                        LIMIT 5
                    """)
                    
                    for record in result:
                        title = record["title"] or "Untitled"
                        content = (record["content"] or "")[:50]
                        user_id = record["user_id"]
                        print(f"   - '{title}' (User: {user_id}) - {content}...")
                
                # Check for user notes
                print(f"\n   Checking Neo4j for user notes...")
                result = session.run("""
                    MATCH (u:User)-[:CREATED]->(n:Note)
                    WHERE u.email = $email
                    RETURN n.title as title, n.content as content, n.created_at as created_at
                    ORDER BY n.created_at DESC
                """, email="david@avery.cloud")
                
                user_notes = list(result)
                print(f"   User notes in Neo4j: {len(user_notes)}")
                for record in user_notes:
                    title = record["title"] or "Untitled"
                    content = (record["content"] or "")[:50]
                    print(f"   - '{title}' - {content}...")
                    
        else:
            print("   ❌ Neo4j connection not available")
            
    except Exception as e:
        print(f"   ❌ Neo4j error: {e}")
        import traceback
        traceback.print_exc()
    
    # Check which notes endpoint is being used
    print("\n3. Checking notes API behavior...")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to get notes via API
            response = await client.get("http://10.185.1.180:8000/notes")
            if response.status_code == 200:
                notes = response.json()
                print(f"   API returned {len(notes)} notes")
                for note in notes[:3]:
                    title = note.get("title", "Untitled")
                    content = (note.get("content", "") or "")[:50]
                    print(f"   - '{title}' - {content}...")
            else:
                print(f"   ❌ API request failed: {response.status_code}")
                print(f"   Response: {response.text}")
                
    except Exception as e:
        print(f"   ❌ API check error: {e}")

if __name__ == "__main__":
    asyncio.run(check_notes_storage())