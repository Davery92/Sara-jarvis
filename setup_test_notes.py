#!/usr/bin/env python3
"""
Create some test notes and then test the search functionality
"""
import asyncio
import httpx
import json
import sys
import os

async def create_test_notes_and_search():
    """Create test notes and test search functionality"""
    
    print("🔍 Setting Up Test Notes and Testing Search")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # First, login to get session
            print("1. Logging in...")
            base_url = os.getenv("BASE_URL", "http://localhost:8000")
            login_response = await client.post(
                f"{base_url}/auth/login",
                json={"email": "david@avery.cloud", "password": "your_password"}  # Use actual password
            )
            
            if login_response.status_code != 200:
                print(f"❌ Login failed: {login_response.status_code}")
                print("Trying without password...")
                # Try to get current user instead
                me_response = await client.get(f"{base_url}/auth/me")
                if me_response.status_code != 200:
                    print("❌ Authentication failed completely")
                    return False
            
            print("✅ Authentication successful")
            
            # Create test notes via the API
            test_notes = [
                {
                    "title": "Web Search Feature",
                    "content": "This is a note about implementing a web search feature in the application. It should include integration with external search APIs and result caching for performance."
                },
                {
                    "title": "Database Migration",
                    "content": "Notes about migrating from SQLite to PostgreSQL. Need to handle data types, indexing, and connection pooling properly."
                },
                {
                    "title": "AI Tool Integration", 
                    "content": "Documentation about integrating AI tools like search_notes, create_reminder, and memory search. Tools should have proper error handling and fallback mechanisms."
                }
            ]
            
            print("2. Creating test notes...")
            created_notes = []
            
            for i, note_data in enumerate(test_notes, 1):
                print(f"   Creating note {i}: '{note_data['title']}'")
                
                response = await client.post(
                    f"{base_url}/notes",
                    json=note_data
                )
                
                if response.status_code == 200:
                    note = response.json()
                    created_notes.append(note)
                    print(f"   ✅ Created note: {note.get('title')}")
                else:
                    print(f"   ❌ Failed to create note: {response.status_code}")
                    print(f"   Response: {response.text}")
            
            if not created_notes:
                print("❌ No notes were created successfully")
                return False
            
            print(f"✅ Created {len(created_notes)} test notes")
            
            # Now test the search functionality
            search_queries = [
                "web search feature",
                "database migration",
                "AI tools"
            ]
            
            for query in search_queries:
                print(f"\n3. Testing search for: '{query}'")
                
                chat_query = f"Search for notes about '{query}' and summarize what you find"
                
                response = await client.post(
                    f"{base_url}/chat/stream",
                    json={
                        "messages": [
                            {"role": "user", "content": chat_query}
                        ]
                    }
                )
                
                if response.status_code != 200:
                    print(f"❌ Chat request failed: {response.status_code}")
                    continue
                
                print("   Processing streaming response...")
                
                tool_rounds = 0
                tool_calls = []
                final_content = ""
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            event_data = json.loads(line[6:])
                            event_type = event_data.get("type")
                            
                            if event_type == "tool_calls_start":
                                tool_rounds += 1
                                tools = event_data.get("data", {}).get("tools", [])
                                print(f"   🔧 Round {tool_rounds}: {tools}")
                                tool_calls.extend(tools)
                                
                            elif event_type == "tool_executing":
                                tool = event_data.get("data", {}).get("tool")
                                print(f"      Executing: {tool}")
                                
                            elif event_type == "final_response":
                                final_content = event_data.get("data", {}).get("content", "")
                                
                            elif event_type == "response_ready":
                                break
                                
                        except json.JSONDecodeError:
                            continue
                
                print(f"   Tool rounds: {tool_rounds}")
                print(f"   Tools used: {set(tool_calls)}")
                print(f"   Response length: {len(final_content)}")
                
                if tool_rounds > 5:
                    print(f"   ⚠️  Possible infinite loop: {tool_rounds} rounds")
                elif tool_rounds == 0:
                    print("   ⚠️  No tools were used")
                else:
                    print(f"   ✅ Reasonable tool usage: {tool_rounds} rounds")
                
                if final_content and query.lower() in final_content.lower():
                    print(f"   ✅ Response mentions '{query}'")
                elif final_content:
                    print(f"   ⚠️  Response doesn't mention '{query}'")
                    print(f"   Content preview: {final_content[:200]}...")
                else:
                    print("   ❌ No response content")
                
                print("   " + "-" * 40)
            
            return True
            
        except Exception as e:
            print(f"❌ Error during test: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    print("🚀 Starting Notes Setup and Search Test")
    
    # Run the test
    success = asyncio.run(create_test_notes_and_search())
    
    if success:
        print("\n🎉 Test completed successfully!")
    else:
        print("\n❌ Test failed!")
        sys.exit(1)
