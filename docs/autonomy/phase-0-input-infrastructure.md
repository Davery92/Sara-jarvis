# Phase 0: Input Infrastructure — Sensory Integration Guide

## Mission Statement

This phase integrates Sara's sensory inputs—audio, visual, screen, and environmental—into the cognitive architecture. Significant infrastructure already exists, including wake word detection on the Jetson and streaming to the desktop agent. Your job is to understand what exists, identify gaps, and connect the existing pipelines to the cognitive architecture defined in Phases 1-4.

**This is primarily an integration and bridging phase, not a build-from-scratch phase.**

---

## Critical Context: What Already Exists

Before doing anything, you must thoroughly audit and document the existing infrastructure:

### Existing Components to Locate and Understand

1. **Jetson Wake Word System**
   - Wake word detection is already running on a Jetson device
   - Audio is already streaming from Jetson to the desktop agent
   - You need to understand: How is this stream delivered? What format? What protocol? Where does it land on the desktop?

2. **Desktop Agent**
   - There is an existing desktop agent receiving audio streams
   - You need to understand: What does it currently do with the audio? How is it processed? Where does output go?

3. **Existing Sara Infrastructure**
   - Sara already exists as an AI assistant
   - There may be existing transcription, memory, or processing pipelines
   - You need to understand: What already processes audio? What already handles visual input? What databases and services exist?

### Your First Task

Before writing any integration plan, create a comprehensive audit document that answers:

**Audio Pipeline Audit:**
- Where does audio originate? (Jetson microphone setup)
- How is wake word detection implemented? (Model, framework, trigger mechanism)
- What streaming protocol connects Jetson to desktop? (WebSocket, gRPC, RTSP, raw TCP?)
- What format is the audio stream? (Sample rate, bit depth, encoding)
- Where does the audio stream land on the desktop? (Which service, which port, which process?)
- What currently happens to audio after wake word? (Is there existing transcription? Where does it go?)
- Is there continuous audio capture or only post-wake-word capture?

**Visual Pipeline Audit:**
- Is there existing camera capture? Where?
- Is there existing screen capture? How implemented?
- What processing currently exists? (Object detection, scene analysis?)
- Where does visual data currently go?

**Environmental Pipeline Audit:**
- Is Home Assistant integrated? How?
- What sensors/entities are available?
- How is state change data currently captured?

**Infrastructure Audit:**
- What message queues or event buses exist?
- What databases are in use? (Postgres, Redis, Neo4j, etc.)
- What GPU resources are available on the desktop? (The 6x GTX 1070 cluster)
- How are GPU workloads currently allocated?
- What container orchestration exists? (Docker, Kubernetes?)

---

## Architecture Overview

### The Two-Mode Sensory System

Sara's sensory system operates in two modes that you must preserve and enhance:

**Ambient Mode (Always Running)**
- Low-power, minimal processing
- Wake word detection active (on Jetson)
- Basic environmental monitoring
- Listening for triggers but not burning compute
- Goal: 24/7 awareness without resource exhaustion

**Active Mode (Triggered)**
- Full processing power engaged
- Complete transcription with speaker diarization
- Full visual scene analysis
- Rich context building
- Triggered by: wake word, direct interaction, high-priority events, or scheduled proactive checks

### Data Flow Architecture

```
JETSON DEVICE                          DESKTOP SYSTEM
─────────────────                      ────────────────────────────────────────
                                       
┌─────────────┐                        ┌─────────────────────────────────────┐
│ Microphone  │                        │         DESKTOP AGENT               │
│   Array     │                        │                                     │
└──────┬──────┘                        │  ┌─────────────────────────────┐   │
       │                               │  │     Audio Receiver          │   │
       ▼                               │  │  (existing - understand it) │   │
┌─────────────┐                        │  └──────────────┬──────────────┘   │
│  Wake Word  │                        │                 │                   │
│  Detection  │──── stream ───────────►│                 ▼                   │
│  (exists)   │                        │  ┌─────────────────────────────┐   │
└─────────────┘                        │  │   NVIDIA Audio Processing   │   │
                                       │  │   - Riva ASR (streaming)    │   │
                                       │  │   - NeMo Diarization        │   │
                                       │  └──────────────┬──────────────┘   │
                                       │                 │                   │
CAMERAS / SCREEN                       │                 ▼                   │
─────────────────                      │  ┌─────────────────────────────┐   │
                                       │  │   Visual Processing         │   │
┌─────────────┐                        │  │   - YOLO object detection   │   │
│   Webcam    │────────────────────────│─►│   - VLLM scene analysis     │   │
│   Screen    │                        │  │   - Screen OCR/context      │   │
└─────────────┘                        │  └──────────────┬──────────────┘   │
                                       │                 │                   │
                                       │                 ▼                   │
HOME ASSISTANT                         │  ┌─────────────────────────────┐   │
─────────────────                      │  │      RAW BUFFER             │   │
                                       │  │   (Phase 1 destination)     │   │
┌─────────────┐                        │  │   - Timestamped entries     │   │
│   Sensors   │──── websocket ─────────│─►│   - All modalities          │   │
│   Entities  │                        │  │   - 48-72hr retention       │   │
└─────────────┘                        │  └─────────────────────────────┘   │
                                       │                                     │
                                       └─────────────────────────────────────┘
```

