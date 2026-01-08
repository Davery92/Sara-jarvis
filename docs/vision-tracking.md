# Vision-Based Activity Tracking System

## Overview

A computer vision system that captures periodic webcam snapshots from iOS and web apps, sends them to a YOLO inference server running on the GPU server (10.185.1.8 with 6x GTX 1070), and tracks behavioral patterns for personal insights.

## Architecture

```
+------------------+     +------------------+     +----------------------+
|   iOS App        |     |   Web App        |     |   Vision Server      |
|   (React Native) |     |   (React/Vite)   |     |   10.185.1.8:8080    |
|                  |     |                  |     |   6x GTX 1070        |
|  - Camera capture|     |  - MediaDevices  |     |                      |
|  - Snapshot POST |---->|  - Canvas capture|---->|  - FastAPI           |
|  - Overlay UI    |     |  - Overlay UI    |     |  - YOLOv8 inference  |
+------------------+     +------------------+     |  - Multi-GPU mgmt    |
         |                        |               +----------+-----------+
         |                        |                          |
         v                        v                          v
+------------------------------------------------------------------------+
|                     Main Backend (10.185.1.180:8000)                   |
|                     FastAPI - main_simple.py                           |
|  - /api/vision/detection (store results)                               |
|  - /api/vision/stats (query aggregations)                              |
|  - /api/vision/session (start/stop tracking)                           |
+------------------------------------------------------------------------+
         |
         v
+------------------------------------------------------------------------+
|                    PostgreSQL (10.185.1.180:5432)                      |
|  - vision_detection (individual detections)                            |
|  - vision_session (tracking sessions)                                  |
|  - vision_daily_summary (aggregated stats per day)                     |
+------------------------------------------------------------------------+
```

## Behaviors Tracked

| Behavior | Detection Method | Data Captured |
|----------|------------------|---------------|
| **Posture** | YOLOv8-pose keypoints | sitting, standing, slouching + duration |
| **Phone Usage** | Object detection | phone detected, in hand, looking at |
| **Headphones/Calls** | Object detection | headphones visible (infer call status) |
| **Activity States** | Pose + context | working, away, eating, exercising |

## Technical Specifications

### Image Capture
- **Format**: Base64-encoded JPEG
- **Resolution**: 640x480
- **Quality**: 80%
- **Size**: ~30-50KB per frame
- **Interval**: 10-30 seconds (adaptive)

### YOLO Models
- **YOLOv8n-pose**: Posture detection (17 keypoints per person)
- **YOLOv8n**: Object detection (phone, headphones, food)

### GPU Management
- Round-robin assignment across 6x GTX 1070
- Each GPU handles inference independently
- ~45ms inference time per frame

---

## Component Details

### 1. Vision Server (10.185.1.8)

**Location**: `~/vision-server/` on GPU server

```
vision-server/
├── app/
│   ├── main.py              # FastAPI application
│   ├── inference.py         # YOLO model loading and inference
│   ├── gpu_manager.py       # Round-robin GPU assignment
│   └── models/
│       ├── detection.py     # Detection result schemas
│       └── request.py       # Request/response models
├── models/                   # YOLO weights
│   ├── yolov8n-pose.pt
│   └── yolov8n.pt
├── config.py
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

**API Endpoints**:

```
POST /infer
  Request: {
    "image": "base64_jpeg_string",
    "user_id": "string",
    "timestamp": "ISO8601",
    "detect_types": ["pose", "objects"]
  }
  Response: {
    "detections": {
      "posture": "sitting|standing|slouching|unknown",
      "posture_confidence": 0.95,
      "phone_detected": true,
      "phone_in_hand": true,
      "looking_at_phone": false,
      "headphones_detected": true,
      "activity_state": "working|away|eating|exercising|unknown",
      "person_count": 1
    },
    "inference_time_ms": 45,
    "gpu_id": 2
  }

GET /health
  Response: { "status": "healthy", "gpus": [...], "models_loaded": true }
