# Ollama API Migration Notes

## Date: 2025-10-30

## Context
Attempted migration from OpenAI-compatible `/v1/chat/completions` endpoint to Ollama native `/api/chat` endpoint to resolve 1-minute connection timeout issues.

**NOTE: MIGRATION WAS REVERTED - User is changing the API**

## Changes Made (Now Reverted)

### 1. Base URL Configuration
**File**: `backend/app/main_simple.py` (line 114)
- Changed: `http://100.104.68.115:11434/v1` → `http://100.104.68.115:11434`
- Reverted back to include `/v1` suffix

### 2. SimpleLLMClient._stream_response()
**File**: `backend/app/main_simple.py` (lines 1055-1124)
- Changed endpoint from `/v1/chat/completions` to `/api/chat`
- Changed streaming format from OpenAI SSE to Ollama NDJSON
- Changed response parsing from `choices[0].delta` to `message`
- **Reverted**: Back to OpenAI format

### 3. SimpleLLMClient.chat()
**File**: `backend/app/main_simple.py` (lines 1126-1144)
- Changed endpoint to `/api/chat`
- Wrapped temperature in `options` object
- Changed response from `choices[0].message.content` to `message.content`
- **Reverted**: Back to OpenAI format

### 4. Notification Generation
**File**: `backend/app/main_simple.py` (line 2822)
- Changed endpoint to `/api/chat`
- Added `options` wrapper and `stream: false`
- Changed response parsing to `result["message"]["content"]`
- **Reverted**: Back to OpenAI format

### 5. Emotional Analysis
**File**: `backend/app/main_simple.py` (line 3198)
- Changed endpoint to `/api/chat`
- Added `options` wrapper and `stream: false`
- Changed response parsing to `result["message"]["content"]`
- **Reverted**: Back to OpenAI format

### 6. Settings Test Endpoint
**File**: `backend/app/main_simple.py` (line 7008)
- Changed endpoint to `/api/chat`
- Removed `max_tokens`, added `stream: false`
- **Reverted**: Back to OpenAI format

### 7. Core LLM Client
**File**: `backend/app/core/llm.py`
- Updated `chat_completion()` method to use `/api/chat`
- Added backward compatibility wrapper
- Auto-strips `/v1` suffix
- **Reverted**: Back to OpenAI format

### 8. Wyoming Voice Routes
**File**: `backend/app/routes/wyoming.py` (2 locations)
- Changed both voice chat endpoints to `/api/chat`
- Updated parameter structure and response parsing
- **Reverted**: Back to OpenAI format

### 9. Fitness Routes
**File**: `backend/app/routes/fitness.py` (line 977)
- Changed fitness chat endpoint to `/api/chat`
- Updated with tool calling support
- Changed response from `choices[0].message` to `message`
- **Reverted**: Back to OpenAI format

### 10. Docker Compose
**File**: `docker-compose.yml` (line 38)
- Changed: `OPENAI_BASE_URL=${OPENAI_BASE_URL-http://100.104.68.115:11434/v1}`
- To: `OPENAI_BASE_URL=${OPENAI_BASE_URL-http://100.104.68.115:11434}`
- **Reverted**: Back to include `/v1`

## Key Differences Between Endpoints

### OpenAI-Compatible (`/v1/chat/completions`)
```python
# Request
{
    "model": "gpt-oss:120b",
    "messages": [...],
    "temperature": 0.7,
    "max_tokens": 150
}

# Response
{
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "..."
        }
    }]
}

# Streaming: SSE format with "data: " prefix
```

### Ollama Native (`/api/chat`)
```python
# Request
{
    "model": "gpt-oss:120b",
    "messages": [...],
    "options": {
        "temperature": 0.7
    },
    "stream": false
}

# Response
{
    "message": {
        "role": "assistant",
        "content": "..."
    },
    "done": true
}

# Streaming: Pure NDJSON with "done" boolean
```

## Files Affected
1. `backend/app/main_simple.py` - 6 locations
2. `backend/app/core/llm.py` - 1 location
3. `backend/app/routes/wyoming.py` - 2 locations
4. `backend/app/routes/fitness.py` - 1 location
5. `docker-compose.yml` - 1 location

Total: 11 code changes across 5 files

## Deployment Notes
- Backend Docker image was rebuilt: `docker compose build --no-cache backend`
- Container was recreated and started successfully
- Backend serving requests normally after migration
- **All changes reverted**: System back to OpenAI-compatible endpoints

## Reason for Reversion
User stated: "im changing the api" - indicating API infrastructure changes are planned.
