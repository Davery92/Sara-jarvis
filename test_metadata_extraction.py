#!/usr/bin/env python3
"""
Test the metadata extraction system
"""
import sys
import os
sys.path.insert(0, '/home/david/jarvis/backend')

from app.services.metadata_extractor import metadata_extractor
from app.services.content_intelligence import ContentType

def test_metadata_extraction():
    print("🔍 Testing Metadata Extraction System")
    print("=" * 50)
    
    # Test with beef stew recipe
    beef_stew_content = """## Ingredients

- 2 ½ lb chuck roast, cut into 1‑inch cubes
- 5 lb red potatoes – scrubbed well
- 1 large onion, diced
- 3 cloves garlic, minced
- 3 carrots, sliced into ½‑inch rounds
- 1 cup frozen mixed veggies (peas, corn, green beans)
- 3 Tbsp tomato paste
- 2 Tbsp Worcestershire sauce
- 4 cups beef broth (or stock)
- 1 tsp dried thyme
- 1 tsp dried rosemary

## Directions

1. **Prep the pot** – Set the Ninja Foodi to "Sauté" on high and add the olive oil.
2. **Brown the beef** – Working in batches, add the beef cubes, season lightly with salt & pepper.
3. **Pressure‑cook** – Close the lid, set the valve to "Seal", and select "Pressure Cook" on High for 30 minutes."""
    
    print("🥩 Testing Beef Stew Recipe Metadata:")
    metadata = metadata_extractor.extract_metadata(
        beef_stew_content, 
        ContentType.RECIPE,
        "Simple Beef Stew (Ninja Foodi)"
    )
    
    print(f"   Entities: {len(metadata.entities)}")
    for entity in metadata.entities[:5]:
        print(f"     - {entity.name} ({entity.entity_type})")
    
    print(f"   Topics: {len(metadata.topics)}")
    for topic in metadata.topics:
        print(f"     - {topic.name} (confidence: {topic.confidence:.2f})")
    
    print(f"   Tags: {metadata.tags}")
    print(f"   Intent: {metadata.intent}")
    print(f"   Urgency: {metadata.urgency_score:.2f}")
    print(f"   Importance: {metadata.importance_score:.2f}")
    print()
    
    # Test with technical document
    tech_content = """**Plan Breakdown: Two‑Stage Retrieval System**

1. **Requirements & Scope**
   - Enable LLM‑driven web search via local SearXNG.
   - Use a lightweight LLM for query generation & summarization.
   - Feed summaries to a heavy LLM for final answer.

2. **Implementation Tasks**
   - TODO: Set up SearXNG locally using Docker
   - Action: Deploy Tiny LLM (LLama‑3‑8B) via vLLM
   - Follow-up: Build async fetcher + readability extractor

```python
def search_pipeline(query):
    # Stage 1: Fast processing
    search_terms = tiny_llm.generate_search(query)
    results = searxng.search(search_terms)
    return results
```

**Timeline (8 weeks)**
- Week 1–2: Environment, SearXNG, API wrapper.
- Week 3–4: Tiny LLM deployment & summarizer."""
    
    print("🔧 Testing Technical Document Metadata:")
    metadata = metadata_extractor.extract_metadata(
        tech_content,
        ContentType.TECHNICAL_DOC,
        "Web Search Feature Implementation"
    )
    
    print(f"   Entities: {len(metadata.entities)}")
    for entity in metadata.entities[:5]:
        print(f"     - {entity.name} ({entity.entity_type})")
    
    print(f"   Topics: {len(metadata.topics)}")
    for topic in metadata.topics:
        print(f"     - {topic.name} (confidence: {topic.confidence:.2f})")
    
    print(f"   Tags: {metadata.tags}")
    print(f"   Intent: {metadata.intent}")
    print(f"   Actionable Items: {len(metadata.actionable_items)}")
    for item in metadata.actionable_items[:3]:
        print(f"     - {item}")
    print(f"   Urgency: {metadata.urgency_score:.2f}")
    print(f"   Importance: {metadata.importance_score:.2f}")
    print(f"   Durations found: {metadata.temporal_info.durations}")
    print()
    
    # Test with workout plan
    workout_content = """User details:
- Height: 6 ft
- Weight: 230 lbs
- Available kettlebells: 10 lb, two 20 lb, 40 lb, 60 lb

Suggested starter weight:
- Primary kettlebell: 20 lb for swings, goblet squats, presses.
- Progress to 40 lb for swings once comfortable (after 2–3 weeks).

Week‑by‑week routine:
1. Week 1: 3 sets of 10 swings, 5 goblet squats
2. Week 2: 4 sets of 12 swings, 8 goblet squats  
3. Week 3: 5 sets of 15 swings, 10 goblet squats

Next steps:
1. Choose workout days/times.
2. Set reminders for consistency."""
    
    print("💪 Testing Workout Plan Metadata:")
    metadata = metadata_extractor.extract_metadata(
        workout_content,
        ContentType.WORKOUT_PLAN,
        "Kettlebell Starter Plan for David"
    )
    
    print(f"   Entities: {len(metadata.entities)}")
    for entity in metadata.entities[:5]:
        print(f"     - {entity.name} ({entity.entity_type})")
    
    print(f"   Topics: {len(metadata.topics)}")
    for topic in metadata.topics:
        print(f"     - {topic.name} (confidence: {topic.confidence:.2f})")
    
    print(f"   Tags: {metadata.tags}")
    print(f"   Intent: {metadata.intent}")
    print(f"   Actionable Items: {len(metadata.actionable_items)}")
    for item in metadata.actionable_items:
        print(f"     - {item}")
    print(f"   Urgency: {metadata.urgency_score:.2f}")
    print(f"   Importance: {metadata.importance_score:.2f}")
    print(f"   Durations found: {metadata.temporal_info.durations}")
    print()
    
    print("✅ Metadata Extraction Testing Complete!")

if __name__ == "__main__":
    test_metadata_extraction()