---

## Audio Pipeline Integration

### Understanding the Existing Flow

The Jetson-to-desktop audio pipeline already exists. Your job is to:

1. **Document the existing stream characteristics**
   - Sample rate (likely 16kHz for speech)
   - Bit depth (likely 16-bit)
   - Channels (mono or stereo)
   - Streaming protocol and endpoint

2. **Identify the wake word trigger mechanism**
   - What signal does the Jetson send when wake word is detected?
   - Is there a pre-roll buffer (audio from before the wake word)?
   - How does the desktop know to switch from ambient to active mode?

3. **Map the current audio destination**
   - Where does audio currently go after arriving at desktop?
   - Is there existing transcription? Using what service?
   - Where do transcripts currently end up?

### NVIDIA Audio Stack Integration

The desktop has a 6x GTX 1070 cluster. The audio processing should use:

**NVIDIA Riva for Streaming ASR**
- Riva provides low-latency streaming speech-to-text
- Requires Riva server running (Docker container)
- Outputs real-time transcription with word-level timestamps

**NVIDIA NeMo for Speaker Diarization**
- Identifies who is speaking (David vs. others)
- Can run post-transcription or in parallel
- Outputs speaker labels with timestamps

### Integration Tasks

1. **Verify or Deploy Riva Server**
   - Check if Riva is already running
   - If not, deploy Riva ASR service on appropriate GPU
   - Configure for streaming mode with appropriate model (English, or multilingual if needed)
   - Document the Riva endpoint (host:port)

2. **Connect Audio Stream to Riva**
   - The existing audio stream from Jetson needs to feed into Riva
   - This may require a bridge service if formats don't match
   - Ensure the connection handles both ambient (buffered) and active (streaming) modes

3. **Implement or Verify Diarization Pipeline**
   - Determine if diarization runs real-time or post-hoc
   - For real-time: NeMo streaming diarization (more complex)
   - For post-hoc: Process completed utterances through NeMo (simpler, slight delay)
   - Speaker embeddings should be stored to recognize David consistently

4. **Create Speaker Profile for David**
   - Enroll David's voice for reliable identification
   - Store speaker embedding in persistent storage
   - This allows "David said X" vs "Unknown speaker said X"

5. **Define Output Format**
   - Transcription output must include:
     - Timestamp (start and end)
     - Transcript text
     - Speaker ID (david, unknown_1, unknown_2, etc.)
     - Confidence score
     - Wake word trigger flag (was this activated by wake word?)

6. **Connect Output to Raw Buffer**
   - Transcribed, diarized audio must flow to the Phase 1 raw buffer
   - Format must match the raw buffer schema
   - Include traceability to original audio if stored

### Ambient vs. Active Mode Handling

**Ambient Mode:**
- Wake word detection runs on Jetson (already exists)
- Desktop receives notification of potential speech
- Minimal transcription—possibly keywords only, or buffered for later
- Rolling buffer maintained for pre-wake-word context

**Active Mode Trigger:**
- Wake word detected → Jetson signals desktop
- Desktop retrieves pre-roll audio buffer (last N seconds before wake word)
- Full Riva transcription begins
- Diarization activates
- Mode remains active until conversation ends (silence timeout or explicit end)

**Mode Transition Signals:**
- Define clear signals for mode transitions
- Wake word → activate
- Extended silence → deactivate
- Explicit "goodbye Sara" or similar → deactivate
- High-priority event → activate (even without wake word)

---

## Visual Pipeline Integration

### Camera Input

1. **Audit Existing Camera Setup**
   - Is there already camera capture running?
   - What resolution and framerate?
   - Where does the feed currently go?

2. **Define Capture Strategy**
   - Ambient mode: Low framerate capture (1-5 FPS), basic object detection only
   - Active mode: Higher framerate (10-15 FPS), full scene analysis
   - Storage: Frames are not stored long-term; only processed metadata goes to raw buffer

