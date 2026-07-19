# Desktop Jarvis Overhaul Plan

**Goal:** Turn the Sara desktop agent (Mac + Windows) into an always-present, overlay-driven, screen-aware companion; make the Jetson voice front-end reliable and loop-proof; and give the backend a real machine-learning layer (trained on David's own behavioral data, using the GPU cluster) so Sara predicts instead of reacts.

This is a single full plan, implemented at once — no timelines, no MVP carve-outs. Anything David must do personally (record wake-word samples, grant macOS permissions, mark home, confirm learned patterns) is built **into the product** as a guided settings flow, never a manual script.

---

## 0. Ground rules for the implementing agent

These are non-negotiable project conventions (from CLAUDE.md / project memory):

1. **Never run the backend locally.** `docker compose -f docker-compose.dev.yml build backend && docker compose -f docker-compose.dev.yml up -d backend`. Backend/celery only load code at container restart — verify the running artifact before declaring anything fixed. Restarting the backend kills in-flight dispatch tasks.
2. **All user-facing time logic in ET** via `app.core.timezone` helpers. Celery crontabs are ET. Never store `datetime.now()` naive into timestamptz — use `datetime.now(timezone.utc)`.
3. **LLM calls for short outputs** must pass `enable_thinking: False` (Qwen returns empty `content` otherwise). LLM stack is Qwen3.6-27B primary / Qwen3.5-35B-A3B fast. Never reference gpt-oss. Never use the word "Expo" for the push system.
4. pgvector casts: `CAST(:param AS vector)`, never `:param::vector`.
5. Desktop actuator tools (typing, clipboard) keep `requires_user_origin = True`.
6. **Attention-queue gotcha:** with `autonomy_attention_enabled`, only high/urgent/critical push to phone; normal/low become silent inbox items. Desktop deliveries in this plan therefore go over the **device WebSocket** (command_router), not the push pipeline.
7. Route registration outside try/except; `extend_existing = True` on models mapping to existing tables.
8. New DB migrations continue the alembic sequence (latest is `080_location_awareness.py`; `081`/`082` may be claimed by the SARA_100 work — check `backend/alembic/versions/` and take the next free numbers).

---

## 1. Verified current state (grounded in code)

### 1.1 Desktop app (`sara-desktop/`)

- Electron 28 + Vite/React. Windows created by `electron/main.ts`: **circle/orb** (240×120, smoke-ring canvas + attention count from `/autonomy/attention/count`), **chat popup** (320×450, `MiniChat.tsx` → `POST /chat/stream` SSE), **NoteViewer**, **TimerFloat**, **Settings** (email/password login → JWT stored in `sara-settings.json`). Tray menu, auto-update via electron-updater against `https://sara-api.avery.cloud/api/updates` (served by `backend/app/routes/desktop_updates.py` from `/updates`).
- Orb **fades to 20% opacity after 10 min inactivity** (`INACTIVITY_TIMEOUT` in main.ts) — the opposite of "always lives on my screen".
- Only the **primary display** is used everywhere (`screen.getPrimaryDisplay()`); screenshots grab monitor 1 only (`sct.monitors[1]` in `sidecar/screenshot.py`).
- **Python sidecar** (`sara-desktop/sidecar/`, PyInstaller-frozen on Windows only): activity monitor (pynput + per-OS active window), focus tracker (spans → `focus_span` WS messages), screenshot service (mss, 30s default, mode-aware 10s/60s via `/api/cognitive/mode`, perceptual-hash dedupe, uploads to `/api/vision/screenshot`, metadata to `/api/cognitive/raw-buffer/screen`), psutil metrics, actuators (`write_clipboard`, `focus_window`, `type_into_window`, `open_url`). Talks to backend over `wss /api/devices/ws/{device_id}?token=` and to Electron over local WS `127.0.0.1:9876`.
- **Command plane:** `app/services/command_router.py` (in-memory WS registry) + `app/routes/device_commands.py`. `CommandType` enum: OPEN_URL, SHOW_NOTE, SHOW_TIMER, TAKE_SCREENSHOT, SPEAK, SHOW_NOTIFICATION, START_LISTENING, OPEN_WORKSPACE, WRITE_CLIPBOARD, FOCUS_WINDOW, TYPE_INTO_WINDOW. **`SPEAK` and `START_LISTENING` have no sidecar handler** — they are silently dropped (`Unknown command type`).
- `unified_notification.py` already tries desktop delivery first (SHOW_NOTIFICATION over WS) before push. Good — keep and extend.
- Chat gaps: `/chat/stream` emits `ui_command` SSE events (see 1.3) but the desktop client **ignores them**; `MiniChat.tryShowNote()` instead regex-guesses note titles out of the response text, and `checkForTimers()` polls after every reply. Both are hacks the overhaul deletes.
- **Mac is configured but not actually shipped:** electron-builder has a mac zip target, but `extraResources` only bundles `sidecar.exe`, there's no frozen mac sidecar, no mac artifacts in `release/`, no `latest-mac.yml` in the update feed, and no macOS permission flow (Screen Recording / Accessibility / Microphone / Input Monitoring), without which mss, pynput, and active-window tracking silently fail.
- Device registry: `machine` table (3 devices registered), `machine_registry.py` (60s offline threshold, activity_level idle/low/medium/high, active app/window, friendly names), `/api/devices/list|active|connected|register|{id}/name`.
- Desktop→backend awareness already flows: `focus_span` and `activity_state` WS messages → `event_bus` (`DESKTOP_FOCUS_SPAN`, `DESKTOP_ACTIVITY_STATE`) → salience → ACS working memory. `activity_state_machine.py` consumes desktop signals (`_handle_desktop`).

### 1.2 Jetson voice (`/home/david/Projects/sara-voice`, deployed copy snapshot in `jarvis/.tmp/jetson-sara-voice-full/`)

- Pipeline: AIRHUG speakerphone 48k→16k mono → noise gate (disabled in config) → custom openWakeWord `hey_sara.onnx` (threshold 0.5, CPU ONNX) → Silero VAD → STT (remote faster-whisper `10.185.1.8:8585`, local whisper fallback) → `POST /api/pi-dashboard/voice/chat` (full tool-calling SSE chat in `main_simple.py:6298`) → Kokoro TTS `10.185.1.9:8880` (af_heart) → PCM streamed over a WS **server on the Jetson (`:8765`)** to a desktop client that plays it through desktop speakers.
- The desktop-side player is a **`voice_bridge.py` that exists only on David's Windows machine** — it is not in any repo. The deployed Jetson code (`.tmp/jetson-sara-voice-full`) is **ahead of the repo**: it has `set_listening`/`get_status` handlers, bare-PCM audio framing, a speaker-verification client, an audio-state asyncio lock, and speech-end reentrancy guards. The repo copy has none of that. **Source of truth is fragmented — this must be reconciled first.**
- State machine: IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN(5s)→IDLE, barge-in from SPEAKING, goodbye phrases, timeouts checked every 0.5s.
- **Why it loops when audio is playing (root causes, all verified in code):**
  1. **No real echo cancellation.** `aec.py` is gain suppression during playback + a 500ms fade tail. TTS plays from *desktop* speakers; the AIRHUG mic hears it. In COOLDOWN/LISTENING the VAD picks up Sara's own voice or the TV → transcript → new backend call → new TTS → loop.
  2. **Barge-in is a raw RMS threshold** (0.05 for 200ms) with no speech/speaker discrimination — music or keyboard noise interrupts Sara mid-sentence, transitions to LISTENING, records the ambient audio, and continues the loop.
  3. **Ambient wake threshold boost is dead code** — `wake_word.set_ambient_active()` is never called by anything, so music/TV get the same 0.5 threshold.
  4. **No local "stop" escape hatch.** Goodbye phrases only work via a full STT round trip in LISTENING. While SPEAKING there is no way to kill it except muting the mic — exactly David's complaint.
  5. `wait_for_playback_complete(timeout=30)` + desktop `playback_complete` reports are the only playback truth; if the bridge client disconnects mid-utterance the echo state is wrong for the whole tail.
  6. The webapp's mute toggle (`/api/sensory/voice-agent/listening`) targets handlers that only exist in the deployed copy — one code sync away from breaking.
- **Control plane already scaffolded, not finished:** `routes/voice_control.py` (config sync, model registry, `train_wake_word`/`train_speakers` job queue, internal-token auth, event stream), `jetson/wake-sensor/` (scaffold; live audio "pending"), webapp **Wake Word Lab** (`frontend/src/components/sensory/SensoryControlPlane.tsx` — dataset recording via `/api/sensory/datasets/...` which records clips *on the Jetson*), `gpu-cluster/` speaker-training worker + enrollment + diarization services.

### 1.3 Overlay/UI intent plane (webapp — the pattern to reuse)

- `app/services/ui_intent.py` intercepts "show me / bring up / pull up X" *before* the LLM and emits a `ui_command` SSE event (`{action: 'open_overlay', overlay: kind, payload}`) plus a one-line ack. Known overlay kinds: `brief`, `nutrition`, `calendar`, `tasks`, `note`. iOS additionally gets `navigate` actions for ~14 screens.
- `frontend/src/components/overlay/SaraOverlayHost.tsx` renders those overlays over any view (BriefContent, NutritionContent, CalendarContent, TasksContent, NoteContent).
- All the data surfaces the user asked for already have APIs: notes CRUD, `/api/fitness/food-log*` (+ `food_search_and_log` tool), `/api/morning-brief/today`, `/api/research-brief/today`, `/api/reports/intelligence/*`, timers, reminders, calendar, assistant inbox.

### 1.4 "ML" today (all heuristic, no trained models)

- Salience scoring (`salience.py`, threshold 1.5), attention learning (`attention_learning.py` — engagement-weighted category policies + decay), Thompson-sampling exploration bonus (`thompson_sampling.py`), `behavioral_pattern` table (45 rows; detection cycle runs inside `nightly_dream_service.py`), daily-rhythm learner (`daily_rhythm.py` + recompute task), `predictive_engine.py` (SQL heuristics over calendar/patterns/rhythm, 30-min Celery task), hand-coded `interruptibility.py`, notification tuner, `implicit_feedback_detector.py`.
- GPU cluster (`10.185.1.8`, multiple GPUs) currently serves only audio (ASR 8585, diarization 8002/8004, enrollment 8003) but already has the **job-claim worker pattern** (`speaker_training_worker.py` claims jobs from voice-control queue) — the template for ML training workers.
- Rich per-user event data already lands in Postgres: focus spans, desktop activity states, locations/geofences, HealthKit, food logs, workouts, calendar, notification outcomes, episodes, agent_run_log. **Nothing consumes it for statistical learning.**

---

## 2. Architecture decisions

**D1 — Overlays are webapp surfaces rendered in frameless Electron windows.**
Rebuilding notes/nutrition/reports natively in `sara-desktop` would fork three UIs. Instead the webapp gets standalone **overlay routes** (`/overlay/<kind>`, chrome-less, dark, compact) and the desktop opens them in transparent always-on-top BrowserWindows. One implementation serves webapp overlays, desktop overlays, and future surfaces. Native-in-Electron stays only for: the orb/HUD, mini chat, quick-jot blank note, voice-note recorder, timers, and toasts (things that must work instantly and offline-ish).

**D2 — One command vocabulary end-to-end.**
`ui_intent` + chat tools + proactive services all speak `open_overlay(kind, payload)`; `command_router` gains `OPEN_OVERLAY` and the desktop honors the same kinds the webapp does. Delete the desktop-side regex/polling hacks.

**D3 — TTS playback moves to the AIRHUG itself (hardware AEC), desktop becomes a secondary sink.**
The AIRHUG is a speakerphone with onboard echo cancellation — but today Sara's voice comes out of the *desktop* speakers, which the AIRHUG mic hears raw. Playing TTS out of the AIRHUG speaker makes its hardware AEC do the work software can't (the reference signal lives where playback happens). Desktop playback remains available as a routed choice ("play on my PC") and as fallback, with the existing echo-state suppression.

**D4 — The unshipped `voice_bridge.py` is absorbed into the sidecar.**
The sidecar gains a `voice/` module: Jetson-bridge client (when at home), local mic capture (push-to-talk / record-a-note / wake-word when away from home), local TTS playback for `SPEAK`, and playback-state reporting. No more orphan scripts on one machine.

**D5 — ML = classical models first, GPU cluster for training + embeddings, shadow-then-promote.**
Single-user data volumes make LightGBM/logistic models the right first tier (interruptibility, notification engagement, next-action). The GPU cluster runs training jobs (generalizing the existing voice-control job queue), embedding/rerank workloads, and wake-word/speaker training. Every model ships in **shadow mode** (logged predictions vs. current heuristic) and is promoted per-model via settings once its logged accuracy beats the heuristic. Nothing user-facing flips silently.

**D6 — "Active device" becomes a first-class, event-driven fact.**
The machine registry already knows; the plan adds a presence resolver + events + context injection so Sara always answers "where is David active right now" the same way everywhere (chat context, routing, overlays, voice-note device selection).

---

## 3. Workstream A — Desktop agent overhaul

### A1. Always-present HUD (the orb grows up)

`sara-desktop/electron/main.ts` + new `src/components/hud/`:

- **Never disappears.** Remove the 10-minute fade-to-20% behavior; replace with a subtle "resting" style. Settings: `hudMode: 'always' | 'dim-when-idle' | 'hide-when-fullscreen'` (default `always`; detect fullscreen apps via sidecar active-window info and auto-dodge if configured).
- **Multi-monitor:** persist position per display id (`screen.getAllDisplays()`), follow the display where the cursor/active window is when `followActive` is on, and clamp on `display-metrics-changed` / `display-removed`.
- **Orb states**, driven by backend + sidecar events over the existing bridge and a new backend→device event channel (A3): `idle`, `listening` (jetson or local mic live), `thinking` (chat/agent streaming), `speaking` (TTS playing), `attention` (inbox count > 0, already partially built), `alert`. Voice states sync from the Jetson via backend events so the on-screen orb glows when "hey Sara" lands — the visible confirmation the wake word worked.
- **Hover flyout (mini-HUD):** attention count, active timers, next calendar event, "Sara's status" line (current autonomy activity from `/api/sara-status`), quick actions: New note · Record voice note · Screenshot & ask · Open chat · Mute voice. Data fetched on open only (same discipline as SPRITE_HUD_SPEC.md).
- **Global hotkeys** (electron `globalShortcut`, all rebindable in settings): summon chat (`Ctrl/Cmd+Shift+Space`), quick-jot note (`Ctrl/Cmd+Shift+N`), record voice note (`Ctrl/Cmd+Shift+R`), screenshot-and-ask (`Ctrl/Cmd+Shift+S`), cancel Sara's speech (`Esc` double-tap while speaking).

### A2. Overlay window system

**Webapp side** (`frontend/`):

- New standalone entry route `/overlay/:kind` (rendered without nav shell; reuse `SaraOverlayHost` content components). Kinds at launch:
  - `note` (payload: note_id | full content) — full note editor, not read-only; saves via existing notes API.
  - `blank-note` — new-note editor, autosaves, `[[link]]`-aware.
  - `nutrition` — food log + quick add + macro summary (`/api/fitness/food-log*`); this is the "log food" window.
  - `brief` — morning brief (`/api/morning-brief/today`).
  - `report` (payload: `{report_type, id|date}`) — renders research briefs (`/api/research-brief/*`), intelligence reports (`/api/reports/intelligence/*`), health reports, and finished agent/background-task results (`task_result_delivery` output). "Freshly run reports" == most recent artifact of each type; provide `/overlay/report?latest=<type>`.
  - `calendar`, `tasks`, `timers`, `inbox` (assistant inbox triage), `recipes`.
- Auth for Electron: overlay routes accept the JWT the desktop already stores (`Authorization` header via fetch interception is impossible in a plain BrowserWindow load, so support `?token=` one-time exchange → sets the normal HTTP-only cookie via a tiny `/auth/token-cookie` endpoint, then redirects to the overlay path without the token in the URL).

**Desktop side** (`electron/main.ts`):

- `createOverlayWindow(kind, payload)`: frameless, resizable, always-on-top, remembers per-kind size/position, ESC closes, multiple simultaneous overlays allowed (Map keyed by kind+id). Loads `${webappBase}/overlay/${kind}?…`.
- Overlay origins that all converge on the same function:
  1. Backend command `OPEN_OVERLAY` (new `CommandType`; payload `{kind, payload}`) — sent by chat tools, `ui_intent`, and proactive services.
  2. `ui_command` SSE events in MiniChat (finally handled): `open_overlay` → IPC → main. Delete `tryShowNote()` and `checkForTimers()`.
  3. HUD quick actions + hotkeys.
- Keep the lightweight native NoteViewer/TimerFloat for the tiny always-on-top timer chip; notes now open the real editor overlay.

**Backend side:**

- `ui_intent.py`: extend `_SURFACES` with `report`, `timers`, `inbox`, `blank note`/"new note", `recipes`; add an `allow_desktop_overlays` capability flag mirroring `allow_screens` so voice/chat sessions originating from a device with a connected desktop emit `open_overlay` commands via `command_router` too (not just SSE — voice from the Jetson has no SSE UI).
- New/updated chat tools in `app/tools/device_commands.py`:
  - `device_open_overlay(kind, payload?, device_name?)` — generic.
  - Update `device_show_note` to send `OPEN_OVERLAY {kind:'note', payload:{note_id}}` (full editor) instead of the static popup.
- Proactive path: `unified_notification.py` desktop branch gains an optional `overlay` field — when a notification carries a surface (e.g. morning brief ready, report finished, meeting prep), the desktop toast includes an "Open" action that opens the overlay (toast → IPC → `createOverlayWindow`).

### A3. Command protocol + realtime event channel

- Add to `CommandType` and sidecar/Electron handlers: `OPEN_OVERLAY`, `RECORD_VOICE_NOTE`, `CANCEL_SPEECH`, `HUD_STATE` (backend-pushed orb state), and implement the already-enumerated `SPEAK` (sidecar synthesizes via Kokoro `10.185.1.9:8880` and plays locally through the new audio module; reports `playback_state` back so echo suppression and orb state stay truthful).
- **Capability negotiation:** device registration payload gains `capabilities` actually used (today it's hardcoded `["screenshot","wake_word","commands"]`): `overlays`, `tts`, `mic`, `screenshot`, `actuators`, `multi_monitor`. `command_router.send_command` checks target capability and falls back cleanly (e.g., no `tts` → push notification instead).
- **Backend→device events:** reuse the existing device WS. New server→client message `{type:'event', event:'hud_state'|'voice_state'|'attention_count'|'timer_update', data}`. `salience_subscriber`/voice pipeline publish voice_state (`listening/thinking/speaking/idle`) so the desktop orb mirrors the Jetson conversation in real time. Electron subscribes via sidecar bridge forwarding (sidecar already forwards `activity_update`/`system_metrics`; add generic `event` forwarding).
- Command **acks with results**: `send_command` today is fire-and-forget; add `command_router.send_command_and_wait(command, timeout)` using the existing `command_result` message (sidecar already sends it for `get_metrics`) keyed by `command_id`. Required for A5.

### A4. Quick capture — blank note + voice notes

- **Quick-jot:** hotkey/HUD → small native editor window (instant open, no web load), first line = title, save → `POST /notes` → toast with "Open full note" (overlay). Offline-safe: queue in local store, flush on reconnect.
- **Voice note ("record a note"):**
  - New sidecar `voice/recorder.py`: opens default input device (`sounddevice`), 16k mono, streams to a temp WAV with live level meter events to the renderer; stop on hotkey/click/silence-timeout. Transcribe via ASR `http://10.185.1.8:8585/v1/audio/transcriptions`; create note titled "Voice note — <ET timestamp>" with transcript (+ store the audio in MinIO via documents API, linked from the note); open the note overlay for review.
  - **Device selection rule (the "unless I'm at home" requirement):** backend tool `record_voice_note` decides the capture device: if presence resolver (A7) says David is home **and** Jetson is healthy (`/api/sensory/status`) → send `RECORD_VOICE_NOTE` to the Jetson path: backend publishes a `record_note` control message to the Jetson (extend the `:8765` control channel / `wake_sensor` control plane), Jetson captures with its far-field mic, uses the same ASR, posts the note, and the active desktop shows the "recording…" orb state + resulting note overlay. Otherwise → `RECORD_VOICE_NOTE` command to the active desktop.
  - Triggerable from: chat ("record a note"), voice ("Sara, take a note" — added to Jetson intent handling as a local fast-path phrase), hotkey, HUD.

### A5. Screen awareness — "what am I looking at?"

Current gap: `device_take_screenshot` returns "requested, will upload shortly" — the model never sees the pixels in the same turn.

- Sidecar `take_screenshot` handler gains `return_result: true` mode: captures (all displays; pick focused display via cursor position), uploads to `/api/vision/screenshot`, and sends `command_result {screenshot_id}`.
- `DeviceTakeScreenshotTool.execute` uses `send_command_and_wait` (timeout ~10s), then runs the existing vision-analyze path (`routes/vision.py` `call_openai_vision`/`call_ollama_vision`, downscaled via `_downscale_for_vlm`) with the user's question as the prompt, and returns the analysis text as the tool result. Chat and voice both get in-turn answers to "what's this?".
- **Trigger phrases from voice:** the Jetson conversation flow passes through the same chat endpoint, so the tool "just works" — but add `screen`/`what am I looking at`/`what's this on my screen` to the tool-intent classifier's device category so the tool actually loads for those turns.
- Multi-monitor: `screenshot.py` captures the display containing the foreground window (fallback: all monitors stitched, capped width) instead of always `monitors[1]`.
- Privacy: per-device screenshot toggle already exists (`machine.screenshot_enabled`); surface it in the desktop settings panel and HUD (camera-off badge on the orb when ambient capture is disabled; on-demand "screenshot & ask" still allowed with an explicit click/hotkey).

### A6. Sidecar audio module + Jetson bridge client

New `sara-desktop/sidecar/voice/` package:

- `playback.py` — sounddevice output stream; plays PCM from Jetson bridge or local Kokoro TTS; emits `playback_state` (is_playing) to both the Jetson bridge (echo state, existing contract) and the backend WS (for orb state + `/api/sensory/audio-playback`).
- `jetson_client.py` — the reconciled `voice_bridge.py`: connects to `ws://<jetson>:8765` **only when on the home network** (config: jetson host + reachability probe), handles bare-PCM frames, `stop_playback`, reports `playback_complete`. Auto-reconnect with backoff.
- `mic.py` — shared capture for A4 recorder and a **push-to-talk chat input** in MiniChat (hold hotkey, speak, release → ASR → send as chat message). This gives desktop voice interaction even away from the Jetson without running a local wake word yet; an optional local openWakeWord mode (`desktop_wake_word_enabled`, default off) can reuse the same model file the control plane distributes.
- System-audio awareness: report "desktop media playing" (Windows: `GlobalSystemMediaTransportControls` via winsdk; macOS: `NowPlaying` info via `mediaremote` fallback to CoreAudio output level) as a `media_state` heartbeat field → stored on machine + published to event bus. This feeds the Jetson's ambient-mode wake thresholding (B2) — Sara *knows* the TV/music is on before deciding how sensitive to be.

### A7. Unified device presence ("always know what device I'm active on")

- New `app/services/device_presence.py`:
  - Resolver: rank sources — desktop heartbeats (activity_level + last_activity_at), iOS presence (`routes/presence.py`), Jetson desk presence (face detection events), HA/location (home vs away) — into a single `{active_device, location_context, confidence, since}`.
  - Publishes `DEVICE_ACTIVE_CHANGED` on the event bus when the answer changes (debounced ≥60s); snapshot cached in Redis working set.
  - `GET /api/devices/presence` returns the snapshot; `command_router.get_active_device_id` delegates to it (keeps its connected-check).
- **Context injection:** `unified_context.py` adds one line to chat/voice context: "David is currently active on <friendly_name> (<platform>, <activity_level>); location: <home/work/away>." — the difference between Sara guessing and knowing.
- Heartbeat cadence: sidecar heartbeat stays as-is; registry `OFFLINE_THRESHOLD_SECONDS` (60) is fine; make the sidecar send an immediate heartbeat on resume-from-sleep/unlock (Electron `powerMonitor` → bridge message → sidecar) so switching machines registers in seconds, not a minute.

### A8. Mac parity (the second desktop client, for real)

- Build pipeline: `scripts/build-sidecar.sh` already exists — produce a frozen mac sidecar (PyInstaller, arm64 + x64 or arm64-only per David's hardware) and add it to `extraResources` per-platform; `npm run build:mac` producing zip + `latest-mac.yml`; publish both platforms' artifacts to `/updates` (document the copy step in `DEPLOYMENT.md`; keep the generic provider).
- macOS specifics in sidecar: active-window via existing AppleScript path (works but needs Automation permission), screenshots need **Screen Recording** permission, pynput needs **Input Monitoring/Accessibility**, mic needs **Microphone**. Add `sidecar/permissions_macos.py` that detects each grant state (attempt + catch, or `CGPreflightScreenCaptureAccess` via pyobjc) and reports a `permissions` map in the heartbeat.
- **Onboarding panel in the desktop Settings window** (both OSes, content differs): checklist UI driven by the sidecar's permission report — each row: status ✅/❌, "Open System Settings" deep link (`x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture` etc.), re-check button. Windows rows: autostart, mic device selection. Nothing requires David to read a doc — the app walks him through it.
- Tray/menu-bar behavior verified on mac (template icon, no dock icon: `app.dock.hide()` + `LSUIElement`).

### A9. Desktop settings panel (in-app, complete)

Replace the current minimal SettingsModal with a tabbed settings window:

1. **Account** — login/logout, backend URL, connection status (backend WS, sidecar, Jetson bridge).
2. **Appearance/HUD** — hud mode, follow-active-display, orb size, hotkey editor.
3. **Overlays** — default sizes, "open reports automatically when finished" toggle, per-kind enable.
4. **Privacy** — ambient screenshots on/off + interval, focus tracking on/off, media-state reporting on/off; every toggle writes through `PATCH /api/devices/{id}/config` (extend `update_machine_config`).
5. **Voice** — mic device picker + level meter, push-to-talk hotkey, local wake word toggle, TTS voice/speed (Kokoro params), "at home use the Jetson" toggle.
6. **Permissions** (A8 onboarding lives here permanently).
7. **About/Updates** — version, check now (exists), release notes.

### A10. Hardening

- Sidecar lifecycle: existing port-9876 takeover logic is Windows-only for force-kill — add POSIX (`lsof -ti :9876 | xargs kill`). Sidecar auto-restart by Electron on crash (relaunch with backoff, max 5/hour).
- Backend WS reconnect keeps exponential backoff; add jitter; on 4001 (invalid token) surface a re-login prompt in the HUD instead of silent retry loop.
- All new IPC channels go through `preload.ts` with explicit APIs (no `nodeIntegration`).
- Command idempotency: include `command_id` on every command (already partially present); sidecar dedupes replays after reconnect.

---

## 4. Workstream B — Jetson voice overhaul

### B1. Reconcile and own the code

- Diff `.tmp/jetson-sara-voice-full/` against `/home/david/Projects/sara-voice` and land the deployed improvements (set_listening handlers, speaker_verification client, `_audio_state_lock`, `_speech_end_in_flight` guard, bare-PCM framing, VAD re-arm on empty speech) into the repo. Move the project into `jarvis/jetson/sara-voice/` (monorepo, next to `wake-sensor`), keep the systemd unit, and add `jetson/sara-voice/deploy.sh` (rsync + systemctl restart over the existing SSH access). Delete `.tmp/` copies once merged. The Windows-only `voice_bridge.py` is superseded by A6 and retired.

### B2. Kill the loops (layered defense, all together)

1. **Hardware AEC via AIRHUG playback (D3):** add `audio/local_playback.py` on the Jetson — TTS PCM plays out the AIRHUG's speaker (sounddevice output on the same device). Config `tts.sink: airhug | desktop | both` (default `airhug`). The AIRHUG's built-in echo cancellation then removes Sara's own voice from the mic signal at the source. Desktop sink remains for "play this on my PC" and as automatic fallback when the AIRHUG output fails.
2. **Self-voice + media gating:** while `echo_state` is active (any sink) **and** for the tail window: wake word suppressed (exists), VAD suppressed (new — currently VAD runs in COOLDOWN and picks up residual TTS), barge-in requires the stronger test below.
3. **Real barge-in:** replace raw RMS with Silero VAD speech confidence (≥0.7 sustained 300ms) **and** — when the speaker-verification service is reachable — a quick embedding check against David's TitaNet profile (`gpu-cluster` verify endpoint, 300ms budget; skip check on timeout). Music no longer interrupts; David still can.
4. **Ambient-aware thresholds, actually wired:** `wake_word.set_ambient_active(True)` when (a) desktop `media_state` says media is playing (from A6, via backend → Jetson control message), or (b) the Jetson's own noise-floor estimator (noise_gate's ambient window — enable it for measurement even with gating off) exceeds a floor. Boosts wake threshold (+0.15, existing knob) and barge-in requirements.
5. **Local stop phrase — the escape hatch.** Train a second tiny openWakeWord model for "sara stop" (same Wake Word Lab pipeline, B3) that runs in **all states**, bypasses the conversation state machine, and immediately: stops TTS (local + desktop `stop_playback`), clears VAD buffers, transitions `force_idle("stop phrase")`, and plays a short "ok" chime. Until the custom model is trained, fall back to a keyword check on any LISTENING transcript prefix and a 2× wake-word-during-SPEAKING trigger (wake word heard while Sara speaks = interrupt+idle, not re-wake).
6. **Cancel from every surface:** desktop hotkey/HUD button and webapp/iOS mute both send `CANCEL_SPEECH` → backend → Jetson control channel (`stop_playback` + `force_idle`). The existing `/api/sensory/voice-agent/listening` toggle now targets handlers that exist in the repo (B1).
7. **Loop breaker of last resort:** conversation watchdog — if ≥4 turns occur with no verified-David speech (speaker verification says non-David or unknown for every turn), or ≥8 turns in 3 minutes, force idle + suppress wake for 60s + send a desktop toast "Voice paused — I kept hearing audio that didn't sound like you. Tap to resume."

### B3. Wake word quality (and the "record hey sara" product flow)

- **Finish `jetson/wake-sensor`** as the wake front-end service: real audio adapter (share the capture ring buffer with sara-voice or subsume sara-voice's wake stage), openWakeWord model loading from the control-plane registry, runtime model reload on `activate` events, ambient calibration loop reporting `ambient_db` in heartbeats.
- **Training pipeline on the GPU cluster:** implement the actual trainer invoked by the existing `train_wake_word` job flow — openWakeWord's synthetic-plus-real recipe: David's recorded positives (Wake Word Lab datasets, recorded on the Jetson mic — the mic that matters), TTS-augmented positives, negatives from ambient recordings + music/TV segments + Sara's own TTS voice saying non-wake phrases (hard negatives against self-trigger). Output ONNX, register version via `/api/voice-control/models/wake_word/versions` with FAR/FRR metrics from a held-out set, manual activate from the Lab (auto-activate stays off).
- **Wake Word Lab UX finish** (webapp `SensoryControlPlane.tsx`, plus link from desktop settings Voice tab): guided session — "Say 'Hey Sara' naturally… 3 of 25", variations prompts (across the room, quiet voice, with music on), live sample count/playback/delete (endpoints exist), then "Record 10 minutes of ambient room noise" for negatives, then a **Train** button (queues the job; job status timeline exists), then a **Live test** mode: model in shadow on the Jetson streaming detection scores to the UI (via `/api/voice-control/events/stream`) so David can compare old vs. new before activating. Same flow, second tab, for the "sara stop" model and for speaker enrollment (endpoints exist under `/api/sensory/speakers/*`).
- Detection telemetry: every wake trigger logs score/threshold/ambient state to voice events; a weekly rollup lands in the learning digest ("wake word: 41 triggers, 2 while media playing, est. 1 false").

### B4. Conversation feel

- Wake acknowledgment: local chime + orb flash on desktop (voice_state events, A3) within 300ms — no more wondering whether she heard.
- Transcripts of voice conversations already join recent chat history (voice/chat cross-device context) — surface them: desktop MiniChat shows the live voice turn ("🎤 …transcribing"), and voice turns appear in conversation history everywhere.
- COOLDOWN follow-ups keep working but now VAD-in-cooldown requires verified speech (B2.3 logic) so the TV can't extend conversations.
- Latency: keep the current collect-full-response-then-TTS, but stream TTS per sentence (Kokoro is already low-latency; `sentence_pause_ms` exists) — begin speaking after the first sentence of the LLM stream instead of the full response. (`_get_and_speak_response` currently buffers everything.)

### B5. Voice-driven overlays

"Sara, open my nutrition window" spoken to the Jetson → voice chat endpoint → `ui_intent` (already intercepts) → but the emitter is SSE-only. Route through `command_router.send_command(OPEN_OVERLAY…)` to the **active desktop** when the session origin is voice/jetson (A2 backend work). Confirmation is spoken ("On your PC.") + overlay appears. This closes the loop the user explicitly asked for: voice as the remote control for desktop surfaces.

---

## 5. Workstream C — Real machine learning in the backend

### C1. Feature foundation (one place, nightly, ET-aware)

New `app/services/ml/feature_store.py` + Celery task `app.tasks.ml.materialize_features` (nightly, after consolidation):

- `ml_feature_daily` (migration): one row per user-day — activity-span aggregates per app-category, first/last desktop activity, location timeline summary, sleep/health metrics, workout/food flags, calendar load, notification counts+engagement, voice interaction counts. Built from existing tables (focus spans land in agent working memory/events — persist them properly first: add `desktop_focus_span` table written by the `DESKTOP_FOCUS_SPAN` subscriber; today they're transient).
- `ml_notification_outcome`: per notification — features at send time (hour, activity state, interruptibility score, device, category, day-of-week, location) + outcome (opened/acted/dismissed/ignored, latency). Sources: `notification_log` + implicit feedback detector + inbox interactions.
- `ml_prediction_log`: model, version, features hash, prediction, later-ground-truth, for every shadow/live inference.

### C2. Training + serving infrastructure (GPU cluster)

- **Generalize the job queue:** rename/extend the voice-control job tables/endpoints into a generic ML job plane (`/api/ml/jobs/claim`, `/api/ml/jobs/{id}/status`, `/api/ml/models/{family}/versions`, internal-token auth — same pattern, same code lineage as `voice_control.py`; keep the voice families working).
- **`gpu-cluster/ml-worker/`** (Dockerfile.ml + worker): claims `train_model` jobs, pulls features from Postgres (read-only creds), trains (LightGBM/sklearn for tabular; PyTorch available for sequence models later), evaluates walk-forward (train on days 1..N-14, test on last 14), writes model artifact to MinIO, registers version with metrics. Runs on `10.185.1.8` beside the audio services.
- **Serving:** models are small — load in-backend. `app/services/ml/inference.py`: loads active model versions from MinIO at startup/refresh, exposes `predict(model_family, features) -> (score, version)`, logs to `ml_prediction_log`. No network hop in the hot path.
- `ml_model_version` table: family, version, artifact_key, metrics json, status (`shadow` | `active` | `retired`), activated_at.
- Nightly `app.tasks.ml.retrain_all` queues one job per family; weekly eval report appended to the learning digest.

### C3. The first four model families

1. **Interruptibility v2** (binary: "good moment to engage"). Features: activity state, focus-span app category + span length so far, calendar-in-meeting, location, time-of-day/dow, media_state, recent-notification fatigue. Labels: `ml_notification_outcome` engagement. Shadow against `interruptibility.py`; once precision@deliver beats the heuristic on ≥200 labeled sends, promote — heuristic remains as floor/ceiling guardrails (never deliver during SLEEPING, always deliver critical).
2. **Notification value** (P(engage | content-category, moment)). Gates proactive sends: predicted-value threshold replaces some hand-tuned cooldowns; integrates with `notification_tuner` instead of replacing it. Anti-nag rules (memory: no repetitive nags) stay as hard constraints on top.
3. **Next-block predictor** (what is David likely doing in the next 1–3 hours). Multiclass over learned activity vocabulary (gym, deep work, meetings, meal, errand, gaming/media, away) from `ml_feature_daily` sequences + calendar + rhythm. Consumed by: morning brief ("today will probably look like…"), `predictive_engine.py` items 1/5 (replace SQL heuristics with model output where confidence ≥ threshold), calendar-prep timing, and the HUD "up next" line.
4. **Rhythm forecaster / anomaly flag**: probabilistic time windows for wake/gym/meals/wind-down (upgrade of `daily_rhythm` from point estimates to distributions) + day-level anomaly score ("today deviates from the norm — skip routine-based nags"). Anomaly high → proactive systems automatically quiet down.

Explicitly out of scope for v1 models: deep sequence models, federated anything, online learning. Revisit after the prediction log has months of data.

### C4. Make the learning visible and correctable (trains trust *and* the models)

- **"Sara's model of you" panel** (webapp Settings → Intelligence, plus overlay kind `patterns`): learned patterns (`behavioral_pattern` rows), rhythm windows, top model features/most-recent predictions with plain-language rendering, each with **Confirm / Wrong / Stop using this** actions → writes labels (`pattern.status`, feedback rows) that feed the next training run.
- Weekly digest section: "What I learned about you this week" + wake-word/voice stats (B3) + model promotions.
- Every model-driven proactive message is tagged (`source="ml:<family>@<version>"`) in `notification_log` so outcomes attribute automatically.

---

## 6. Workstream D — Proactive delivery, tied together

- **Routing rule:** proactive output goes to the active device (A7). Desktop active → HUD toast + optional overlay; phone active → existing push/inbox rules (respecting the attention-queue behavior); Jetson-present + high urgency + interruptible → spoken one-liner (SPEAK to Jetson sink) — spoken proactivity is gated by interruptibility v2 ≥ high threshold and capped 3/day (tunable).
- Report-finished events (background tasks, research briefs, deep research) → toast with "Open report" overlay action on the active desktop.
- Morning: if David sits at the desktop before having seen the brief (desk presence/first activity), one-time HUD prompt "Morning brief is ready" → overlay. (Uses first-desktop-activity event; no new scheduler.)
- All of this respects existing anti-harping ledgers (`followup_thread`, tell-once) — the plan adds delivery surfaces, not new nag sources.

---

## 7. Implementation order (dependency order, not a timeline)

1. **B1** repo reconciliation (everything voice depends on knowing what's actually deployed).
2. **A3** command protocol + event channel + capability flags (+ `send_command_and_wait`) — foundation for A2/A4/A5/A6/B5/D.
3. **A2** webapp overlay routes + Electron overlay windows + ui_intent extensions + tool updates.
4. **A1/A9/A10** HUD, settings panel, hardening. **A8** mac build + permissions onboarding.
5. **A6** sidecar voice module (playback, jetson client, mic) → retire voice_bridge.py; **A4** quick capture + voice notes; **A5** screenshot-and-answer; **A7** presence resolver + context injection.
6. **B2** loop defenses (AIRHUG playback first — it's the highest-leverage single change), **B4** conversation feel, **B5** voice-driven overlays.
7. **B3** wake-word training pipeline + Lab UX (parallelizable with 6 once the control plane pieces from 2 exist).
8. **C1→C2→C3 shadow→C4**; **D** last (it composes everything).

---

## 8. Verification checklist (each must be demonstrated, not assumed)

**Desktop**
- [ ] Orb visible after 30 min idle; survives display sleep/unplug; correct on both monitors; mac menu-bar app runs without dock icon.
- [ ] "Show me my nutrition" in desktop chat → nutrition overlay opens; food logged from it appears in iOS Fitness.
- [ ] "Open the report you just ran" (after a research brief) → report overlay with today's brief.
- [ ] Hotkey blank note → typed → saved → visible in webapp notes within seconds.
- [ ] "Record a note" away from home → desktop mic records, transcript note opens. Same phrase while home with Jetson healthy → Jetson records (desktop mic never opens), same result.
- [ ] "What am I looking at?" (chat and voice) → screenshot → VLM answer **in the same turn**, describing the actual foreground window.
- [ ] Pull network cable / sleep laptop → other machine becomes active device within ~15s (`/api/devices/presence`), chat context line updates.
- [ ] `SPEAK` command produces audio on the desktop; orb shows speaking state; echo state reported.
- [ ] Mac: permissions checklist detects each missing grant, deep-links correctly, all green → screenshots + activity + mic all function. Auto-update works on both platforms from `/api/updates`.

**Jetson**
- [ ] With music playing at conversation volume: zero wake triggers in 30 min (ambient mode), wake still works when David addresses her directly.
- [ ] Sara speaking + David silent: she never hears herself (AIRHUG sink), never barge-ins on her own voice, COOLDOWN doesn't re-trigger from TTS tail.
- [ ] "Sara stop" (or interim fallback) halts speech <500ms from any state; desktop cancel button does the same.
- [ ] Watchdog: play a podcast at her — after the capped turns she goes idle and toasts the desktop instead of looping.
- [ ] Wake Word Lab: full record→train→shadow-test→activate cycle completes from the UI; new model version live on the Jetson without SSH.
- [ ] Webapp mute toggle round-trips (`listening_status` reflects reality).

**ML**
- [ ] `ml_feature_daily` populated nightly for ≥7 days; spot-check a day against raw sources.
- [ ] Training job: queue → GPU worker claims → version registered with walk-forward metrics → artifact in MinIO → backend loads it after refresh.
- [ ] Interruptibility v2 shadow log shows side-by-side heuristic vs. model decisions; promotion flips behavior only after the settings toggle.
- [ ] "Sara's model of you" panel renders patterns; "Wrong" on one prevents it from being suggested again (existing `times_rejected` path) and lands as a training label.
- [ ] A model-tagged proactive notification's outcome appears in `ml_notification_outcome` with correct attribution.

---

## 9. File/endpoint inventory (quick reference for the implementer)

| Area | Touch |
|---|---|
| Electron main/windows | `sara-desktop/electron/main.ts`, `preload.ts` |
| HUD/overlays UI | `sara-desktop/src/components/hud/*`, `src/App.tsx`; webapp `frontend/src/overlay/*` new entry, `SaraOverlayHost` content reuse |
| Sidecar | `sara-desktop/sidecar/{main.py,screenshot.py,voice/*,permissions_macos.py}`, build scripts |
| Command plane | `app/services/command_router.py`, `app/routes/device_commands.py`, `app/tools/device_commands.py` |
| UI intent | `app/services/ui_intent.py` (+ its call site in `main_simple.py` chat stream ~L8337) |
| Presence | new `app/services/device_presence.py`, `app/services/unified_context.py`, `app/services/machine_registry.py` |
| Notifications | `app/services/unified_notification.py` (overlay action field) |
| Vision | `app/routes/vision.py`, `DeviceTakeScreenshotTool` |
| Jetson | `jetson/sara-voice/*` (moved), `jetson/wake-sensor/*`, `app/routes/sensory.py`, `app/routes/voice_control.py` |
| Wake Lab UI | `frontend/src/components/sensory/SensoryControlPlane.tsx` |
| ML | new `app/services/ml/*`, `app/tasks/ml.py`, `gpu-cluster/ml-worker/*`, migrations for `ml_feature_daily`, `ml_notification_outcome`, `ml_prediction_log`, `ml_model_version`, `desktop_focus_span` |
| Existing heuristics to integrate (not delete) | `interruptibility.py`, `predictive_engine.py`, `daily_rhythm.py`, `attention_learning.py`, `notification_tuner`, `behavioral_pattern_service.py` |

Related plans this supersedes/extends: `ASSISTANT_EXPERIENCE_PLAN.md` (presence/voice phases — this is the desktop+jetson deep dive), `SARA_100_PLAN.md` (rhythm engine — C3.4 builds on it, don't duplicate the `daily_rhythm` learner), `SPRITE_HUD_SPEC.md` (webapp sprite HUD — unrelated surface, patterns borrowed).
