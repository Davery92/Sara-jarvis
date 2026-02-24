# GPU Cluster - Audio Services

This directory contains the deployment configuration for Sara's NVIDIA audio processing stack.

## Architecture

```
Jetson/Desktop audio -> ASR service (8585) -> Diarization service (8002/8004)
                                         -> Audio worker -> Sara backend
```

## Services

### 1. ASR Service (faster-whisper scaffold)
- **Image**: Custom (`Dockerfile.asr`)
- **Port**: 8585 (REST)
- **Features**:
  - REST transcription endpoint (`/transcribe`)
  - Word timestamps when available
  - Model/device from env (`ASR_MODEL_NAME`, `ASR_DEVICE`, `ASR_COMPUTE_TYPE`)

### 2. NeMo Diarization (default diarization backend)
- **Image**: Custom (Dockerfile.nemo)
- **GPU**: 2
- **Port**: 8002 (REST)
- **Features**:
  - Speaker diarization (who spoke when)
  - Speaker verification
  - Speaker enrollment
  - TitaNet embeddings

### 3. pyannote Diarization (optional profile)
- **Image**: Custom (`Dockerfile.pyannote`)
- **Port**: 8004 (REST)
- **Features**:
  - `POST /diarize` with NeMo-compatible response schema
  - `GET /health` reports backend state (`pyannote` or `mock`)
  - Optional install via `INSTALL_PYANNOTE=true`

### 4. Speaker Enrollment Service
- **Image**: Custom (Dockerfile.enrollment)
- **Port**: 8003 (REST)
- **Features**:
  - Register known speakers (David)
  - Manage speaker profiles
  - Add/remove voice samples

### 5. Audio Worker
- **Image**: Custom (Dockerfile.worker)
- **Features**:
  - Processes audio queue from Redis
  - Orchestrates ASR -> diarization pipeline
  - Optional segment-level speaker linking against enrolled profiles
  - Sends results to Sara backend

### 6. Speaker Training Worker (optional profile)
- **Image**: Custom (`Dockerfile.speaker-training`)
- **Profile**: `training`
- **Features**:
  - Claims `train_speakers` jobs from voice control plane
  - Runs configurable trainer command (`SPEAKER_TRAIN_COMMAND`) or uses enrollment service with sample folders
  - Registers speaker model versions
  - Optionally auto-activates trained speaker profiles

The worker now supports fallback order:
1. Riva gRPC
2. ASR REST service (`ASR_SERVICE_URL`)

For diarization routing:
1. `DIARIZATION_SERVICE_URL` (default `http://nemo-diarization:8002`)
2. `NEMO_DIARIZATION_URL` (legacy fallback)

## Deployment

### Prerequisites
- NVIDIA Docker runtime installed
- GPU with enough memory for selected models

### Quick Start

```bash
# 1. Start default stack (ASR + NeMo diarization)
docker compose -f docker-compose.simple.yml up -d

# 2. Verify health
curl http://10.185.1.8:8585/health           # ASR
curl http://10.185.1.8:8002/health           # NeMo diarization
curl http://10.185.1.8:8003/health           # Enrollment

# 3. Optional: start pyannote diarization profile
INSTALL_PYANNOTE=true docker compose -f docker-compose.simple.yml --profile pyannote up -d pyannote-diarization

# 4. Optional: start training worker profile for speaker model jobs
docker compose -f docker-compose.simple.yml --profile training up -d speaker-training-worker
```

Speaker training dataset layout for enrollment mode:

```text
/data/enrollment-samples/
  <dataset_id>/
    david/
      sample_0.wav
      sample_1.wav
    guest_1/
      sample_0.wav
```

If `dataset_id` is omitted in a job, the worker uses `/data/enrollment-samples/<speaker_id>/...`.

### Enroll David

```bash
# From the main jarvis directory
python scripts/enroll_david.py \
  samples/david_sample1.wav \
  samples/david_sample2.wav \
  samples/david_sample3.wav

# Check enrollment
python scripts/enroll_david.py --status
```

## Configuration

### Environment Variables

