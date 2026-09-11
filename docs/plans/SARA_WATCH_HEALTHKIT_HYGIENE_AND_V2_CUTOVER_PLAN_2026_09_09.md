# Sara Watch: HealthKit Hygiene and v2 Cutover Plan

Date: 2026-09-09
Status: Ready for an agent to execute. Written from a code and database audit
on this date; every file and line anchor below was verified against
`feat/sara-mind-v2` at commit 1f0b5797.

Predecessors: `SARA_APPLE_WATCH_FITNESS_IMPLEMENTATION_PLAN_2026_07_25.md`
(the product contract, cited as "§n" below),
`SARA_WORKOUT_RELIABILITY_AND_FLEXIBLE_SETS_PLAN_2026_07_27.md`,
`SARA_IOS_AND_WATCH_BUILD_UPDATE_RUNBOOK.md` (how to ship a build).

---

## 0. Why this plan exists

David found many short (2 to 4 minute) workouts attributed to Sara in his
iPhone Health history. Root cause, verified in code:

The Watch's Apple workout (`HKWorkoutSession` + `HKLiveWorkoutBuilder`) and
Sara's canonical session (`active_workout_session`) are two independent
lifecycles. The Watch starts recording an Apple workout the moment it wakes,
before Sara has acknowledged anything, and `finalizeHealthKit(discard: false)`
saves whatever was recorded whenever it is asked to stop. Nothing checks that
a Sara session exists, that any set was logged, or that the workout is longer
than a few seconds. The end date is stamped when the Watch finally finalizes,
not when Sara completed the workout.

Evidence from the dev database (which holds real data; last workout 2026-09-01):

| Fact | Value |
|---|---|
| Watch-originated Sara sessions | 9, all 2026-08-03/04; 8 abandoned within 8 s to 4 min |
| Apple workouts ingested that evening | 1009 s, 250 s, 350 s, 119 s: the failed starts were saved, not discarded |
| Session 2026-08-13 | 28 min in Sara, 5960 s (99 min) in Health: the Watch finalized an hour late |
| `WORKOUT_COMMAND_V2_ENABLED`, `WATCH_WORKOUT_ENABLED`, `WORKOUT_COACHING_AUDIO_ENABLED` | no `app_settings` rows, so all OFF |
| `workout_adjustment_proposal` rows ever | 0 |
| `workout_approved_policy` rows | 0 (so coaching audio never speaks) |
| Watch command conflicts | `complete`/`rest_stop` against already-completed sessions (Aug 5, 6); phone `rest_start` two seconds after every completion |

The Watch was rebuilt on the Mac on 2026-09-02 from source that is byte-identical
to this repo (md5 of `WorkoutManager.swift`, `watchWorkout.ts`,
`WorkoutModeContext.tsx` match). This is a design defect in current code, not a
stale build.

Second finding: the whole v2 feature set (refuse-to-clobber start, approval
enforcement, server-driven rest, proposals, coaching audio) is built and tested
(82 backend tests green) but dormant because the flags are off and the phone
still calls the legacy start endpoint.

---

## 1. Outcome

After this plan:

1. The Watch never writes an Apple workout to Health unless Sara acknowledged
   the session, at least one set was logged, and the workout ran at least
   `MIN_SAVE_SECONDS` (300). Everything else is discarded.
2. Saved Apple workouts end at Sara's completion time, not at Watch-reconnect
   time.
3. Existing stray workouts authored by the Sara Watch app can be listed and
   deleted from the Watch, with confirmation.
4. Phone starts go through v2 with resume-or-end conflict handling. The three
   flags are on. Proposals, policy, and audio coaching are live.
5. The two known conflict patterns (stale Watch `complete`, stray phone
   `rest_start`) no longer produce conflict rows.
7. Sara's spoken coaching plays only through connected headphones. Never the
   iPhone speaker, never the Watch.
