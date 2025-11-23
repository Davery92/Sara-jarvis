# Sara Enhancement API Documentation

**Version:** 1.0.0
**Last Updated:** 2025-11-14

This document covers all new API endpoints added in Phases 1-4 of the Sara Enhancement project.

---

## Table of Contents

1. [Emotion Analysis APIs](#emotion-analysis-apis)
2. [Intelligence Reports APIs](#intelligence-reports-apis)
3. [Goals APIs](#goals-apis)
4. [Proactive Suggestions APIs](#proactive-suggestions-apis)
5. [Daily Briefings APIs](#daily-briefings-apis)
6. [Event Bus APIs](#event-bus-apis)
7. [Context APIs](#context-apis)

---

## Emotion Analysis APIs

Base Path: `/api/emotions`

### GET /api/emotions/summary

Get emotion summary for a date range.

**Query Parameters:**
- `days` (int, optional): Number of days to analyze. Default: 7

**Response:**
```json
{
  "period_days": 7,
  "total_episodes": 42,
  "average_sentiment": 0.65,
  "sentiment_distribution": {
    "positive": 28,
    "neutral": 10,
    "negative": 4
  },
  "top_emotions": [
    {"emotion": "joy", "count": 15},
    {"emotion": "calm", "count": 12},
    {"emotion": "excited", "count": 8}
  ],
  "average_intensity": 0.72
}
```

### GET /api/emotions/trends

Get daily emotion trends.

**Query Parameters:**
- `days` (int, optional): Number of days. Default: 30

**Response:**
```json
{
  "trends": [
    {
      "date": "2025-11-14",
      "avg_sentiment": 0.7,
      "avg_intensity": 0.65,
      "episode_count": 8,
      "dominant_emotion": "joy"
    }
  ]
}
```

### GET /api/emotions/shifts

Detect significant mood shifts.

**Query Parameters:**
- `days` (int, optional): Number of days. Default: 30
- `threshold` (float, optional): Shift threshold. Default: 0.3

**Response:**
```json
{
  "shifts": [
    {
      "date": "2025-11-10",
      "before_sentiment": 0.3,
      "after_sentiment": 0.8,
      "magnitude": 0.5,
      "direction": "positive"
    }
  ]
}
```

### GET /api/emotions/patterns

Get detected emotion patterns.

**Query Parameters:**
- `days` (int, optional): Number of days. Default: 30

**Response:**
```json
{
  "patterns": [
    {
      "type": "weekly_pattern",
      "description": "Lower mood on Mondays",
      "confidence": 0.75,
      "occurrences": 4
    }
  ]
}
```

### GET /api/emotions/distribution

Get emotion type distribution.

**Query Parameters:**
- `days` (int, optional): Number of days. Default: 30

**Response:**
```json
{
  "distribution": {
    "joy": 25,
    "calm": 18,
    "excited": 12,
    "anxious": 8,
    "sad": 3
  },
  "total_episodes": 66
}
```

---

## Intelligence Reports APIs

Base Path: `/api/reports`

### GET /api/reports/weekly/{week_start}

Get or generate weekly intelligence report.

**Path Parameters:**
- `week_start` (date): Monday of the week (YYYY-MM-DD)

**Response:**
```json
{
  "id": 123,
  "report_type": "weekly",
  "period_start": "2025-11-11",
  "period_end": "2025-11-17",
  "summary": "This week you completed 5 workouts and averaged 7.5h of sleep",
  "insights": [
    "Strong workout consistency this week",
    "Sleep quality improved by 15%",
    "Nutrition tracking remained consistent"
  ],
  "patterns": [
    {
      "type": "workout_consistency",
      "description": "Strong workout consistency: 5 sessions",
      "severity": "positive"
    }
  ],
  "recommendations": [
    "Continue current workout schedule",
    "Consider increasing protein intake"
  ],
  "report_data": {
    "workouts": {"count": 5, "total_minutes": 250, "avg_duration": 50},
    "recovery": {"avg_sleep": 7.5, "avg_hrv": 65, "avg_soreness": 3.2},
    "nutrition": {"meal_count": 28},
    "notes": {"count": 12},
    "calendar": {"event_count": 8}
  },
  "generation_time_ms": 2450,
  "created_at": "2025-11-17T21:00:00Z",
  "delivered_at": "2025-11-17T21:00:05Z"
}
```

### GET /api/reports/monthly/{month_start}

Get or generate monthly intelligence report.

**Path Parameters:**
- `month_start` (date): First day of month (YYYY-MM-DD)

**Response:** Same structure as weekly report

### GET /api/reports/quarterly/{quarter_start}

Get or generate quarterly intelligence report.

**Path Parameters:**
- `quarter_start` (date): First day of quarter (YYYY-MM-DD)

**Response:** Same structure as weekly report

### POST /api/reports/generate

Manually trigger report generation.

**Request Body:**
```json
{
  "report_type": "weekly",
  "period_start": "2025-11-11"
}
```

**Response:** Same structure as GET endpoints

### GET /api/reports/latest/{report_type}

Get the latest report of a given type.

**Path Parameters:**
- `report_type` (string): weekly, monthly, or quarterly

**Response:** Same structure as GET endpoints, or null if no report exists

---

## Goals APIs

**Note:** Goal APIs are implemented in the service layer but routes need to be created.

### Goal Service Methods

```python
from app.services.goal_manager import get_goal_manager

# Create goal
goal = Goal(
    user_id="user123",
    title="Reach 185 lbs",
    goal_type="fitness",
    target_value=185.0,
    current_value=190.0,
    unit="lbs",
    target_date=date(2025, 12, 31),
    priority=8
)
goal_id = await goal_manager.create_goal(goal)

# List goals
goals = await goal_manager.list_goals(
    user_id="user123",
    status="active",
    goal_type="fitness"
)

# Add progress
progress = GoalProgress(
    goal_id=goal_id,
    value=188.5,
    notes="Morning weigh-in",
    source="manual"
)
await goal_manager.add_progress(progress)

# Get percentage
percentage = await goal_manager.calculate_percentage(goal_id)

# Get progress history
history = await goal_manager.get_progress_history(goal_id, limit=30)
```

---

## Proactive Suggestions APIs

**Note:** Suggestion APIs are implemented in the service layer but routes need to be created.

### Suggestion Service Methods

```python
from app.services.proactive_intelligence import get_proactive_intelligence

# Analyze and generate suggestions
suggestions = await proactive_engine.analyze_and_suggest(user_id="user123")

# Get active suggestions
active = await proactive_engine.get_active_suggestions(user_id="user123")

# Accept suggestion
await proactive_engine.accept_suggestion(
    suggestion_id=456,
    user_id="user123"
)

# Dismiss suggestion
await proactive_engine.dismiss_suggestion(
    suggestion_id=457,
    user_id="user123"
)
```

**Suggestion Object:**
```json
{
  "id": 456,
  "user_id": "user123",
  "suggestion_type": "meal",
  "title": "Time for lunch?",
  "description": "You usually eat around 13:00. Want to log a meal?",
  "action_data": {"type": "log_meal", "suggested_time": 13},
  "confidence": 0.7,
  "priority": 6,
  "status": "pending",
  "expires_at": "2025-11-14T14:00:00Z",
  "created_at": "2025-11-14T12:30:00Z"
}
```

---

## Daily Briefings APIs

**Note:** Briefing APIs are implemented in the service layer but routes need to be created.

### Briefing Service Methods

```python
from app.services.daily_briefing import get_daily_briefing_service

# Generate morning briefing
morning = await briefing_service.generate_morning_briefing(
    user_id="user123",
    briefing_date=date.today()
)

# Generate evening briefing
evening = await briefing_service.generate_evening_briefing(
    user_id="user123",
    briefing_date=date.today()
)

# Mark as delivered
await briefing_service.mark_as_delivered(
    briefing_id=789,
    delivery_method="push"
)
```

**Briefing Object:**
```json
{
  "id": 789,
  "user_id": "user123",
  "briefing_type": "morning",
  "briefing_date": "2025-11-14",
  "content": "# 🌅 Good Morning!\n\n## 💪 Recovery Status\n- Sleep: 7.5h\n- HRV: 65\n- Soreness: 3/10\n\n**Today's Training:** You're recovered - ready for training!\n\n## 📅 Today's Schedule\n- 09:00 AM: Team Meeting\n- 02:00 PM: Workout\n\n## 🎯 Active Goals\n- Reach 185 lbs: 75%\n- Workout 5x/week: 80%\n\nHave a great day! 🚀",
  "data": {
    "recovery": {"sleep_hours": 7.5, "hrv": 65, "soreness_level": 3},
    "schedule": [...],
    "goals": [...],
    "workout_recommendation": "You're recovered - ready for training!"
  },
  "delivered": true,
  "delivered_at": "2025-11-14T07:00:05Z",
  "delivery_method": "push",
  "read": false,
  "generation_time_ms": 1850,
  "created_at": "2025-11-14T07:00:00Z"
}
```

---

## Event Bus APIs

The Event Bus operates asynchronously through service integration.

### Event Types

```python
class EventType(Enum):
    # Workout events
    WORKOUT_LOGGED = "workout.logged"
    WORKOUT_STARTED = "workout.started"
    WORKOUT_COMPLETED = "workout.completed"

    # Food events
    FOOD_LOGGED = "food.logged"

    # Timer events
    TIMER_STARTED = "timer.started"
    TIMER_COMPLETED = "timer.completed"

    # Reminder events
    REMINDER_CREATED = "reminder.created"
    REMINDER_COMPLETED = "reminder.completed"

    # Note events
    NOTE_CREATED = "note.created"
    NOTE_UPDATED = "note.updated"

    # Goal events
    GOAL_CREATED = "goal.created"
    GOAL_COMPLETED = "goal.completed"
    GOAL_MILESTONE_REACHED = "goal.milestone_reached"

    # Recovery events
    RECOVERY_LOGGED = "recovery.logged"

    # Calendar events
    CALENDAR_EVENT_CREATED = "calendar_event.created"
    CALENDAR_EVENT_UPDATED = "calendar_event.updated"

    # Context events
    CONTEXT_MODE_CHANGED = "context.mode_changed"

    # Memory events
    MEMORY_RETRIEVED = "memory.retrieved"
    MEMORY_CONSOLIDATED = "memory.consolidated"
```

### Publishing Events

```python
from app.services.event_bus import get_event_bus, Event, EventType

event_bus = get_event_bus()

# Publish an event
await event_bus.publish(Event(
    event_type=EventType.WORKOUT_LOGGED,
    user_id="user123",
    payload={
        "workout_id": 456,
        "duration": 3600,
        "exercises": ["bench_press", "squats"]
    },
    source="workout_log_api"
))
```

### Subscribing to Events

```python
from app.services.event_bus import get_event_bus, EventType

event_bus = get_event_bus()

@event_bus.on(EventType.WORKOUT_LOGGED)
async def handle_workout_logged(event: Event):
    logger.info(f"Workout logged: {event.payload}")
    # Update goal progress, trigger suggestions, etc.
```

---

## Context APIs

**Note:** Context APIs are implemented in the service layer.

### Context Builder

```python
from app.services.context_builder import build_context_packet

# Build context packet
context = await build_context_packet(
    user_id="user123",
    db=db,
    redis_client=redis_client,
    include_tools=True
)

# Convert to LLM context string
llm_context = context.to_llm_context()
```

**Context Packet Structure:**
```json
{
  "user_id": "user123",
  "user_state": {
    "active_goals": ["Reach 185 lbs", "Workout 5x/week"],
    "current_mode": "fitness",
    "preferences": {...}
  },
  "memory_context": {
    "recent_episodes": [...],
    "relevant_notes": [...],
    "importance_summary": {...}
  },
  "recent_actions": [
    {"action": "workout_logged", "timestamp": "2025-11-14T10:00:00Z"},
    {"action": "meal_logged", "timestamp": "2025-11-14T12:30:00Z"}
  ],
  "ephemeral_context": {
    "active_timers": [...],
    "pending_reminders": [...]
  },
  "tools_available": ["log_workout", "log_meal", "create_note", ...]
}
```

### LifeOS Context

```python
from app.services.lifeos_context import get_lifeos_context

# Aggregate user life context
lifeos = get_lifeos_context(db)
context = await lifeos.aggregate_context(user_id="user123")
```

**LifeOS Context Structure:**
```json
{
  "active_goals": [...],
  "current_habits": [...],
  "current_projects": [...],
  "health_status": {
    "sleep_quality": 0.85,
    "recovery_score": 0.78,
    "activity_level": 0.82
  },
  "focus_mode": "fitness",
  "stress_level": 3,
  "mood_profile": {
    "current_sentiment": 0.75,
    "dominant_emotion": "calm",
    "intensity": 0.65
  },
  "energy_level": 7
}
```

---

## HYDRA Retrieval APIs

**Note:** HYDRA is implemented in the service layer.

### HYDRA Retrieval

```python
from app.services.hydra_retrieval import get_hydra_retrieval
from app.services.bge_reranker import get_reranker

# Initialize
reranker = await get_reranker()
hydra = get_hydra_retrieval(db, redis_client, reranker)

# Retrieve and rank knowledge
results = await hydra.retrieve(
    query="What was my workout yesterday?",
    user_id="user123",
    sources=["episodes", "notes", "documents"],
    top_k=50,
    rerank_top_k=10
)
```

**Retrieval Result:**
```json
{
  "source": "episodes",
  "id": "ep_12345",
  "content": "Logged a great chest and triceps workout...",
  "score": 0.85,
  "rerank_score": 0.92,
  "metadata": {
    "importance": 0.8,
    "created_at": "2025-11-13T17:30:00Z",
    "emotional_tone": "positive",
    "topics": ["workout", "chest", "triceps"]
  },
  "timestamp": "2025-11-13T17:30:00Z"
}
```

---

## Authentication

All APIs require authentication via JWT token in HTTP-only cookie or Authorization header.

**Cookie Authentication:**
- Cookie name: `access_token`
- Domain: `.sara.avery.cloud`
- Secure: true
- HttpOnly: true

**Header Authentication:**
```
Authorization: Bearer <jwt_token>
```

**Getting Current User:**
```python
from app.auth import get_current_user
from fastapi import Depends

@router.get("/example")
async def example_endpoint(user=Depends(get_current_user)):
    user_id = user.id
    # ...
```

---

## Rate Limiting

**Default Limits:**
- Standard endpoints: 100 requests/minute
- Heavy operations (reports, HYDRA): 10 requests/minute
- Briefing generation: 5 requests/minute

**Headers:**
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Time when limit resets (Unix timestamp)

---

## Error Responses

**Standard Error Format:**
```json
{
  "detail": "Error message describing what went wrong",
  "error_code": "SPECIFIC_ERROR_CODE",
  "timestamp": "2025-11-14T12:30:00Z"
}
```

**Common HTTP Status Codes:**
- `200 OK`: Success
- `201 Created`: Resource created
- `400 Bad Request`: Invalid input
- `401 Unauthorized`: Authentication required
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Resource not found
- `422 Unprocessable Entity`: Validation error
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Server error

---

## Performance Notes

### Caching

**Redis Cache TTLs:**
- Context packets: 5 minutes
- HYDRA retrieval: 1 hour
- Goal calculations: 10 minutes
- Pattern analysis: 30 minutes

**Cache Invalidation:**
- Automatic on relevant events via Event Bus
- Manual via cache key deletion

### Response Times

**Target Performance:**
- Emotion analysis: < 100ms
- Context building: < 200ms
- HYDRA retrieval (cached): < 200ms
- HYDRA retrieval (uncached): < 1s
- Report generation: < 5s
- Briefing generation: < 2s
- Goal operations: < 100ms

---

## Webhook Support (Future)

Planned support for webhooks to notify external systems of events:

- `goal.completed`
- `report.generated`
- `briefing.delivered`
- `pattern.detected`
- `suggestion.created`

---

## SDK Support (Future)

Planned official SDKs:
- Python SDK
- TypeScript SDK
- Swift SDK (iOS)

---

## Changelog

### Version 1.0.0 (2025-11-14)
- Initial release
- Emotion Analysis APIs
- Intelligence Reports APIs
- Goal Management (service layer)
- Proactive Suggestions (service layer)
- Daily Briefings (service layer)
- Event Bus infrastructure
- Context Builder
- HYDRA Retrieval
- BGE Reranking

---

## Support

For API support and questions:
- Documentation: https://docs.sara.avery.cloud
- Issues: https://github.com/sara/issues
- Email: support@sara.avery.cloud

---

**Last Updated:** 2025-11-14
**API Version:** 1.0.0
