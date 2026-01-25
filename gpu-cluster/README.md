# GPU Cluster - NVIDIA Audio Stack

This directory contains the deployment configuration for Sara's NVIDIA audio processing stack.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     GPU Cluster (10.185.1.8)                    │
│                        6x GTX 1070                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   Riva ASR      │  │ NeMo Diarization│  │    VLLM/Vision  │ │
│  │   (GPU 0-1)     │  │    (GPU 2)      │  │   (GPU 3-4)     │ │
│  │   Port: 50051   │  │   Port: 8002    │  │   Port: 11434   │ │
│  └────────┬────────┘  └────────┬────────┘  └─────────────────┘ │
│           │                    │                                │
│           └──────────┬─────────┘                                │
│                      │                                          │
│           ┌──────────┴──────────┐                               │
│           │   Audio Worker      │                               │
│           │   (Orchestrates)    │                               │
│           └──────────┬──────────┘                               │
│                      │                                          │
└──────────────────────┼──────────────────────────────────────────┘
                       │
                       ▼
              Sara Backend (10.185.1.180:8000)
                /api/cognitive/audio/processed
```

## Services

### 1. Riva ASR (Speech Recognition)
- **Image**: `nvcr.io/nvidia/riva/riva-speech:2.14.0`
- **GPUs**: 0, 1
- **Port**: 50051 (gRPC)
- **Features**:
  - Real-time streaming transcription
  - Word-level timestamps
  - Automatic punctuation
  - Multi-language support

### 2. NeMo Diarization (Speaker Identification)
- **Image**: Custom (Dockerfile.nemo)
- **GPU**: 2
- **Port**: 8002 (REST)
- **Features**:
  - Speaker diarization (who spoke when)
  - Speaker verification
  - Speaker enrollment
  - TitaNet embeddings

### 3. Speaker Enrollment Service
- **Image**: Custom (Dockerfile.enrollment)
- **Port**: 8003 (REST)
- **Features**:
  - Register known speakers (David)
  - Manage speaker profiles
  - Add/remove voice samples

### 4. Audio Worker
- **Image**: Custom (Dockerfile.worker)
- **Features**:
  - Processes audio queue from Redis
  - Orchestrates Riva → NeMo pipeline
  - Sends results to Sara backend

## Deployment

### Prerequisites
- NVIDIA Docker runtime installed
- NGC API key for Riva models
- At least 24GB total GPU memory

### Quick Start

```bash
# 1. Set NGC credentials (for Riva model download)
export NGC_API_KEY=your_key_here

# 2. Initialize Riva models (first time only)
docker compose --profile init up riva-init

# 3. Start all services
docker compose up -d

# 4. Verify health
curl http://10.185.1.8:8001/v1/health/ready  # Riva
curl http://10.185.1.8:8002/health           # NeMo
curl http://10.185.1.8:8003/health           # Enrollment
```

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

# Riva
RIVA_API_KEY=your_ngc_key  # Optional, for premium models

# Redis (for audio queue)
REDIS_URL=redis://audio-redis:6379/0
```

### GPU Allocation

Edit `docker-compose.yml` to change GPU assignments:

```yaml
environment:
  - NVIDIA_VISIBLE_DEVICES=0,1  # Riva uses GPUs 0 and 1
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
for port in 8001 8002 8003; do
  echo "Port $port: $(curl -s http://10.185.1.8:$port/health | jq -r .status)"
done
```

### Logs

```bash
# View all logs
docker compose logs -f

# View specific service
docker compose logs -f riva-server
docker compose logs -f nemo-diarization
docker compose logs -f audio-worker
```

### GPU Usage

```bash
# Monitor GPU utilization
watch -n 1 nvidia-smi
```

## Troubleshooting

### Riva not starting
1. Check NGC credentials: `docker login nvcr.io`
2. Verify model download: `docker compose --profile init up riva-init`
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
2. **Audio Worker** processes through Riva → NeMo
3. **Results** sent to `/api/cognitive/audio/processed`
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
