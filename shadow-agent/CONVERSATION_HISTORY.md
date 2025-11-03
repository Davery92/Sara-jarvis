# Conversation History - 10 Turn Sliding Window

## Overview

The backend maintains **10 turns** (user messages) of conversation history per session. This provides context for the AI while preventing token overflow and keeping conversations focused.

## How It Works

### Sliding Window Mechanism

```
Turn 1:  User: "Hello"          }
         Sara: "Hi there!"       } ← 2 messages (1 turn)

Turn 2:  User: "How are you?"   }
         Sara: "I'm great!"      } ← 4 messages (2 turns)

... continues up to 10 turns (20 messages) ...

Turn 11: User: "New message"    }
         Sara: "Response"        } ← Turn 1 gets removed
                                    Now have turns 2-11 (20 messages)

Turn 12: User: "Another message"}
         Sara: "Response"        } ← Turn 2 gets removed
                                    Now have turns 3-12 (20 messages)
```

### Key Points

- **Maximum**: 10 user messages (turns)
- **Total messages**: 20 (10 user + 10 assistant)
- **Automatic trimming**: Oldest turn drops when turn 11 starts
- **Per session**: Each computer (hostname) has its own history
- **Persistent**: Lasts until backend restart

## Response Metadata

Every response includes tracking information:

```json
{
  "response": "AI response text",
  "metadata": {
    "model": "gpt-oss:120b",
    "session_id": "DESKTOP-ABC123",
    "history_length": 14,        // Total messages in history
    "turn_count": 7,             // Number of user turns
    "max_turns": 10              // Maximum turns before trimming
  }
}
```

### Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `history_length` | int | Total messages (user + assistant) |
| `turn_count` | int | Number of user messages |
| `max_turns` | int | Maximum turns (always 10) |
| `session_id` | string | Computer hostname |
| `model` | string | LLM model used |

## Examples

### Example 1: Fresh Conversation

```json
// Turn 1
{
  "message": "What's the weather?"
}
→ Response metadata:
{
  "history_length": 2,   // 1 user + 1 assistant = 2 messages
  "turn_count": 1,       // First turn
  "max_turns": 10
}

// Turn 2
{
  "message": "What about tomorrow?"
}
→ Response metadata:
{
  "history_length": 4,   // 2 user + 2 assistant = 4 messages
  "turn_count": 2,       // Second turn
  "max_turns": 10
}
```

### Example 2: Reaching Limit

```json
// Turn 10
{
  "message": "Tenth message"
}
→ Response metadata:
{
  "history_length": 20,  // 10 user + 10 assistant = 20 messages
  "turn_count": 10,      // At limit
  "max_turns": 10
}

// Turn 11 - Trimming occurs!
{
  "message": "Eleventh message"
}
→ Backend logs: "Trimmed conversation history to last 10 turns (20 messages)"
→ Response metadata:
{
  "history_length": 20,  // Still 20 (oldest removed)
  "turn_count": 10,      // Still 10 (sliding window)
  "max_turns": 10
}
```

## Benefits

### 1. Context Retention
- Recent conversation context maintained
- AI remembers last 10 exchanges
- Natural conversation flow

### 2. Token Efficiency
- Prevents context overflow
- Keeps token count manageable
- Faster responses (less context to process)

### 3. Focused Conversations
- AI focuses on recent topics
- Less confusion from old context
- More relevant responses

### 4. Automatic Management
- No manual cleanup needed
- Handles long conversations gracefully
- Works transparently

## Behavior Patterns

### Short Conversations (< 10 turns)
```
Turns 1-10: All history retained
             Context grows with each turn
             Nothing is trimmed
```

### Long Conversations (> 10 turns)
```
Turn 11+: Sliding window active
          Oldest turn drops with each new turn
          Always maintains last 10 turns
```

### Conversation Mode Integration
```
1. Say "Sarah" → Enter conversation mode
2. Multiple turns without wake word
3. Each turn adds to history
4. After 10 turns, sliding window activates
5. 5-second silence timeout → exits conversation mode
   (History is preserved! Can re-enter with "Sarah")
```

## Technical Details

### Session Storage

```python
# In-memory storage (per backend instance)
conversation_sessions = {
    "DESKTOP-ABC123": [
        {"role": "user", "content": "Message 1"},
        {"role": "assistant", "content": "Response 1"},
        {"role": "user", "content": "Message 2"},
        {"role": "assistant", "content": "Response 2"},
        # ... up to 20 messages (10 turns)
    ]
}
```

