# Sara's Memory System - In-Depth Guide

## 🧠 Overview

Sara's memory system is a sophisticated episodic memory architecture that enables persistent, contextual conversations. Built on PostgreSQL with pgvector extensions, it provides semantic search capabilities across all user interactions, creating a truly intelligent personal assistant that remembers everything.

## 🏗️ Architecture

### Core Components

```mermaid
graph TB
    A[User Message] --> B[Chat Endpoint]
    B --> C[LLM Processing]
    C --> D[Response Generation]
    D --> E[Memory Storage]
    E --> F[Embedding Generation]
    F --> G[PostgreSQL + pgvector]
    
    H[Memory Search Tool] --> I[Query Embedding]
    I --> J[Semantic Search]
    J --> G
    G --> K[Ranked Results]
    K --> L[Context Injection]
    L --> C
```

### Database Schema

#### Conversations Table
```sql
CREATE TABLE conversation (
    id VARCHAR PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR NOT NULL,
    title VARCHAR DEFAULT '',
    summary TEXT DEFAULT '',
    total_messages INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Conversation Turns Table
```sql
CREATE TABLE conversation_turn (
    id VARCHAR PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    embedding VECTOR(1024),  -- pgvector for semantic search
    created_at TIMESTAMP DEFAULT NOW()
);
```

## 📊 Memory Storage Process

### 1. Automatic Storage
Every chat interaction triggers memory storage:

```python
# After each chat response
await llm_client.store_conversation(request.messages, response_content, current_user.id)
```

### 2. Conversation Creation
```python
conversation = Conversation(
    user_id=user_id,
    title="",  # Will be generated later
    total_messages=len(messages) + 1
)
```

### 3. Message Processing
For each message in the conversation:

```python
# Generate embedding using BGE-M3 model
embedding = await embedding_service.generate_embedding(message.content)

# Store turn with embedding
turn = ConversationTurn(
    conversation_id=conversation.id,
    user_id=user_id,
    role=message.role,
    content=message.content,
    message_index=turn_index,
    embedding=embedding_data
)
```

### 4. Database Persistence
- PostgreSQL stores all data with pgvector extension
- Embeddings stored as 1024-dimensional vectors
- Automatic indexing for fast retrieval

## 🔍 Memory Search Architecture

### Dual Search Strategy

#### 1. Semantic Vector Search (Primary)
```sql
SELECT 
    ct.content, ct.role, ct.created_at, c.title,
    (1 - (ct.embedding <=> :query_embedding)) as similarity
FROM conversation_turn ct
JOIN conversation c ON ct.conversation_id = c.id
WHERE ct.user_id = :user_id 
  AND ct.embedding IS NOT NULL
ORDER BY ct.embedding <=> :query_embedding
LIMIT 10
```

#### 2. Text-Based Search (Fallback)
```sql
SELECT ct.content, ct.role, ct.created_at, c.title
FROM conversation_turn ct
JOIN conversation c ON ct.conversation_id = c.id
WHERE ct.user_id = :user_id
  AND ct.content ILIKE '%:query%'
ORDER BY ct.created_at DESC
LIMIT 8
```

### Search Algorithm
```python
async def search_memory_tool(self, query, user_id):
    # 1. Generate query embedding
    query_embedding = await embedding_service.generate_embedding(query)
    
    # 2. Semantic search (primary)
    semantic_results = await semantic_search(query_embedding, user_id)
    
    # 3. Text search (fallback)
    text_results = await text_search(query, user_id)
    
    # 4. Combine and rank results
    combined_results = merge_and_rank(semantic_results, text_results)
    
    return formatted_results
```

## ⚙️ Vector Embedding System

### BGE-M3 Model
- **Model**: BAAI/bge-m3
- **Dimensions**: 1024
- **Language**: Multilingual support
- **Optimization**: Semantic similarity optimized

### Embedding Generation
```python
class EmbeddingService:
    async def generate_embedding(self, text: str) -> List[float]:
        response = await self.client.post("/embeddings", json={
            "model": "bge-m3",
            "input": text
        })
        return response["data"][0]["embedding"]
```

### Vector Storage
```python
# PostgreSQL with pgvector
if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
    embedding_data = embedding  # Direct vector storage
else:
    # SQLite fallback: JSON string
    embedding_data = json.dumps(embedding)
```

## 🎯 Memory Retrieval & Prioritization

### Recency Bias Implementation

#### Time-Based Ordering
```python
# Recent conversations prioritized
ORDER BY Conversation.updated_at DESC

# Recent messages prioritized in text search
ORDER BY ConversationTurn.created_at DESC
```

#### Semantic Relevance Override
```python
# High semantic similarity overrides recency
if similarity_score > 0.8:
    high_priority = True
elif created_at > recent_threshold:
    medium_priority = True
