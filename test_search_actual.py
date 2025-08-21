#!/usr/bin/env python3
"""
Test search functionality with actual notes
"""
import asyncio
import httpx
import json

async def test_search_with_actual_notes():
    print("🔍 Testing Search with Your Actual Notes")
    print("=" * 50)
    
    # Test queries based on the notes we found
    test_queries = [
        "web search feature",
        "kettlebell workout", 
        "beef stew recipe"
    ]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        for query in test_queries:
            print(f"\n🔍 Testing search: '{query}'")
            print("-" * 40)
            
            try:
                response = await client.post(
                    "http://10.185.1.180:8000/chat/stream",
                    json={
                        "messages": [
                            {"role": "user", "content": f"Search for notes about '{query}' and tell me what you find"}
                        ]
                    },
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code != 200:
                    print(f"❌ Request failed: {response.status_code}")
                    print(f"Response: {response.text}")
                    continue
                
                print("✅ Request successful, processing stream...")
                
                tool_rounds = 0
                tools_used = []
                final_content = ""
                has_errors = False
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            event_data = json.loads(line[6:])
                            event_type = event_data.get("type")
                            
                            if event_type == "tool_calls_start":
                                tool_rounds += 1
                                tools = event_data.get("data", {}).get("tools", [])
                                tools_used.extend(tools)
                                print(f"   🔧 Round {tool_rounds}: Using tools {tools}")
                                
                            elif event_type == "tool_executing":
                                tool = event_data.get("data", {}).get("tool")
                                print(f"      ⚡ Executing: {tool}")
                                
                            elif event_type == "tool_completed":
                                tool = event_data.get("data", {}).get("tool")
                                print(f"      ✅ Completed: {tool}")
                                
                            elif event_type == "final_response":
                                final_content = event_data.get("data", {}).get("content", "")
                                
                            elif event_type == "response_ready":
                                rounds = event_data.get("data", {}).get("rounds", tool_rounds)
                                print(f"   🎉 Response ready after {rounds} rounds")
                                break
                                
                            elif event_type == "error":
                                print(f"   ❌ Error: {event_data.get('message', 'Unknown error')}")
                                has_errors = True
                                
                        except json.JSONDecodeError as e:
                            continue
                
                # Analyze results
                print(f"\n📊 Results for '{query}':")
                print(f"   Tool rounds: {tool_rounds}")
                print(f"   Tools used: {set(tools_used)}")
                print(f"   Response length: {len(final_content)} chars")
                
                if tool_rounds > 10:
                    print(f"   ⚠️  INFINITE LOOP DETECTED: {tool_rounds} rounds!")
                elif tool_rounds == 0:
                    print("   ⚠️  No tools used - might be answering directly")
                elif tool_rounds > 5:
                    print(f"   ⚠️  High tool usage: {tool_rounds} rounds")
                else:
                    print(f"   ✅ Normal tool usage: {tool_rounds} rounds")
                
                if has_errors:
                    print("   ❌ Errors detected during processing")
                
                if final_content:
                    # Check if response is relevant
                    query_words = query.lower().split()
                    content_lower = final_content.lower()
                    
                    matches = sum(1 for word in query_words if word in content_lower)
                    relevance = matches / len(query_words) if query_words else 0
                    
                    print(f"   Relevance: {relevance:.1%} ({matches}/{len(query_words)} words matched)")
                    
                    if relevance > 0.5:
                        print("   ✅ Response seems relevant")
                    else:
                        print("   ⚠️  Response may not be relevant")
                    
                    print(f"\n📝 Response preview:")
                    print("   " + final_content[:200].replace('\n', '\n   ') + ("..." if len(final_content) > 200 else ""))
                else:
                    print("   ❌ No response content received")
                
            except Exception as e:
                print(f"❌ Error testing '{query}': {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_search_with_actual_notes())