6. A phone-started workout shows on the Watch as an active workout within a
   few seconds, not as an orphan banner.

---

## 2. Ground rules for the executing agent

- **Never start the backend locally.** `docker compose -f docker-compose.dev.yml up -d backend` after backend changes; run tests with
  `docker compose -f docker-compose.dev.yml exec -T backend sh -c 'cd /app && python -m pytest -q tests/test_workout_command_service.py tests/test_workout_approval_enforcement.py tests/test_workout_flexible_sets.py tests/test_workout_session_legacy_compat.py'`.
- **The wire contract exists in four copies** (`ios-app/targets/watch/WorkoutWireModels.swift`, `ios-app/modules/sara-workout-native/ios/WorkoutWireModels.swift`, `ios-app/src/services/workoutContracts.ts`, `backend/app/services/workout_command_service.py`). Any new field or kind goes into all four, then run `node ios-app/scripts/check-workout-contract-parity.mjs`. The two Swift files must stay identical (`diff` them).
- **Bump `SCHEMA_VERSION` only if a change is incompatible.** Adding optional payload fields is compatible; do not bump for Phases 1 to 5.
- **No Xcode on this host.** Swift changes can only be compiled on the Mac (runbook §4 to §6). Write Swift carefully, keep diffs small, and read the surrounding code before editing. Compile errors surface only at build time on the Mac.
- **User-facing times are ET** via `app.core.timezone`; never bare `datetime.now()` in the backend.
- **Do not commit or push unless David asks.** Leave the work on the current branch.
- **Do not flip the flags before Phase 4's phone change is built and installed.** Flipping `WORKOUT_COMMAND_V2_ENABLED` alone changes the legacy start route from "abandon" to "409" (`backend/app/routes/fitness.py:5452`), which the current phone build does not handle.
- Every phase ends with the acceptance checks listed. Report what was verified and what could not be (anything requiring the Mac build or a physical device).

---

## 3. Architecture reference (read before editing)

| Layer | File | Role |
|---|---|---|
| Watch app | `ios-app/targets/watch/WorkoutManager.swift` (1353 lines) | Owns `HKWorkoutSession`/builder, command queue, start state, finalize |
| Watch start state | `ios-app/targets/watch/WorkoutStartState.swift` | `HealthKitPhase` (idle/authorizing/starting/running/failed/ended), `SaraSessionPhase` (none/requesting/active/conflict/failed), diagnostics |
| Watch transport | `ios-app/targets/watch/WorkoutWireTransport.swift` | mirror → WCSession interactive → `transferUserInfo` durable |
| Watch views | `ios-app/targets/watch/views/*.swift`, `WatchDiagnosticsView.swift` | Home, pre-start, active, rest, summary, diagnostics |
| Phone native | `ios-app/modules/sara-workout-native/ios/IPhoneWorkoutCoordinator.swift`, `SaraWorkoutNativeModule.swift`, `WorkoutCoachingAudioCoordinator.swift` | Mirror receiver, `startWatchApp`, audio |
| Phone JS bridge | `ios-app/src/services/watchWorkout.ts` | Envelope routing, replies, `launchWatch`, `endWatchWorkout`, `syncCatalog` |
| Phone coordinator | `ios-app/src/services/workoutCoordinator.ts` | v2 start/commands/sync with queue-first idempotency |
| Phone workout UI state | `ios-app/src/context/WorkoutModeContext.tsx` | `startWorkout` (line 365, still legacy), `completeWorkout` (~503), `abandonWorkout` (~535) |
| Phone set panel | `ios-app/src/components/fitness/WorkoutPanel.tsx` | `startRestTimer` after log (line 131) |
| Phone API | `ios-app/src/services/fitness.ts` | legacy `startWorkoutSession` (959), `v2Start` (1143) etc. |
| Phone HealthKit | `ios-app/src/services/healthKit.ts` | `getWorkoutsForSync` (897), `queryWorkoutSamples` (934) |
| Backend routes | `backend/app/routes/workout_v2.py` | `/api/fitness/workout-session/v2/*` |
| Backend legacy | `backend/app/routes/fitness.py` | `/workout-session/start` (5641), calendar start (5425) |
| Backend service | `backend/app/services/workout_command_service.py` | `start` (278), `execute` (508), `_apply_complete` (1396), `_v2_enabled` (2237), `DEFAULT_POLICY` (91) |
| Flags | `backend/app/core/feature_flags.py` | `is_enabled`, `set_flag(flag, enabled, updated_by)`; read from `app_settings` |
| Tables | migration `124_watch_workout_sync.py` | `workout_session_command`, `workout_session_event`, `workout_adjustment_proposal`, `workout_approved_policy`; columns on `active_workout_session` |

