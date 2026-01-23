# Sara Self-Knowledge: Architecture

## Core Data Layer

| Component | Purpose | Location |
|-----------|---------|----------|
| **PostgreSQL** | Primary durable storage for episodes, notes, tasks, health samples, projects, conversations | `docker-compose.yml` (jarvis-db-1) |
| **Neo4j** | Knowledge graph for relationships, entities, topics, semantic connections | `docker-compose.yml` (jarvis-neo4j-1) |
| **Redis** | Caching, working set for recent memories, session state | `docker-compose.yml` (jarvis-redis-1) |
| **pgvector** | Vector similarity search over episodic memory using HNSW indexing | PostgreSQL extension |
| **MinIO** | Object storage for document uploads | `docker-compose.yml` (jarvis-minio-1) |

## Memory System

Your memory is sophisticated and multi-layered:

### Three-Tiered Retrieval

1. **Redis Working Set (Hot Tier)**
   - Recent memories cached in Redis sorted sets
   - TTL: 48 hours (configurable via `REDIS_FOCUS_TTL_SECONDS`)
   - Max items: 1000 per user
   - Ultra-fast recency access

2. **PostgreSQL HNSW Vector Search (Warm Tier)**
   - Uses pgvector extension with HNSW algorithm
   - Semantic similarity search with configurable distance metric
   - Default time window: 30 days
   - Location: `backend/app/services/memory_service.py`

3. **Neo4j Graph Edges (Cold Tier)**
   - 1-hop neighbor expansion from top vector results
   - Conceptual connections between memories
   - Bidirectional relationship tracking

### Episodic Memory (PostgreSQL)
- Every conversation turn is stored as an episode
- Episodes have embeddings for semantic retrieval (bge-m3, 1024 dimensions)
- Importance scores determine what surfaces during recall
- User ratings provide feedback that improves future retrieval
- Location: `Episode` model in `backend/app/main_simple.py`

### Knowledge Graph (Neo4j)
- Entities extracted from conversations: people, organizations, concepts, projects
- Topics and smart tags for categorization
- Relationships: SEMANTIC_SIMILAR, TEMPORAL_NEAR, REFERENCES, CONTAINS_ENTITY, SHARES_ENTITIES, SHARES_TOPICS, SHARES_CONTEXT
- Enables traversal queries: "What do I know about X and everything related to it?"
- Location: `backend/app/services/neo4j_service.py`, `backend/app/services/enhanced_neo4j_schema.py`

### Confidence Scoring

**Wilson Score** (`backend/app/services/rating_service.py`)
- 95% confidence intervals for memory reliability
- Formula: `(p + z²/2n - z√(p(1-p)/n + z²/4n²)) / (1 + z²/n)` where z=1.96
- Prevents manipulation by single votes
- Combined with temporal decay (30-day half-life for ratings)

**Thompson Sampling** (`backend/app/services/thompson_sampling.py`)
- Beta distribution sampling for cold-start mitigation
- Explores less-accessed memories probabilistically
- 7-day cold-start window with linear age decay
- Max exploration bonus: 10% of retrieval score

### Composite Retrieval Scoring

Location: `backend/app/main_simple.py` (lines 4914-4918)

```
Composite Score =
  (1 - cosine_distance) × 0.40 +     // Semantic similarity (40%)
  exp(-t / (14 × 86400)) × 0.20 +    // Recency - 14-day half-life (20%)
  importance_score × 0.20 +           // AI-scored importance (20%)
  rating_boost × 0.15 +               // Wilson Score + temporal decay (15%)
  exploration_bonus × 0.05            // Thompson Sampling (5%)
```

### Temporal Decay
- **Memory recency**: Exponential decay with **14-day half-life**
- **Rating boost**: Exponential decay with 30-day half-life
- Frequently accessed or highly-rated memories resist decay
- Nightly rescoring recalculates importance across all memories

## Processing Pipeline

When David sends a message:
1. Message stored in PostgreSQL with embedding (bge-m3)
2. Relevant memories retrieved using composite scoring
3. Context assembled from:
   - Memories (semantic search)
   - Insights (from dream consolidation)
   - Cognitive context (reflections, hypotheses)
   - Body state (physiological awareness)
   - Journal (inner monologue)
   - Workout context (if active session)
   - Daily brief (background knowledge)
4. Response generated via LLM (gpt-oss:120b default)
5. Response stored as episode
6. Background workers process for entity extraction, topic classification, graph updates

## Database Schema (Key Tables)

**Memory & Episodes:**
- `Episode` - Individual memory traces with embeddings
- `EpisodeRating` - User ratings for episodes
- `SemanticSummary` - Daily/weekly compacted summaries
- `MemoryTrace`, `MemoryEmbedding`, `MemoryEdge` - Alternative memory storage

**Knowledge Garden:**
- `Note` - User's saved notes with folder organization
- `Folder` - Hierarchical folder structure
- `NoteConnection` - Bidirectional links (reference/semantic/temporal)

**Intelligence:**
- `DreamInsight` - Nightly dream-generated insights
- `IntelligenceReport` - Curated intelligence summaries
- `ProactiveSuggestion` - AI-generated suggestions
- `DetectedPattern` - Cross-domain pattern detection

**Time Management:**
- `Reminder`, `Timer`, `CalendarEvent`

**Total Tables:** 43+

## LLM Configuration

- **Primary Model:** gpt-oss:120b via `http://100.104.68.115:11434/v1`
- **Fallback Model:** gpt-oss:20b via local endpoint
- **Embedding Model:** bge-m3 (1024 dimensions)
- **Timezone:** America/New_York (Eastern)
