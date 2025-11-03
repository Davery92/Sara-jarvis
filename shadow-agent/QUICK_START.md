# Sara Voice Agent - Quick Start Guide

## ✅ Build Complete!

Your optimized voice agent is ready: `dist\SaraShadowAgent.exe`

## Running the Voice Agent

### Option 1: Run the Executable (Recommended)
```cmd
dist\SaraShadowAgent.exe
```

### Option 2: Use the Test Script
```cmd
TEST_VOICE.bat
```

### Option 3: Run from Source (for debugging)
```cmd
python src\main_voice.py
```

## What to Expect

### Startup
```
2025-10-10 16:17:29 - Audio capture initialized: 16000Hz, 1ch, int16
2025-10-10 16:17:29 - ✅ WebRTC VAD loaded
2025-10-10 16:17:29 - ✅ Voice agent started
2025-10-10 16:17:29 - Say 'sarah' to activate
```

### Wake Word Detection
```
2025-10-10 16:22:03 - 🎤 Wake word 'sarah' detected! (score: 0.76)
2025-10-10 16:22:03 - 🔴 Recording started
```

### Speech Recognition (NEW: Faster!)
```
2025-10-10 16:22:07 - ⏹️ Recording stopped (4.64s)
2025-10-10 16:22:07 - Processing utterance (4.64s of audio)
2025-10-10 16:22:11 - 📝 Transcript: I'm pretty tired of working today.  ← ~4s latency!
```

**Before:** 15.5 seconds latency
**After:** 3-5 seconds latency ✅

### AI Response (NEW: With Memory!)
```
2025-10-10 16:22:11 - 💬 Sending to AI: I'm pretty tired of working today.
2025-10-10 16:22:27 - 🤖 AI response: Hey, I hear you—long days can really drain you...
```

### TTS Playback
```
2025-10-10 16:22:30 - 🔊 Playing TTS audio (14.70s)
2025-10-10 16:22:45 - ✅ Playback complete
```

## Testing Conversational History

### Test 1: Name Memory
1. Say: **"Sarah, my name is David"**
2. Wait for response
3. Say: **"Sarah, what is my name?"**
4. Sara should respond: **"Your name is David"** ✅

### Test 2: Topic Continuity
1. Say: **"Sarah, I'm interested in learning Python"**
2. Wait for response
3. Say: **"Sarah, what should I start with?"**
4. Sara should respond with Python advice (remembering the topic) ✅

### Test 3: Multi-Turn Conversation
1. Say: **"Sarah, I'm planning a trip to Japan"**
2. Wait for response
3. Say: **"Sarah, what's the best time to visit?"**
4. Say: **"Sarah, what cities should I go to?"**
5. Each response should build on the previous conversation ✅

## Performance Benchmarks

### STT Latency (4 seconds of speech)

| Version | Latency | Improvement |
|---------|---------|-------------|
| Before | 13-16s | Baseline |
| After | 3-5s | **3-5x faster** ✅ |

### Conversation Memory

| Version | Memory | Retention |
|---------|--------|-----------|
| Before | None | N/A |
| After | Last 5 exchanges | Until restart ✅ |

## System Tray

The voice agent runs in the system tray. Look for the Sara icon:
- **Green:** Listening for wake word
- **Red:** Recording speech
- **Blue:** Processing/Speaking

Right-click the tray icon for options:
- **Exit:** Quit the application

## Troubleshooting

### "Wake word not detected"
- Speak clearly: "Sarah" (not too fast, not too slow)
- Check microphone is working
- Try adjusting microphone volume in Windows settings

### "Speech recognition not working"
- Check backend is running: `http://10.185.1.180:8000`
- Verify STT service is running: `http://10.185.1.8:8585`
- Check logs for errors

### "No TTS playback"
- Check TTS service is running: `http://10.185.1.8:9000`
- Check audio output device
- Look for errors in logs

### "Conversation history not working"
- Verify backend version with conversation support
- Check session_id in logs (should be your hostname)
- Restart backend if needed: `docker compose restart backend`

## Advanced Configuration

### Change Wake Word Threshold
Edit `src/wake_word.py`:
```python
threshold=0.6  # 0.5 = more sensitive, 0.8 = less sensitive
```

### Change VAD Aggressiveness
Edit `src/audio_session.py`:
```python
aggressiveness=3  # 0-3, higher = more aggressive filtering
```

### Change Recording Timeout
Edit `src/audio_session.py`:
```python
self.recording_timeout_seconds = 10  # seconds
```

### Disable Fast STT (use legacy Wyoming)
Edit `src/wyoming_client.py`:
```python
use_fast_path=False  # in transcribe_audio() call
```

## Logs Location

Console logs show all activity. For debugging:
1. Run from command line to see live logs
2. Check for errors during:
   - Wake word detection
   - Speech recognition
   - AI response
   - TTS playback

## Stopping the Agent

### From Console
Press `Ctrl+C`

### From System Tray
Right-click Sara icon → Exit

## Next Steps

### Optional Optimizations

1. **Even Faster STT:**
   - Use smaller Whisper model (`tiny` or `base`)
   - Enable GPU acceleration for Faster-Whisper
   - Configure beam_size for speed vs accuracy

2. **Persistent Memory:**
   - Configure Redis for conversation history
   - Store conversations in Sara's episodic memory
   - Cross-device conversation sync

3. **Better Wake Word:**
   - Train custom "Sarah" model with your voice
   - Adjust threshold for your environment
   - Add multiple wake words

## Support

For issues or questions:
- Check `OPTIMIZATION_NOTES.md` for technical details
- Review logs for error messages
- Test individual components (STT, TTS, backend)

---

**Version:** 2.0 (Optimized)
**Features:** Conversational History + Fast STT
**Backend:** http://10.185.1.180:8000
**Build Date:** 2025-10-10