Watch-side Apple workout lifecycle today:

- `startWorkout(templateId:…)` (line 219): Watch-originated. Starts HK first, then `submitStartRequest`.
- `startWorkoutFromPhone(configuration:)` (line 296): invoked by `SaraWatchExtensionDelegate.handle(_:)` when the phone calls `startWatchApp`. Starts HK, sends `watch_recovered_session`, waits for a projection.
- `finishWorkout()` (691): issues `complete`, then `finalizeHealthKit(discard: false)`.
- `abandonWorkout()` (701): issues `abandon`, then `finalizeHealthKit(discard: true)`.
- `.workoutEnded` handler (859): phone's terminal instruction; finalizes with `discard` from payload.
- `finalizeHealthKit` (1021): ends session, `endCollection(at: Date())`, then `finishWorkout()` or `discardWorkout()`.
- `discardOrphanStart()` (406): the home screen's "End Apple Workout" button; discards.
- `WatchDiagnosticsView.swift:99`: a Finish button that calls `finishWorkout()` unconditionally.

---

## 4. Phases

### Phase 1: HealthKit subordinate to the Sara session (Watch, Swift)

Goal: outcome 1 and 2. No wire change except one optional field.

1. **Add a save gate in `WorkoutManager.swift`.**
   - Add `private static let minSaveSeconds: TimeInterval = 300`.
   - Track `private var loggedSetCount = 0`; set it from every accepted projection (`applyProjection`, use `projection.progress.completedSets`) and reset in `teardown`.
   - Add `private func shouldSaveHealthKit(sessionId: String?) -> (save: Bool, reason: String)` that returns false when `sessionId == nil`, when `startState.saraSession` was never `.active` for this attempt (track `private var saraAcknowledged = false`, set true in the `.startAccepted/.projectionUpdated` branch when `projection != nil`, reset in teardown), when `loggedSetCount == 0`, or when elapsed since the HK session start is under `minSaveSeconds`.
   - In `finalizeHealthKit`, when `discard == false`, call the gate. If it says no: log the reason via `recordDiagnostic(stage: "healthkit_discarded_by_gate", …)`, and take the discard path (`endCollection` then `discardWorkout`, send `healthkit_finished` with `discarded: true` and add `reason` to the payload).
2. **Use Sara's completion time as the end date.**
   - Extend the `workout_ended` payload with optional `ended_at` (ISO 8601). Phone side: `watchWorkout.ts endWatchWorkout` passes `options.endedAt`; `WorkoutModeContext.completeWorkout` passes the top-level `completed_at` that `POST /api/fitness/workout-session/complete` already returns (verified: `workout_session_service.py:755` copies it from `_apply_complete`). Add `completed_at?: string` to the `completeWorkoutSession` return type in `fitness.ts` if it is not typed.
   - Watch: `finalizeHealthKit` takes `endDate: Date? = nil`; the `.workoutEnded` handler decodes `ended_at` and passes it. Clamp: never earlier than the HK start date plus 1 s, never later than `Date()`.
   - Add `endedAt` to `WorkoutWireModels.swift` (both copies) and `workoutContracts.ts` if the envelope payload is typed there; backend does not consume it.
