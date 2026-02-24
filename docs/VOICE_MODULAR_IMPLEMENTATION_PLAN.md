# Voice Modular Implementation Plan

Status date: 2026-02-24

Goal: Rebuild the office voice pipeline as modular services:
Jetson wake sensor -> GPU ASR/diarization -> Sara orchestration -> Windows Kokoro TTS -> desktop playback.

## Target Service Topology

1. `wake-sensor` (Jetson Orin)
2. `speech-asr` (GPU cluster)
3. `speaker-diarization` (GPU cluster)
4. `speaker-registry` (GPU/backend)
5. `voice-orchestrator` (backend)
6. `tts-router` (Windows)
7. `playback-agent` (Windows sidecar)
8. `voice-control` (backend control plane)

## Core Contracts

Canonical event types:
- `job.queued`
- `job.updated`
- `wake.detected`
- `utterance.started`
- `utterance.ended`
- `asr.partial`
- `asr.final`
- `diarization.final`
- `speaker.verified`
- `sara.request.started`
- `sara.response.delta`
- `sara.response.final`
- `tts.chunk`
- `tts.final`
- `playback.state`
- `pipeline.error`

Trace contract:
- every event includes `trace_id`
- `trace_id` is stable for one full turn
- per-service heartbeat reports include `latency_ms` and `version`

## Phased Execution

### Phase 0: Control Plane and Contracts (in progress)

- [x] Add backend `voice-control` API surface for config/models/jobs/events
- [x] Add voice pipeline heartbeat/status endpoints
- [x] Add voice event stream publisher + query endpoint
- [x] Add no-hardware demo simulation endpoint for remote testing
- [x] Add Sensory UI control-plane tabs and controls
- [x] Add SSE/WebSocket stream endpoint for live voice events (instead of polling)
- [x] Add auth policy hardening for service-to-service endpoints
- [x] Add OpenAPI examples for contract payloads/events

### Phase 1: Jetson Wake Sensor

- [x] Create dedicated `wake-sensor` service scaffold (`jetson/wake-sensor`)
- [x] Add wake-word training job worker hooks (claim -> run -> register model version)
- [x] Add wake-word trainer command hook (`WAKE_SENSOR_WAKE_TRAIN_COMMAND`) with simulation fallback
- [ ] Integrate `openWakeWord` model management hooks
- [x] Add adaptive ambient profiler and VAD threshold policy (simulation scaffold)
- [ ] Emit canonical events (`wake.detected`, `utterance.*`)
- [x] Add model version metadata in events and heartbeats

### Phase 2: GPU Speech Stack

- [x] Add `speech-asr` scaffold (`gpu-cluster/asr_service.py`, `Dockerfile.asr`)
- [x] Stand up `speaker-diarization` with `pyannote` service endpoint
- [x] Add speaker training worker scaffold (`gpu-cluster/speaker_training_worker.py`)
- [x] Add dataset-based speaker enrollment training path + optional command hook
- [x] Propagate `trace_id` through audio-worker job metadata into Sara audio handoff
- [ ] Add speaker linking against versioned registry profiles
- [ ] Ensure all outputs publish canonical events with shared `trace_id`
- [ ] Add replay tests using recorded WAV fixtures

### Phase 3: Voice Orchestration + Sara

- [ ] Build `voice-orchestrator` service boundary for turn assembly
- [ ] Route finalized user turns into Sara backend memory/tool chain
- [ ] Support barge-in and interruption events
- [ ] Emit `sara.response.delta` and `sara.response.final` events
- [ ] Add SLO metrics: end-of-speech -> first Sara token

### Phase 4: TTS + Playback Path

- [ ] Build `tts-router` adapter for Kokoro on Windows
- [ ] Keep playback local via sidecar `playback-agent`
- [ ] Emit playback state events and echo suppression telemetry
- [ ] Add retry/backpressure handling for chunk stream
- [ ] Add SLO metrics: first token -> first audio

### Phase 5: Sensory Training UX

- [ ] Replace legacy SSH-driven enrollment flow with job-based training workflows
- [ ] Wake Word Lab: capture dataset metadata, queue training, deploy/rollback versions
- [ ] Speaker Lab: retrain known speakers and display quality metrics
- [ ] Ambient Adaptation: profile snapshots + policy tuning history
- [ ] Models tab: active version, canary switch, rollback

### Phase 6: At-Home Calibration (requires hardware access)

- [ ] Capture new wake-word dataset on current Orin mic setup
- [ ] Retrain wake model and compare ROC/false trigger stats
- [ ] Re-enroll/retrain speaker profiles with new recordings
- [ ] Tune ambient policy in office conditions
- [ ] Verify end-to-end latency/accuracy SLOs

## Immediate Next Actions

1. Replace simulated wake-word/speaker training with real training pipelines (`openWakeWord`, speaker embeddings).
2. Replace simulated ambient profiling with real mic-noise calibration snapshots on Jetson hardware.
3. Add canonical `trace_id` propagation from wake sensor through GPU services into Sara handoff.
4. Replace remaining legacy sensory SSH actions with control-plane-backed job execution.