else:
    low_priority = True
```

### Search Result Formatting
```python
def format_memory_results(semantic_results, text_results):
    """Combine and format search results"""
    formatted = []
    
    # Process semantic results
    for result in semantic_results:
        formatted.append({
            'content': result.content,
            'role': result.role,
            'created_at': result.created_at.isoformat(),
            'similarity': round(result.similarity, 3),
            'source': 'semantic_search'
        })
    
    # Process text results
    for result in text_results:
        formatted.append({
            'content': result.content,
            'role': result.role,
            'created_at': result.created_at.isoformat(),
            'source': 'text_search'
        })
    
    return deduplicate_and_rank(formatted)
```

## 🛠️ Tool Integration

### Memory Search Tool
```python
{
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": "Search through Sara's conversation memory for past interactions",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find relevant memories"
                }
            },
            "required": ["query"]
        }
    }
}
```

### Automatic Memory Usage
Sara automatically searches memory when:
- User references previous conversations
- Context would improve response quality
- User asks about personal preferences
- Continuity is needed across sessions

### Manual Memory Search
```python
# API endpoint for direct memory search
@app.get("/memory/search")
async def search_memory(
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user)
):
    return await llm_client.search_memory_tool(query, current_user.id)
```

## 🚀 Performance Optimization

### Database Indexing
```sql
-- Vector similarity index
CREATE INDEX idx_conversation_turn_embedding 
ON conversation_turn USING ivfflat (embedding vector_cosine_ops);

-- Chronological indexes
CREATE INDEX idx_conversation_turn_created_at 
ON conversation_turn (created_at DESC);

CREATE INDEX idx_conversation_updated_at 
ON conversation (updated_at DESC);

-- User filtering indexes
CREATE INDEX idx_conversation_turn_user_id 
ON conversation_turn (user_id);
```

### Memory Management
```python
# Connection pooling
DATABASE_URL = "postgresql+psycopg://sara:sara123@host:5432/sara_hub"
engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)

# Efficient batch processing
async def store_conversation_batch(messages_batch, user_id):
    """Store multiple messages efficiently"""
    with SessionLocal() as db:
        db.bulk_insert_mappings(ConversationTurn, turns_data)
        db.commit()
```

### Query Optimization
```python
# Limit result sets for performance
SEMANTIC_SEARCH_LIMIT = 10
TEXT_SEARCH_LIMIT = 8
MEMORY_SEARCH_TIMEOUT = 5.0  # seconds

# Pagination for large datasets
async def paginated_memory_search(query, offset=0, limit=50):
    return await search_with_pagination(query, offset, limit)
```

## 📈 Monitoring & Analytics

### Memory Usage Metrics
```python
async def get_memory_stats(user_id: str):
    """Get user memory statistics"""
    stats = {
        'total_conversations': await count_conversations(user_id),
        'total_messages': await count_messages(user_id),
        'memory_size_mb': await calculate_memory_size(user_id),
        'oldest_memory': await get_oldest_memory(user_id),
        'most_active_period': await analyze_activity_patterns(user_id)
    }
    return stats
```

### Search Analytics
```python
async def log_search_metrics(query, results_count, search_time):
    """Track search performance and usage"""
    logger.info(f"Memory search: query='{query}', results={results_count}, time={search_time}ms")
```

## 🔧 Configuration & Setup

### Environment Variables
```bash
# Database Configuration
DATABASE_URL=postgresql+psycopg://sara:sara123@host:5432/sara_hub

# Embedding Service
EMBEDDING_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Memory Settings
MEMORY_SEARCH_LIMIT=10
MEMORY_RETENTION_DAYS=365  # Optional: for cleanup policies
```

### Docker Setup
```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: sara_hub
      POSTGRES_USER: sara
      POSTGRES_PASSWORD: sara123
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

### Database Migration
```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create tables with vector support
\i schema/memory_tables.sql

-- Create indexes for performance
\i schema/memory_indexes.sql
```

## 🧪 Testing & Validation

### Memory Storage Tests
```python
async def test_memory_storage():
    """Test conversation storage and retrieval"""
    # Store test conversation
    await store_conversation(test_messages, "test_user")
    
    # Verify storage
    conversations = await get_conversations("test_user")
    assert len(conversations) == 1
    
    # Test embedding generation
    turns = await get_conversation_turns(conversations[0].id)
    assert all(turn.embedding is not None for turn in turns)
```

### Search Quality Tests
```python
async def test_semantic_search():
    """Test semantic search accuracy"""
    # Store known conversations
    await store_test_conversations()
    
    # Test semantic similarity
    results = await search_memory("machine learning project", "test_user")
    
    # Verify relevant results returned
    assert any("AI" in result.content for result in results)
    assert len(results) > 0
```

