# Rating System API Documentation

Complete API documentation for Sara's rating-aware memory engine.

## Overview

The rating system allows users to rate episodes (memories) with 1-5 stars, influencing memory retrieval through Wilson Score confidence intervals, temporal decay, and Thompson Sampling exploration.

---

## API Endpoints

### 1. Rate an Episode

**POST** `/api/episodes/{episode_id}/rate`

Rate a specific episode (1-5 stars).

**Headers:**
- `Authorization: Bearer <token>` (JWT via HTTP-only cookie)

**Path Parameters:**
- `episode_id` (string, UUID): Episode to rate

**Request Body:**
```json
{
  "rating": 5
}
```

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Episode rated successfully",
  "rating": {
    "episode_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_rating": 5,
    "rating_count": 1,
    "average_rating": 5.0,
    "rating_sum": 5,
    "last_rated": "2025-01-24T10:30:00.000Z"
  }
}
```

**Error Responses:**
- `400 Bad Request`: Invalid rating (must be 1-5)
- `404 Not Found`: Episode doesn't exist
- `401 Unauthorized`: Not authenticated

**Example:**
```bash
curl -X POST http://10.185.1.180:8000/api/episodes/123e4567-e89b-12d3-a456-426614174000/rate \
  -H "Content-Type: application/json" \
  -d '{"rating": 5}'
```

---

### 2. Get Episode Rating

**GET** `/api/episodes/{episode_id}/rating`

Get rating data for a specific episode.

**Headers:**
- `Authorization: Bearer <token>`

**Path Parameters:**
- `episode_id` (string, UUID): Episode ID

**Response** (200 OK):
```json
{
  "rated": true,
  "episode_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_rating": 5,
  "rating_count": 12,
  "average_rating": 4.5,
  "rating_sum": 54,
  "last_rated": "2025-01-24T10:30:00.000Z"
}
```

**Response** (not rated):
```json
{
  "rated": false
}
```

**Error Responses:**
- `401 Unauthorized`: Not authenticated
- `500 Internal Server Error`: Database error

**Example:**
```bash
curl http://10.185.1.180:8000/api/episodes/123e4567-e89b-12d3-a456-426614174000/rating
```

---

### 3. Delete Episode Rating

**DELETE** `/api/episodes/{episode_id}/rating`

Delete user's rating for an episode.

**Headers:**
- `Authorization: Bearer <token>`

**Path Parameters:**
- `episode_id` (string, UUID): Episode ID

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Rating deleted successfully"
}
```

**Error Responses:**
- `404 Not Found`: Rating not found
- `401 Unauthorized`: Not authenticated

**Example:**
```bash
curl -X DELETE http://10.185.1.180:8000/api/episodes/123e4567-e89b-12d3-a456-426614174000/rating
```

---

### 4. Get Rating Statistics

**GET** `/api/rating/stats`

Get global rating system statistics.

**Headers:**
- `Authorization: Bearer <token>`

**Response** (200 OK):
```json
{
  "cache_stats": {
    "total_rated_episodes": 245,
    "pending_sync_count": 12
  },
  "database": {
    "total_ratings": 233,
    "average_rating": 4.2
  }
}
```

**Error Responses:**
- `401 Unauthorized`: Not authenticated

**Example:**
```bash
curl http://10.185.1.180:8000/api/rating/stats
```

---

## Rating System Formulas

### 1. Wilson Score Confidence Interval

Prevents manipulation by single votes. Provides a confidence interval for the true rating.

```python
def calculate_rating_boost(rating_sum, rating_count, created_at):
    # Normalize to 0-1 scale
    p = rating_sum / (5.0 * rating_count)

    # Wilson Score parameters
    z = 1.96  # 95% confidence
    n = rating_count

    # Wilson Score lower bound
    numerator = p + (z²/(2n)) - z*√(p(1-p)/n + z²/(4n²))
    denominator = 1 + (z²/n)
    confidence = numerator / denominator

    # Temporal decay (exponential, 30-day half-life)
    age_days = (now - created_at).days
    decay_constant = ln(2) / 30.0
    age_decay = exp(-decay_constant * age_days)

    # Final boost (0-0.25 range, 25% of total score)
    rating_boost = confidence * age_decay * 0.25

    return rating_boost
```

### 2. Thompson Sampling (Cold-Start Exploration)

Addresses the cold-start problem by giving new memories a probabilistic boost.

