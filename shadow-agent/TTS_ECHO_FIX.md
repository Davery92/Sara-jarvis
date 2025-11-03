# TTS Echo Wake Word Detection Fix

## Problem: Inconsistent Wake Word Response After TTS

### Symptoms
- Sometimes after TTS playback, you can say "Sarah" and it works
- Other times after TTS playback, it immediately triggers without you saying anything
- This creates inconsistent behavior where the agent seems to randomly "allow" continuation

### Root Cause: TTS Echo Detection

Looking at the logs:

**Case 1 - Normal (3 second gap):**
```
08:07:18,466 - TTS playback ended
08:07:21,558 - Wake word detected (score: 0.68)  ← 3 seconds later (you said it)
```

**Case 2 - TTS Echo (0.8 second gap):**
```
08:07:48,489 - TTS playback ended
08:07:49,317 - Wake word detected (score: 0.68)  ← 0.8 seconds later (TTS echo!)
```

**What's happening:**
1. TTS finishes playing Sara's voice saying something
2. There's still audio reverberating in the room/microphone
3. The tail end of "Sara" saying words that sound like "sarah" triggers detection
4. Wake word detector picks this up within 0.8 seconds
5. You get an immediate recording start without saying "sarah"

**Why it seems random:**
- If Sara's TTS response ends with words like "Sara," "share," or similar sounds → triggers
- If Sara's TTS response ends with different sounds → doesn't trigger
- This makes it seem like the agent randomly decides to listen or not

## Solution: Wake Word Suppression Window

Implemented a 2-second suppression window after TTS playback:

```python
# After TTS ends:
1. Suppress wake word detection for 2 seconds
2. Stop echo suppression (after 0.5s delay)
3. Clear pre-roll buffer
4. Reset wake word detector
5. Return to listening state (but still suppressed)
6. Wait remaining 1.5 seconds
7. Log "Ready for next wake word"
```

### Code Changes

**Added suppression timestamp:**
```python
self.suppress_wake_word_until = 0  # Timestamp to suppress wake word detection
```

**Check suppression in audio callback:**
```python
if self.state == VoiceAgentState.LISTENING_FOR_WAKE:
    # Check if wake word detection is temporarily suppressed
    current_time = time.time()
    if current_time < self.suppress_wake_word_until:
        return  # Skip wake word processing during suppression
```

**Set suppression after TTS:**
```python
def _on_tts_end(self):
    # Suppress wake word detection for 2 seconds
    self.suppress_wake_word_until = time.time() + 2.0
    logger.debug("🔇 Suppressing wake word detection for 2 seconds")

    # ... rest of cleanup ...

    time.sleep(1.5)  # Wait out most of suppression period
    logger.info("🎧 Ready for next wake word...")
```

## Expected Behavior After Fix

### Timeline After TTS Playback:

```
00:00 - TTS playback ends
        ✅ TTS playback ended

00:00 - Suppression starts (2 second window)
        🔇 Suppressing wake word detection for 2 seconds

00:00-00:50 - Echo settling period
              Audio still reverberating
              Wake word detection BLOCKED

00:50 - Echo suppressor stops
        Pre-roll buffer cleared
        Wake word detector reset

00:50-02:00 - Continued suppression
              Any remaining TTS echo BLOCKED
              State = listening_for_wake (but suppressed)

02:00 - Suppression ends
        🎧 Ready for next wake word...
        Now truly ready for user's wake word
```

## Testing

### Before Fix:
```
Round 1: "Sarah" → Response → [Random] → Maybe works
Round 2: "Sarah" → Response → [Random] → Maybe works
Round 3: "Sarah" → Response → [Random] → Maybe immediate trigger
```

### After Fix:
```
Round 1: "Sarah" → Response → Always requires "Sarah"
Round 2: "Sarah" → Response → Always requires "Sarah"
Round 3: "Sarah" → Response → Always requires "Sarah"
Round N: Consistent behavior every time
```

### What to Look For:

**Good logs (after fix):**
```
✅ TTS playback ended
🔇 Suppressing wake word detection for 2 seconds
🔄 State: speaking → listening_for_wake
🎧 Ready for next wake word...
[2+ second gap]
🎤 Wake word detected: sarah (score: 0.68)  ← You said it
```

**Bad logs (TTS echo - should not happen after fix):**
```
✅ TTS playback ended
🎧 Ready for next wake word...
[< 1 second gap]  ← Too fast!
🎤 Wake word detected: sarah (score: 0.68)  ← TTS echo (blocked now)
```

## Why 2 Seconds?

**Too short (0.5s):**
- TTS echo still present
- Audio reverb not settled
- False positives from tail of speech

**Too long (5s+):**
- User has to wait too long
- Poor user experience
- Feels unresponsive

**2 seconds is optimal:**
- Long enough for all TTS echo to settle
- Short enough for good responsiveness
- Covers worst-case room acoustics
- Matches natural conversation pause

## Additional Benefits

1. **Consistent behavior:** Agent always requires wake word
2. **No false starts:** Won't begin recording from TTS echo
3. **Better user experience:** Clear when agent is ready
4. **Predictable:** Always works the same way

## Implementation Details

### Suppression Check Location

The suppression is checked in the main audio callback BEFORE wake word processing:

```python
def _audio_callback(self, audio_chunk):
    # State machine
    if self.state == VoiceAgentState.LISTENING_FOR_WAKE:
        # Check suppression FIRST
        if time.time() < self.suppress_wake_word_until:
            return  # Don't even process wake word

        # Normal wake word processing
        detection = self.wake_detector.process_chunk(audio_chunk)
```

This ensures:
- Zero CPU wasted on wake word processing during suppression
- No chance of false detection during suppression period
- Clean state transitions

### Error Handling

If any error occurs during TTS end callback:
```python
except Exception as e:
    logger.error(f"Error in TTS end callback: {e}")
    self.suppress_wake_word_until = 0  # Clear suppression
    self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
```

This ensures the agent doesn't get stuck in suppressed state if something goes wrong.

## Files Modified

- `shadow-agent/src/audio_session.py`
  - Line 80: Added `suppress_wake_word_until` timestamp
  - Lines 219-223: Check suppression before wake word processing
  - Lines 415-453: Enhanced TTS end callback with suppression

## Version

- **v2.2** - TTS echo prevention with wake word suppression
- **Previous:** v2.1 - Immediate recording + state fixes
- **Previous:** v2.0 - Conversational history + fast STT

## Rebuild Instructions

Run on Windows:
```cmd
APPLY_FIXES.bat
```

Then test with:
```cmd
TEST_VOICE.bat
```

## Success Criteria

✅ No immediate wake word detection after TTS (< 1.5 seconds)
✅ Consistent behavior across all conversation rounds
✅ Clear "Ready for next wake word" message after suppression
✅ User must always say "Sarah" to activate
✅ No random/unpredictable activations