3. **YOLO Object Detection**
   - Deploy YOLO (v8 recommended) on designated GPU
   - Configure for relevant object classes:
     - People (presence, count)
     - Posture (standing, sitting, lying down)
     - Common objects (phone, laptop, cup, etc.)
     - Pets if relevant
   - Output: Timestamped list of detected objects with bounding boxes and confidence

4. **VLLM Scene Analysis**
   - Periodic (every N seconds) full scene description
   - Use vision-language model (LLaVA, or similar running locally)
   - Generate natural language description of the scene
   - Include: Who's present, what they're doing, notable objects, apparent mood/activity
   - Output: Timestamped scene description

5. **Define Output Format**
   - Visual data to raw buffer must include:
     - Timestamp
     - Object detections (structured)
     - Scene description (if generated)
     - Frame reference (if frames are temporarily stored for audit)

### Screen Capture

1. **Audit Existing Screen Capture**
   - Is there already screen capture implemented?
   - What triggers capture? (Periodic, on-change, manual?)
   - Where do screenshots go?

2. **Define Capture Strategy**
   - Periodic screenshots (every 10-30 seconds in ambient, every 3-5 in active)
   - Change detection to avoid redundant captures
   - Privacy consideration: What applications/windows should be excluded?

3. **Screen Analysis**
   - OCR for text extraction (what's on screen)
   - Application identification (what app is focused)
   - Activity inference (coding, browsing, writing, etc.)
   - Use VLLM for contextual understanding of screen content

4. **Define Output Format**
   - Screen data to raw buffer must include:
     - Timestamp
     - Active application
     - Window title
     - OCR text (summarized, not full dump)
     - Activity classification
     - Screenshot reference (if stored for audit)

---

## Environmental Pipeline Integration

### Home Assistant Integration

1. **Audit Existing Integration**
   - Is Home Assistant already connected?
   - What connection method? (WebSocket API, REST API, MQTT?)
   - What entities are currently tracked?

2. **Define Entity Tracking**
   - Identify relevant entities for Sara's awareness:
     - Presence sensors (is David home?)
     - Door/window sensors (arrivals, departures)
     - Light states (is it day/night, what room is active?)
     - Climate sensors (temperature, humidity)
     - Media players (is music/TV playing?)
     - Calendar events (upcoming appointments)
   - Not all entities are relevant—filter to what matters for context

3. **State Change Handling**
   - Subscribe to state changes for relevant entities
   - Don't poll—use event subscription (WebSocket)
   - Debounce rapid changes (lights flickering shouldn't spam the buffer)

4. **Define Output Format**
   - Environmental data to raw buffer must include:
     - Timestamp
     - Entity ID
     - Old state
     - New state
     - Relevant attributes

### Other Environmental Sources

Consider what other data sources might feed environmental awareness:

- **Calendar Integration**: Upcoming events, busy/free status
- **Weather API**: Current conditions, forecasts
- **Time-based Context**: Time of day, day of week, holidays
- **System Sensors**: Desktop CPU/GPU load, memory usage (for self-awareness)

---

## GPU Resource Allocation

### Available Hardware

6x NVIDIA GTX 1070 (8GB VRAM each)

### Recommended Allocation Strategy

**GPU 0-1: Audio Processing**
- Riva ASR server (streaming transcription)
- NeMo diarization models
- These are latency-sensitive—dedicate GPUs for consistent performance

**GPU 2: Visual Processing - Detection**
- YOLO object detection
- Posture detection
- Real-time, continuous processing

**GPU 3: Visual Processing - Analysis**
- VLLM for scene description
- VLLM for screen analysis
- Periodic, heavier processing

**GPU 4: Lightweight Always-On**
- Any on-device wake word backup
- Keyword spotting
- VAD if running on desktop

**GPU 5: Overflow and Batch**
- Handle load spikes
- Batch processing for reflection agent
- LLM inference for Sara (or this may be on separate infrastructure)

### Resource Management

1. **Document Current GPU Usage**
   - What's currently running on each GPU?
   - What VRAM is consumed?
   - Are there conflicts or resource contention?

2. **Implement GPU Allocation**
   - Ensure services are pinned to specific GPUs (CUDA_VISIBLE_DEVICES)
   - Monitor VRAM usage
   - Alert if approaching limits

3. **Handle Contention**
   - Define priority: Audio > Visual detection > Visual analysis > Batch
   - Implement queuing if needed
   - Graceful degradation if GPUs are overloaded

---

## Streaming Protocols and Data Flow

### Jetson to Desktop Communication

1. **Document Existing Protocol**
   - What protocol is currently used? (WebSocket, gRPC, RTSP, ZeroMQ, raw TCP?)
   - What is the message format?
   - How is connection health monitored?

2. **Ensure Reliability**
   - What happens if connection drops?
   - Is there automatic reconnection?
   - Is audio buffered on Jetson during disconnection?

3. **Define Message Types**
   - Audio chunk (raw PCM or encoded)
   - Wake word trigger event
   - Mode change signals
   - Health/status messages

### Internal Desktop Communication

1. **Audit Existing Message Bus**
   - Is there already a message queue? (Redis pub/sub, RabbitMQ, ZeroMQ?)
   - How do components currently communicate?

2. **Define Event Bus for Sensory System**
   - All sensory outputs should publish to a common bus
   - Events:
     - `audio.chunk.received` — Raw audio arrived
     - `audio.transcription.partial` — Streaming partial transcript
     - `audio.transcription.final` — Complete utterance transcribed
     - `audio.speaker.identified` — Speaker diarization result
     - `audio.wake_word.detected` — Wake word triggered
     - `visual.objects.detected` — YOLO detection results
     - `visual.scene.analyzed` — VLLM scene description
     - `screen.captured` — New screenshot processed
     - `environment.state.changed` — Home Assistant state change
     - `mode.changed` — Ambient ↔ Active transition

3. **Connect to Raw Buffer**
   - Phase 1's raw buffer subscribes to relevant events
   - All events are timestamped and stored
   - This is the handoff point between Phase 0 and Phase 1

---

## Mode Management

### Mode Controller

A central component must manage ambient vs. active mode:

1. **Mode State**
   - Current mode (ambient or active)
   - Mode entry timestamp
   - Reason for current mode

2. **Activation Triggers**
   - Wake word detected
   - Direct user interaction (typed message)
   - High-priority environmental event
   - Scheduled proactive check
   - Manual activation command

3. **Deactivation Triggers**
   - Extended silence (configurable timeout, e.g., 30 seconds)
   - Explicit end command ("Thanks Sara", "Goodbye")
   - Scheduled deactivation
   - Manual deactivation command

4. **Mode Change Effects**
   - Ambient → Active:
     - Retrieve pre-roll audio buffer
     - Start full transcription
     - Increase visual processing rate
     - Notify Sara's cognitive system
   - Active → Ambient:
     - Stop full transcription
     - Reduce visual processing rate
     - Flush final context to working memory
     - Notify Sara's cognitive system

5. **Mode Persistence**
   - Active mode should persist through brief pauses
   - Configurable "conversation timeout" before returning to ambient
   - Consider context: If Sara asked a question, wait longer for response

---

## Integration with Phase 1

### Handoff Point

Phase 0 ends where Phase 1 begins: the raw buffer.

All sensory pipelines must ultimately write to the raw buffer with:

1. **Consistent Timestamp Format**
   - UTC timestamps with microsecond precision
   - All streams use the same time source (synchronized clocks)

2. **Consistent Schema**
   - Every entry has: timestamp, stream_type, data, metadata
   - Stream types: audio, visual, screen, text, environmental
   - Data format is defined per stream type

3. **Traceability**
   - Each entry can reference raw source data if needed for audit
   - Consolidation can trace back to original inputs

### What Phase 1 Expects

Phase 1's consolidation agent expects to find in the raw buffer:

- **Audio entries**: Timestamped transcripts with speaker tags
- **Visual entries**: Object detection results and scene descriptions
- **Screen entries**: Application context and activity classification
- **Environmental entries**: State changes with entity identification

If these aren't flowing correctly, Phase 1 cannot function.

---

## Testing and Validation

### Integration Tests for Phase 0

1. **Audio Pipeline Test**
   - Speak into microphone
   - Verify audio reaches Riva
   - Verify transcription is produced
   - Verify diarization identifies speaker
   - Verify output reaches raw buffer with correct format

2. **Wake Word Test**
   - Say wake word
   - Verify mode transitions to active
   - Verify pre-roll buffer is captured
   - Verify transcription of post-wake-word speech
   - Verify return to ambient after silence

3. **Visual Pipeline Test**
   - Ensure camera is capturing
   - Verify YOLO detects objects in frame
   - Verify scene description is generated periodically
   - Verify output reaches raw buffer

4. **Screen Pipeline Test**
   - Verify screenshots are captured
   - Verify screen analysis produces context
   - Verify output reaches raw buffer

5. **Environmental Pipeline Test**
   - Change a Home Assistant entity state
   - Verify event is captured
   - Verify output reaches raw buffer

6. **Mode Transition Test**
   - Start in ambient mode
   - Trigger wake word → verify active mode
   - Wait for timeout → verify return to ambient
   - Trigger manual activation → verify active mode
   - Send end command → verify return to ambient

7. **GPU Resource Test**
   - Run all pipelines simultaneously
   - Monitor GPU memory and utilization
   - Verify no OOM errors
   - Verify latency stays acceptable

### Performance Benchmarks

Define and measure:

- Audio transcription latency (wake word to first transcript)
- Object detection latency (frame to detection result)
- Scene analysis latency (frame to description)
- Raw buffer write latency
- End-to-end latency (speech to raw buffer entry)

---

## Completion Criteria

**Phase 0 is NOT complete until:**

- [ ] Existing infrastructure fully audited and documented
- [ ] Audio stream from Jetson successfully received on desktop
- [ ] Riva ASR deployed and producing transcriptions
- [ ] Speaker diarization identifying David vs. others
- [ ] David's voice enrolled for consistent identification
- [ ] Wake word triggers mode transition correctly
- [ ] Pre-roll buffer captured on wake word
- [ ] Camera capture operational
- [ ] YOLO object detection running and producing results
- [ ] VLLM scene analysis running periodically
- [ ] Screen capture operational
- [ ] Screen analysis producing application context
- [ ] Home Assistant state changes captured
- [ ] All sensory data flowing to raw buffer
- [ ] Raw buffer schema matches Phase 1 expectations
- [ ] Mode controller managing ambient/active transitions
- [ ] GPU allocation documented and stable
- [ ] All integration tests passing
- [ ] Performance benchmarks meeting requirements
- [ ] No dropped audio or visual frames under normal load
- [ ] Graceful handling of component failures

---

## Files and Components

### Audit Documents to Create

```
docs/
  infrastructure-audit.md      # Complete audit of existing systems
  audio-pipeline-map.md        # Detailed audio flow documentation
  visual-pipeline-map.md       # Detailed visual flow documentation
  gpu-allocation.md            # GPU assignment and utilization
  message-formats.md           # All message/event schemas
```

### Components to Integrate or Create

```
services/
  audio/
    jetson_receiver.py         # Receives stream from Jetson (may exist)
    riva_client.py             # Connects to Riva ASR
    diarization_service.py     # NeMo speaker diarization
    speaker_enrollment.py      # David's voice profile
    
  visual/
    camera_capture.py          # Camera input (may exist)
    yolo_detector.py           # Object detection
    scene_analyzer.py          # VLLM scene description
    
  screen/
    screen_capture.py          # Screenshot capture (may exist)
    screen_analyzer.py         # Screen context extraction
    
  environmental/
    homeassistant_client.py    # HA WebSocket connection (may exist)
    entity_filter.py           # Filter relevant entities
    
  core/
    mode_controller.py         # Ambient/Active mode management
    event_bus.py               # Central event publication (may exist)
    raw_buffer_writer.py       # Write to Phase 1 raw buffer
```

### Configuration

```
config/
  audio_config.yaml            # Audio pipeline settings
  visual_config.yaml           # Visual pipeline settings
  gpu_config.yaml              # GPU assignments
  mode_config.yaml             # Mode transition settings
  entities_config.yaml         # Relevant Home Assistant entities
```

---

## Notes for Claude Code

1. **Audit before building.** Most of this infrastructure already exists in some form. Your first job is to understand it completely.

2. **Don't duplicate.** If there's already a service doing something, integrate with it—don't create a parallel system.

3. **The Jetson pipeline is sacred.** Wake word detection on the Jetson works. Don't break it while integrating.

4. **Timestamps are critical.** Every piece of sensory data must have precise, synchronized timestamps. The cognitive architecture depends on temporal alignment.

5. **Resource awareness matters.** The GTX 1070s have 8GB VRAM each. Know what's using what, and don't overcommit.

6. **Latency matters for audio.** The path from speech to transcript should be fast enough for natural conversation. Target under 500ms.

7. **The raw buffer is the goal.** Everything in Phase 0 exists to feed Phase 1's raw buffer. That's the integration point. That's success.

8. **Test the full path.** Don't just test components in isolation. Test speech → transcription → diarization → raw buffer as a single flow.

9. **Document everything.** The audit documents are as important as the code. Future you (and future phases) will need them.

10. **Graceful degradation.** If a camera fails, Sara should still hear. If audio fails, Sara should still see. Design for partial failure.