```

### 2. Database Schema

**Migration**: `backend/alembic/versions/037_vision_activity_tracking.py`

#### vision_session
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | String(36) | User identifier |
| started_at | DateTime | Session start |
| ended_at | DateTime | Session end (nullable) |
| client_type | String(20) | 'ios' or 'web' |
| status | String(20) | 'active', 'paused', 'ended' |
| total_frames | Integer | Frames captured |
| settings | JSONB | Capture interval, enabled detections |

#### vision_detection
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to vision_session |
| user_id | String(36) | User identifier |
| detected_at | DateTime | Detection timestamp |
| posture | String(20) | sitting, standing, slouching, unknown |
| posture_confidence | Float | 0.0-1.0 |
| phone_detected | Boolean | Phone visible |
| phone_in_hand | Boolean | Holding phone |
| looking_at_phone | Boolean | Looking at phone |
| headphones_detected | Boolean | Wearing headphones |
| activity_state | String(30) | Current activity |
| activity_confidence | Float | 0.0-1.0 |
| person_detected | Boolean | Person in frame |
| person_count | Integer | Number of people |
| raw_detections | JSONB | Optional debug data |
| inference_time_ms | Integer | Processing time |
| client_type | String(20) | Source client |

#### vision_daily_summary
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | String(36) | User identifier |
| summary_date | Date | Date of summary |
| sitting_seconds | Integer | Time sitting |
| standing_seconds | Integer | Time standing |
| slouching_seconds | Integer | Time slouching |
| phone_usage_seconds | Integer | Phone usage time |
| phone_checks_count | Integer | Number of phone checks |
| working_seconds | Integer | Time working |
| away_seconds | Integer | Time away |
| eating_seconds | Integer | Time eating |
| exercising_seconds | Integer | Time exercising |
| headphones_seconds | Integer | Time with headphones |
| total_frames | Integer | Frames processed |
| tracking_seconds | Integer | Total tracking time |

**Indexes**:
- `uq_vision_daily_user_date` UNIQUE on (user_id, summary_date)
- `ix_vision_detection_user_time` on (user_id, detected_at)

### 3. Backend API

**Routes**: `backend/app/routes/vision.py`

```python
# Session Management
POST   /api/vision/session/start     # Start tracking session
POST   /api/vision/session/stop      # Stop tracking session
GET    /api/vision/session/active    # Get current session

# Detection Logging
POST   /api/vision/detection         # Log detection from client

# Statistics
GET    /api/vision/stats/today       # Today's aggregated stats
GET    /api/vision/stats/daily       # Stats for specific date
GET    /api/vision/stats/range       # Stats for date range

# Real-time State
GET    /api/vision/current           # Current detection state (for overlay)
```

**Service**: `backend/app/services/vision_tracking_service.py`

```python
class VisionTrackingService:
    async def start_session(user_id, client_type, db) -> VisionSession
    async def stop_session(user_id, db) -> dict
    async def log_detection(user_id, detection, db) -> None
    async def get_current_state(user_id, db) -> dict
    async def aggregate_daily_stats(user_id, date, db) -> dict
    async def save_to_episodic_memory(user_id, summary, db) -> None
```

### 4. iOS App Implementation

**New Files**:
- `ios-app/src/services/visionTracking.ts` - API service
- `ios-app/src/hooks/useVisionCapture.ts` - Camera capture hook
- `ios-app/src/context/VisionTrackingContext.tsx` - State management
- `ios-app/src/components/VisionTrackingOverlay.tsx` - Floating overlay

**Modified Files**:
- `ios-app/app.json` - Camera permissions
- `ios-app/src/components/AuthenticatedOverlays.tsx` - Add overlay

**Context Interface**:
```typescript
interface VisionTrackingContextType {
  isEnabled: boolean;
  isCapturing: boolean;
  currentState: VisionDetection | null;
  todayStats: VisionStats | null;

