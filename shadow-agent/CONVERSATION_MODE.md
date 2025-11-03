# Conversation Mode - Multi-Turn Dialog

## Overview

**Conversation Mode** enables natural multi-turn conversations without repeating the wake word "Sarah" for each exchange.

## How It Works

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. IDLE - Listening for wake word "Sarah"                  │
└─────────────────────────────────────────────────────────────┘
                          ↓
                    You say "Sarah"
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. CONVERSATION MODE ACTIVATED                               │
│    💬 Entering conversation mode                            │
│    🔴 Recording started (immediate)                         │
└─────────────────────────────────────────────────────────────┘
                          ↓
                 You say your message
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. PROCESSING & RESPONSE                                     │
│    📝 Transcript received                                    │
│    🤖 AI generates response                                  │
│    🔊 TTS playback                                          │
└─────────────────────────────────────────────────────────────┘
                          ↓
                   TTS finishes
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. WAITING FOR YOUR NEXT MESSAGE (No wake word needed!)    │
│    💬 Conversation mode active - waiting for response...    │
│    (Will return to wake word mode after 5s of silence)     │
└─────────────────────────────────────────────────────────────┘
                          ↓
               ┌──────────┴──────────┐
               │                     │
        You start speaking      5 seconds pass
               │                     │
               ↓                     ↓
    ┌──────────────────┐   ┌──────────────────┐
    │ Recording starts │   │ Exit conversation│
    │ (no wake word!)  │   │ Back to wake word│
    └──────────────────┘   └──────────────────┘
               │
               ↓
        Go back to step 3
        (Loop continues)
```

## Example Conversation

```
You: "Sarah"
     💬 Entering conversation mode
     🔴 Recording started

You: "Get ready, we have a lot of work to do today"
     📝 Transcript: Get ready, we have a lot of work to do today
     🤖 AI: I'm ready! What would you like to tackle first?
     🔊 TTS playback...
     ✅ TTS playback ended
     💬 Conversation mode active - waiting for your response...

You: [Just start talking - no "Sarah" needed!]
     "Let's start with reviewing the project timeline"
     🎤 Speech detected - starting recording (conversation mode)
     📝 Transcript: Let's start with reviewing the project timeline
     🤖 AI: Great, let me help you with that...
     🔊 TTS playback...
     ✅ TTS playback ended
     💬 Conversation mode active - waiting for your response...

You: [Continue the conversation]
     "What about the budget?"
     🎤 Speech detected - starting recording (conversation mode)
     ... continues ...

[If you stop talking for 5 seconds]
     ⏱️ Conversation timeout (5.0s) - returning to wake word mode
     🎧 Ready for next wake word...
```

## Key Features

### 1. **Wake Word Starts Conversation**
- Say "Sarah" once to enter conversation mode
- Immediately starts recording your first message
- No waiting, no delays

### 2. **Automatic Turn-Taking**
- After Sara responds (TTS ends), she automatically waits for your next message
- **No wake word needed for follow-up messages**
- Just start talking naturally

### 3. **Speech Detection**
- Uses VAD to detect when you start speaking
- Captures your full message from the beginning
- No first words lost

### 4. **5-Second Timeout**
- If you don't speak within 5 seconds, exits conversation mode
- Returns to wake word listening
- Prevents staying in recording mode indefinitely

### 5. **Multi-Turn Support**
- Unlimited conversation rounds
- Each response automatically sets up for the next turn
- Natural back-and-forth dialog

## States

### LISTENING_FOR_WAKE
- Default state
- Listening for "Sarah" wake word
- Not in conversation mode

### CONVERSATION MODE → RECORDING
- Wake word detected
- Enters conversation mode
- Immediately recording your message

### PROCESSING
- Transcribing speech
- Getting AI response
- Generating TTS

### SPEAKING
- Playing TTS response
- Echo suppression active

### WAITING_FOR_SPEECH (Conversation Mode Active)
- **New state!**
- After TTS ends in conversation mode
- Listening for you to start speaking
- No wake word required
- 5-second timeout to exit

## Configuration

### Conversation Timeout

Default: **5 seconds** of silence

Adjust in `audio_session.py`:
```python
self.conversation_mode_timeout = 5.0  # Change to preferred seconds
```

**Recommendations:**
- **3 seconds**: Fast-paced, less thinking time
- **5 seconds**: Balanced (default)
- **10 seconds**: Generous thinking time
- **15+ seconds**: May feel unresponsive

### Recording Timeout

Default: **10 seconds** max recording time

This is the maximum time for a single message:
```python
self.recording_timeout_seconds = 10
```

## Logs to Watch

### Entering Conversation Mode:
```
🎤 Wake word detected: sarah (score: 0.76)
💬 Entering conversation mode
🔴 Recording started (immediate after wake word)
```

### Staying in Conversation Mode:
```
✅ TTS playback ended
💬 Conversation mode active - waiting for your response...
   (Will return to wake word mode after 5.0s of silence)