3. **Remove unconditional saves.**
   - `WatchDiagnosticsView.swift:99` Finish → route through the same `finishWorkout()` (the gate now protects it) and relabel to "Finish workout" only visible when `manager.projection?.status == "active"`; otherwise show "Discard Apple workout" calling `discardOrphanStart()`.
   - `WorkoutModeContext.completeWorkout` error path (~line 520): change `endWatchWorkout('completion requested on phone')` to pass `{ discarded: false }` only when the backend actually confirmed; when the complete call threw, pass `{ keepRunning: true }` semantics: do not end the Watch at all, let the queued `complete` reconcile. Simplest: on the error path, do not call `endWatchWorkout`; leave a note in `this.note`.
4. **Auto-discard abandoned orphans.**
   - In `submitStartRequest`'s 12 s timeout task, do nothing new. Add a second watchdog: if `startState.isOrphanedHealthKit` persists for 10 minutes with `loggedSetCount == 0`, call `discardOrphanStart()` and set `lastError = "Ended an Apple workout Sara never started"`. Implement as a `Task` stored in `private var orphanWatchdogTask`, started in `failStart` and in `startWorkoutFromPhone` after HK starts, cancelled in the `.startAccepted` branch and in `teardown`.
5. **Stale terminal commands.** In the `.commandRejected` handler (line 824), when `payload["code"] == "no_active_session"` and the rejected command's kind is `complete`, `abandon`, `rest_stop`, or `healthkit_state`, call `Task { await finalizeHealthKit(discard: loggedSetCount == 0, sessionId: …) }` so the Watch stops tracking a workout the phone already closed. Look the entry up in `queue.pending` by `command.commandId` before discarding it; `WorkoutCommandQueue.Entry.command.kind` already carries the kind (verified, `WorkoutCommandQueue.swift:18`).

Acceptance (code-level, this host):
- `diff ios-app/targets/watch/WorkoutWireModels.swift ios-app/modules/sara-workout-native/ios/WorkoutWireModels.swift` is empty.
- `node ios-app/scripts/check-workout-contract-parity.mjs` passes.
- `grep -n "finishWorkout()" ios-app/targets/watch` shows every call site guarded by the gate (all go through `finalizeHealthKit`).
- Write down the four device test cases for §6 with the expected Health outcome for each.

### Phase 2: Stray-workout cleanup (Watch, Swift; phone trigger optional)

Goal: outcome 3.

HealthKit only lets the source that authored an object delete it. The stray
workouts were authored by `cloud.avery.sara-ios.watch`, so deletion has to run
on the Watch, not the phone. (`@kingstinct/react-native-healthkit` exposes
`deleteObjects`, but calling it from the iPhone app for Watch-authored
workouts will fail with an authorization error. Do not build the phone path
first; verify on-device if you try it at all.)

1. Add `WatchHealthCleanup.swift` in `ios-app/targets/watch/`:
   - `func findStrayWorkouts(maxSeconds: TimeInterval = 600) async throws -> [HKWorkout]`: `HKSampleQuery` for `HKObjectType.workoutType()` with predicate `HKQuery.predicateForObjects(from: HKSource.default())` AND `duration < maxSeconds`, sorted by start date descending, limit 200.
   - `func delete(_ workouts: [HKWorkout]) async throws -> Int` using `healthStore.delete(_:)`.
   - The Watch cannot query the backend directly. Treat "authored by this Watch app AND shorter than `maxSeconds`" as the stray definition. Longer misattributed workouts (the 99 minute one) are out of scope for automatic deletion; list them in the UI as "long, review on phone" without a delete button.
2. `WatchDiagnosticsView.swift`: add a "Stray Apple workouts" section that runs the query on appear, shows count, date, duration, and a destructive "Delete N workouts" button behind a confirmation dialog. Refresh after delete.
3. Optional phone trigger: none in this plan. Keep it Watch-local.

