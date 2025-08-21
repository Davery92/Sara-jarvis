#!/usr/bin/env python3
"""
Test script to verify the notes search functionality works correctly
"""
import asyncio
import httpx
import json
import sys
import os

# Add the backend to the path
sys.path.insert(0, '/home/david/jarvis/backend')

from app.main_simple import SessionLocal, Note
from sqlalchemy import text

async def test_notes_search():
    """Test the notes search API endpoint"""
    
    print("🔍 Testing Notes Search Functionality")
    print("=" * 50)
    
    # First, let's see what notes exist
    print("\n1. Checking existing notes in database...")
    db = SessionLocal()
    try:
        # Get all notes
        notes = db.query(Note).order_by(Note.created_at.desc()).limit(10).all()
        
        if not notes:
            print("❌ No notes found in database")
            return False
        
        print(f"✅ Found {len(notes)} notes:")
        for i, note in enumerate(notes, 1):
            title = note.title or "Untitled"
            content_preview = (note.content or "")[:80]
            print(f"   {i}. '{title}' - {content_preview}...")
        
        # Pick the first note to search for
        test_note = notes[0]
        search_term = (test_note.title or test_note.content[:20]).split()[0] if test_note.title or test_note.content else "test"
        
    finally:
        db.close()
    
    print(f"\n2. Testing search for term: '{search_term}'")
    
    # Test the chat/stream endpoint with a search query
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # First, login to get session
            login_response = await client.post(
                "http://10.185.1.180:8000/auth/login",
                json={"email": "david@avery.cloud", "password": "your_password_here"}
            )
            
            if login_response.status_code != 200:
                print(f"❌ Login failed: {login_response.status_code}")
                return False
            
            print("✅ Login successful")
            
            # Now test the chat stream endpoint
            search_query = f"Search for notes about '{search_term}' and summarize what you find"
            
            print(f"\n3. Sending chat request: '{search_query}'")
            
            response = await client.post(
                "http://10.185.1.180:8000/chat/stream",
                json={
                    "messages": [
                        {"role": "user", "content": search_query}
                    ]
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                print(f"❌ Chat request failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
            
            print("✅ Chat stream started, processing events...")
            
            # Process the streaming response
            events = []
            tool_calls = []
            final_content = ""
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        event_data = json.loads(line[6:])
                        events.append(event_data)
                        
                        event_type = event_data.get("type")
                        
                        if event_type == "tool_calls_start":
                            tools = event_data.get("data", {}).get("tools", [])
                            round_num = event_data.get("data", {}).get("round", 1)
                            print(f"🔧 Round {round_num}: Starting tool calls: {tools}")
                            
                        elif event_type == "tool_executing":
                            tool = event_data.get("data", {}).get("tool")
                            print(f"   Executing: {tool}")
                            
                        elif event_type == "tool_completed":
                            tool = event_data.get("data", {}).get("tool")
                            print(f"   ✅ Completed: {tool}")
                            
                        elif event_type == "text_chunk":
                            final_content = event_data.get("data", {}).get("full_content", "")
                            
                        elif event_type == "final_response":
                            final_content = event_data.get("data", {}).get("content", "")
                            
                        elif event_type == "response_ready":
                            rounds = event_data.get("data", {}).get("rounds", 1)
                            print(f"🎉 Response ready after {rounds} rounds")
                            break
                            
                    except json.JSONDecodeError:
                        continue
            
            print(f"\n4. Final response length: {len(final_content)} characters")
            if final_content:
                print("✅ Got response content:")
                print("-" * 40)
                print(final_content[:500] + ("..." if len(final_content) > 500 else ""))
                print("-" * 40)
                
                # Check if the response mentions the search term
                if search_term.lower() in final_content.lower():
                    print(f"✅ Response contains search term '{search_term}'")
                else:
                    print(f"⚠️  Response doesn't mention search term '{search_term}'")
                    
                # Check if tool was used
                tool_events = [e for e in events if e.get("type") in ["tool_calls_start", "tool_executing", "tool_completed"]]
                if tool_events:
                    print(f"✅ Tool usage detected: {len(tool_events)} tool events")
                    
                    # Check for loops
                    tool_rounds = len([e for e in events if e.get("type") == "tool_calls_start"])
                    if tool_rounds > 5:
                        print(f"⚠️  Possible tool loop: {tool_rounds} rounds")
                    else:
                        print(f"✅ Reasonable tool usage: {tool_rounds} rounds")
                else:
                    print("❌ No tool usage detected")
                    
                return True
            else:
                print("❌ No response content received")
                return False
                
        except Exception as e:
            print(f"❌ Error during chat test: {e}")
            return False

if __name__ == "__main__":
    print("🚀 Starting Notes Search Test")
    
    # Set up environment
    os.environ["DATABASE_URL"] = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
    
    # Run the test
    success = asyncio.run(test_notes_search())
    
    if success:
        print("\n🎉 Test completed successfully!")
    else:
        print("\n❌ Test failed!")
        sys.exit(1)