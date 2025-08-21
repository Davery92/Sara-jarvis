#!/usr/bin/env python3
"""
Test the new content intelligence system
"""
import sys
import os
sys.path.insert(0, '/home/david/jarvis/backend')

from app.services.content_intelligence import content_intelligence, ContentType

def test_content_detection():
    print("🧪 Testing Content Intelligence System")
    print("=" * 50)
    
    # Test with beef stew recipe
    beef_stew_content = """## Ingredients

- 2 ½ lb chuck roast, cut into 1‑inch cubes
- 5 lb red potatoes – scrubbed well; you can leave the skins on
- 1 large onion, diced
- 3 cloves garlic, minced
- 3 carrots, sliced into ½‑inch rounds
- 1 cup frozen mixed veggies
- 3 Tbsp tomato paste
- 2 Tbsp Worcestershire sauce
- 4 cups beef broth (or stock)

## Directions

1. **Prep the pot** – Set the Ninja Foodi to "Sauté" on high and add the olive oil.
2. **Brown the beef** – Working in batches, add the beef cubes, season lightly with salt & pepper.
3. **Sauté aromatics** – In the same pot, add the diced onion and cook until translucent.
4. **Build the stew** – Return the browned beef to the pot. Add the carrots, frozen mixed veggies.
5. **Pressure‑cook** – Close the lid, set the valve to "Seal", and select "Pressure Cook" on High for 30 minutes."""
    
    print("🥩 Testing Beef Stew Recipe:")
    content_type, chunks = content_intelligence.process_content(
        beef_stew_content, 
        "Simple Beef Stew (Ninja Foodi)"
    )
    print(f"   Detected type: {content_type.value}")
    print(f"   Chunks created: {len(chunks)}")
    for i, chunk in enumerate(chunks[:3]):  # Show first 3 chunks
        print(f"   Chunk {i+1}: {chunk.chunk_type.value} - {chunk.content[:60]}...")
    print()
    
    # Test with technical document
    tech_content = """**Plan Breakdown: Two‑Stage Retrieval System**

1. **Requirements & Scope**
   - Enable LLM‑driven web search via local SearXNG.
   - Use a lightweight LLM for query generation & summarization.
   - Feed summaries to a heavy LLM for final answer.
   - Preserve user context & memory.

2. **Architecture Overview**
   - **Front‑end**: Chat UI → API.
   - **Stage 1 (Lightweight)**:
     * Tiny LLM (e.g., Llama‑3‑8B) → Search prompt.
     * SearXNG search → Top‑N URLs.
   - **Stage 2 (Heavyweight)**:
     * Large LLM (e.g., GPT‑4‑Turbo) receives Q + summaries + memory.

```python
def search_pipeline(query):
    # Stage 1: Fast processing
    search_terms = tiny_llm.generate_search(query)
    results = searxng.search(search_terms)
    summaries = tiny_llm.summarize(results)
    
    # Stage 2: Heavy processing
    answer = large_llm.generate_answer(query, summaries)
    return answer
```"""
    
    print("🔧 Testing Technical Document:")
    content_type, chunks = content_intelligence.process_content(
        tech_content, 
        "Web Search Feature"
    )
    print(f"   Detected type: {content_type.value}")
    print(f"   Chunks created: {len(chunks)}")
    for i, chunk in enumerate(chunks[:3]):  # Show first 3 chunks
        print(f"   Chunk {i+1}: {chunk.chunk_type.value} - {chunk.content[:60]}...")
    print()
    
    # Test with workout plan
    workout_content = """User details:
- Height: 6 ft
- Weight: 230 lbs
- Available kettlebells: 10 lb, two 20 lb, 40 lb, 60 lb

Suggested starter weight:
- Primary kettlebell: 20 lb (single) for swings, goblet squats, presses.
- Use 10 lb for learning swing mechanics if needed.
- Progress to 40 lb for swings once comfortable (after 2–3 weeks).

Week‑by‑week routine:
1. Week 1: 3 sets of 10 swings, 5 goblet squats
2. Week 2: 4 sets of 12 swings, 8 goblet squats  
3. Week 3: 5 sets of 15 swings, 10 goblet squats

Next steps:
1. Choose workout days/times.
2. Set reminders if desired."""
    
    print("💪 Testing Workout Plan:")
    content_type, chunks = content_intelligence.process_content(
        workout_content, 
        "Kettlebell Starter Plan for David"
    )
    print(f"   Detected type: {content_type.value}")
    print(f"   Chunks created: {len(chunks)}")
    for i, chunk in enumerate(chunks[:3]):  # Show first 3 chunks
        print(f"   Chunk {i+1}: {chunk.chunk_type.value} - {chunk.content[:60]}...")
    print()
    
    print("✅ Content Intelligence Testing Complete!")

if __name__ == "__main__":
    test_content_detection()