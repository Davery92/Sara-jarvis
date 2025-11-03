# Sara's Memory Integration Architecture

## Overview

Sara uses a **dual-database architecture** combining PostgreSQL and Neo4j to provide both raw memory storage and intelligent knowledge graph capabilities.

## Database Roles

### PostgreSQL - Raw Memory Layer
**Purpose**: Store all raw interactions and searchable content with semantic embeddings

**What it stores**:
- **Episodes**: Every conversation turn (user messages and Sara's responses)
- **Notes**: User-created notes with semantic embeddings
- **Documents**: File uploads with metadata
- **Reminders/Timers/Calendar**: Time-based functionality
- **Users**: Authentication and user data

**Key Features**:
- pgvector extension for semantic similarity search
- Vector embeddings (bge-m3 model, 1024 dimensions)
- Full-text search capabilities
- Recency-based retrieval
- Episode importance scoring
- Dream insights (generated during nightly consolidation)

**Access Pattern**:
- Direct read/write during conversations
- Semantic search for memory retrieval
- RAG (Retrieval Augmented Generation) context building

### Neo4j - Knowledge Graph Layer
**Purpose**: Store structured knowledge with rich relationships for advanced graph intelligence

**What it stores**:
- **Content nodes**: Consolidated conversation sessions
- **Chunks**: Intelligent content segments (code, general, workout sections)
- **Entities**: People, places, organizations, tools extracted from content
- **Topics**: Main themes and subjects
- **Tags**: Smart categorization with priority and confidence
- **ActionItems**: Extracted tasks and commitments
- **TemporalInfo**: Time-based patterns and schedules

**Relationships**:
- `CONTAINS_ENTITY`: Content → Entity
- `HAS_TOPIC`: Content → Topic
- `HAS_TAG`: Content → Tag
- `HAS_CHUNK`: Content → Chunk
- `HAS_ACTION_ITEM`: Content → ActionItem
- `SHARES_ENTITIES`: Content → Content (2+ shared entities)
- `SHARES_TOPICS`: Content → Content (shared topics)
- `SHARES_CONTEXT`: Content → Content (shared high-priority tags)

**Access Pattern**:
- Written during nightly dream consolidation
- Queried via knowledge graph tools
- Future: Real-time connection discovery

## Data Flow Architecture

### Real-Time Layer (PostgreSQL)
```
User Message → API Endpoint
    ↓
Episode Created (PostgreSQL)
    ↓
RAG Retrieval (semantic search on Episodes)
    ↓
Sara Response Generated
    ↓
Response Episode Stored
```

### Nightly Consolidation Layer (PostgreSQL → Neo4j)
```
2:00 AM Eastern (Scheduled)
    ↓
NightlyDreamService starts
    ↓
1. Fetch yesterday's Episodes from PostgreSQL
    ↓
2. Group into conversation sessions (30min gap threshold)
    ↓
3. For each session:
       ├─ Content Intelligence: Detect content type, create chunks
       ├─ Metadata Extraction: Extract entities, topics, temporal info
       ├─ Smart Tagging: Generate priority tags with confidence
       └─ Neo4j Storage: Store as Content node with relationships
    ↓
4. Create meaningful connections:
       ├─ Entity-based: Connect content sharing 2+ entities
       ├─ Topic-based: Connect content with overlapping topics
       └─ Context-based: Connect via high-priority tags
    ↓
5. Generate daily summary (also stored in Neo4j)
    ↓
6. Run DreamingService (PostgreSQL insights generation)
```

## Integration Points

### Current Integration
1. **Nightly Dream Service** (`nightly_dream_service.py`)
   - Runs at 2:00 AM Eastern
   - Processes PostgreSQL Episodes → Neo4j Content nodes
   - Uses asyncio.to_thread() for synchronous Neo4j calls
   - Generates both Neo4j knowledge graph AND PostgreSQL insights

2. **Knowledge Graph Tools** (`knowledge_graph.py`)
   - `knowledge_graph_search`: Search across Neo4j content
   - `find_connections`: Discover related content
   - `discover_knowledge_clusters`: Find knowledge communities
   - `analyze_knowledge_gaps`: Identify isolated content

3. **Notes System** (PostgreSQL only)
   - Notes currently stored ONLY in PostgreSQL
   - NOT automatically synced to Neo4j
   - Uses semantic embeddings for search

### Missing Integration Points
1. **Notes → Neo4j**: Notes are not currently being synced to Neo4j
2. **Real-time Neo4j Updates**: Neo4j only updated nightly (not during conversations)
3. **Unified Search**: No single search across both PostgreSQL and Neo4j
4. **Cross-Reference**: No automatic linking between PostgreSQL notes and Neo4j content

## System Strengths

### Why PostgreSQL?
- **Speed**: Fast inserts during real-time conversations
- **Semantic Search**: pgvector enables similarity-based retrieval
- **Simplicity**: Straightforward CRUD operations
- **Episode History**: Complete conversation chronology

### Why Neo4j?
- **Relationships**: First-class support for connections between content
- **Graph Algorithms**: Community detection, path finding, centrality
- **Semantic Meaning**: Entity and topic extraction creates rich metadata
- **Connection Discovery**: Find related content through shared entities/topics
- **Knowledge Gaps**: Identify isolated or under-connected content

### Why Both?
- **Complementary**: PostgreSQL = raw data, Neo4j = structured knowledge
- **Performance**: Each optimized for its use case
- **Flexibility**: Can query either based on need
- **Future-Proof**: Neo4j enables advanced graph intelligence features

## Current Implementation Status

### ✅ Working
- Nightly dream consolidation (PostgreSQL → Neo4j)
- Content intelligence pipeline (chunking, entities, topics, tags)
- Neo4j storage with relationships
- Knowledge graph tools (search, connections, clusters, gap analysis)
- Async/sync integration via asyncio.to_thread()
- Metadata serialization (JSON strings for nested dicts)
- Clean codebase with no dead code

### 📋 Available But Unused API Methods
The following methods in `enhanced_neo4j_schema.py` are intentionally designed for future use:
- `find_content_by_tags()` - Query content by tag names
- `find_related_content()` - Find similar content by entity/topic overlap
- `get_content_analytics()` - Get usage statistics and analytics

These are part of the public API and ready for integration with future features.

### ⚠️ Limitations
- **One-way sync**: PostgreSQL → Neo4j only (nightly)
- **No notes in Neo4j**: User-created notes not in knowledge graph
- **No real-time graph updates**: Must wait for nightly consolidation
- **Separate search**: Cannot search both databases simultaneously

### 🔮 Future Potential
1. **Bi-directional Sync**: Update both databases in real-time
2. **Notes Integration**: Sync notes to Neo4j with entity/topic extraction
3. **Unified Search**: Single API to query both PostgreSQL and Neo4j
4. **Smart Recommendations**: Use graph algorithms to suggest related content
5. **Auto-Linking**: Real-time connection creation during conversations
6. **Temporal Analysis**: Track how topics evolve over time
7. **Influence Mapping**: See which entities/topics drive conversations

## Key Files

### PostgreSQL Layer
- `app/models/episode.py`: Episode model with embeddings
- `app/models/note.py`: Note model
- `app/services/memory.py`: Episode retrieval and RAG
- `app/services/embeddings.py`: Vector embedding generation

### Neo4j Layer
- `app/services/neo4j_service.py`: Base Neo4j connection
- `app/services/enhanced_neo4j_schema.py`: Enhanced storage with intelligence
- `app/services/content_intelligence.py`: Content type detection and chunking
- `app/services/metadata_extractor.py`: Entity and topic extraction
- `app/services/tagging_system.py`: Smart tag generation

### Integration Layer
- `app/services/nightly_dream_service.py`: Orchestrates PostgreSQL → Neo4j
- `app/tools/knowledge_graph.py`: Sara's tools to query Neo4j
- `app/tools/notes.py`: Sara's tools for PostgreSQL notes

## Technical Considerations

### Async/Sync Pattern
Neo4j driver is synchronous, FastAPI is async. Solution:
```python
# Wrap synchronous Neo4j calls in thread pool
success = await asyncio.to_thread(
    enhanced_neo4j.store_intelligent_content,
    content_id=session_content_id,
    # ... parameters
)
```

### Metadata Serialization
Neo4j only supports primitive types. Solution:
```python
# Serialize nested dicts to JSON strings
metadata_json = json.dumps(chunk.metadata) if chunk.metadata else "{}"
```

### Connection Creation
Use Cypher queries to find meaningful connections:
- Require minimum overlap (2+ shared entities)
- Calculate connection strength (confidence scores)
- Auto-generate bidirectional relationships

## Architecture Diagrams

### Real-Time Flow
```
┌─────────────┐
│    User     │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  FastAPI Server │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌──────┐  ┌──────────┐
│ RAG  │  │ Episodes │
└──┬───┘  │PostgreSQL│
   │      └──────────┘
   │
   ▼
┌────────────┐
│ LLM (GLM)  │
└────────────┘
```

### Nightly Consolidation Flow
```
┌────────────────────┐
│ Episodes (PG) ←────┼─── Yesterday's conversations
└─────────┬──────────┘
          │
          ▼
┌──────────────────────────┐
│ Content Intelligence     │
│ - Type detection         │
│ - Chunking               │
│ - Entity extraction      │
│ - Topic modeling         │
│ - Smart tagging          │
└──────────┬───────────────┘
           │
           ▼
┌─────────────────────────┐
│ Neo4j Knowledge Graph   │
│ - Content nodes         │
│ - Entity relationships  │
│ - Topic connections     │
│ - Context clustering    │
└─────────────────────────┘
```

## Verification Queries

### Check Neo4j Data
```cypher
// Count all nodes by type
MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC

// Count all relationships
MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC

// Sample content nodes
MATCH (c:Content) RETURN c.title, c.content_type LIMIT 5

// Find highly connected entities
MATCH (e:Entity)
WITH e, size((e)<-[:CONTAINS_ENTITY]-()) as connection_count
WHERE connection_count > 3
RETURN e.name, e.entity_type, connection_count
ORDER BY connection_count DESC
```

### Check PostgreSQL Data
```sql
-- Count episodes by user
SELECT user_id, COUNT(*) FROM episodes GROUP BY user_id;

-- Recent episodes
SELECT role, LEFT(content, 50), created_at
FROM episodes
ORDER BY created_at DESC
LIMIT 10;

-- Notes with embeddings
SELECT id, title, created_at
FROM notes
WHERE embedding IS NOT NULL
ORDER BY created_at DESC;
```

## Performance Characteristics

### PostgreSQL
- **Write Speed**: Excellent (real-time inserts)
- **Read Speed**: Very Good (indexed queries, vector search)
- **Search Type**: Semantic similarity, full-text
- **Best For**: Real-time conversation memory

### Neo4j
- **Write Speed**: Good (batch inserts nightly)
- **Read Speed**: Excellent (graph traversal)
- **Search Type**: Relationship-based, pattern matching
- **Best For**: Finding connections, knowledge exploration

## Conclusion

Sara's dual-database architecture provides both immediate conversational memory (PostgreSQL) and deep knowledge intelligence (Neo4j). The nightly dream consolidation bridges the two systems, extracting structured knowledge from raw conversations.

**Current State**: Fully functional for conversation consolidation and knowledge graph querying

**Next Evolution**: Real-time graph updates, notes integration, unified search

---

*Last Updated: 2025-11-01*
*Status: Phase 2 Analysis Complete ✅*