### Performance Benchmarks
```python
async def benchmark_search_performance():
    """Benchmark search response times"""
    import time
    
    start_time = time.time()
    results = await search_memory("test query", "test_user")
    search_time = time.time() - start_time
    
    assert search_time < 1.0  # Should complete within 1 second
    assert len(results) <= 10  # Proper result limiting
```

## 🔮 Future Enhancements

### Planned Features
1. **Memory Consolidation**: Automatic summary generation for old conversations
2. **Importance Scoring**: Weight memories by interaction frequency and user feedback
3. **Memory Clustering**: Group related conversations by topic
4. **Temporal Relationships**: Track how topics evolve over time
5. **Memory Sharing**: Allow users to share memories between instances

### Scalability Improvements
1. **Distributed Storage**: Support for multiple database nodes
2. **Caching Layer**: Redis integration for frequently accessed memories
3. **Async Processing**: Background embedding generation
4. **Compression**: Optimize storage for large conversation histories

### Advanced Features
1. **Memory Graphs**: Relationship mapping between conversations
2. **Emotional Context**: Sentiment analysis integration
3. **Memory Triggers**: Proactive memory suggestions
4. **Context Windows**: Dynamic context injection based on relevance

## 📚 API Reference

### Memory Endpoints

#### Search Memory
```http
GET /memory/search?query=project&limit=10
Authorization: Bearer <token>

Response:
{
  "query": "project",
  "results": [
    {
      "content": "Let's work on the ML project",
      "role": "user",
      "created_at": "2024-01-15T10:30:00Z",
      "similarity": 0.85,
      "source": "semantic_search"
    }
  ]
}
```

#### Get Conversations
```http
GET /conversations?limit=20
Authorization: Bearer <token>

Response:
{
  "conversations": [
    {
      "id": "uuid",
      "title": "Project Discussion",
      "summary": "Discussed ML project requirements",
      "total_messages": 12,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T11:00:00Z"
    }
  ]
}
```

#### Get Conversation Turns
```http
GET /conversations/{conversation_id}/turns
Authorization: Bearer <token>

Response:
{
  "turns": [
    {
      "id": "uuid",
      "conversation_id": "parent_uuid",
      "role": "user",
      "content": "How do I implement this feature?",
      "message_index": 0,
      "created_at": "2024-01-15T10:00:00Z"
    }
  ]
}
```

## 💡 Best Practices

### Memory Storage
1. **Consistent Format**: Ensure all messages follow the same structure
2. **Error Handling**: Gracefully handle embedding generation failures
3. **Batch Processing**: Store multiple messages efficiently
4. **Validation**: Verify message content before storage

### Search Optimization
1. **Query Preprocessing**: Clean and normalize search queries
2. **Result Ranking**: Combine semantic and temporal relevance
3. **Caching**: Cache frequent searches for better performance
4. **Filtering**: Allow users to filter by time period or topic

### Data Management
1. **Backup Strategy**: Regular database backups with point-in-time recovery
2. **Privacy Controls**: User-controlled memory deletion
3. **Data Retention**: Configurable retention policies
4. **Export Capabilities**: Allow users to export their memory data

## 🚨 Troubleshooting

### Common Issues

#### Embedding Generation Failures
```python
# Check embedding service health
async def check_embedding_service():
    try:
        test_embedding = await embedding_service.generate_embedding("test")
        return len(test_embedding) == 1024
    except Exception as e:
        logger.error(f"Embedding service error: {e}")
        return False
```

#### Search Performance Issues
```python
# Monitor search performance
async def debug_search_performance(query, user_id):
    start_time = time.time()
    
    # Check database connection
    db_healthy = await check_database_health()
    
    # Check index usage
    query_plan = await explain_search_query(query, user_id)
    
    # Check result set size
    result_count = await count_search_results(query, user_id)
    
    total_time = time.time() - start_time
    
    logger.info(f"Search debug: db_healthy={db_healthy}, "
                f"results={result_count}, time={total_time}s")
```

#### Memory Storage Issues
```python
# Validate memory storage
async def validate_memory_storage(user_id):
    recent_conversations = await get_recent_conversations(user_id, limit=5)
    
    for conv in recent_conversations:
        turns = await get_conversation_turns(conv.id)
        
        # Check for missing embeddings
        missing_embeddings = [t for t in turns if t.embedding is None]
        if missing_embeddings:
            logger.warning(f"Missing embeddings in conversation {conv.id}")
            
        # Check for orphaned turns
        orphaned_turns = await find_orphaned_turns(conv.id)
        if orphaned_turns:
            logger.error(f"Orphaned turns found: {len(orphaned_turns)}")
```

---

This memory system provides Sara with true conversational continuity, enabling natural, context-aware interactions that improve over time. The combination of semantic search and temporal prioritization creates an intelligent memory that feels both comprehensive and relevant.