```python
def calculate_exploration_bonus(rating_sum, rating_count, created_at):
    age_days = (now - created_at).days

    # Only apply for first 7 days
    if age_days >= 7:
        return 0.0

    # Beta distribution parameters
    alpha = rating_sum + 1
    beta = (5 * rating_count - rating_sum) + 1

    # Sample from Beta distribution
    sample = np.random.beta(alpha, beta)

    # Scale by remaining cold-start period
    age_factor = (7 - age_days) / 7.0

    return sample * age_factor * 0.1  # 0-0.1 range
```

### 3. Enhanced Retrieval Scoring

Memory retrieval uses composite scoring with rating influence:

```sql
composite_score =
    (1 - (embedding <=> query_embedding)) * 0.40 +  -- Semantic (40%)
    EXP(-EXTRACT(EPOCH FROM (NOW() - created_at)) / (7 * 86400)) * 0.20 +  -- Recency (20%)
    COALESCE(importance, 0.5) * 0.20 +  -- AI Importance (20%)
    COALESCE(rating_boost, 0.0) * 0.15 +  -- Rating Boost (15%)
    COALESCE(exploration_bonus, 0.0) * 0.05  -- Exploration (5%)
```

---

## Redis Pub/Sub Events

### Event: `sara:episode:rated`

Published when an episode is rated.

**Payload:**
```json
{
  "type": "episode_rated",
  "episode_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "456e7890-e89b-12d3-a456-426614174000",
  "rating": 5,
  "net_score": 15,
  "rating_count": 3,
  "average_rating": 5.0,
  "timestamp": "2025-01-24T10:30:00.000Z"
}
```

### Event: `sara:rating:updated`

Published when a rating is changed.

**Payload:**
```json
{
  "type": "rating_updated",
  "episode_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "456e7890-e89b-12d3-a456-426614174000",
  "old_rating": 4,
  "new_rating": 5,
  "net_score": 15,
  "timestamp": "2025-01-24T10:30:00.000Z"
}
```

### Event: `sara:rating:synced`

Published after nightly consolidation completes.

**Payload:**
```json
{
  "type": "rating_synced",
  "episode_ids": ["uuid1", "uuid2", "uuid3"],
  "success_count": 150,
  "error_count": 2,
  "timestamp": "2025-01-24T02:30:00.000Z"
}
```

---

## Database Schema

### Table: `episode_rating`

```sql
CREATE TABLE episode_rating (
    episode_id VARCHAR PRIMARY KEY REFERENCES episode(id) ON DELETE CASCADE,
    user_rating INTEGER,  -- User's 1-5 star rating
    rating_count INTEGER DEFAULT 0,
    average_rating FLOAT DEFAULT 0.0,
    rating_sum INTEGER DEFAULT 0,
    last_rated TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Modified Table: `episode`

Added columns:
```sql
ALTER TABLE episode
ADD COLUMN rating_boost FLOAT DEFAULT 0.0,
ADD COLUMN exploration_bonus FLOAT DEFAULT 0.0;

