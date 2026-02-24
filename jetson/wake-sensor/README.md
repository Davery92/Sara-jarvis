# Jetson Wake Sensor Service (Scaffold)

This service is the extraction target for the Jetson-side voice front-end.

Responsibilities:
- Wake-word detection (`openWakeWord`) on live mic audio
- VAD segmentation and utterance boundary detection
- Ambient/noise profile sampling for adaptive thresholds
- Emitting canonical voice events into Sara's control plane
- Reporting heartbeat and latency telemetry

Current status:
- Scaffold complete
- Simulation mode complete (no hardware required)
- Live audio capture integration pending
- Training-job worker hooks complete (`train_wake_word`)
- Internal config sync complete (`/api/voice-control/config/internal`)
- Ambient threshold auto-adjust loop scaffolded (simulation)
- Wake-model version metadata included in heartbeat + `wake.detected` events

## Runtime Modes

1. `simulate=true`:
- Emits synthetic voice events at a fixed interval
- Validates control-plane auth and event contracts remotely

2. `simulate=false`:
- Starts heartbeat loop
- Placeholder for live audio pipeline extraction (`openWakeWord` + VAD + mic device)

3. Training worker:
- Polls control-plane queue for `train_wake_word` jobs
- Runs configured wake training command when `WAKE_SENSOR_WAKE_TRAIN_COMMAND` is set
- Falls back to simulation when enabled (`WAKE_SENSOR_WAKE_TRAIN_ALLOW_SIMULATION_FALLBACK=true`)
- Registers model versions in voice-control model registry
- Optional auto-activation via `WAKE_SENSOR_AUTO_ACTIVATE_TRAINED_MODEL=true`
- Supports `dataset_id` from queued jobs (`/models/wake-word/train`)

Command hook env passed to your trainer:
- `VOICE_JOB_ID`
- `VOICE_TARGET_PHRASE`
- `VOICE_DATASET_ID`
- `VOICE_JOB_NOTES`

Optional command stdout contract:
- emit a JSON line, example
  - `{"version":"hey_sara_v20260224","metrics":{"far":0.01},"auto_activate":false}`

## Quick Start

```bash
cd jetson/wake-sensor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.env .env
# edit .env (SARA_BACKEND_URL + VOICE_CONTROL_INTERNAL_TOKEN)

python -m wake_sensor
```

## Required Backend Endpoints

- `POST /api/voice-control/services/{service_id}/heartbeat`
- `GET /api/voice-control/config/internal`
- `POST /api/voice-control/events/publish-internal`
- `POST /api/voice-control/jobs/claim`
- `POST /api/voice-control/jobs/{job_id}/status`
- `POST /api/voice-control/models/wake_word/versions`
- `POST /api/voice-control/models/wake_word/activate-internal`

Headers used:
- `X-Internal-Service: wake-sensor`
- `X-Internal-Token: <VOICE_CONTROL_INTERNAL_TOKEN>`

## Next Implementation Steps

1. Add real audio input adapter for Jetson mic array.
2. Integrate `openWakeWord` model loading and thresholding.
3. Integrate VAD and utterance extraction.
4. Add wake-word model selection and runtime reload from control-plane config.
5. Add ambient profiler with periodic calibration events.