  enableTracking: () => Promise<void>;
  disableTracking: () => Promise<void>;
  refreshStats: () => Promise<void>;
}
```

**Capture Flow**:
1. Request camera permission (front camera)
2. Capture frame at configured interval
3. Encode as base64 JPEG (640x480, 80% quality)
4. POST to vision server at 10.185.1.8:8080
5. Receive detection results
6. POST detection to main backend
7. Update overlay UI

### 5. Web App Implementation

**New Files**:
- `frontend/src/hooks/useVisionTracking.ts` - Camera + capture
- `frontend/src/components/VisionTrackingOverlay.tsx` - Floating overlay

**Modified Files**:
- `frontend/src/App-interactive.tsx` - Add overlay when authenticated

**Capture Flow**:
1. Request webcam via `navigator.mediaDevices.getUserMedia()`
2. Create hidden video + canvas elements
3. Draw frame to canvas at interval
4. Export as base64 JPEG via `canvas.toDataURL()`
5. POST to vision server
6. Update overlay UI

### 6. Overlay UI

**Collapsed State** (default):
- Small floating pill in bottom-right corner
- Shows current posture icon + activity icon
- Subtle animation on state change
- Tap/click to expand

**Expanded State**:
- Current detection details with confidence
- Today's time breakdown (pie chart or bars)
- Enable/disable toggle
- Capture interval setting
- Close button

---

## Sara Integration

### Episodic Memory
Daily summaries saved to episode table:
```
"Today you spent 4h sitting (65%), 2h standing (25%), 45min slouching (10%).
Phone checked 23 times, 45min total usage. Activity: 6h working, 1h eating."
```

### Pattern Correlation
Add `vision_metrics` to `temporal_bin` for cross-domain insights:
```json
{
  "sitting_pct": 0.65,
  "standing_pct": 0.25,
  "slouching_pct": 0.10,
  "phone_checks": 23,
  "phone_usage_min": 45,
  "active_tracking_min": 480
}
```

Enables patterns like:
- "You tend to slouch more after 3pm"
- "Phone usage increases when sitting for 2+ hours"
- "Standing desk time correlates with higher productivity"

### Proactive Nudges
- Slouching > 30 min: "Time to adjust your posture?"
- Sitting > 2 hours: "Consider a stretch break"
- Phone checks increasing: "Noticed more phone usage. Everything okay?"

---

## Privacy Considerations

1. **No image storage**: Frames processed and discarded immediately
2. **Server-side only**: All inference on dedicated GPU server
3. **User control**: Clear enable/disable toggle always visible
4. **Transparency**: Show exactly what is being detected
5. **Session indicators**: Camera active indicator when tracking
6. **Auto-pause**: Stop capture when app backgrounded

### Data Retention
- Individual detections: 30 days
- Daily summaries: 1 year
- Raw keypoints/objects: Never stored in production

---

## Implementation Order

### Phase 1: Vision Server
1. Set up FastAPI project on 10.185.1.8
2. Implement YOLO model loading with multi-GPU
3. Create `/infer` endpoint
4. Docker containerization
5. Basic health monitoring

### Phase 2: Backend Integration
1. Create database migration
2. Define SQLAlchemy models
3. Implement vision routes
4. Create vision_tracking_service
5. Add router to main_simple.py

### Phase 3: iOS Implementation
1. Add camera permissions
2. Create visionTracking service
3. Implement useVisionCapture hook
4. Build VisionTrackingContext
5. Create overlay components
6. Integrate with AuthenticatedOverlays

### Phase 4: Web Implementation
1. Create useVisionTracking hook
2. Build VisionTrackingOverlay
3. Integrate with App-interactive.tsx
4. Responsive styling

### Phase 5: Integration & Polish
1. Episodic memory integration
2. Pattern correlation hooks
3. Proactive notification triggers
4. Stats in fitness dashboard
5. Testing and optimization

---

## File Summary

### New Files
| Path | Description |
|------|-------------|
| `~/vision-server/` (on 10.185.1.8) | YOLO inference server |
| `backend/alembic/versions/037_vision_activity_tracking.py` | DB migration |
| `backend/app/routes/vision.py` | API endpoints |
| `backend/app/services/vision_tracking_service.py` | Business logic |
| `ios-app/src/services/visionTracking.ts` | iOS API service |
| `ios-app/src/hooks/useVisionCapture.ts` | Camera capture |
| `ios-app/src/context/VisionTrackingContext.tsx` | State context |
| `ios-app/src/components/VisionTrackingOverlay.tsx` | iOS overlay |
| `frontend/src/hooks/useVisionTracking.ts` | Web capture hook |
| `frontend/src/components/VisionTrackingOverlay.tsx` | Web overlay |

### Modified Files
| Path | Changes |
|------|---------|
| `backend/app/main_simple.py` | Include vision router |
| `ios-app/app.json` | Camera permissions |
| `ios-app/src/components/AuthenticatedOverlays.tsx` | Add overlay |
| `frontend/src/App-interactive.tsx` | Add overlay |