-- Indexes
CREATE INDEX idx_episode_rating_boost ON episode(rating_boost);
CREATE INDEX idx_episode_exploration_bonus ON episode(exploration_bonus);
CREATE INDEX idx_episode_user_created_rating ON episode(user_id, created_at, rating_boost);
```

---

## Redis Cache Keys

### Episode Rating

**Key:** `episode_rating:{episode_id}`
**Type:** Hash
**TTL:** 30 days
**Fields:**
```
user_rating: INTEGER (1-5)
rating_count: INTEGER
average_rating: FLOAT
rating_sum: INTEGER
last_rated: ISO8601 timestamp
```

### User Rating

**Key:** `user_rating:{user_id}:{episode_id}`
**Type:** String
**TTL:** 30 days
**Value:** INTEGER (1-5)

### Dirty Set

**Key:** `rating_dirty_set`
**Type:** Set
**Members:** Episode UUIDs needing PostgreSQL sync

---

## Nightly Consolidation Job

**Schedule:** 2:30 AM daily (after memory compaction at 2:10 AM)

**Process:**
1. Fetch dirty episode IDs from Redis (`rating_dirty_set`)
2. Batch process (100 episodes at a time)
3. For each episode:
   - Calculate `rating_boost` (Wilson Score + temporal decay)
   - Calculate `exploration_bonus` (Thompson Sampling)
   - Update PostgreSQL `episode` and `episode_rating` tables
   - Update Neo4j episode node (if available)
4. Run consistency checks (Redis vs PostgreSQL)
5. Publish `sara:rating:synced` event

**Monitoring:**
- Logs to `/home/david/jarvis/logs/rating_consolidation.log`
- Success/error counts tracked
- Data consistency warnings for >10% discrepancy

---

## Rate Limiting & Abuse Detection

### Rating Fatigue Prevention

Only prompt for rating if:
- Message is from assistant (not user's own messages)
- Message length >= 50 characters
- Not a low-value message ("I'm", "Let me", "Sure", etc.)
- < 3 rating prompts in current conversation

### Manipulation Detection (Logged, Not Enforced)

Suspicious patterns logged to `logs/rating_abuse.log`:
- User rates >90% of messages 5-star within 24h
- Rapid rating (>10 ratings in 1 minute)
- Bulk rating old memories (>20 episodes >30 days old)

---

## Integration Examples

### Frontend (React)

```typescript
// Rate an episode
const rateEpisode = async (episodeId: string, rating: number) => {
  const response = await fetch(`/api/episodes/${episodeId}/rate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating })
  });
  return response.json();
};

// Get episode rating
const getEpisodeRating = async (episodeId: string) => {
  const response = await fetch(`/api/episodes/${episodeId}/rating`);
  return response.json();
};
```

### Mobile (React Native)

```typescript
import { apiClient } from './services/apiClient';

// Rate an episode
const rateEpisode = async (episodeId: string, rating: number) => {
  return apiClient.post(`/api/episodes/${episodeId}/rate`, { rating });
};

// Offline queueing
import AsyncStorage from '@react-native-async-storage/async-storage';

const queueRating = async (episodeId: string, rating: number) => {
  const queue = JSON.parse(await AsyncStorage.getItem('rating_queue') || '[]');
  queue.push({ episodeId, rating, timestamp: Date.now() });
  await AsyncStorage.setItem('rating_queue', JSON.stringify(queue));
};
```

---

## Troubleshooting

### Issue: Ratings not appearing in memory retrieval

**Check:**
1. Has nightly consolidation run? (check `rating_boost` column)
2. Is Redis cache populated? (check `episode_rating:{id}` key)
3. Are episodes marked dirty? (check `rating_dirty_set` size)

**Debug:**
```bash
# Check episode rating_boost
python3 -c "import psycopg; conn = psycopg.connect('...'); cur = conn.cursor(); cur.execute('SELECT id, rating_boost FROM episode WHERE rating_boost > 0 LIMIT 10'); print(cur.fetchall())"

# Check Redis cache
redis-cli GET "episode_rating:123e4567-e89b-12d3-a456-426614174000"
```

### Issue: Ratings not syncing to database

**Check:**
1. Is scheduler running? (check logs)
2. Are there dirty episodes? (`SCARD rating_dirty_set`)
3. Check consolidation job logs for errors

**Manual Sync:**
```python
from app.services.rating_consolidation_job import run_rating_consolidation_job
await run_rating_consolidation_job(db, neo4j_service)
```

---

## Performance Considerations

- **Redis Cache**: 30-day TTL prevents unbounded growth
- **Batch Processing**: Consolidation processes 100 episodes per batch
- **Indexed Columns**: `rating_boost`, `exploration_bonus` indexed for fast retrieval
- **Composite Score**: Pre-computed during nightly job (no runtime calculation)
- **Thompson Sampling**: Probabilistic, minimal CPU overhead

---

## Future Enhancements

1. **Multi-User Ratings**: Currently single-user, expand to aggregate ratings from multiple users
2. **Rating Categories**: Allow rating on multiple dimensions (accuracy, helpfulness, clarity)
3. **Rating Explanations**: Capture "why" user rated (too generic, wrong fact, etc.)
4. **A/B Testing**: Compare retrieval quality with/without rating boost
5. **ML Tuning**: Learn optimal scoring weights per user
6. **Rating Trends**: Track rating changes over time
7. **Collaborative Filtering**: Recommend highly-rated memories from similar users

---

## Support

For issues or questions:
- GitHub: https://github.com/anthropics/sara
- Logs: `/home/david/jarvis/logs/rating_*.log`
- Database: `postgresql://sara:sara123@10.185.1.180:5432/sara_hub`