🔄 State: speaking → waiting_for_speech
```

### Detecting Your Speech (No Wake Word):
```
🎤 Speech detected - starting recording (conversation mode)
🔄 State: waiting_for_speech → recording
```

### Exiting Conversation Mode (Timeout):
```
⏱️ Conversation timeout (5.0s) - returning to wake word mode
🔄 State: waiting_for_speech → listening_for_wake
🎧 Ready for next wake word...
```

## Benefits

### Natural Conversation Flow
```
❌ OLD:
You: "Sarah, what's the weather?"
Sara: "It's sunny today"
You: "Sarah, what about tomorrow?"    ← Awkward!
Sara: "Tomorrow will be cloudy"
You: "Sarah, should I bring an umbrella?" ← Repetitive!

✅ NEW:
You: "Sarah, what's the weather?"
Sara: "It's sunny today"
You: "What about tomorrow?"           ← Natural!
Sara: "Tomorrow will be cloudy"
You: "Should I bring an umbrella?"    ← Smooth!
```

### Faster Interactions
- No time wasted saying "Sarah" repeatedly
- Responses feel immediate
- More like talking to a person

### Context Retention
- Backend maintains conversation history
- Multi-turn questions build on each other
- Sara remembers what you just discussed

## Edge Cases

### What if I want to exit conversation mode immediately?
Just stop talking. After 5 seconds of silence, it automatically exits.

### What if I accidentally trigger conversation mode?
If you don't say anything after "Sarah", it will timeout and return to wake word mode.

### What if TTS echo triggers speech detection?
- 2-second echo suppression prevents this
- VAD requires actual speech patterns
- Pre-roll buffer cleared after TTS

### Can I say "Sarah" during conversation mode?
Yes! If you say "Sarah" during conversation mode:
- It will be transcribed as part of your message
- Won't re-trigger wake word (suppressed during recording/speaking)
- Continues conversation normally

### What if I have a long pause mid-sentence?
- Recording timeout is 10 seconds (generous)
- VAD detects silence at end of sentence (600ms)
- If you pause 600ms+ mid-sentence, recording may stop early
- Solution: Speak more continuously or adjust `min_silence_duration_ms`

## Troubleshooting

### "Conversation mode exits too quickly"
Increase timeout:
```python
self.conversation_mode_timeout = 10.0  # Instead of 5.0
```

### "Conversation mode stays active too long"
Decrease timeout:
```python
self.conversation_mode_timeout = 3.0  # Instead of 5.0
```

### "Not detecting my speech in conversation mode"
- Check microphone volume
- Speak louder/clearer
- Adjust VAD aggressiveness (currently 3)
- Check logs for "Speech detected" message

### "Still requiring wake word after TTS"
- Verify "💬 Conversation mode active" appears in logs
- Check for errors in TTS end callback
- Ensure `in_conversation_mode = True` is set

## Comparison: Before vs After

| Feature | Without Conversation Mode | With Conversation Mode |
|---------|--------------------------|------------------------|
| Wake word frequency | Every message | Only first message |
| User experience | Repetitive | Natural |
| Speed | Slower (extra wake words) | Faster |
| Context retention | ✅ Yes (backend) | ✅ Yes (backend) |
| Timeout behavior | N/A | 5s silence → exit |
| Multi-turn dialog | Possible but tedious | Seamless |

## Technical Implementation

### State Machine Addition

New state: `WAITING_FOR_SPEECH`
- Active only in conversation mode
- Listens for speech via VAD
- Times out after 5 seconds
- No wake word processing

### Conversation Mode Flag

```python
self.in_conversation_mode = False  # Default
```

Set to `True` when wake word detected
Set to `False` when:
- Conversation timeout (5s)
- Recording timeout (10s)
- Error occurs
- User exits (future feature)

### Speech Detection in WAITING_FOR_SPEECH

```python
vad_result = self.vad.process_chunk(audio_chunk)
if vad_result['is_speech'] or vad_result['speech_started']:
    # User started speaking!
    self._set_state(VoiceAgentState.RECORDING)
```

### TTS End Behavior

```python
if self.in_conversation_mode:
    # Stay in conversation
    self._set_state(VoiceAgentState.WAITING_FOR_SPEECH)
    self.waiting_for_speech_start_time = time.time()
else:
    # Return to wake word
    self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
```

## Files Modified

- `shadow-agent/src/audio_session.py`
  - Added `VoiceAgentState.WAITING_FOR_SPEECH` state
  - Added `in_conversation_mode` flag
  - Added `conversation_mode_timeout` setting
  - Added speech detection in audio callback
  - Modified TTS end callback for conversation mode
  - Enhanced wake word detection to enter conversation mode

## Version

**v2.3** - Conversation Mode with Multi-Turn Dialog
- Previous: v2.2 - TTS echo prevention
- Previous: v2.1 - Immediate recording + state fixes
- Previous: v2.0 - Conversational history + fast STT
