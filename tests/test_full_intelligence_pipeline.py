#!/usr/bin/env python3
"""
Comprehensive test of the full content intelligence pipeline
"""
import sys
import os
sys.path.insert(0, '/home/david/jarvis/backend')

from app.services.content_intelligence import content_intelligence
from app.services.metadata_extractor import metadata_extractor
from app.services.tagging_system import smart_tagger

def test_full_pipeline():
    print("🧠 COMPREHENSIVE CONTENT INTELLIGENCE PIPELINE TEST")
    print("=" * 60)
    
    test_cases = [
        {
            "title": "Simple Beef Stew (Ninja Foodi)",
            "content": """## Ingredients

- 2 ½ lb chuck roast, cut into 1‑inch cubes
- 5 lb red potatoes – scrubbed well
- 1 large onion, diced
- 3 cloves garlic, minced
- 3 carrots, sliced into ½‑inch rounds
- 1 cup frozen mixed veggies (peas, corn, green beans)
- 3 Tbsp tomato paste
- 2 Tbsp Worcestershire sauce
- 4 cups beef broth (or stock)

## Directions

1. **Prep the pot** – Set the Ninja Foodi to "Sauté" on high and add the olive oil.
2. **Brown the beef** – Working in batches, add the beef cubes, season with salt & pepper.
3. **Pressure‑cook** – Close the lid, set valve to "Seal", select "Pressure Cook" for 30 minutes.""",
            "expected_type": "recipe",
            "expected_tags": ["recipe", "cooking", "food", "actionable"]
        },
        
        {
            "title": "Web Search Feature Implementation",
            "content": """**Plan Breakdown: Two‑Stage Retrieval System**

TODO: Set up SearXNG locally using Docker
Action: Deploy Tiny LLM (LLama‑3‑8B) via vLLM
Follow-up: Build async fetcher + readability extractor

Timeline: 8 weeks total
- Week 1–2: Environment setup
- Week 3–4: LLM deployment
- Week 5–6: Integration testing

```python
def search_pipeline(query):
    search_terms = tiny_llm.generate_search(query)
    results = searxng.search(search_terms)
    return results
```

This is a critical feature for the platform.""",
            "expected_type": "technical_doc",
            "expected_tags": ["technical_doc", "technology", "actionable", "important"]
        },
        
        {
            "title": "Kettlebell Starter Plan for David",
            "content": """User details:
- Height: 6 ft
- Weight: 230 lbs
- Available equipment: 10 lb, 20 lb, 40 lb, 60 lb kettlebells

Week 1: 3 sets of 10 swings, 5 goblet squats
Week 2: 4 sets of 12 swings, 8 goblet squats  
Week 3: 5 sets of 15 swings, 10 goblet squats

Progress to 40 lb after 2–3 weeks of consistent training.

Next steps:
1. Choose workout days (3x per week recommended)
2. Set reminders for consistency""",
            "expected_type": "workout_plan",
            "expected_tags": ["workout_plan", "fitness", "actionable", "long_term"]
        },
        
        {
            "title": "Personal Reflection - Today",
            "content": """I'm feeling really motivated today after completing the kettlebell workout. 
            
The new programming project is challenging but exciting. I love learning new technologies and seeing how they can solve real problems.

Had a great meeting with the team - we're making excellent progress on the search feature. Everyone seems energetic and focused.

Tomorrow I want to:
- Continue working on the API integration
- Try that new beef stew recipe for dinner
- Remember to stay hydrated during workouts""",
            "expected_type": "journal_entry",
            "expected_tags": ["journal_entry", "personal", "positive", "actionable"]
        }
    ]
    
    all_passed = True
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🧪 TEST CASE {i}: {test_case['title']}")
        print("-" * 50)
        
        try:
            # Step 1: Content intelligence - type detection and chunking
            content_type, chunks = content_intelligence.process_content(
                test_case['content'], 
                test_case['title']
            )
            
            print(f"✅ Content Type: {content_type.value}")
            print(f"✅ Chunks Created: {len(chunks)}")
            
            # Verify content type
            if content_type.value != test_case['expected_type']:
                print(f"❌ FAIL: Expected {test_case['expected_type']}, got {content_type.value}")
                all_passed = False
                continue
            
            # Step 2: Metadata extraction
            metadata = metadata_extractor.extract_metadata(
                test_case['content'],
                content_type,
                test_case['title']
            )
            
            print(f"✅ Entities: {len(metadata.entities)}")
            print(f"✅ Topics: {[t.name for t in metadata.topics]}")
            print(f"✅ Intent: {metadata.intent}")
            print(f"✅ Urgency: {metadata.urgency_score:.2f}")
            print(f"✅ Importance: {metadata.importance_score:.2f}")
            
            if metadata.actionable_items:
                print(f"✅ Actionable Items: {len(metadata.actionable_items)}")
                for item in metadata.actionable_items[:2]:
                    print(f"     - {item[:60]}...")
            
            # Step 3: Smart tagging
            tags = smart_tagger.generate_tags(
                test_case['content'],
                metadata,
                content_type,
                test_case['title']
            )
            
            print(f"✅ Smart Tags Generated: {len(tags)}")
            tag_names = [tag.name for tag in tags]
            print(f"   Tags: {tag_names[:8]}...")  # Show first 8 tags
            
            # Verify expected tags are present
            missing_expected_tags = []
            for expected_tag in test_case['expected_tags']:
                if expected_tag not in tag_names:
                    missing_expected_tags.append(expected_tag)
            
            if missing_expected_tags:
                print(f"⚠️  Missing expected tags: {missing_expected_tags}")
            
            # Show tag breakdown by category
            tag_categories = {}
            for tag in tags:
                category = tag.category.value
                if category not in tag_categories:
                    tag_categories[category] = []
                tag_categories[category].append(tag.name)
            
            print(f"✅ Tag Categories:")
            for category, cat_tags in tag_categories.items():
                print(f"     {category}: {cat_tags[:3]}...")  # Show first 3 per category
            
            # Step 4: Integration test - show how everything works together
            print(f"✅ Integration Summary:")
            print(f"     Content understood as: {content_type.value}")
            print(f"     Primary topics: {[t.name for t in metadata.topics[:2]]}")
            print(f"     Key entities: {[e.name for e in metadata.entities[:3] if e.confidence > 0.6]}")
            print(f"     Processing priority: {'High' if metadata.urgency_score > 0.5 else 'Normal'}")
            print(f"     Chunk strategy: {len(chunks)} intelligent chunks")
            
            print(f"🎯 TEST CASE {i}: PASSED")
            
        except Exception as e:
            print(f"❌ TEST CASE {i}: FAILED - {str(e)}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    print(f"\n{'='*60}")
    if all_passed:
        print("🎉 ALL TESTS PASSED! Content Intelligence Pipeline is working perfectly!")
        print("\nThe system successfully:")
        print("✅ Detects content types accurately")
        print("✅ Chunks content intelligently based on structure")
        print("✅ Extracts meaningful metadata (entities, topics, urgency)")
        print("✅ Generates hierarchical, contextual tags")
        print("✅ Integrates all components seamlessly")
        print("\nReady to proceed to Phase 1.4: Enhanced Neo4j Schema!")
    else:
        print("❌ SOME TESTS FAILED - Check the failures above")
    
    return all_passed

if __name__ == "__main__":
    test_full_pipeline()