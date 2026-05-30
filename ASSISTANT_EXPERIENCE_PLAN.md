# Assistant Experience Plan — making Sara feel like Jarvis/Cortana

**Branch:** `assistant-experience-jarvis`
**Started:** 2026-05-30
**Owner:** David

## Thesis

The backend cognition is years ahead of the two front-ends. We have an ACS daemon
with real agency, an emotional-state model, a personal knowledge graph, a
deliberation gate, standing orders, and consolidation cycles. The hard part is built.

But both the webapp and the iOS app are mostly **CRUD surfaces bolted onto that mind**:

- The **web chat** has no voice and no avatar; the daemon's thoughts are buried three
  taps deep in an "ACS Mind" page nobody opens.
- The **iOS app** has voice I/O wired but **currently broken** (doesn't transcribe), and
  no Siri / widgets / Live Activities — so Sara only exists when the app is foregrounded.

Jarvis and Cortana feel alive because they are **present, continuous, and proactive**.
Sara currently feels alive only if you go looking for her.

**Every phase below serves one goal: stop hiding the mind we already built. Make
presence, continuity, and proactivity the default — and cut the sprawl that dilutes it.**

---

## Verified current state (grounded in code, not assumptions)

### Voice pipeline (the P0 problem)
- Backend endpoints **DO exist** (contrary to first investigation): defined inline in
  `backend/app/main_simple.py` with `@app.post`, not in `routes/`:
  - `POST /api/voice-agent/transcribe` — `main_simple.py:9224`. Accepts `audio` UploadFile,
    saves `/tmp/*.m4a`, posts to Whisper at `http://10.185.1.8:8585/v1/audio/transcriptions`
    (model `distil-small.en`), returns `{"transcription": text}`.
  - `POST /api/voice-agent/speak` — `main_simple.py:9297`. Kokoro TTS at
    `http://10.185.1.9:8880/v1/audio/speech`, voice `af_sarah(1)+af_bella(1)`, returns WAV.
- iOS client: `ios-app/src/services/voice.ts` — records m4a via `expo-av` (SDK 54),
  client-side VAD (metering, `-35 dB` threshold, 1.5 s silence), `transcribeAudio()` at
  `voice.ts:234` does a direct `fetch()` to `/api/voice-agent/transcribe` with multipart
  `audio` field, reads `data.transcription || data.text`. **The field name matches the
  backend.** Consumed by `ios-app/src/hooks/useSaraChat.ts` and `FloatingAssistant.tsx`.

**Conclusion:** the client/server contract is actually aligned. The two leading real
suspects are (a) the Whisper service at `10.185.1.8:8585` being unreachable/erroring, or
(b) VAD capturing near-silence → Whisper hallucination → caught by the backend
hallucination filter (`main_simple.py:9242-9281`) → returned as `""` → silent no-op that
the user experiences as "doesn't transcribe." Errors are swallowed on the client
(`voice.ts` catch logs only; `useSaraChat` resets state silently). **Fix must start with
instrumentation, not a blind code change.**

### Presence & cognition surfaces (already have data, just not surfaced)
- Emotional state: `GET /api/sara/status` (used by iOS `HomeScreen`, `FloatingAssistant`).
- ACS daemon activity: SSE `GET /api/acs/v2/stream`, plus `/api/acs/v2/daemon-status`,
  `/focus`, `/inbox`. Web surfaces these only in `ACSMindSection.tsx` (deep page).
- Web shell header has **no** daemon/presence indicator.
- Web chat (`ChatInterface.tsx`) is one-shot: no voice, no persisted/searchable history,
  even though the backend stores every interaction as an episode.
- Autonomous sweeps, standing orders, consolidations, and daemon `notify_david` all run
  **silently** unless the user opens the ACS page.

### Sprawl (working against "flagship" feel)
- Web: 24 views (`frontend/src/navigation/views.ts`). Stubs/opaque: Email, Projects,
  Privacy Dashboard, **Orchestrator Lab (1,262 LOC)**, System Status, Settings.
- iOS: 41 screens. Stubs: Email compose, Projects, Learning content, SmartInsights,
  ContextMode, TemerantRpg.

---

## Phases

Priorities: **P0** = the Jarvis/Cortana feeling + fix what's broken. Then continuity,
proactivity, focus. Each item lists target files and an acceptance check.

### P0 — Presence & Voice (the actual flagship feeling)

#### P0.1 — Fix iOS voice transcription  ⛔ BLOCKING / user-reported broken
Instrument first, then fix the real cause.
1. **Verify the STT service is up:** from the backend container,
   `curl http://10.185.1.8:8585/health` (or a tiny m4a POST to the transcriptions route).
   If down/moved, that's the bug — fix the URL/service, not the app.
2. **Add diagnostics** (temporary): log `audio_content` byte length in
   `transcribe_audio` (`main_simple.py:9236`) and the raw Whisper JSON before filtering;
   on iOS, log recorded file size + duration in `voice.ts` `stopRecording()`.
3. **Surface errors on the client:** replace silent catches in `voice.ts:268` and
   `useSaraChat.ts` with a user-visible toast/Alert ("Couldn't hear that" vs "Voice
   service unavailable") so failures stop being invisible.
4. **VAD hardening:** if `status.metering` is `undefined` (meteringEnabled not honored),
   the `-160` fallback makes it perpetually "silent" → empty recordings. Confirm metering
   is non-null on a real device; if not, switch to a fixed max-duration + manual-stop
   recording for the hold-to-talk path.
5. **Loosen/relocate the hallucination filter** so a real short utterance ("yes", "stop")
   isn't silently dropped — distinguish "empty audio" from "low-confidence word."
- **Files:** `backend/app/main_simple.py:9224-9295`, `ios-app/src/services/voice.ts`,
  `ios-app/src/hooks/useSaraChat.ts`, `ios-app/src/components/FloatingAssistant.tsx`.
- **Accept:** holding the orb, speaking a sentence, and seeing the transcript appear in
  chat on a physical device; a failure shows a clear message instead of nothing.

#### P0.2 — Voice in the web chat (cheapest big win)
Wire the existing backend voice endpoints into `ChatInterface.tsx`.
- Mic button → record (MediaRecorder, webm/opus) → `POST /api/voice-agent/transcribe`
  (confirm Whisper accepts webm; transcode server-side if not) → populate input.
- Speaker toggle → on assistant message, `POST /api/voice-agent/speak` → play returned WAV.
- Add a barge-in / cancel control (also missing on iOS).
- **Files:** `frontend/src/components/ChatInterface.tsx`, a new
  `frontend/src/services/voice.ts`, `frontend/src/api/client.ts`.
- **Accept:** speak to the web chat, get a transcript, hear the reply read back.

#### P0.3 — Live presence element (both platforms)
A single persistent, animated presence driven by **real** daemon state.
- Subscribe to `/api/acs/v2/stream` + poll `/api/sara/status`; map
  idle/listening/thinking/found-something/speaking → animation + color.
- When the daemon fires `focus_set` or `notify_david`, the presence **visibly reacts**
  before any notification — that's the Cortana "she just noticed" moment.
- **Web:** presence chip in the shell header (`frontend/src/components/shell/`) opening a
  "what Sara's doing now" popover (current focus + last 3 activity events). Reuses
  `ACSMindSection` data without forcing navigation.
- **iOS:** promote `FloatingAssistant` orb to all tabs incl. Sara; drive emoji/animation
  from `emotional_state` instead of the static map.
- **Accept:** trigger a daemon focus change and watch the presence react on both surfaces.

### P1 — Continuity (turn separate tools into one mind)

#### P1.1 — Persistent, searchable chat history
- Persist conversations (backend already stores episodes; expose
  list/get/search by `episode_id` / conversation id). Web chat resumes & searches past
  threads; iOS mini-chat shows which conversation it's in.
- **Files:** `frontend/src/components/ChatInterface.tsx`, `frontend/src/stores/chatStore.ts`,
  iOS `ChatScreen.tsx` / `useSaraChat.ts`, backend conversation/episode routes.

#### P1.2 — Cross-device presence sync
- Use the existing 30 s heartbeat (`current_view`, `client_id`, platform) so a
  conversation started on web is known on phone; sync "thinking/typing" state.

#### P1.3 — "Chat about this" everywhere
- Context action on a note, inbox item, calendar event, fitness log → opens chat
  pre-loaded with that context.

### P2 — Proactivity (surface the autonomy we run silently)

#### P2.1 — "What Sara did / found" home feed (both apps)
- A feed on the home surface: recent insights, completed background tasks, focus changes,
  decisions awaiting input. The Cortana "Notebook" — the user sees Sara working for them.
- **Files:** web `DashboardHomeView.tsx`, iOS `SaraScreen.tsx` / `AssistantInboxScreen.tsx`;
  data from autonomous sweep + ACS activity endpoints.

#### P2.2 — Action cards with real verbs
- "You're free 2–4pm tomorrow — schedule your workout? [Yes] [Pick another time]."
  Lean on the deliberation gate + 5-min standing-order undo. Propose → confirm.

### P3 — Focus & Trust + iOS system integration

#### P3.1 — Cut the sprawl
- Per stub surface (Email, Projects, Privacy Dashboard, Orchestrator Lab, System Status,
  TemerantRpg, SmartInsights, ContextMode): **finish, fold, or hide behind a flag.**
- Collapse to ~5 primary destinations per platform; demote power-user/debug surfaces
  (ACS introspection, Sensory Monitor, Orchestrator Lab) under an "Advanced" area.

#### P3.2 — Trust: real Privacy + Settings
- Privacy Dashboard → "what Sara knows / why," backed by PKG (source, confidence,
  confirmation counts already tracked).
- Settings → autonomy controls: sweep cadence, quiet hours (server already has ET-aware
  cooldowns — expose them), per-category proactivity toggles.

#### P3.3 — iOS system-level presence
- **Siri / App Intents** ("Hey Siri, ask Sara…") — #1 iOS gap.
- **Lock Screen / Home Screen widgets** — next event, daemon state, active timer.
- **Live Activities** — workout/timer on the lock screen.

---

## Sequencing

1. **P0.1** (fix iOS voice — unblock the user's reported breakage), in parallel with **P0.2** (web voice).
2. **P0.3** (presence) — highest "feel" payoff once voice works.
3. **P1** continuity → **P2** proactivity → **P3** focus/trust/system.

## "If only three things"
1. Voice in the web chat (P0.2).
2. Siri/App-Intents + a lock-screen widget on iOS (P3.3).
3. A live, daemon-driven presence element on both (P0.3).

These three move Sara from "impressive personal dashboard" to "Sara is *here*."