Acceptance: code compiles in review. New Swift files under `targets/watch/` are picked up automatically: the existing target already builds `views/*.swift` with no per-file registration in `expo-target.config.js`.

### Phase 3: Backend fixes and defaults

1. **Phone stray `rest_start` after completion.** In `WorkoutPanel.tsx:131`, skip `startRestTimer` when `result.workout_complete` is true (the legacy log-set response already carries it; typed at `fitness.ts:982`). Backend side, make `_apply_rest_start` (line 1378) a no-op that returns the projection when the session's `status != 'active'` rather than raising through `execute`; `execute` already raises `no_active_session` before dispatch, so the backend change is unnecessary if the phone stops sending. Do the phone fix; leave the backend as is.
2. **Legacy `/complete` response.** Already returns `completed_at` (verified). Nothing to do beyond the TypeScript type in Phase 1.
3. **Policy defaults for audio.** Keep `DEFAULT_POLICY` speak flags false (David opts in through the existing `WorkoutCoachingSection.tsx` settings UI, which issues `set_policy`). No change unless the settings section does not persist; verify by issuing `set_policy` through `/v2/commands` with curl against the dev backend and reading `/v2/policy` back.
4. **Coaching audio plays through headphones only (David, 2026-09-09).** The Watch has no audio path at all today (haptics only, `WatchHaptics.swift`); keep it that way. The phone's `WorkoutCoachingAudioCoordinator.swift` plays through whatever route `AVAudioSession` has, which means the iPhone speaker when no headphones are connected. Add a route guard in `activateSession()` (line 228): read `AVAudioSession.sharedInstance().currentRoute.outputs` and proceed only if at least one output's `portType` is `.headphones`, `.bluetoothA2DP`, `.bluetoothHFP`, or `.bluetoothLE`. If none, return false, log `"coaching audio skipped: no headphones"`, and let the prompt fall through to text and haptics (`finish` must still dequeue it). Also observe `AVAudioSession.routeChangeNotification` so a prompt queued while AirPods disconnect is cancelled rather than played out loud. Add a `coachingPlaybackChanged` event with `state: "no_headphones"` so the phone UI can show "Put in headphones to hear Sara" once per workout.
5. **Tests.** Add to `tests/test_workout_command_service.py`: a `complete` payload with `healthkit_ended_at` earlier than `started_at` is clamped or rejected (choose reject with `ValueError` → 400). Run the four workout test files.

Acceptance: 82 existing tests plus the new one pass inside the container.

### Phase 4: Phone onto v2 start, then flags on

Goal: outcome 4.

1. **`WorkoutModeContext.startWorkout` (line 365):** replace `fitnessService.startWorkoutSession(templateId)` with `workoutCoordinator.start(templateId, { originDevice: 'phone', onConflict: 'error', startAttemptId: <uuid persisted in AsyncStorage under STORAGE_KEY + ':attempt' until accepted> })`. On `{ conflict }` with code `active_workout_conflict`: there is no conflict UI on the phone today (verified: no `conflict` consumer in `WorkoutModeScreen.tsx` or `components/fitness/`), so use `Alert.alert` with "Resume" (call `refreshSession()`) and "End it" (call `workoutCoordinator.start(templateId, { onConflict: 'abandon' })`). The v2 projection is not the legacy `ActiveWorkoutSession` shape; after a successful start call `refreshSession()` to load the legacy shape the rest of the context still uses, rather than rewriting the context.
2. **Broadcast immediately.** After the start succeeds: `void watchWorkout.launchWatch('strength')` (already there), then `await syncWatch()` instead of `void syncWatch()`, and additionally call `watchWorkout.broadcast(projection)` with the projection returned by start so the Watch does not wait for a `watch_recovered_session` round trip. (Outcome 6.)
3. **Calendar start** (`fitness.py:5425`) already switches to `on_conflict="error"` with the flag; no change.
4. **Flip the flags** only after the phone build containing steps 1 and 2 is installed (David confirms). Use the backend container:
   ```
   docker compose -f docker-compose.dev.yml exec -T backend sh -c 'cd /app && python -c "
   from app.core.feature_flags import Flag, set_flag
   for f in (Flag.WORKOUT_COMMAND_V2_ENABLED, Flag.WATCH_WORKOUT_ENABLED, Flag.WORKOUT_COACHING_AUDIO_ENABLED):
       set_flag(f, True, updated_by=\"watch_plan_2026_09_09\")
   "'
   ```
   Then confirm with `GET /api/diagnostics/feature-flags` (router prefix `/api/diagnostics`, handler at `backend/app/routes/diagnostics.py:81`). Production uses a different database; if David wants this on prod, the same call runs in the prod backend container. Document which one you flipped.
