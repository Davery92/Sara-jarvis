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

## Status (2026-05-30)

Net-new work shipped this initiative (things that genuinely did **not** exist):
- **P0.1** iOS voice fixed (root cause was the ASR image missing CUDA libs — server-side).
- **P0.3** live daemon-driven presence: web shell chip + iOS orb reactions.
- **P1.1** conversation history browser + cross-conversation search (web).
- **P1.3** "Chat about this" on notes.
- **P2.1** "What Sara's been up to" dashboard feed.
- **P3.3** entire iOS system layer: Siri/App Intents, Home/Lock widgets, Live Activities
  — **EAS build succeeded 2026-05-30** (compiles & signs). Pending on-device functional check.

Recurring lesson: most surfaces the initial survey called "stubs" were already built and
substantial — web chat persistence, cross-device resume, "chat about this" for inbox,
propose→confirm action cards (attention inbox), the PKG browser, Privacy Dashboard, and a
2.2k-line Settings with proactivity toggles + behavior tunables. The backend cognition is
even further ahead of the front-ends than assumed; most of this work was **exposing** it.

Remaining (deferred by David): **P3.1 cut-the-sprawl** ("tackle later"). Optional polish:
iOS history-drawer, calendar/fitness "chat about this", live cross-device typing sync.

## Phases

Priorities: **P0** = the Jarvis/Cortana feeling + fix what's broken. Then continuity,
proactivity, focus. Each item lists target files and an acceptance check.

### P0 — Presence & Voice (the actual flagship feeling)

#### P0.1 — Fix iOS voice transcription  ✅ DONE (2026-05-30)
**Real root cause (found via live logs, not guesswork):** the ASR service image
(`gpu-cluster/Dockerfile.asr`, `python:3.11-slim` + `nvidia` runtime on host
`10.185.1.8`) was missing CUDA math libs. faster-whisper 1.1.0 / CTranslate2 4.x loads
the model but every inference 500s with `libcublas.so.12 is not found`. `/health` stayed
green, masking it. The app, VAD, multipart upload, and field contract were all correct.
**Fix (`4b85e360`):** add `nvidia-cublas-cu12` + `nvidia-cudnn-cu12==9.*` wheels to the
image and put them on `LD_LIBRARY_PATH`; rebuilt + redeployed on the GPU host. Verified
end-to-end: Kokoro-synthesized phrase round-trips to "The quick brown fox…" on
`device:cuda`, and a live iOS attempt logged `[Voice] Transcribed audio: "This is a test.
Can you hear me?"` → 200 plus TTS reply → 200.
Remaining (minor, optional): short-utterance hallucination-filter tuning ("yes"/"stop"),
and client-side error surfacing so future failures aren't silent.

<details><summary>Original instrument-first plan (kept for reference)</summary>

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
</details>

#### P0.2 — Voice in the web chat (cheapest big win)
Wire the existing backend voice endpoints into `ChatInterface.tsx`.
- Mic button → record (MediaRecorder, webm/opus) → `POST /api/voice-agent/transcribe`
  (confirm Whisper accepts webm; transcode server-side if not) → populate input.
- Speaker toggle → on assistant message, `POST /api/voice-agent/speak` → play returned WAV.
- Add a barge-in / cancel control (also missing on iOS).
- **Files:** `frontend/src/components/ChatInterface.tsx`, a new
  `frontend/src/services/voice.ts`, `frontend/src/api/client.ts`.
- **Accept:** speak to the web chat, get a transcript, hear the reply read back.

#### P0.3 — Live presence element (both platforms)  ✅ DONE (2026-05-30, pending visual check)
**Web (`f309ee25`):** `SaraPresence` chip in the shell header — polls daemon-status /
focus / sara-status and subscribes to the `/api/acs/v2/stream` SSE feed; notable activity
(`focus_set`, `notify_david`, `thought`, `tool_call`) briefly overrides the base state so
the chip *reacts*, with an emphatic ping for focus_set / notify_david. Click → popover
(focus + why, latest thought, last 3 events). Emotional state drives emoji + idle label.
**iOS (`43393498`):** new `useSaraPresence` hook (RN has no EventSource, so it polls
sara/status + daemon-status + acs/v2/activity); the floating orb now tints to the
reaction color and gets a heartbeat pulse on emphatic reactions, replacing its old
emoji-only 60s fetch. Both typecheck clean; all four endpoints confirmed live (401 w/o
auth). Still TODO: visual confirmation on a real device + browser; the web SSE is a 2nd
connection alongside ACSMindSection (fine for single-user). iOS orb still hidden on the
Sara tab by design (full chat lives there).

<details><summary>Original design notes</summary>
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
</details>

### P1 — Continuity (turn separate tools into one mind)

#### P1.1 — Persistent, searchable chat history  ✅ DONE (2026-05-30, web)
Correction from the survey: the web chat was **not** one-shot — it already persists &
resumes the *active* conversation (`/api/conversations/active` + `/{id}/messages`) and
even checks `/api/session/active` for cross-device sessions. The real gap was browsing &
searching past threads.
- **Backend (`5968b685`):** new `GET /api/conversations/search?q=` — ILIKE over episode
  content, rolled up per conversation with a match-centered snippet. (Conversation list /
  messages / active already existed.) Live after backend restart (no `--reload` in dev).
