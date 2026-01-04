#!/usr/bin/env python3
"""
Generate tool call training data by prompting the LLM with scenarios
and capturing the exact tool call format it produces.
"""
import asyncio
import json
import httpx
import os
import sys

sys.path.insert(0, '/home/david/jarvis/backend')

from app.tools.registry import tool_registry

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:120b")

# Example prompts for each tool
TOOL_PROMPTS = {
    # Notes
    "notes_create": "Create a note about my meeting with John where we discussed the Q1 budget",
    "notes_search": "Find my notes about Python programming",
    "notes_edit": "Update note abc123 to add information about the deadline being extended",
    "notes_delete": "Delete note abc123",
    "notes_list": "Show me all my notes",

    # Memory
    "memory_search": "What did I say about my fitness goals last week?",

    # Reminders
    "reminders_create": "Remind me to call mom tomorrow at 3pm",
    "reminders_list": "What reminders do I have?",
    "reminders_cancel": "Cancel my reminder about calling mom",

    # Timers
    "timers_start": "Start a 25 minute focus timer",
    "timers_status": "How much time is left on my timer?",
    "timers_cancel": "Stop the timer",

    # Calendar
    "calendar_list": "What's on my calendar this week?",
    "calendar_create": "Add a meeting with Sarah on Friday at 2pm",

    # Knowledge Graph
    "knowledge_graph_search": "Search my knowledge graph for concepts related to machine learning",
    "find_connections": "Find connections between my work projects and personal goals",
    "discover_knowledge_clusters": "What knowledge clusters exist in my notes?",
    "analyze_knowledge_gaps": "What knowledge gaps do I have in my understanding of Python?",

    # Web Search
    "web_search": "Search the web for latest news about AI",
    "open_page": "Open the Wikipedia page about Python programming",

    # Fitness
    "fitness_note_create": "Log that I did 30 pushups today and felt strong",
    "food_log_create": "I had a chicken salad for lunch, about 400 calories",
    "food_search_and_log": "Log that I ate 2 eggs and toast for breakfast",
    "workout_log_create": "Log my workout: bench press 3x10 at 135lbs, squats 3x8 at 185lbs",
    "recovery_log_create": "Log my recovery: slept 7 hours, feeling 8/10, no soreness",
    "fitness_summary": "How am I doing with my fitness this week?",

    # Chess
    "chess_start_game": "Let's play chess, I want to be white",
    "chess_move": "Move my pawn from e2 to e4",
    "chess_get_board": "Show me the current board position",
    "chess_stats": "What are my chess stats?",
}


async def get_tool_call_example(tool_name: str, user_prompt: str):
    """Call the LLM with a prompt and capture the tool call response"""

    # Get the tool schema
    tool = tool_registry.get_tool(tool_name)
    if not tool:
        print(f"Tool {tool_name} not found")
        return None

    tool_schema = tool.to_openai_schema()

    system_prompt = """You are Sara, a helpful AI assistant. You have access to tools to help the user.
When the user asks you to do something, use the appropriate tool.
Always use tools when they're available and relevant to the request."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json={
                    "model": OPENAI_MODEL,
                    "messages": messages,
                    "tools": [tool_schema],
                    "tool_choice": {"type": "function", "function": {"name": tool_name}},
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            )
            response.raise_for_status()
            result = response.json()

            return {
                "tool_name": tool_name,
                "user_prompt": user_prompt,
                "tool_schema": tool_schema,
                "llm_response": result,
                "tool_calls": result.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
            }
    except Exception as e:
        print(f"Error calling LLM for {tool_name}: {e}")
        return None


async def main():
    print("=" * 80)
    print("TOOL CALL TRAINING DATA GENERATOR")
    print(f"Model: {OPENAI_MODEL}")
    print(f"Endpoint: {OPENAI_BASE_URL}")
    print("=" * 80)
    print()

    examples = []

    for tool_name, prompt in TOOL_PROMPTS.items():
        print(f"\n{'='*60}")
        print(f"TOOL: {tool_name}")
        print(f"PROMPT: {prompt}")
        print("-" * 60)

        result = await get_tool_call_example(tool_name, prompt)

        if result and result.get("tool_calls"):
            tool_call = result["tool_calls"][0]
            print(f"TOOL CALL ID: {tool_call.get('id', 'N/A')}")
            print(f"FUNCTION NAME: {tool_call.get('function', {}).get('name', 'N/A')}")
            print(f"ARGUMENTS: {tool_call.get('function', {}).get('arguments', '{}')}")

            # Parse arguments for pretty print
            try:
                args = json.loads(tool_call.get('function', {}).get('arguments', '{}'))
                print(f"PARSED ARGS: {json.dumps(args, indent=2)}")
            except:
                pass

            examples.append({
                "tool_name": tool_name,
                "user_prompt": prompt,
                "tool_call": tool_call,
                "full_response": result["llm_response"]
            })
        else:
            print("NO TOOL CALL RETURNED")
            # Check if there's content instead
            if result:
                content = result.get("llm_response", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    print(f"CONTENT INSTEAD: {content[:200]}...")

    # Save all examples to file
    output_file = "/home/david/jarvis/backend/scripts/tool_call_examples.json"
    with open(output_file, "w") as f:
        json.dump(examples, f, indent=2)

    print(f"\n\n{'='*80}")
    print(f"Saved {len(examples)} examples to {output_file}")
    print("=" * 80)

    # Print summary format for training
    print("\n\nTRAINING DATA FORMAT:")
    print("=" * 80)
    for ex in examples[:3]:  # Show first 3 as example
        print(f"""
### Example: {ex['tool_name']}

**User:** {ex['user_prompt']}

**Assistant Tool Call:**
```json
{json.dumps(ex['tool_call'], indent=2)}
```
""")


if __name__ == "__main__":
    asyncio.run(main())
