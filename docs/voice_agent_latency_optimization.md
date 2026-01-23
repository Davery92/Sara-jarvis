# Voice Agent Latency Optimization

**Date:** 2025-01-19
**Files Modified:**
- `david@10.185.1.155:/home/david/Projects/Wake Word/files/sara_voice_agent.py` (v12 → v13)
- `david@10.185.1.155:/home/david/Projects/Wake Word/files/taskbar.py` (v1 → v2)

## Problem

Voice interactions had ~7-8 second latency from end of speech to start of audio playback.

### Measured Latency Breakdown

| Stage | Component | Latency | Notes |
|-------|-----------|---------|-------|
| 1 | Silence timeout | 2.0s | Fixed wait after speech ends |
| 2 | STT (Whisper) | 39ms | distil-small.en is fast |
| 3 | Chat (LLM) | 4.6s | gpt-oss:20b has CoT reasoning overhead |
| 4 | TTS (Kokoro) | 380ms | af_heart voice |
| 5 | Audio transfer | ~200ms | WebSocket chunked |
| 6 | Playback ack | 500ms | SILENCE_THRESHOLD in taskbar.py |

**Key Finding:** STT and TTS are NOT bottlenecks. The LLM reasoning tokens before content are the main issue.

## Solution

Two-phase optimization:

### Phase 1: Config Tuning

Reduced timeouts that were overly conservative:

| Parameter | Before | After | File |
|-----------|--------|-------|------|
| `silence_timeout` | 2.0s | 1.2s | sara_voice_agent.py |
| `followup_timeout` | 10.0s | 5.0s | sara_voice_agent.py |
| `SILENCE_THRESHOLD` | 0.5s | 0.25s | taskbar.py |

**Savings: ~1.3s**

### Phase 2: Streaming TTS Pipeline

Instead of waiting for the full LLM response before starting TTS, we now:

1. Stream LLM response token-by-token
2. Buffer until a complete sentence (ends with `.` `!` `?`)
3. Send that sentence to TTS immediately
4. Stream audio to Windows while LLM continues generating
5. Repeat for subsequent sentences

```
OLD FLOW:
[LLM generates full response 4.6s] → [TTS full response 380ms] → [Play]

NEW FLOW:
[LLM: sentence 1] → [TTS sentence 1] → [Play]
     [LLM: sentence 2] → [TTS sentence 2] → [Play]
          [LLM: sentence 3] → ...
```

**Savings: ~2-3s** (audio starts on first sentence, not after full response)

## Code Changes

### sara_voice_agent.py

**New `chat_streaming()` method in Sara class:**
- Streams SSE response from backend
- Yields complete sentences as they arrive
- Uses regex to detect sentence boundaries

**New `do_streaming_response()` method in Agent class:**
- Calls `chat_streaming()` generator
- For each sentence: generate TTS → stream to Windows
- No waiting between sentences

**New CLI flag:**
- `--no-streaming`: Disable streaming, use original blocking mode (for debugging)

### taskbar.py

- Reduced `SILENCE_THRESHOLD` from 0.5s to 0.25s
- Updated version banner to v2

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Total latency | ~7-8s | ~3-4s |
| Time to first audio | ~7s | ~2-3s |

## Usage

**Start voice agent (streaming enabled by default):**
```bash
python3 sara_voice_agent.py --use-sara --sara-token=<token>
```

**Start with debug output:**
```bash
python3 sara_voice_agent.py --use-sara --sara-token=<token> --debug
```

**Disable streaming (fallback to v12 behavior):**
```bash
python3 sara_voice_agent.py --use-sara --sara-token=<token> --no-streaming
```

## Rollback

If issues occur, the `--no-streaming` flag provides immediate fallback. For full rollback, restore the original timeout values:

```python
# sara_voice_agent.py Config class
self.silence_timeout = 2.0   # was 1.2
self.followup_timeout = 10.0 # was 5.0

# taskbar.py audio_playback_thread
SILENCE_THRESHOLD = 0.5  # was 0.25
```

## Future Optimizations

If further latency reduction is needed:

1. **Direct tool execution**: Skip LLM for simple commands like "set a timer for 5 minutes" using regex pattern matching
2. **Use ministral-3**: Slightly faster than gpt-oss:20b (3.8s vs 4.6s)
3. **Speculative TTS**: Start generating TTS for common response prefixes before LLM finishes