- **Web (`5968b685`):** `ConversationHistoryDrawer` (list + debounced search + resume +
  new chat) opened from a History button in the chat toolbar; `loadConversation()` swaps
  the active thread. tsc clean.
- **Remaining/optional:** iOS already has `loadHistory` + active conversation; could add
  the same history/search drawer there. Search is ILIKE, not semantic — fine at this scale.

#### P1.2 — Cross-device presence sync  ◑ PARTIAL (pre-existing)
- Resume-across-devices already works: the web chat checks `/api/session/active` on mount
  and picks up a conversation started on iOS. **Not built:** live "thinking/typing" state
  syncing across devices (lower value; deferred).

#### P1.3 — "Chat about this" everywhere  ✅ CORE DONE (2026-05-30)
- Already existed for inbox items (`onOpenContentChat` / `onOpenAttentionChat`).
- **Added (`9ae50e71`):** notes — a "Chat about this" button in the note editor toolbar
  opens the chat pre-loaded with the note's title + a trimmed excerpt
  (`onChatAboutNote`, threaded App-interactive → ShellWorkspaceContent → NotesPage).
- **Optional remaining surfaces:** calendar events, fitness logs (same one-handler pattern).

### P2 — Proactivity (surface the autonomy we run silently)

#### P2.1 — "What Sara did / found" home feed  ✅ DONE (2026-05-30, web)
- **Web (`8d0fc040`):** self-contained `SaraActivityFeed` card on the dashboard polls
  `/api/acs/v2/activity` (15s), filters out tick/external_event noise, and renders the
  last 8 daemon events as a human-labeled timeline (focused / reflected / reached out /
  finished …). Surfaces the autonomy that previously only lived on the ACS page. tsc clean.
- **Optional:** port to iOS `SaraScreen` / `AssistantInboxScreen`.

#### P2.2 — Action cards with real verbs  ✅ ALREADY EXISTS (attention inbox)
- This is already built: the **attention inbox** is the propose→confirm system.
  `POST /api/autonomy/attention/{item_id}/actions/{action_id}` + `AttentionInbox.tsx`
  (`AttentionAction` items, `runAction`, confirm/defer/clarify) is exactly the
  "schedule your workout? [Yes] [Pick another time]" pattern. Building a parallel
  action-card system would duplicate it. Future polish only: surface attention actions
  inline in chat / on the dashboard rather than just the inbox view.

### P3 — Focus & Trust + iOS system integration

#### P3.1 — Cut the sprawl
- Per stub surface (Email, Projects, Privacy Dashboard, Orchestrator Lab, System Status,
  TemerantRpg, SmartInsights, ContextMode): **finish, fold, or hide behind a flag.**
- Collapse to ~5 primary destinations per platform; demote power-user/debug surfaces
  (ACS introspection, Sensory Monitor, Orchestrator Lab) under an "Advanced" area.

#### P3.2 — Trust: real Privacy + Settings  ✅ ALREADY EXISTS (verified 2026-05-30)
Like P2.2, the survey was wrong — these are built, not stubs:
- **"What Sara knows / why"** → `PersonalKnowledge.tsx` (full PKG browser: confidence,
  source, first-learned / last-confirmed, edit-confidence, delete, `/api/pkg/needs-review`,
  `/api/pkg/validation-report`).
- **Privacy Dashboard** (`privacy/PrivacyDashboard.tsx`, 452 LOC) → data-summary, export,
  per-category delete (`/privacy/*`).
- **Settings** (`pages/Settings.tsx`, 2,264 LOC) → a "Behavior Tunables (cooldowns,
  deliberation thresholds, brief tone)" section, **per-category proactivity toggles**
  (notification categories Sara may use), autonomy-flag visibility, notification prefs.
- Net: nothing genuine to add; building more would duplicate. Optional only: surface a
  distinct "quiet hours" control if cooldowns + category toggles ever feel insufficient.

#### P3.3 — iOS system-level presence  ✅ BUILT (EAS build succeeded 2026-05-30) — pending on-device check
Built via `@bacons/apple-targets` (widget extension) + a local Expo module
(`modules/sara-native`) + a config plugin for main-target App Intents. See
`ios-app/NATIVE_FEATURES.md` for setup (npm install, App Group registration, APPLE_TEAM_ID),
build, verify, and risks.
- **Siri / App Intents** ✅ — "Ask Sara" AppShortcut in the main target → `sara://ask?q=…`
  → `siriDeepLink.ts` routes into chat as a quick-reply.
- **Lock/Home Screen widgets** ✅ — `SaraWidget.swift` (systemSmall/medium + accessory
  families); emotional state + latest thought + next event via App Group (`widgetBridge.ts`).
- **Live Activities** ✅ — timer countdown (lock screen + Dynamic Island) via
  `Text(timerInterval:)`, wired into `TimerContext`.
- TS clean (0 errors in new code); plugin/target/JSON validated; all native APIs confirmed
  present. **EAS build compiles & signs cleanly (2026-05-30); on-device behavior pending.**

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
