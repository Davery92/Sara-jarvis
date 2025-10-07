# 🎙️ Voice Implementation - Phase 2 Progress

## ✅ Completed So Far

### Phase 1: Foundation (COMPLETE)
- ✅ Wake word detection (openWakeWord with custom "sarah" model)
- ✅ Pre-roll audio buffer
- ✅ Audio capture from microphone
- ✅ Recording scripts and training pipeline
- ✅ Windows setup and testing scripts

### Phase 2: Voice Pipeline (IN PROGRESS)
- ✅ **VAD Implementation** (`shadow-agent/src/vad.py`)
  - Silero VAD integration
  - Speech start/stop detection
  - Recording window management
  - 200ms speech trigger, 500ms silence end

- ✅ **Wyoming Client** (`shadow-agent/src/wyoming_client.py`)
  - WebSocket communication with backend
  - Audio streaming to STT
  - TTS audio reception
  - Session management

- ✅ **Wyoming Server** (`backend/app/routes/wyoming.py`)
  - `/wyoming/asr` endpoint (STT)
  - `/wyoming/tts` endpoint (TTS)
  - Proxies to Faster-Whisper (http://10.185.1.8:8585)
  - Proxies to TTS service (http://10.185.1.8:9000)
  - Registered in main_simple.py

---

## ✅ PHASE 2 COMPLETE!

### All Components Implemented

1. ✅ **Audio Session Orchestrator** (`shadow-agent/src/audio_session.py`)
   - Complete state machine: IDLE → LISTENING → RECORDING → PROCESSING → SPEAKING
   - Coordinates wake word → VAD → STT → TTS pipeline
   - Error handling and automatic recovery
   - Barge-in detection during TTS playback

2. ✅ **TTS Audio Playback** (`shadow-agent/src/tts_playback.py`)
   - TTSPlayer with WAV audio parsing
   - EchoSuppressor for feedback prevention
   - Threaded playback with interruption support
   - Cross-platform audio output via sounddevice

3. ✅ **System Tray UI** (`shadow-agent/src/system_tray.py`)
   - Cross-platform implementation using pystray
   - Color-coded status icons (green, red, yellow, blue, gray)
   - Radio button menu for mode switching
   - Actions: Test Voice, Settings, View Logs, Restart, Quit

4. ✅ **Packaging & Distribution**
   - Windows: PyInstaller packaging script (`shadow-agent/package_windows.py`)
   - macOS: py2app packaging script (`shadow-agent/package_macos.py`)
   - Backend download endpoints (`backend/app/routes/agent_downloads.py`)
   - Frontend download page (`frontend/src/components/VoiceAgentDownload.tsx`)
   - Automatic download tracking and analytics

---

## 📁 Files Created (Phase 2)

### Agent (Python)
```
shadow-agent/
├── src/
│   ├── vad.py                    ✅ Voice activity detection
│   ├── wyoming_client.py         ✅ Backend communication
│   ├── wake_word.py              ✅ (Phase 1)
│   ├── audio_buffer.py           ✅ (Phase 1)
│   ├── audio_capture.py          ✅ (Phase 1)
│   ├── audio_session.py          ✅ Main orchestrator
│   ├── tts_playback.py           ✅ Audio output & echo suppression
│   ├── system_tray.py            ✅ UI controls
│   └── main_voice.py             ✅ Entry point
├── package_windows.py            ✅ Windows packaging script
└── package_macos.py              ✅ macOS packaging script
```

### Backend (FastAPI)
```
backend/app/routes/
├── wyoming.py                    ✅ STT/TTS WebSocket endpoints
└── agent_downloads.py            ✅ Download endpoints & version management
```

### Frontend (React)
```
frontend/src/components/
└── VoiceAgentDownload.tsx        ✅ Download page UI
```

---

## 🎯 Architecture Overview

```
┌─────────────────────────────────────────┐
│  SHADOW AGENT (Desktop - Always Running)│
├─────────────────────────────────────────┤
│                                         │
│  System Tray Icon                       │
│    ├─ Status: Listening / Idle         │
│    ├─ Mode: Always-On / Shadow-Only    │
│    └─ Settings & Controls              │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │  Audio Session Orchestrator       │ │
│  │  ┌─────────────────────────────┐  │ │
│  │  │ 1. Wake Word (sarah)        │  │ │
│  │  │    ↓                        │  │ │
│  │  │ 2. VAD (detect speech)      │  │ │
│  │  │    ↓                        │  │ │
│  │  │ 3. Wyoming → STT            │  │ │
│  │  │    ↓                        │  │ │
│  │  │ 4. Process Command          │  │ │
│  │  │    ↓                        │  │ │
│  │  │ 5. Wyoming ← TTS            │  │ │
│  │  │    ↓                        │  │ │
│  │  │ 6. Play Audio (speakers)    │  │ │
│  │  └─────────────────────────────┘  │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
           ↕ WebSocket (Wyoming Protocol)
┌─────────────────────────────────────────┐
│  SARA BACKEND (FastAPI)                 │
├─────────────────────────────────────────┤
│  /wyoming/asr  → Faster-Whisper (STT)  │
│  /wyoming/tts  → TTS Service            │
│  /chat         → Tool Execution         │
│  /shadow/*     → Shadow Mode API        │
└─────────────────────────────────────────┘
```

---

## 🎨 System Tray UI Design

### Windows
```
 ╔═════════════════════════╗
 ║  🎙️ Sara Voice Agent   ║
 ╠═════════════════════════╣
 ║  Status: Listening      ║
 ║  Wake Word: sarah       ║
 ║                         ║
 ║  Mode:                  ║
 ║    ● Always-On          ║
 ║    ○ Shadow-Only        ║
 ║    ○ Push-to-Talk       ║
 ║                         ║
 ║  ──────────────────     ║
 ║  ⚙️  Settings           ║
 ║  📊 Show Stats          ║
 ║  🔄 Restart             ║
 ║  ❌ Quit                ║
 ╚═════════════════════════╝
```

### States
- 🟢 **Listening** - Wake word detection active
- 🔴 **Recording** - Capturing user speech
- 🟡 **Processing** - Sending to STT/waiting for response
- 🔵 **Speaking** - Playing TTS audio
- ⚫ **Idle** - In Shadow-Only mode, no session active

---

## 📦 Distribution Plan

### Windows Package
```
SaraShadowAgent-Setup.exe
  ├─ sara_shadow_agent.exe      (PyInstaller bundle)
  ├─ models/
  │  └─ sarah.tflite / sarah.onnx
  ├─ config.json                (user settings)
  └─ README.txt
```

**Installation:**
- Run installer
- Sets up auto-start (Windows Startup folder)
- Creates desktop shortcut
- Adds to system tray

### macOS Package
```
SaraShadowAgent.app
  └─ Contents/
     ├─ MacOS/sara_shadow_agent
     ├─ Resources/
     │  ├─ models/sarah.tflite
     │  └─ icon.icns
     └─ Info.plist
```

**Installation:**
- Drag to Applications folder
- First run: Grant microphone permissions
- Launch at Login (LaunchAgent)

---

## 🔧 Configuration File

`config.json`:
```json
{
  "backend_url": "ws://10.185.1.180:8000",
  "api_token": "user-api-token-here",
  "voice_mode": "always_on",  // always_on, shadow_only, ptt
  "wake_word": {
    "model_path": "models/sarah.tflite",
    "threshold": 0.5,
    "debounce_seconds": 1.5
  },
  "vad": {
    "threshold": 0.5,
    "min_speech_duration_ms": 200,
    "min_silence_duration_ms": 500
  },
  "audio": {
    "sample_rate": 16000,
    "pre_roll_seconds": 1.5,
    "echo_suppression": true
  },
  "ui": {
    "show_notifications": true,
    "auto_start": true,
    "minimize_to_tray": true
  }
}
```

---

## 🚀 Next Steps for Production

### Testing & Deployment

1. **Build Packages**
   ```bash
   # Windows (on Windows machine or cross-compile)
   cd shadow-agent
   python3 package_windows.py

   # macOS (on macOS machine)
   cd shadow-agent
   python3 package_macos.py
   ```

2. **Test End-to-End**
   - Test wake word detection on clean machines
   - Verify STT/TTS pipeline works
   - Test all 3 modes: Always-On, Shadow-Only, Push-to-Talk
   - Verify system tray controls work
   - Test barge-in and echo suppression

3. **Deploy to Production**
   - Upload packages to backend server
   - Verify download endpoints work
   - Add link to voice agent download in main Sara UI
   - Update documentation with setup instructions

4. **Future Enhancements**
   - Auto-update mechanism
   - Settings UI panel (instead of editing config.json)
   - Voice feedback/confirmation sounds
   - Multi-language support
   - Custom wake word training UI

---

## 💬 What We'll Be Able to Do

Once complete:

```
User: [Opens computer]
Agent: [Starts in system tray, listening for "sarah"]

User: "sarah"
Agent: [Ding! Pre-roll buffer activated, VAD listening]

User: "shadow me for 30 minutes while I work on authentication"
Agent: [Sends audio → STT → "shadow me for..."]
       [Tool: start_shadow_session(duration=30, context="authentication")]
       [TTS: "Shadow Mode session started for 30 minutes..."]
       [Plays audio through speakers]

... work continues ...

User: "sarah"
Agent: [Listening...]

User: "wrap up my shadow session"
Agent: [STT → Tool → Summary generation]
       [TTS: "Your shadow session summary: 3 tasks, 2 decisions..."]
```

All controlled from the system tray!

---

**Status:** ✅ **Phase 2 is 100% COMPLETE!**

All core components implemented:
- ✅ Voice pipeline (Wake word → VAD → STT → TTS)
- ✅ Audio orchestrator with full state machine
- ✅ System tray UI with mode switching
- ✅ Windows and macOS packaging scripts
- ✅ Backend download endpoints
- ✅ Frontend download page

**Ready for building and testing!**