```bash
# Sara Backend
SARA_BACKEND_URL=http://10.185.1.180:8000

# Diarization routing
DIARIZATION_SERVICE_URL=http://nemo-diarization:8002
# DIARIZATION_SERVICE_URL=http://pyannote-diarization:8004

# pyannote optional model auth
HUGGINGFACE_TOKEN=hf_xxx

# voice-control internal service auth (for training workers)
VOICE_CONTROL_INTERNAL_TOKEN=change-me-voice-internal-token

# speaker training worker data/command options
SPEAKER_ENROLLMENT_URL=http://speaker-enrollment:8003
SPEAKER_TRAIN_DATASET_ROOT=/data/enrollment-samples
SPEAKER_TRAIN_COMMAND=
SPEAKER_TRAIN_TIMEOUT_SECONDS=1800
SPEAKER_TRAIN_ALLOW_SIMULATION_FALLBACK=true

# optional speaker linking in audio-worker
SPEAKER_LINKING_ENABLED=true
SPEAKER_VERIFY_THRESHOLD=0.55
SPEAKER_MIN_SEGMENT_SECONDS=0.8

# optional event publishing from audio-worker to voice-control
VOICE_CONTROL_URL=http://10.185.1.180:8000
VOICE_CONTROL_INTERNAL_TOKEN=change-me-voice-internal-token
VOICE_HEARTBEAT_INTERVAL_SECONDS=15

# Redis (for audio queue)
REDIS_URL=redis://audio-redis:6379/0
```

If `VOICE_CONTROL_URL`/`VOICE_CONTROL_INTERNAL_TOKEN` are not set, the Sensory pipeline table will show services as `offline` because heartbeats are disabled.

### GPU Allocation

Edit `docker-compose.simple.yml` to change GPU assignments:

```yaml
environment:
  - NVIDIA_VISIBLE_DEVICES=2
```

## API Reference

### NeMo Diarization Service

```bash
# Diarize audio file
POST /diarize
{
  "audio_path": "/data/audio/recording.wav",
  "num_speakers": null,  # Auto-detect
  "max_speakers": 8,
  "min_speakers": 1
}

# Verify speaker
POST /verify
{
  "audio_path": "/data/audio/sample.wav",
  "speaker_id": "david",
  "threshold": 0.5
}

# Enroll speaker
POST /enroll
{
  "speaker_id": "david",
  "audio_paths": ["/data/samples/s1.wav", "/data/samples/s2.wav"]
}

# List speakers
GET /speakers

# Delete speaker
DELETE /speakers/{speaker_id}
```

### Speaker Enrollment Service

```bash
# Enroll with file upload
POST /enroll/{speaker_id}
Content-Type: multipart/form-data
files: [audio1.wav, audio2.wav, ...]
display_name: "David"

# Add sample to existing speaker
POST /speakers/{speaker_id}/add-sample
Content-Type: multipart/form-data
file: audio.wav
```

## Monitoring

### Health Checks

All services expose health endpoints:

```bash
# Check all services
for port in 8585 8002 8003; do
  echo "Port $port: $(curl -s http://10.185.1.8:$port/health | jq -r .status)"
done
```

### Logs

```bash
# View all logs
docker compose -f docker-compose.simple.yml logs -f

# View specific service
docker compose -f docker-compose.simple.yml logs -f asr-service
docker compose -f docker-compose.simple.yml logs -f nemo-diarization
docker compose -f docker-compose.simple.yml logs -f pyannote-diarization
docker compose -f docker-compose.simple.yml logs -f speaker-training-worker
docker compose -f docker-compose.simple.yml logs -f audio-worker
```

### GPU Usage

```bash
# Monitor GPU utilization
watch -n 1 nvidia-smi
```

## Troubleshooting

### ASR service not starting
1. Check container logs: `docker compose -f docker-compose.simple.yml logs asr-service`
2. Verify GPU/runtime and model env values
3. Check GPU memory: `nvidia-smi`

### Diarization failing
1. Verify NeMo model loaded: Check logs for "TitaNet model loaded"
2. Check audio format: Must be WAV, 16kHz, mono
3. Verify file path accessible from container

### Speaker not recognized
1. Check enrollment: `python scripts/enroll_david.py --status`
2. Verify sample quality: Clear speech, no background noise
3. Add more samples: `python scripts/enroll_david.py --add-sample new.wav`

## Integration with Sara

The audio pipeline integrates with Sara's cognitive architecture:

1. **Desktop Sidecar** captures audio from microphone
2. **Audio Worker** processes through ASR -> diarization backend
3. **Results** sent to `/api/cognitive/audio/processed` with `trace_id` metadata
4. **Raw Buffer** stores transcripts with speaker info
5. **Consolidation** processes for working memory
6. **Sara** uses speaker context for personalized responses

```
Microphone → Sidecar → GPU Cluster → Sara Backend → Raw Buffer
                            ↓
                     [Transcript]
                     [Speaker: david]
                     [Diarization segments]
```