### Trimming Logic

```python
# After storing new message pair
if len(session_history) > 20:
    # Keep only last 20 messages (10 turns)
    session_history = session_history[-20:]
    conversation_sessions[request.session_id] = session_history
    logger.debug("Trimmed conversation history to last 10 turns")
```

### Turn Counting

```python
# Count user messages only
turn_count = len([msg for msg in session_history if msg["role"] == "user"])
```

## Configuration

### Change Maximum Turns

Edit `backend/app/routes/wyoming.py`:

```python
# Current: 10 turns (20 messages)
if len(session_history) > 20:
    session_history = session_history[-20:]

# For 15 turns (30 messages):
if len(session_history) > 30:
    session_history = session_history[-30:]

# For 5 turns (10 messages):
if len(session_history) > 10:
    session_history = session_history[-10:]
```

**Recommendations:**
- **5 turns**: Short-term memory, very focused
- **10 turns**: Balanced (default)
- **20 turns**: Extended memory, may slow responses
- **50+ turns**: Not recommended (token overflow)

## Monitoring

### Backend Logs

```bash
# Watch for trimming events
docker compose logs -f backend | grep "Trimmed conversation"

# Example output:
INFO:app.routes.wyoming:Voice agent chat [DESKTOP-ABC]: Message 11
DEBUG:app.routes.wyoming:Trimmed conversation history to last 10 turns (20 messages)
```

### Client Side

The Windows voice agent doesn't track turns directly, but you can infer from conversation flow:

```
After 10 exchanges with Sara:
- Next message will trigger trimming
- Oldest context is dropped
- Conversation continues normally
```

## Edge Cases

### What if I clear session?

```bash
curl -X POST http://10.185.1.180:8000/voice-agent/clear-session \
  -H "Content-Type: application/json" \
  -d '{"session_id": "DESKTOP-ABC123"}'
```

Result:
- All history deleted
- Next message starts fresh (turn 1)
- Conversation mode can still activate normally

### What if backend restarts?

- All conversation history is lost (in-memory storage)
- Next message starts fresh session
- This is expected behavior

### What if I reach 10 turns mid-conversation?

- Trimming happens transparently
- You won't notice any difference
- AI may "forget" very early context
- Recent context (last 10 turns) is preserved

### What if conversation mode times out?

- History is preserved
- Re-enter with "Sarah"
- Conversation continues where you left off
- Turn count continues incrementing

## Performance Impact

### Memory Usage

Per session:
- **Average**: ~5-10 KB per session
- **Maximum**: ~20 KB at 10 turns (depends on message length)
- **Total**: Minimal for typical use

### Response Time

- **Turns 1-5**: Fast (small context)
- **Turns 6-10**: Slightly slower (more context)
- **Turns 11+**: Constant (sliding window keeps context stable)

### LLM Token Usage

Approximate per turn:
- **System prompt**: ~50 tokens
- **User message**: ~10-50 tokens
- **Assistant response**: ~50-150 tokens
- **History (10 turns)**: ~1000-2000 tokens
- **Total**: ~1100-2250 tokens per request

With 10-turn limit, stays well within GPT-3.5/4 context limits (4K-8K tokens).

## Best Practices

### For Users

1. **Long conversations**: Accept that very old context will be dropped
2. **Important info**: Repeat key details if needed after 10+ turns
3. **New topic**: Consider clearing session or using new wake word

### For Developers

1. **Token limits**: 10 turns is safe for most models
2. **Memory**: In-memory storage is fine for single-user deployments
3. **Production**: Consider Redis for persistent storage
4. **Monitoring**: Watch for trimming logs in high-usage scenarios

## Future Enhancements

Potential improvements:

1. **Persistent storage**: Redis or database for history
2. **Summary compression**: Summarize old turns instead of dropping
3. **Importance scoring**: Keep important turns longer
4. **User control**: "Remember this" command to pin messages
5. **Memory export**: Save conversation history to notes

## Related Features

- **Conversation Mode**: Multi-turn without wake word (CONVERSATION_MODE.md)
- **Fast STT**: Low-latency transcription (OPTIMIZATION_NOTES.md)
- **Session Management**: Clear history endpoint (BUG_FIXES.md)

## Version

**v2.3** - 10 Turn Sliding Window
- Previous: v2.2 - TTS echo prevention
- Previous: v2.1 - Immediate recording
- Previous: v2.0 - Conversational history (5 turns)
