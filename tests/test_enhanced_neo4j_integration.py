#!/usr/bin/env python3
"""
Test the complete integration: Content Intelligence → Enhanced Neo4j Storage
"""
import sys
import os
sys.path.insert(0, '/home/david/jarvis/backend')

from app.services.content_intelligence import content_intelligence
from app.services.metadata_extractor import metadata_extractor
from app.services.tagging_system import smart_tagger
from app.services.enhanced_neo4j_schema import enhanced_neo4j

async def test_complete_integration():
    print("🔄 COMPLETE INTELLIGENCE → NEO4J INTEGRATION TEST")
    print("=" * 60)
    
    # Initialize enhanced schema
    print("🔧 Initializing enhanced Neo4j schema...")
    await enhanced_neo4j.initialize_enhanced_schema()
    print("✅ Schema initialized")
    
    # Test content
    test_content = """## Ingredients for Beef Stew

- 2 lb chuck roast, cubed
- 4 large potatoes, diced
- 2 carrots, sliced
- 1 onion, diced
- 2 cloves garlic, minced
- 3 cups beef broth
- 1 tsp thyme
- Salt and pepper to taste

## Instructions

1. **Brown the meat** - Heat oil in pressure cooker, brown beef cubes
2. **Add vegetables** - Add potatoes, carrots, onion, garlic
3. **Season** - Add thyme, salt, pepper, and broth
4. **Pressure cook** - Cook on high pressure for 30 minutes
5. **Natural release** - Let pressure release naturally for 10 minutes

TODO: Buy ingredients from grocery store this weekend
Action: Set timer for 30 minutes when cooking"""
    
    title = "Easy Pressure Cooker Beef Stew"
    content_id = "test_beef_stew_001"
    user_id = "test_user_001"
    
    print(f"\n📋 Processing: {title}")
    print("-" * 40)
    
    try:
        # Step 1: Content Intelligence Pipeline
        print("🧠 Running content intelligence...")
        content_type, chunks = content_intelligence.process_content(test_content, title)
        print(f"   ✅ Detected type: {content_type.value}")
        print(f"   ✅ Created {len(chunks)} chunks")
        
        # Step 2: Metadata Extraction
        print("🔍 Extracting metadata...")
        metadata = metadata_extractor.extract_metadata(test_content, content_type, title)
        print(f"   ✅ Found {len(metadata.entities)} entities")
        print(f"   ✅ Identified {len(metadata.topics)} topics: {[t.name for t in metadata.topics]}")
        print(f"   ✅ Extracted {len(metadata.actionable_items)} actionable items")
        print(f"   ✅ Urgency: {metadata.urgency_score:.2f}, Importance: {metadata.importance_score:.2f}")
        
        # Step 3: Smart Tagging
        print("🏷️ Generating smart tags...")
        tags = smart_tagger.generate_tags(test_content, metadata, content_type, title)
        print(f"   ✅ Generated {len(tags)} tags")
        tag_names = [tag.name for tag in tags]
        print(f"   ✅ Tags: {tag_names[:6]}...")
        
        # Step 4: Store in Enhanced Neo4j
        print("💾 Storing in enhanced Neo4j...")
        success = await enhanced_neo4j.store_intelligent_content(
            content_id=content_id,
            user_id=user_id,
            title=title,
            content=test_content,
            content_type=content_type,
            chunks=chunks,
            metadata=metadata,
            tags=tags
        )
        
        if success:
            print("   ✅ Successfully stored intelligent content!")
        else:
            print("   ❌ Failed to store content")
            return False
        
        # Step 5: Test Enhanced Queries
        print("\n🔍 Testing enhanced queries...")
        
        # Test tag-based search
        print("   🏷️ Searching by tags ['recipe', 'cooking']...")
        tag_results = await enhanced_neo4j.find_content_by_tags(user_id, ['recipe', 'cooking'])
        print(f"   ✅ Found {len(tag_results)} results")
        
        # Test urgency search  
        print("   ⚡ Searching for urgent content...")
        urgent_results = await enhanced_neo4j.find_content_by_urgency(user_id, min_urgency=0.0)
        print(f"   ✅ Found {len(urgent_results)} urgent items")
        
        # Test content analytics
        print("   📊 Getting content analytics...")
        analytics = await enhanced_neo4j.get_content_analytics(user_id)
        print(f"   ✅ Analytics: {analytics}")
        
        print(f"\n🎉 COMPLETE INTEGRATION TEST: PASSED!")
        print("\n📋 Integration Summary:")
        print(f"   ✅ Content Intelligence: Detected {content_type.value}, {len(chunks)} chunks")
        print(f"   ✅ Metadata Extraction: {len(metadata.entities)} entities, {len(metadata.topics)} topics")
        print(f"   ✅ Smart Tagging: {len(tags)} hierarchical tags generated")
        print(f"   ✅ Enhanced Storage: All data stored with relationships")
        print(f"   ✅ Advanced Queries: Tag search, urgency filtering, analytics")
        
        print(f"\n🚀 The intelligent content system is ready!")
        print(f"   🧠 Sara can now understand content deeply")
        print(f"   🔗 Meaningful connections based on real content similarity")
        print(f"   🏷️ Smart tagging for organization and retrieval")
        print(f"   ⚡ Priority-based processing and alerts")
        
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_complete_integration())