5. **What the flags change, so the agent can verify each:** approval enforcement in `_create_session` (line 382), server-side rest auto-start (817), approved-weight source (1328), next-session proposals (1690), permanent set proposals (1730), legacy start conflict mode (`fitness.py:5452`).

Acceptance: with the flags on in dev, run the four workout test files again (they set flags themselves; confirm they still pass), then a manual sequence against the dev backend with curl: v2 start → log_set → complete → `GET /v2/proposals` returns at least one pending proposal when the RPE was low enough to earn one (see `_maybe_propose_weight`, line 1573).

### Phase 5: Build, install, and device verification (David + Mac)

The agent cannot do this; write the exact hand-off.

1. Sync source to the Mac (runbook §4) and run `/Users/david/sara-ios-build/build-sara-watch-local.sh` in the visible Terminal (§6). Bump `buildNumber` in `ios-app/app.json` (currently "11") to "12" before syncing so the Watch diagnostics show the new build.
2. Install (§7), launch (§8).
3. Device matrix, each followed by opening Health → Workouts and confirming exactly the listed result:

| Case | Steps | Health result |
|---|---|---|
| Start on Watch, log 2 sets, Finish after 6 min | Watch → Today → Start | one workout, ~6 min |
| Start on Watch, abandon after 1 min | Watch → Abandon | nothing |
| Start on Watch with phone locked, wait 11 min | do nothing | nothing (orphan watchdog discarded it); Watch shows the explanation |
| Start on phone, log 1 set, complete on phone after 6 min | phone | one workout, ~6 min, end time = phone completion time |
| Start on phone, complete after 2 min | phone | nothing (under the floor); Sara session still completed |
| Start on phone with Watch in airplane mode 20 min, then reconnect | phone completes at minute 6 | one workout ending at minute 6, not minute 20 |
| Diagnostics → Stray Apple workouts → Delete | Watch | the old 2 to 17 minute entries from Aug 4 are gone |

4. Record the outcome in the runbook's §13 release record.

---

## 5. Out of scope

- Rewriting `WorkoutModeContext` around the v2 projection shape (it still uses the legacy `ActiveWorkoutSession`). Phase 4 keeps the legacy shape and only swaps the start call.
- HealthKit link rate for pre-Watch workouts (82 of 91 unlinked are from before the Watch existed).
- The iOS Fitness screen redesign and Tabata features.
- EAS builds. Local Mac builds are the working path (runbook §1).

---

## 6. Deliverables checklist

- [ ] Phase 1 Swift changes, both wire-model copies identical, parity script green
- [ ] Phase 2 `WatchHealthCleanup.swift` + diagnostics section
- [ ] Phase 3 phone rest fix, headphones-only audio guard, new clamp test, all workout tests green in container
- [ ] Phase 4 phone start on v2 with conflict handling and immediate broadcast; flags NOT flipped until David confirms the install
- [x] Hand-off note for Phase 5 with the build number and device matrix
- [x] Update memory file `project_apple_watch_workout.md` when the flags flip
