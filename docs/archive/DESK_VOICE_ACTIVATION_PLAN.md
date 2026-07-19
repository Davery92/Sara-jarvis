# Desk Voice Activation Plan

**Goal:** David sits at his desk, says "hey sara …", and Sara hears him, executes, and answers out loud through his desktop speakers — seamlessly, Jarvis-style. No looping, no dead mic, no silent responses.

**Status date:** 2026-07-18. Every claim in §1 was verified live on that date (SSH to the Jetson, HTTP checks against the GPU services, diffs between the deployed tree and the repo tree). Re-verify anything load-bearing before acting on it — see the [deployed-code-lags gotcha](#gotchas).

**Audience:** an implementing agent with access to this repo (`/home/david/jarvis`, branch `assistant-experience-jarvis`), SSH to the Jetson (`david@10.185.1.84`, **no passwordless sudo**), and the backend dev host (this box, 10.185.1.180).

Related docs: `DESKTOP_JARVIS_OVERHAUL_PLAN.md` (§1.2 root-cause analysis of the voice loops, workstream B), `docs/VOICE_MODULAR_IMPLEMENTATION_PLAN.md` (target modular topology — **not** in scope here).

---

## 1. Verified current state

### 1.1 The pipeline (what exists)

```
AIRHUG speakerphone (capture-only) ──► sara-voice agent on Jetson Orin Nano (10.185.1.84)
  wake word (openWakeWord hey_sara.onnx, CPU) → Silero VAD → STT
  STT: faster-whisper @ http://10.185.1.8:8585 (distil-large-v3, CUDA int8) with local whisper.cpp fallback
  chat: POST http://10.185.1.180:8000/api/pi-dashboard/voice/chat (device-token auth, SSE,
        joins David's active conversation if <1h old — full tool-calling Sara)
  TTS: Kokoro @ http://10.185.1.9:8880 (voice af_heart, PCM sentence streaming)
  playback: PCM streamed over the Jetson's own WebSocket server :8765 ("desktop bridge")
            to a desktop client that plays it on the desk speakers
  state machine: IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN, barge-in, goodbye phrases,
                 follow-up turns without re-wake, 20-turn cap
```

Backend surface (all live): `routes/sensory.py` (`/api/sensory/*` — jetson health, vision events, conversation events, mute toggle, remote stop, speak-via-jetson, speaker/wake-word enrollment flows), `routes/voice_control.py` + `services/voice/control_plane.py` (Redis control plane: config, model registry, training jobs, event stream), voice endpoints in `main_simple.py` (`/api/pi-dashboard/voice/{transcribe,chat,speak,fast}`, `/api/voice-agent/{transcribe,speak}`). Voice replies use `VOICE_MODEL` (Qwen3.5-35B-A3B).

### 1.2 Why it is dead right now (two independent breaks)

1. **Deaf.** The deployed config (`~/Projects/sara-voice/config/config.yaml` on the Jetson) has `input_device: "AIRHUG"`. PipeWire holds the AIRHUG's raw ALSA device exclusively, so PortAudio cannot see it by name; on the Jul 14 restart the agent logged `No named device found, using system default input (index 4)` — index 4 is a **Tegra APE loopback**, i.e. silence. Last wake-word detection in the log: **2026-02-23**. The mic works and is reachable as PortAudio device `pulse` (index 24; `pactl` default source is already the AIRHUG). Additionally, David keeps the AIRHUG **hardware-muted** right now — verification (§6) requires him to unmute.
2. **Mute.** The AIRHUG reports 0 output channels — playback was always meant to go through the desktop bridge (`:8765`). **No client is connected** to it. The only clients that ever connected came from 10.185.1.180 (tests), last on Jul 13. David's desktop app is running but its sidecar predates the voice module (see §5).

Also observed: the Jetson intermittently failed to reach the backend for health reports overnight Jul 17 (19:56–23:33, `All connection attempts failed` to 10.185.1.180:8000); it recovered by morning. Worth watching, not the primary problem.

### 1.3 The two diverged code copies (THE central complication)

There are two meaningfully different versions of `sara_voice`, **each with improvements the other lacks**:

- **Deployed** (Jetson `~/Projects/sara-voice`, running as `sara-voice.service`, up since Jul 14): a Feb-2026 line with **live tuning from Feb 23** that fixed real false-wake problems, plus reentrancy hardening.
- **Repo** (`jarvis/jetson/sara-voice/`, checkpoint commit `5b90c6a6`, the "Desktop Jarvis Overhaul" workstream-B line): the audio-device fixes, local playback, loop-killing defenses, and the code the new desktop sidecar client was written against.

A snapshot of the earlier deployed tree also exists at `jarvis/.tmp/jetson-sara-voice-full/` (referenced by the overhaul plan). Treat the **live Jetson tree** as the authoritative "deployed" side, not that snapshot. A `~/Projects/sara-voice-stable` backup dir also exists on the Jetson.

**Do not blind-rsync in either direction.** The merge spec in §2 says exactly what to take from each side.

### 1.4 Shared services — all verified healthy 2026-07-18

| Service | Where | Status |
|---|---|---|
| faster-whisper STT | 10.185.1.8:8585 | healthy; transcribes (200) — old cuBLAS failure resolved via int8 compute |
| NeMo/speechbrain speaker verify + diarization | 10.185.1.8:8002 | healthy, GPU available, model loaded |
| Kokoro TTS | 10.185.1.9:8880 | healthy; returns audio (tested af_heart/wav) |
| Backend | 10.185.1.180:8000 | healthy; `/api/pi-dashboard/voice/chat` is the voice orchestrator |

---

## 2. Workstream 1 — Merge the two code lines (repo becomes source of truth)

Direction: **start from the repo copy** (`jetson/sara-voice/`), port the deployed-only improvements into it. Work file by file; the divergence was measured per file (changed-line counts from `diff`):

| File | Divergence | Repo-only (keep) | Deployed-only (port into repo) |
|---|---|---|---|
| `audio/wake_word.py` | 165 lines | `ignore_suppression` arg on `process()` (B2.5 "stop while Sara speaks" escape hatch) | **All of the Feb tuning:** `consecutive_hits_required` streak logic, `min_chunk_rms` + `min_rms_hits_required` energy filters (kills keyboard/click false wakes), `allowed_model_names` allow-list with name normalization, near-miss diagnostics (`near_miss_floor`, `near_miss_log_interval_seconds`), hard-fail `load()` when the model file is missing (no bundled-model fallback), rich detection logging (score/streak/rms), per-model `_hit_streak`/`_rms_hit_streak` dicts, `_last_detection` metadata |
| `service.py` | 594 lines | Watchdog loop-breaker (`_check_conversation_watchdog`, `_watchdog_resume`), `tts.sink` routing + `LocalPlayback` import/wiring, ambient mode (`_update_ambient_mode`, `ambient_db_floor`), desktop media-state handling (`_on_media_state_changed`), remote stop (`_on_remote_stop_request`), proactive speak (`_on_speak_proactive_request` — this is what backend `speak_via_jetson` targets), VAD-snippet barge-in (`_handle_barge_in(speech_snippet)`) | `_listening_saw_speech` tracking, `_speech_end_in_flight` reentrancy guard, `_maybe_force_speech_end_before_timeout`, wake metadata capture (`_last_wake_score` / `_last_wake_rms` / `_last_wake_monotonic` — feeds the first-turn speaker-verification override) |
| `clients/desktop_bridge.py` | 185 lines | (repo is the simpler side here) | **Deployed is richer — prefer its implementation:** utterance-id-keyed playback futures (`_resolve_playback_futures`), client dedup by client key, per-utterance chunk tracking, `backend` field in messages. Note: deployed already resolves `data.get("utterance_id") or self._active_utterance_id`, so the new sidecar client (which sends bare `playback_complete`, no utterance_id — verified) still works. Ideally also update the sidecar client to echo `utterance_id` back. |
| `audio/vad.py` | 62 | `probe_confidence()` + `reset_barge_state()` (confidence barge-in needs these) | `force_speech_end()` |
| `clients/tts.py` | 49 | `synthesize_streaming()` + `_pop_complete_sentence()` (streams TTS off SSE deltas — big latency win) | nothing significant |
| `state/conversation.py` | 33 | Confidence-based barge-in config (`confidence_threshold` 0.7, `min_duration_ms` 300, ambient boosts) replacing raw-RMS `check_barge_in`; `set_ambient_active()` | goodbye/follow-up handling differences — diff carefully, keep deployed semantics where they conflict (they're field-tested) |
| `clients/speaker_verification.py` | 10 | `timeout_override` param on `verify()` | verify both sides' return-shape handling matches after merge |
| `clients/event_reporter.py` | 11 | `report_watchdog_paused()` | — |
| `audio/noise_gate.py`, `audio/stt.py`, `clients/backend.py` | ≤11 each | trivial — take repo, eyeball the diff | — |
| `audio/local_playback.py` | new in repo | keep (needed for `tts.sink: airhug/both` and the wake chime) | n/a |
| `audio/aec.py`, vision/*, gpu/*, health/* | — | not in the measured diff set or unchanged; take repo | — |

Working method: the deployed tree is already pulled to the scratchpad of the session that wrote this plan; re-pull fresh with
`rsync -a --exclude __pycache__ david@10.185.1.84:Projects/sara-voice/ <workdir>/jetson-deployed/`
and diff per file. After merging, run the repo's `scripts/test_wake.py` / `test_vad_only.py` logic checks locally where imports allow (no audio hardware on the dev box — most tests need the Jetson).

## 3. Workstream 2 — Merged `config.yaml`

Base = repo config (`jetson/sara-voice/config/config.yaml`), with the deployed live tuning restored. The final file must have:

- **audio:** `input_device: "pulse"`, `output_device: "pulse"`, `fallback_device: "OBSBOT"` — plus the repo's comment block explaining the PipeWire situation. (Precondition, already true: `pactl` default source on the Jetson = the AIRHUG.)
- **wake_word:** `threshold: 0.86`, `consecutive_hits_required: 1`, `min_chunk_rms: 0.010`, `min_rms_hits_required: 1`, `refractory_seconds: 2.0`, `ambient_threshold_boost: 0.15`, `allowed_model_names: [hey_sara]`, `model_path: models/hey_sara.onnx`. (Deployed values — they were tuned live on Feb 23 to stop false wakes while keeping fast response. Repo's 0.5 default **will** false-wake with TV/music.)
- **vad:** repo values, but decide `max_speech_seconds`: deployed 12, repo 30. Recommend **30** (long commands are the point of "hey sara do x y z"), the watchdog now guards runaway turns.
- **speaker_verification:** `enabled: true` (service is healthy), `require_target_speaker: false` initially, and **keep the deployed first-turn-after-wake override block** (`first_turn_after_wake_*` keys) and short-utterance keys — the merged code from §2 consumes them.
- **conversation:** keep deployed's `goodbye_phrases`, `allow_followup_without_wake_word: true`, `max_turns: 20`; repo's confidence barge-in block (`confidence_threshold: 0.7`, `min_duration_ms: 300`, ambient boosts); repo's `watchdog` block (4 unverified turns, 8 turns/180s, 60s suppress).
- **noise_gate:** repo (`enabled: false`, adaptive ambient tracking on, `ambient_db_floor: -35`).
- **tts:** `url: http://10.185.1.9:8880`, `voice: af_heart`, `format: pcm`, **`sink: "desktop"`** (AIRHUG can't play audio; switch to `both` only if a real speaker is ever attached to the Jetson).
- **backend:** unchanged deployed values (base_url `http://10.185.1.180:8000`, device bootstrap, sensory base).
- **vision:** **`enabled: false` for this phase.** Repo flips it on, but it drags in InsightFace/TensorRT and the OBSBOT camera as failure modes. Desk voice first; re-enable vision as its own follow-up.
- **desktop_bridge / echo / gpu / health:** repo values.

## 4. Workstream 3 — Deploy to the Jetson

1. **Path decision (must decide, then be consistent):** the deployed install lives at `/home/david/Projects/sara-voice`; the repo's `systemd/sara-voice.service` and `deploy.sh` target **`/home/david/sara-voice`**. Recommended: adopt the repo's `/home/david/sara-voice` (clean break, matches all repo tooling), leave the old dir in place as a rollback, and make sure the **systemd unit is replaced** so only one install is live. Alternative: `JETSON_PATH=/home/david/Projects/sara-voice ./deploy.sh` and patch the unit paths — fine too, just pick one.
2. `deploy.sh` **excludes models** (`models/*.onnx`, `*.bin`, `*.npy`). Copy them from the existing install: `hey_sara.onnx`, `silero_vad.onnx`, `ggml-base.en.bin` (local STT fallback), `david_face.npy`. The merged `wake_word.load()` hard-fails without `hey_sara.onnx` — that's intentional.
3. **Sudo:** `deploy.sh` runs `sudo systemctl …` over SSH; the Jetson has **no passwordless sudo**. Run the rsync/venv part non-interactively, then have David run the sudo commands (suggest he uses `! ssh -t david@10.185.1.84 'sudo …'` from his session), or do the whole deploy with an interactive `ssh -t`.
4. **Venv:** must be created `--system-site-packages` (JetPack torch for Silero; no aarch64+CUDA torch wheel on PyPI — see `requirements.txt` note). `deploy.sh` already does this. Keep `websockets`, `openwakeword`, `sounddevice` pinned as-is unless imports fail.
5. **Verify after restart (all from logs / status, before any live test):**
   - `Audio capture started: device=<pulse index>` — **NOT** "No named device found / system default input".
   - `Wake word model loaded: models/hey_sara.onnx (threshold=0.86 …)` with `loaded=['hey_sara']`.
   - `Desktop bridge WebSocket server started on 0.0.0.0:8765`.
   - `Authenticated with Sara backend` + a successful health POST (check `GET /api/sensory/jetson/health` from the backend side, and `systemctl status sara-voice` shows the sd_notify watchdog happy).
   - No import errors from the merged modules (watch `journalctl -u sara-voice -f` through startup).

## 5. Workstream 4 — Desktop playback client (the mouth)

Facts: the sidecar voice module exists at `sara-desktop/sidecar/voice/` (`jetson_client.py` — auto-connects to `SARA_JETSON_HOST`, default 10.185.1.84:8765, with backoff; `playback.py`; `recorder.py`) and is wired in `sidecar/main.py`. David's desktop app is running **but nothing is connected to :8765**, so his machine is running a frozen `sidecar.exe` that predates the voice module (the sidecar is PyInstaller-frozen for Windows; `sidecar/dist-frozen/` and `sidecar/sidecar.spec` are the build artifacts/spec).

Steps:
1. Confirm what his desktop runs: backend `machine` table / `/api/devices/connected`, or just check `ss` on the Jetson for :8765 after each step.
2. Rebuild the Windows sidecar including the `voice/` package (PyInstaller must run **on Windows** — this cannot be done from the Linux dev box; either David runs `sidecar/setup.bat`/build script on his desktop, or ship the sidecar as a source-run for now). Verify `sidecar.spec` includes the `voice` package and its deps (`websockets`, `sounddevice`/audio backend used by `playback.py`) before building.
3. Playback device: `playback.py` plays the 24kHz int16 PCM stream — confirm it selects David's desk speakers (default output) and that `echo_state`/`playback_complete` messages flow back (the Jetson's barge-in/cooldown logic depends on them; without them `wait_for_playback_complete` falls back to timeouts and the conversation feel degrades).
4. Optional but recommended: make `jetson_client` echo `utterance_id` in `playback_complete` (see §2 desktop_bridge row).
5. Success check: Jetson log shows `Desktop client connected: ('<desktop-ip>', …) (active=1)` and it **stays** connected across app restarts (auto-reconnect backoff working).

## 6. Workstream 5 — End-to-end verification (with David at the desk)

Preconditions: David **unmutes the AIRHUG**; desktop app running with new sidecar; `sara-voice.service` freshly deployed.

1. "Hey sara, what time is it?" → wake logged (score ≥0.86), transcript correct, spoken answer from desktop speakers. Round-trip feel: target < ~3s utterance-end → first audio.
2. Follow-up without re-wake ("and what's on my calendar?") works within the follow-up window.
3. **Barge-in:** talk over Sara mid-answer → she stops, listens, and the transcript is your interruption, not her own voice.
4. **Stop escape hatch:** "hey sara" (or "stop") **while she is speaking** kills playback (B2.5 `ignore_suppression` path).
5. **No self-loop:** let a long answer play with the mic hot — she must not answer herself (echo_state suppression + watchdog). Also play music/TV: no false wakes (ambient boost + rms filters).
6. Goodbye phrase → COOLDOWN → IDLE; conversation-ended event visible in `/api/sensory` recent events; webapp SensoryMonitor mute toggle works against the deployed handlers.
7. `voice_conversation_active` reaches unified context (check a chat during/after a voice session), and check `/api/sensory/jetson/health` stays green for 24h (watch for a recurrence of the Jul 17 overnight connectivity failures).

Rollback: stop `sara-voice.service`, repoint the unit at the old `/home/david/Projects/sara-voice` (or restore from `sara-voice-stable`), restart.

---

## 7. iOS voice — audit findings (separate, smaller workstream)

The iOS voice mode is **functional and reasonably designed, but not "solid"** — the happy path works; the failure paths can wedge the hands-free loop.

What exists (`ios-app/src/services/voice.ts`, used by `ChatScreen.tsx`, `PushToTalkButton.tsx`, `ChatInput.tsx`, `FloatingAssistant.tsx`, `useSaraChat.ts`):
- Two modes: hold-to-talk, and a **hands-free continuous mode** — metering-based VAD (poll every 100ms, silence < −35dB for 1.5s ends the utterance; only >−30dB resets the timer), auto-resumes listening after Sara finishes speaking. That's a real conversation loop, and empty-transcription / error paths all correctly resume listening.
- STT: `POST /api/voice-agent/transcribe` (m4a multipart, field `audio` — matches the backend; Bearer auth; backend filters Whisper hallucinations). TTS: `POST /api/voice-agent/speak` → Kokoro (`af_sarah+af_bella` blend, WAV), text emoji-stripped and chunked ≤500 chars, chunks played sequentially via expo-av from base64 data URIs, audio session flipped record↔playback around speech.
- Verified: expo-av `HIGH_QUALITY` preset has `isMeteringEnabled: true`, so the VAD metering genuinely works (the per-platform `meteringEnabled` keys added in `startContinuousRecording` are dead keys — harmless).

Defects to fix, in priority order:
1. **`speak()` can hang forever, killing the hands-free loop.** `speakChunk()` resolves only on `didJustFinish`; if `stopSpeaking()` unloads the sound mid-chunk, or an audio-session interruption (phone call, route change) stalls playback, the status callback never fires a terminal state → the promise never settles → in `ChatScreen` the `finally` never runs, `isPlayingAudio` sticks true, and continuous listening never resumes. Fix: per-chunk timeout (e.g. 2× expected duration + 10s), and make `stopSpeaking()` settle the in-flight promise; also add a cancellation flag so the chunk loop stops instead of playing chunk *i+1* after a stop.
2. **No prefetch:** each chunk is fetch-then-play, inserting a full TTS round trip of dead air between chunks. Prefetch chunk *i+1* while *i* plays.
3. **No barge-in on iOS:** while Sara speaks there is no way to interrupt by voice (mic is in playback mode); the only stop is UI — which currently trips defect 1. At minimum, wire a reliable on-screen stop; true barge-in would need simultaneous record+playback (`allowsRecordingIOS` stays true + echo handling) and is optional.
4. Cosmetic/latent: comments claim "Orpheus TTS" (it's Kokoro) and `interruptionModeIOS: 1` is labeled "Mix with others" but 1 = DoNotMix — align the value with intent (probably `2` DuckOthers or `0` MixWithOthers while recording). `expo-av` is deprecated upstream (migrate to `expo-audio` whenever the next EAS native rebuild happens anyway — see `reference_ios_build_workflow`); JS-only fixes above need only a reload, no rebuild.
5. Nice-to-have: reuse the Jetson conversation continuity — iOS voice already goes through normal chat (`sendMessage`), so it shares conversation state; no change needed there. Consider streaming TTS off the SSE deltas (like the Jetson's `synthesize_streaming`) later.

---

## 8. Gotchas (hard-won, do not rediscover) {#gotchas}

- Jetson SSH: `david@10.185.1.84`, **no passwordless sudo**. Backend/GPU hosts: `10.185.1.180` (backend, Docker), `10.185.1.8` (GPU STT/verify), `10.185.1.9` (Kokoro).
- PipeWire owns the AIRHUG's raw ALSA device on the Jetson → PortAudio must use the `pulse` device; `pactl` default source is already set to the AIRHUG. The AIRHUG has **0 output channels** — never plan local playback through it.
- Jetson venv must be `--system-site-packages` (JetPack torch; no aarch64 torch on PyPI).
- The AIRHUG has a **hardware mute button** and it is currently muted — unmute before any live test; a "deaf" symptom after deploy may just be the mute LED.
- Deployed-code-lags: the Jetson service only loads code at restart; `systemctl restart sara-voice` after every change, then check `journalctl -u sara-voice -f`.
- Backend runs in Docker only (`docker compose -f docker-compose.dev.yml …`); backend code changes need a container rebuild/restart (kills in-flight dispatch tasks).
- The webapp mute toggle and backend `speak_via_jetson`/`request_jetson_stop` (in `routes/sensory.py`) shell out over SSH from the backend container and/or hit bridge handlers — after the merge, re-verify both directions (§6.6).
- The repo `wake_word.load()` (post-merge) hard-fails if `models/hey_sara.onnx` is missing — deploy models first (§4.2).
- `voice_linter.py` in the backend is unrelated to audio (One-Mind prose-style linter) — don't touch it in this work.
