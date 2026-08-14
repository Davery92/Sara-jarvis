# Sara Apple Watch and Cross-Device Fitness Implementation Plan

Date: 2026-07-25

Status: implementation handoff

Scope: Apple Watch companion, cross-device active workout control, live HealthKit
workout tracking, AirPods coaching, and explicit approval for every Sara-proposed
change.

This plan is based on the current iOS, native, HealthKit, voice, and backend
implementation in this repository. It is not a greenfield redesign.

---

## 1. Executive Outcome

Build one active Sara workout that can be started and controlled from either the
Apple Watch or iPhone.

The Watch must start the real Apple Health workout and collect live heart rate.
The iPhone must preserve every capability in the current workout experience.
Both devices must display and mutate the same backend-owned workout session.
AirPods coaching must briefly duck other audio, including YouTube Music, speak
Sara's coaching, and then return audio focus cleanly.

The result must behave as one workout with two controllers:

- Start on Watch -> Watch begins HealthKit tracking, Sara creates/resumes the
  canonical active workout, and the iPhone immediately recognizes it.
- Start on iPhone -> Sara creates the canonical active workout and launches or
  wakes the Watch companion to begin HealthKit tracking.
- Log or change something on either device -> the other device converges on the
  same state without duplicate sets or conflicting cursors.
- Complete on either device -> both devices end together and exactly one Sara
  workout and one HealthKit workout are retained.
- Sara may calculate and present recommendations, but she may not apply a
  change without David's explicit approval.

The Watch is an additional first-class controller. It does not replace or reduce
the existing phone workout experience.

---

## 2. Confirmed Product Decisions

These are settled requirements, not open design questions.

### 2.1 Daily use

- David uses every Fitness area: workouts, nutrition, recovery, cardio, plans,
  progress, and related features.
- Existing phone Fitness functionality must remain available.
- The implementation must not simplify Fitness by deleting or disabling current
  capabilities.

### 2.2 Apple Watch

- David always wears an Apple Watch during workouts.
- Today he must manually start an Apple Workout to get workout heart-rate data.
- Starting a Sara workout must remove that double-start requirement.
- Starting from the Watch is a primary workflow.
- Starting from the iPhone must also bring the Watch into the same workout.
- The phone and Watch are both readily accessible during sets.

### 2.3 AirPods coaching

- David always wears AirPods while training.
- Sara may interrupt or duck YouTube Music to coach.
- Sara should speak short, contextual coaching during the workout.
- Music must resume or return to its prior level after Sara finishes speaking.

### 2.4 Approval boundary

- Sara must not change workouts, exercises, order, sets, reps, weight, RPE
  targets, rest rules, day type, nutrition targets, programs, or progression
  without approval.
- A spoken recommendation is not an applied change.
- Silence or expiration is not approval.
- David's direct input is an instruction and does not require an additional
  approval.
- David may approve a standing bounded policy, such as adaptive rest inside an
  agreed range. Operation inside that previously approved policy is allowed.
- Every approval and rejection must be durable and attributable.

### 2.5 EAS-first Watch build decision

- The primary repository host is Ubuntu Linux and does not have local Xcode.
- This does not block implementation or the first Watch build.
- Source, configuration, backend work, TypeScript tests, and non-Apple tooling
  run on the Linux host.
- The first compiled iPhone/Watch artifact must be produced by EAS Build, whose
  iOS jobs run on remote macOS/Xcode infrastructure.
- David will run the EAS build and, when prompted, his dad will authenticate the
  individual paid Apple Developer account and complete two-factor
  authentication as he does for the current iOS app.
- EAS should be allowed to create the new Watch bundle identifier, synchronize
  HealthKit capabilities, and generate the Watch provisioning profile before
  anyone performs manual Apple Developer portal setup.
- Existing iPhone signing credentials do not replace the Watch target's own
  bundle identifier and provisioning profile.
- The MacBook is the fallback for Xcode target repair, runtime device logs, and
  physical debugging. It is not a prerequisite for attempting the EAS build.

---

## 3. Current App: What Exists Today

### 3.1 Platform and native baseline

The iOS app currently uses:

- Expo SDK 54.
- React Native 0.81.
- An iOS 18 deployment target.
- `@kingstinct/react-native-healthkit`.
- `@bacons/apple-targets`.
- A local Expo native module under `ios-app/modules/sara-native`.
- A WidgetKit/ActivityKit target under `ios-app/targets/widget`.
- HealthKit, background delivery, push, Live Activity, App Group, calendar,
  microphone, speech, camera, photo, and background-location capabilities.

The current Apple target is a widget/Live Activity extension. There is no
watchOS workout app target yet.

The locally installed `@bacons/apple-targets` package lists `type: "watch"` as a
supported companion Watch App target, but its own documentation warns that not
every target type has been fully tested. Target generation and EAS signing must
therefore be treated as an early build spike, not assumed to work at the end.

### 3.2 Current phone active-workout experience

The active workout is already a real product, not a placeholder.

`ios-app/src/context/WorkoutModeContext.tsx` currently:

- Fetches an active backend workout on mount.
- Polls the active session every two seconds.
- Stores the active session ID in AsyncStorage.
- Holds a local rest countdown while persisting rest state to the backend.
- Starts and updates an ongoing-event Live Activity.
- Supports start, log set, skip, select exercise, set variation, rest start/stop,
  complete, abandon, and session recovery.

`ios-app/src/components/fitness/WorkoutPanel.tsx` currently supports:

- The current exercise and total-set progress.
- Suggested weight and progression reasoning.
- Template coaching notes.
- Per-side, set-technique, and superset markers.
- Machine/variation selection with separate history.
- Weight and rep steppers plus direct numeric entry.
- Effort input using easy/right/hard language.
- Set logging.
- Dynamic rest countdown.
- PR alerts.
- Last-session performance.
- Goal display.
- Jumping between exercises in any order.
- Skip, finish, and embedded Sara chat.

`ios-app/src/screens/fitness/WorkoutModeScreen.tsx` currently:

- Protects against accidental dismissal.
- Allows completion or abandonment.
- Shows a workout summary.
- Merges Apple Watch heart-rate/calorie data into the summary when available.
- Allows the workout panel to collapse and reveal the full embedded chat.

This phone behavior is the compatibility baseline. The Watch implementation must
adapt to it, not replace it.

### 3.3 Current backend workout authority

`backend/app/services/workout_session_service.py` and the Fitness routes already
provide:

- One active workout row per user through a partial unique database index.
- A template snapshot frozen at workout start.
- Recovery-aware progression suggestions.
- Deload handling.
- Set persistence in `workout_log`.
- Machine-specific exercise identity.
- Cursor movement based on actually logged sets.
- Exercise jumping and skip/return behavior.
- Smart rest calculation.
- PR detection.
- Set coaching text.
- Workout completion and abandonment.
- Chat context describing the active workout.

The existing endpoints are user-global:

- `POST /api/fitness/workout-session/start`
- `GET /api/fitness/workout-session/active`
- `POST /api/fitness/workout-session/log-set`
- `POST /api/fitness/workout-session/skip`
- `POST /api/fitness/workout-session/select-exercise`
- `POST /api/fitness/workout-session/set-variant`
- `POST /api/fitness/workout-session/rest-timer`
- `GET /api/fitness/workout-session/rest-timer`
- `POST /api/fitness/workout-session/complete`
- `POST /api/fitness/workout-session/abandon`

The current service silently abandons an existing active workout when a new one
starts. That behavior is unsafe once two devices can issue start commands. It
must be replaced with an explicit conflict response and Resume/End choices.

The existing set endpoint commits the set and then waits for coaching generation
before returning. A Watch controller needs the durable command acknowledgment
immediately; coaching must become a separate event so an LLM or TTS delay cannot
make `Log Set` feel unreliable.

### 3.4 Current HealthKit behavior

`ios-app/src/services/healthKit.ts` currently reads:

- Heart rate and resting heart rate.
- HRV.
- Sleep.
- Steps, energy, distance, and other health metrics.
- Completed HealthKit workout samples.

`ios-app/src/services/backgroundHealthSync.ts` currently:

- Periodically ingests HealthKit metrics.
- Ingests completed Apple Watch/HealthKit workouts to
  `/api/health/workouts/batch`.
- Deduplicates those workouts through their HealthKit workout UUID.

The backend stores those completed workouts in `external_workout`.

When a Sara strength workout is completed, the backend currently looks for a
same-day external Watch workout and chooses the best strength-like match. This
heuristic is a useful fallback, but it is not a sufficient primary link for a
Sara-owned Watch workout. The new Watch workout must carry and return the exact
Sara active-session ID.

### 3.5 Current voice and audio behavior

`ios-app/src/services/voice.ts` currently:

- Records audio.
- Supports hold-to-talk and continuous voice flows.
- Sends text to `/api/voice-agent/speak`.
- Plays Sara's backend-generated voice audio.
- Chunks and prefetches long TTS responses.
- Attempts to duck other audio for recording/listening modes.

This is suitable as a voice source, but active workout coaching must not depend
only on foreground JavaScript execution. A native audio coordinator is required
for reliable short coaching while the phone is locked, backgrounded, or showing
another app.

### 3.6 Current native ambient surfaces

The app already has:

- A Sara home/lock-screen widget.
- Timer Live Activities.
- Ongoing workout/task Live Activities.
- Siri "Ask Sara" App Intent support.
- A shared App Group for iPhone/widget data.
- A native Expo module that controls WidgetKit and ActivityKit.

The new Watch target must coexist with these. Do not convert the existing widget
target into the Watch app.

---

## 4. Product Contract

### 4.1 One canonical workout

There must never be separate "phone workout" and "Watch workout" records.

Use these authority boundaries:

| Concern | Authority |
| --- | --- |
| Template, exercises, approved targets, set logs, cursor, proposals | Sara backend active workout |
| Live heart rate, active energy, elapsed HealthKit workout | Watch `HKWorkoutSession` and `HKLiveWorkoutBuilder` |
| Full editing and detailed control | Existing iPhone workout UI |
| Fast set control and live physiology | Watch UI |
| AirPods coaching playback | iPhone native audio coordinator |
| Cross-device transport | HealthKit workout mirroring plus versioned wire messages |
| Durable reconciliation | Backend command log and session version |

The Watch owns the primary HealthKit workout session because the sensors and
workout runtime live there. The iPhone receives a mirrored session.

### 4.2 Start from Watch

1. David opens Sara on the Watch.
2. The first screen shows Today's Workout, Resume if active, and recent/other
   templates.
3. David chooses a workout.
4. The Watch creates a traditional-strength `HKWorkoutSession`, attaches a live
   workout builder, and starts collection.
5. The Watch begins mirroring the workout to the companion iPhone.
6. The Watch sends a versioned `start_requested` message containing the template
   ID, a unique command ID, and HealthKit start time.
7. The iPhone companion receives the mirrored workout and sends the idempotent
   start command to Sara's backend.
8. The backend either:
   - Creates one active session and returns its projection.
   - Returns the existing active session for resume.
   - Returns an explicit conflict that requires David to choose Resume or End.
9. The iPhone sends the accepted projection back to the Watch.
10. The iPhone starts/updates the existing workout Live Activity.
11. If the iPhone is not visibly open, it does not need to force foreground.
    When David opens Sara, it must route directly to the active workout.

The Watch may display a local "Starting..." state while waiting for the backend,
but it must not invent a second active Sara session.

### 4.3 Start from iPhone

1. David starts a workout from the current Fitness or Workout Mode flow.
2. The iPhone sends an idempotent backend start command.
3. After the backend accepts the session, iPhone calls
   `HKHealthStore.startWatchApp(with:)` using the mapped workout configuration.
4. The Watch app launches or wakes and starts the primary workout session.
5. The iPhone receives the mirrored workout through
   `workoutSessionMirroringStartHandler`.
6. The iPhone sends the Sara session projection and session ID to the Watch.
7. Both surfaces show the same exercise, set, targets, and rest state.

Do not start the backend and HealthKit sessions in an untracked fire-and-forget
race. Persist a start attempt ID and reconcile partial success:

- Backend accepted, Watch failed -> keep Sara session and present Retry Watch.
- Watch started, backend delayed -> keep local Watch workout, retry the same
  idempotent start command, and prevent set loss.
- Existing Apple Workout is active -> present a clear conflict; do not silently
  end or replace it.

### 4.4 During the workout

Every action uses the same command contract whether it originated on iPhone or
Watch:

- Log set.
- Select exercise.
- Set machine/variation.
- Skip exercise.
- Start/stop rest.
- Approve/reject a proposal.
- Complete.
- Abandon.

The command is acknowledged only after durable backend acceptance. The UI may be
optimistic, but it must reconcile to the returned session version.

The other device receives the new projection immediately through workout
mirroring. Foreground polling remains as a reconciliation fallback, not the
primary interaction transport.

### 4.5 Completion

Completion is a coordinated two-phase operation:

1. The originating device requests canonical Sara workout completion.
2. The backend returns a completed projection or an idempotent replay.
3. The Watch stops activity collection and asks the live builder to finish.
4. The HealthKit workout is saved with Sara session metadata.
5. The Watch sends the HealthKit workout UUID and final metrics to the iPhone.
6. The iPhone/backend link the exact HealthKit workout to the Sara session.
7. Both devices end their active UI and Live Activity.
8. The summary can update when final HealthKit statistics arrive, without
   creating another workout or requiring same-day heuristic matching.

If HealthKit finalization succeeds before backend completion, retain the exact
link locally and retry completion. If backend completion succeeds first, show
"Finishing Health data..." rather than silently losing the physiological record.

### 4.6 Abandonment

Abandonment remains destructive and requires confirmation.

- Confirm on the device where it was requested.
- Broadcast the decision to the other device.
- End the HealthKit session using the chosen discard/save policy.
- Preserve the existing backend rule that abandoned Sara sets are removed unless
  product behavior is intentionally changed in a separately approved decision.
- Never auto-abandon merely because another device issues Start.

---

## 5. Canonical Cross-Device Contracts

Do not send ad hoc dictionaries between Swift, React Native, and Python. Define a
versioned contract and generate/duplicate small Codable/TypeScript/Pydantic
representations with parity tests.

### 5.1 Workout projection

The backend returns a complete renderable projection:

```json
{
  "schema_version": 1,
  "session_id": "uuid",
  "version": 14,
  "status": "active",
  "started_at": "2026-07-25T18:02:00Z",
  "origin_device": "watch",
  "template": {
    "id": "uuid",
    "name": "Upper A",
    "is_deload": false
  },
  "cursor": {
    "exercise_index": 1,
    "set_index": 2
  },
  "progress": {
    "completed_sets": 6,
    "total_sets": 18,
    "total_volume": 8430
  },
  "current_exercise": {
    "name": "Incline Dumbbell Press",
    "variant": null,
    "target_sets": 4,
    "target_reps": "8-10",
    "target_rpe": 8,
    "approved_weight": 65,
    "completed_sets": 2,
    "last_session": {
      "weights": [60, 60, 60, 60],
      "reps": [10, 10, 9, 8],
      "avg_rpe": 7.5
    },
    "progression_note": "Last approved progression: 60 -> 65 lb"
  },
  "rest": {
    "active": true,
    "started_at": "2026-07-25T18:18:20Z",
    "duration_seconds": 120
  },
  "pending_proposal": null,
  "updated_at": "2026-07-25T18:18:22Z"
}
```

The projection may include the full exercise list for iPhone. The Watch payload
may use a compact form, but it must carry the same session/version identity.

### 5.2 Command envelope

```json
{
  "schema_version": 1,
  "command_id": "client-generated-uuid",
  "session_id": "uuid",
  "expected_version": 14,
  "origin_device": "watch",
  "kind": "log_set",
  "created_at": "2026-07-25T18:18:22Z",
  "payload": {
    "exercise_index": 1,
    "weight": 65,
    "reps": 9,
    "effort": "hard",
    "notes": null
  }
}
```

Required properties:

- `command_id` is globally unique and client-generated before sending.
- A replay of the same command returns the same result and cannot duplicate a
  set.
- `session_id` prevents a delayed command from mutating a newer workout.
- `expected_version` detects stale UI.
- `origin_device` is recorded for diagnostics and conflict analysis.
- The backend returns `accepted`, `replayed`, `conflict`, the current projection,
  and any newly created event/proposal IDs.

### 5.3 Wire envelope

Watch/iPhone transport uses:

```json
{
  "schema_version": 1,
  "message_id": "uuid",
  "session_id": "uuid-or-null",
  "kind": "command_requested",
  "sent_at": "2026-07-25T18:18:22Z",
  "payload": {}
}
```

Watch -> iPhone message kinds:

- `start_requested`
- `command_requested`
- `live_metrics`
- `healthkit_started`
- `healthkit_paused`
- `healthkit_resumed`
- `healthkit_finished`
- `watch_recovered_session`

iPhone -> Watch message kinds:

- `start_accepted`
- `start_conflict`
- `command_accepted`
- `command_rejected`
- `projection_updated`
- `coaching_event`
- `proposal_created`
- `proposal_resolved`
- `finish_confirmed`

Unknown schema versions or message kinds must be ignored safely and surfaced in
diagnostics. Never crash an active workout because one device is on an older
build.

### 5.4 Coaching event

```json
{
  "event_id": "uuid",
  "session_id": "uuid",
  "after_version": 15,
  "kind": "set_feedback",
  "text": "Good set. Hold 65 pounds and aim for nine again.",
  "speak": true,
  "priority": "normal",
  "expires_at": "2026-07-25T18:19:15Z",
  "proposal_id": null
}
```

Coaching is an event, not a state mutation.

### 5.5 Adjustment proposal

```json
{
  "proposal_id": "uuid",
  "session_id": "uuid",
  "kind": "next_set_weight",
  "scope": {
    "exercise_index": 1,
    "set_index": 3
  },
  "current_value": { "weight": 65 },
  "proposed_value": { "weight": 60 },
  "reason": "The last set was above the approved effort target.",
  "evidence": {
    "target_rpe": 8,
    "reported_effort": "hard",
    "completed_reps": 8
  },
  "status": "pending",
  "expires_at": "2026-07-25T18:21:00Z"
}
```

Approval applies the exact proposal atomically. Rejection, dismissal, timeout,
or device disconnection leaves the current state unchanged.

---

## 6. Backend and Database Work

This work belongs on the core/native branch.

### 6.1 Add session versioning and device identity

Add to `active_workout_session`:

- `version BIGINT NOT NULL DEFAULT 1`
- `origin_device VARCHAR(20)`
- `healthkit_state VARCHAR(20)`
- `healthkit_workout_uuid VARCHAR(128)`
- `healthkit_activity_type VARCHAR(80)`
- `healthkit_started_at TIMESTAMPTZ`
- `healthkit_ended_at TIMESTAMPTZ`
- `last_device_sync_at TIMESTAMPTZ`

Use a migration with repository-standard Alembic helpers. Do not edit the
database manually.

### 6.2 Add durable command idempotency

Create `workout_session_command`:

- `command_id UUID/TEXT PRIMARY KEY`
- `session_id`
- `user_id`
- `origin_device`
- `kind`
- `expected_version`
- `payload JSONB`
- `result JSONB`
- `status`
- `created_at`
- `applied_at`

For every mutation:

1. Begin a transaction.
2. Return the stored result if `command_id` already exists.
3. Lock the active session row.
4. Validate user, session ID, status, and expected version.
5. Apply the mutation once.
6. Increment session version.
7. Store the result projection.
8. Commit.

Set logging must have a unique client command reference as an additional defense
against duplicate set rows.

### 6.3 Add proposal persistence

Create `workout_adjustment_proposal`:

- `id`
- `user_id`
- `session_id`
- `kind`
- `scope JSONB`
- `current_value JSONB`
- `proposed_value JSONB`
- `reason`
- `evidence JSONB`
- `status` (`pending`, `approved`, `rejected`, `expired`, `superseded`)
- `created_at`
- `expires_at`
- `resolved_at`
- `resolved_by_device`
- `approval_command_id`

Only the approval service can apply `proposed_value`.

### 6.4 Link external HealthKit workouts directly

Add to `external_workout`:

- `sara_session_id`
- an index on `(user_id, sara_session_id)`

Write `com.avery.sara.session_id` and a stable Sara start-attempt ID into the
HealthKit workout metadata. Extract that metadata during HealthKit ingestion.

Linking order:

1. Exact Sara session metadata.
2. Previously stored HealthKit workout UUID.
3. Current strength/day/time heuristic as a legacy fallback.

Never create a second Fitness workout from the HealthKit ingestion of a workout
that already belongs to a Sara session.

### 6.5 Introduce a versioned command API

Recommended endpoints:

- `POST /api/fitness/workout-session/v2/start`
- `GET /api/fitness/workout-session/v2/active`
- `POST /api/fitness/workout-session/v2/commands`
- `GET /api/fitness/workout-session/v2/sync?after_version=N`
- `POST /api/fitness/workout-session/v2/healthkit-link`
- `GET /api/fitness/workout-session/v2/catalog`

Keep the existing endpoints operational through a compatibility adapter until
the current phone path has moved to the new command service.

Do not maintain two independent workout mutation implementations. Old endpoints
must translate into v2 commands internally.

### 6.6 Stop implicit abandonment

Change Start behavior:

- No active session -> create.
- Same idempotent start attempt -> replay.
- Active session for the same template -> return Resume.
- Active session for another template -> `409 active_workout_conflict` with the
  active projection.
- End or abandon requires an explicit follow-up command.

### 6.7 Separate command acceptance from coaching generation

The current set path waits for LLM coaching. Refactor:

1. Commit and acknowledge the set immediately.
2. Produce a deterministic immediate event when needed, such as PR or rest
   start.
3. Queue richer coaching generation after commit.
4. Store coaching as an ordered workout event.
5. Deliver it through the sync response and mirrored iPhone/Watch channel.
6. Drop expired coaching rather than speaking stale advice.

The set command must remain successful even if coaching generation or TTS fails.

### 6.8 Preserve current progression behavior while enforcing approval

Today, progression logic computes a suggested starting weight at session start.
Split calculation from application:

- `calculated_suggestion`: Sara's current recommendation.
- `approved_prescription`: the most recently approved execution target.
- `pending_proposal`: difference between the two, if material.

Starting a workout pre-fills the approved prescription. A new calculated
suggestion is presented for approval before it changes the execution target.

Post-workout progression should create proposals for the next workout, allowing
David to approve them outside the gym rather than approving every exercise at
the next start.

### 6.9 Standing policy approvals

Support durable bounded policies:

- Adaptive rest enabled/disabled.
- Allowed rest range.
- Speak routine coaching.
- Speak PRs.
- Speak proposals.
- Automatically start rest after a logged set.

These policies are approved settings. Sara may operate inside them without
asking repeatedly. She may not silently widen their scope.

---

## 7. Native Apple Architecture

This infrastructure belongs on the core/native branch. Visible product screens
belong on the UI branch.

### 7.1 Add a separate Watch app target

Add `ios-app/targets/watch/` rather than changing `targets/widget/`.

Expected target configuration:

- Type: companion Watch app.
- Bundle ID: `cloud.avery.sara-ios.watch` or the repository's chosen equivalent.
- Companion app bundle ID: `cloud.avery.sara-ios`.
- SwiftUI.
- HealthKit.
- WatchKit.
- A deployment target compatible with David's actual Watch.
- Health share/update usage descriptions.
- HealthKit entitlement.

The plan assumes iOS 18 and a compatible modern watchOS release. Confirm David's
Watch model and watchOS before fixing the Watch deployment target.

Create and sign the target in a small build-only phase before implementing the
workout UI. Verify:

- EAS generates the target.
- The App ID and provisioning profile exist.
- HealthKit capability is enabled for the Watch target.
- The companion relationship is correct.
- The Watch app installs on a physical paired device.

If `@bacons/apple-targets` cannot produce a reliable Watch target, create a
focused Expo config plugin that adds the native target deterministically. Do not
hand-edit generated Xcode files as the long-term solution.

### 7.2 Add an iPhone native workout coordinator

Prefer a dedicated module:

`ios-app/modules/sara-workout-native`

Responsibilities:

- Own `HKHealthStore` multidevice workout setup on iPhone.
- Call `startWatchApp(with:)`.
- Register `workoutSessionMirroringStartHandler` early in app startup.
- Recover a mirrored/active workout after process restart.
- Send and receive versioned remote workout messages.
- Emit native events to React Native.
- Maintain the iPhone side of the HealthKit mirror while the JS UI is absent.
- Coordinate native coaching audio.
- Expose current mirror/Watch reachability diagnostics.

Do not overload the existing widget/Live Activity module with this lifecycle.

Suggested JS interface:

```ts
startWorkoutOnWatch(configuration): Promise<StartAttempt>
sendWorkoutMessage(envelope): Promise<void>
getMirroredWorkoutState(): Promise<NativeWorkoutState>
endMirroredWorkout(reason): Promise<void>
setWorkoutAudioPolicy(policy): Promise<void>
addListener('workoutMessage', handler)
addListener('liveMetrics', handler)
addListener('mirrorStateChanged', handler)
addListener('coachingPlaybackChanged', handler)
```

### 7.3 Watch workout manager

Create a native `WorkoutManager` that owns:

- `HKHealthStore`
- `HKWorkoutSession`
- `HKLiveWorkoutBuilder`
- Workout session delegate.
- Live workout builder delegate.
- Mirroring start/stop.
- Remote message send/receive.
- Recovery after Watch app lifecycle changes.
- Final HealthKit workout creation.
- Session metadata linking to Sara.

The primary activity mapping must be explicit:

- Strength templates -> traditional strength training.
- Cardio presets -> the appropriate activity type when known.
- Tabata/interval sessions -> HIIT when appropriate.
- Unknown/custom -> functional strength or other approved fallback.

### 7.4 Use HealthKit workout mirroring for live transport

Use Apple's multidevice workout APIs:

- Watch: `startMirroringToCompanionDevice`.
- iPhone: `workoutSessionMirroringStartHandler`.
- Both: `sendToRemoteWorkoutSession(data:)`.

Use this for low-latency active-workout messages and metrics.

Do not use the shared App Group for Watch/iPhone workout transport. The current
App Group is appropriate for the iPhone/widget extension on one device, not as
the cross-device workout protocol.

### 7.5 Template catalog on Watch

The Watch needs enough data to start without navigating the phone first.

The iPhone should synchronize a compact catalog whenever:

- Authentication completes.
- Fitness templates load or change.
- The daily target changes.
- The app enters foreground.

Cache on Watch:

- Today's workout.
- Active workout projection, if any.
- Recent/favorite templates.
- Template ID/name/exercise count.
- Minimal exercise targets required to render a pre-start summary.
- Catalog generation time.

The backend projection remains authoritative after Start. Cached template data
must never create a different canonical workout snapshot.

### 7.6 Live metrics policy

Watch should calculate and render:

- Heart rate.
- Active energy.
- Elapsed time.
- Optional heart-rate zone once defined.

Send to iPhone at a controlled rate:

- UI updates may be up to 1 Hz.
- Cross-device messages should be throttled/coalesced.
- Backend summaries should not receive raw one-second heart-rate events unless
  there is a defined storage and privacy need.

The completed HealthKit workout remains the authoritative physiological record.

### 7.7 Recovery and offline queue

The Watch must retain:

- The active Sara session ID.
- Last accepted session version.
- Unacknowledged command envelopes.
- HealthKit start metadata.
- Last full projection.

On reconnect:

1. Replay unacknowledged commands using their original command IDs.
2. Accept idempotent stored results.
3. Fetch the latest projection.
4. Resolve version conflicts visibly if the action can no longer apply.
5. Never duplicate sets.

If phone/backend communication is unavailable, allow set logging into the Watch
queue with an explicit pending indicator. HealthKit tracking must continue.

---

## 8. Watch Product UI

All visible Watch screens belong on the UI branch based on the completed
core/native foundation.

### 8.1 Watch home

Priority order:

1. Resume active workout.
2. Start Today's Workout.
3. Other workouts.
4. Connection/HealthKit problem only when actionable.

Do not turn the Watch app into the complete Fitness dashboard. Its purpose is
starting and controlling active training.

### 8.2 Pre-start screen

Show:

- Workout name.
- Exercise count.
- Approved day type.
- Expected duration when available.
- Readiness note from Sara, if present.
- `Start Workout`.
- A concise link/action for choosing a different cached workout.

If Sara has an unapproved workout-level recommendation, show the current
approved workout as the default and the proposal separately.

### 8.3 Active set screen

The default wrist-raise screen shows:

- Exercise name.
- Set X of Y.
- Live heart rate.
- Target weight and reps.
- Previous set result.
- Large `Log Set`.
- Rest state when active.

Actions:

- Adjust weight with the Digital Crown or plus/minus.
- Adjust reps.
- Log Set.
- Effort: Easy / Right / Hard.
- Open exercise list.
- Skip.
- Finish.

The most common path should require one deliberate tap after a set when the
weight and reps match the approved/default values.

### 8.4 Rest screen

Show:

- Large countdown.
- Live heart rate.
- Next-set target.
- Stop/skip rest.
- Pending proposal if one exists.

Haptics:

- Optional warning at 10 seconds.
- Strong completion haptic.
- Distinct haptic for an approval request.
- Distinct success haptic for a PR.

### 8.5 Exercise list

Show every exercise with:

- Completed/target sets.
- Current marker.
- Partial marker.
- Tap to jump.

Preserve the current phone ability to do exercises in any order and return to a
skipped machine.

Machine/variation selection may use a short recent list on Watch. Full search,
creation, and detailed editing remain on iPhone.

### 8.6 Proposal screen

Show:

- What Sara recommends.
- Current versus proposed value.
- One-sentence reason.
- `Approve`.
- `Keep current`.
- Optional `Discuss on iPhone`.

No countdown default may apply the proposal automatically.

### 8.7 Completion screen

Show:

- Duration.
- Sets.
- Volume.
- Average/max heart rate when finalized.
- Calories.
- PRs.
- Pending next-workout proposals.
- `Done`.

Detailed history and editing remain on iPhone.

---

## 9. iPhone Product Integration

Visible iPhone changes belong on the UI branch. Native events and state
coordination belong on the core/native branch.

### 9.1 Preserve current phone flexibility

Do not remove or degrade:

- Weight/reps direct entry.
- Machine/variation management.
- Set feedback.
- Exercise jumping.
- Skip/return.
- Rest controls.
- PR display.
- Full exercise list.
- Embedded Sara chat.
- Completion/abandonment.
- Workout history and editing.

Refactor `WorkoutModeContext` behind a stable coordinator interface so the
existing `WorkoutPanel` can consume v2 projections without a full rewrite.

### 9.2 Active workout entry

When Watch starts:

- The Fitness screen shows `Workout active on Watch`.
- The persistent Sara workout Live Activity begins/updates.
- Tapping the banner opens Workout Mode.
- Opening the app from cold start routes to the active workout after auth.

Do not force a disruptive visible app launch solely because the Watch started.

### 9.3 Device state

In Workout Mode, show device state quietly:

- Watch tracking.
- Heart rate available.
- Reconnecting.
- Pending Watch actions.
- HealthKit permission required.

Do not display transport terminology in normal success states.

### 9.4 Phone-originated actions

Phone actions use the same command IDs and versions as Watch actions. The phone
may remain optimistic for responsiveness, but it must show a short reconciliation
state instead of silently discarding conflicts.

### 9.5 Coaching and approvals

When coaching speaks:

- Render the same sentence briefly in the phone workout UI.
- If it contains a proposal, show Approve/Keep current.
- Keep the proposal accessible after speech finishes.
- Do not hide a pending proposal after five seconds like ordinary coaching.

### 9.6 Fitness navigation

Promoting Fitness to a primary iOS tab and consolidating its eight internal tabs
remain good product recommendations, but they are not prerequisites for the
Watch companion. Do not combine that broader navigation redesign with the
core/native Watch migration.

If implemented later on the UI branch, preserve all current features under:

- Today.
- Train.
- Eat.
- Progress.

---

## 10. AirPods Coaching

### 10.1 Audio owner

Use the iPhone as the primary coaching-audio owner because YouTube Music and the
AirPods route normally live there.

The Watch sends coaching events to iPhone. The iPhone fetches/plays Sara's voice.
If iPhone audio is unavailable, Watch shows text and haptics rather than playing
a competing second voice path in the first release.

### 10.2 Native audio session

Create a native `WorkoutCoachingAudioCoordinator` using `AVAudioSession`.

For short exercise-style spoken prompts:

- Use a playback/spoken-audio configuration.
- Use `duckOthers`.
- Use `interruptSpokenAudioAndMixWithOthers` as appropriate.
- Activate only for the prompt.
- Deactivate with `notifyOthersOnDeactivation`.
- Restore music promptly.

Do not leave YouTube Music ducked across a whole workout.

### 10.3 Voice source

Prefer the existing Sara/Kokoro TTS endpoint so workout coaching sounds like the
same Sara as chat.

Reliability layers:

1. Prefetched/cached fixed prompts for countdowns and basic transitions.
2. Backend TTS for contextual coaching.
3. Native synthesized fallback when network/TTS is unavailable.
4. Text plus haptic if audio playback fails.

### 10.4 Speech queue

The native queue must:

- Deduplicate by coaching event ID.
- Drop expired events.
- Prevent overlapping speech.
- Allow critical events to replace routine events.
- Cancel cleanly when the workout ends.
- Avoid speaking a proposal after it has already been rejected.
- Avoid speaking old coaching after a newer set has been logged.

### 10.5 Useful spoken moments

Speak:

- Workout started and first approved target.
- Set logged when confirmation is helpful.
- Ten seconds remaining, if enabled.
- Rest complete.
- Exercise transition.
- PR.
- Specific adjustment proposal.
- Workout completion summary.

Do not speak:

- Every live heart-rate update.
- Routine UI state.
- Debugging or connectivity messages.
- Long plan explanations during a set.

### 10.6 Verbal approval

Tap approval on Watch/iPhone is required for the first release.

Voice approval can follow after the state/transport path is reliable:

- Sara asks a closed question.
- David explicitly says yes/no through AirPods.
- Speech recognition returns a constrained intent.
- The phone presents/announces the interpreted action.
- The backend receives a normal idempotent approval command.

Never treat ambiguous speech or silence as approval.

---

## 11. Approval and Safety Model

### 11.1 Actions Sara may take without a new approval

- Observe live heart rate and workout progress.
- Speak already approved targets.
- Confirm successful user actions.
- Start a rest timer under an approved policy.
- Calculate recommendations.
- Create proposals.
- Record health data generated by the user-started workout.
- Synchronize state between the user's devices.

### 11.2 Actions requiring explicit approval

- Change target weight or reps.
- Add/remove/reorder an exercise.
- Change set count or RPE target.
- Change from training to rest or rest to training.
- Change nutrition/macros.
- Modify a program or phase.
- Apply progression for a future workout.
- Expand an approved automation policy.

### 11.3 Proposal application rules

- Apply only the exact proposed values.
- Re-check that the proposal still matches the current session version/scope.
- Reject stale proposals with a new explanation.
- Store who/where approved it.
- Return the new projection.
- Broadcast resolution to both devices.
- Keep an audit trail visible in detailed workout history.

### 11.4 Wording rules

Before approval:

- "I recommend..."
- "Would you like me to..."
- "Approve?"

After approval:

- "Approved. I changed..."

Never say "I dropped the weight" before the approval transaction succeeds.

---

## 12. Branch and Worktree Strategy

The user requires UI changes to remain separate from core behavior changes.

### 12.1 Current repository caution

At the time this plan was written, the current worktree was on
`feat/singular-sara-proactivity-core` and contained existing modifications in
HealthKit-related iOS files. The implementing agent must not switch branches or
overwrite those changes in this dirty worktree.

Use a clean Git worktree or first ensure the existing owner has committed their
work. Preserve all unrelated changes.

### 12.2 Core/native branch

Suggested branch:

`feat/sara-watch-workout-core`

Contains:

- Database migrations.
- Versioned command/proposal/event model.
- Backend compatibility adapters.
- Direct HealthKit workout linking.
- Watch target scaffolding and capabilities.
- Native iPhone workout coordinator.
- Watch HealthKit workout manager.
- Cross-device wire models.
- Offline/idempotency mechanics.
- Native AirPods coaching coordinator.
- Tests and feature flags.

It must not include the broader iPhone navigation/Fitness redesign.

The Watch target may contain a minimal diagnostic shell required to compile and
exercise native behavior. Product Watch screens belong on the UI branch.

### 12.3 UI branch

Suggested branch:

`feat/sara-watch-workout-ui`

Create it from the completed core/native branch or from its stable contract
commit.

Contains:

- Product Watch SwiftUI screens.
- Watch haptics and interaction polish.
- iPhone Watch status/banner.
- Proposal controls.
- Coaching display.
- Workout audio settings.
- Optional later Fitness-tab promotion and four-area Fitness organization.

### 12.4 Integration order

1. Merge or stabilize core contracts.
2. Prove Watch target installation and HealthKit workout on physical devices.
3. Prove bidirectional start and command sync using diagnostic controls.
4. Build product Watch UI.
5. Add native audio coaching.
6. Roll iPhone UI integration onto the same contracts.
7. Enable for David only behind a feature flag.
8. Remove old mutation paths only after live parity.

### 12.5 EAS-first build and credential runbook

The absence of Xcode on the Linux repository host is not an implementation
blocker. The implementing agent must create the Watch target and attempt the
minimal EAS build spike before requiring the MacBook.

Repository configuration must declare the Watch target early enough for EAS
credential discovery:

- Give the target a stable bundle identifier, such as
  `cloud.avery.sara-ios.watch`.
- Configure the companion iPhone bundle identifier.
- Declare the Watch target and its entitlements through
  `@bacons/apple-targets`.
- Confirm the resolved Expo config contains the Watch target under
  `extra.eas.build.experimental.ios.appExtensions`.
- Include `com.apple.developer.healthkit` and all required HealthKit usage
  descriptions in the resolved target configuration.
- Do not commit certificates, provisioning profiles, Apple passwords, session
  cookies, or two-factor codes.

Initial credential flow:

1. From `ios-app`, validate the resolved Expo configuration and generated target
   metadata on Linux.
2. David starts an iOS development build using the existing EAS project and
   development profile.
3. EAS detects the new Watch target and requests credentials for its bundle
   identifier.
4. Because the paid membership is an individual account, David's dad, as
   Account Holder, signs in and completes two-factor authentication.
5. Allow EAS to register the Watch identifier, synchronize the supported
   HealthKit capability, and create or update the Watch provisioning profile.
6. EAS stores the resulting managed credentials so later builds can normally be
   initiated without another Apple login until identifiers, capabilities,
   devices, or profiles change.
7. Install the resulting iPhone build and its embedded companion Watch app on
   David's paired devices.

The first attempt should use:

```bash
cd ios-app
eas build --platform ios --profile development
```

Do not create a separate App Store Connect product for the companion Watch app.
It is embedded in the existing Sara iPhone application. The new target still
requires its own Apple bundle identifier and provisioning profile.

EAS log failures are not, by themselves, a reason to move to the MacBook. Fix
ordinary Swift compilation, target configuration, entitlement, bundle
identifier, and provisioning errors from the source configuration and retry.

Escalate to the MacBook with Xcode when any of the following occurs:

- The generated Watch target or embed phase cannot be represented correctly by
  the Expo target plugin after focused fixes.
- EAS successfully archives the iPhone app but the Watch app is absent from the
  archive or cannot install.
- Signing requires inspecting or repairing the generated Xcode target directly.
- The application installs but HealthKit authorization, workout sessions,
  mirroring, WatchConnectivity, background execution, or AirPods routing fails
  without sufficient application diagnostics.
- A physical-device debugger or Apple device console is required.

The MacBook uses the same Git branch and source of truth. Do not make
unreproducible Xcode-only project edits; any required Xcode correction must be
encoded back into the target configuration or config plugin so EAS builds remain
repeatable.

---

## 13. Implementation Phases

### Phase 0: Baseline and guardrails

- Capture current phone workout behavior with focused integration tests.
- Test every existing `WorkoutModeContext` action.
- Test existing HealthKit workout ingestion and same-day fallback matching.
- Record current EAS build configuration and Apple capabilities.
- Confirm David's Watch model and watchOS.
- Add feature flags:
  - `watch_workout_enabled`
  - `workout_command_v2_enabled`
  - `workout_coaching_audio_enabled`
- Confirm a rollback path that leaves current iPhone workouts untouched.

Exit criteria:

- Existing phone workout flow has a regression suite.
- Watch work can be disabled without reverting code.

### Phase 1: Backend command foundation

- Add session version.
- Add durable command table.
- Add proposal table.
- Add HealthKit link columns.
- Implement v2 start/active/command/sync/link endpoints.
- Lock mutations transactionally.
- Make every command idempotent.
- Replace implicit Start abandonment with explicit conflict.
- Adapt old endpoints to the same command service.
- Separate set acknowledgment from coaching.

Exit criteria:

- Replaying Log Set cannot duplicate a row.
- Stale commands cannot mutate a newer session.
- Current phone tests pass through the compatibility adapter.

### Phase 2: Watch target build spike

- Add a minimal companion Watch target containing one diagnostic SwiftUI screen.
- Add the Watch bundle identifier, companion relationship, HealthKit capability,
  and usage text through reproducible Expo target configuration.
- Verify the resolved Expo config declares the target for EAS credential
  discovery.
- Start the development EAS build from Linux; do not require local Xcode for
  this first attempt.
- Have David's dad authenticate the individual Apple Developer account when EAS
  needs to create the Watch identifier and credentials.
- Confirm EAS registers or reuses the identifier, enables HealthKit, generates
  the Watch provisioning profile, and embeds the Watch app in the iPhone
  archive.
- Install a minimal Watch app on David's paired physical devices.
- Request HealthKit permissions.
- Start and finish a local Watch workout.
- Verify live heart rate arrives.
- Verify exactly one HealthKit workout is saved.

Exit criteria:

- Repeatable EAS build initiated from the Linux repository host.
- Watch target credentials remain managed in EAS after the Account Holder's
  initial authorization.
- Companion app installs on the paired Watch from the EAS-produced build.
- No product UI work begins before this is stable.

### Phase 3: Native multidevice workout mirror

- Add iPhone workout native module.
- Add Watch `WorkoutManager`.
- Start mirroring Watch -> iPhone.
- Launch Watch from iPhone using workout configuration.
- Register iPhone mirror handler during authenticated startup.
- Add versioned wire envelopes.
- Add native event delivery to React Native.
- Recover an active mirror after app lifecycle changes.

Exit criteria:

- Start works in both directions on physical devices.
- Phone can display Watch live heart rate.
- Mirrored message round-trip works with phone foregrounded and locked.

### Phase 4: Canonical session bridge

- Watch catalog cache.
- Watch Start -> backend session through iPhone.
- iPhone Start -> backend session -> Watch launch.
- Command gateway for log/select/skip/rest/complete/abandon.
- State projection broadcast.
- Offline Watch command queue.
- Idempotent replay.
- Direct HealthKit session metadata and final link.

Exit criteria:

- One set logged on Watch appears on phone and backend once.
- One set logged on phone appears on Watch.
- Disconnect/reconnect does not lose or duplicate sets.
- One completed workout produces one Sara record and one linked HealthKit record.

### Phase 5: Watch product UI

- Home/resume/today catalog.
- Pre-start.
- Active set screen.
- Digital Crown editing.
- Effort feedback.
- Rest screen/haptics.
- Exercise list and jump.
- Skip/finish/abandon.
- Proposal approval.
- Completion summary.
- Accessibility and dynamic type where applicable.

Exit criteria:

- A normal workout can be started and completed from Watch.
- The current phone flow remains fully available throughout.

### Phase 6: AirPods coaching

- Native audio coordinator.
- TTS fetch/cache/fallback.
- Event queue and expiry.
- Duck YouTube Music temporarily.
- Resume other audio after each prompt.
- Speak start, rest, transition, PR, proposal, and completion events.
- Render the same event on phone/Watch.

Exit criteria:

- Coaching is audible through AirPods while YouTube Music plays.
- Music returns after every prompt.
- No stale or duplicate coaching is spoken.

### Phase 7: Approval enforcement

- Split calculated suggestions from approved prescriptions.
- Create post-workout next-session proposals.
- Add in-session next-set proposals.
- Add approve/reject commands.
- Add bounded policy approvals.
- Remove any remaining path where coaching text mutates execution state.
- Add approval history to detailed workout data.

Exit criteria:

- No Sara-originated plan/target mutation can occur without a recorded approval
  or previously approved bounded policy.

### Phase 8: Reliability and rollout

- Background/locked-phone tests.
- Watch-only temporary network loss.
- Incoming call/Siri/audio interruption tests.
- HealthKit permission denial and revocation.
- Existing Apple Workout conflict.
- Crash/relaunch recovery.
- Battery and message-rate review.
- David-only feature rollout.
- Live telemetry review for at least several workouts.

Exit criteria:

- David can use the Watch flow daily without double-starting Apple Workout.
- The old iPhone path remains available as rollback.

### Phase 9: Optional Fitness information architecture

This remains UI-only and must not be mixed into the Watch core migration.

- Promote Fitness to a primary tab.
- Merge Chat into Sara.
- Organize Fitness as Today/Train/Eat/Progress.
- Keep all existing features reachable.

---

## 14. Testing Strategy

### 14.1 Backend automated tests

Add tests for:

- First start.
- Duplicate start replay.
- Start conflict with existing active workout.
- Duplicate Log Set command.
- Stale version.
- Wrong session ID.
- Phone and Watch commands in alternating order.
- Exercise jump with partial progress.
- Variant identity.
- Rest start/stop replay.
- Complete replay.
- Abandon confirmation path.
- Proposal creation without application.
- Approval application.
- Rejection/no mutation.
- Expired proposal/no mutation.
- HealthKit exact-link ingestion.
- Legacy same-day fallback.
- No duplicate external/Sara workout.
- Coaching failure does not fail Log Set.

### 14.2 Swift tests

Test:

- Codable parity for every wire envelope.
- Unknown schema/message handling.
- Command queue persistence.
- Command deduplication.
- Projection version ordering.
- Stale projection rejection.
- Start state machine.
- Finish state machine.
- Workout recovery after relaunch.
- Metrics throttling.
- Audio queue deduplication and expiration.

### 14.3 React Native tests

Test:

- `WorkoutModeContext` compatibility adapter.
- Watch-started active workout banner.
- Projection reconciliation.
- Pending command indicators.
- Proposal controls.
- Audio setting behavior.
- Existing phone controls.

### 14.4 Physical-device test matrix

Apple's multidevice workout sample requires physical devices. Simulator-only
validation is insufficient.

Run:

1. Start on Watch, phone foregrounded.
2. Start on Watch, phone locked.
3. Start on Watch, phone app not recently visible.
4. Start on iPhone, Watch app closed.
5. Start on iPhone, Watch temporarily unreachable.
6. Existing Apple Workout already active.
7. Log alternating sets from phone and Watch.
8. Tap Log Set twice during poor connectivity.
9. Move between exercises on both devices.
10. Disconnect Bluetooth/network mid-workout.
11. Reconnect and replay pending commands.
12. Complete from Watch.
13. Complete from iPhone.
14. Abandon from both surfaces.
15. Kill/relaunch the iPhone app.
16. Kill/relaunch the Watch UI while the workout session remains active.
17. Revoke HealthKit permission.
18. AirPods connected with YouTube Music playing.
19. Incoming phone call during coaching.
20. Siri interruption during coaching.
21. TTS endpoint unavailable.
22. Backend unavailable temporarily.
23. Verify one HealthKit workout and one Sara workout.
24. Verify final HR/calorie data links to the exact Sara session.

### 14.5 User acceptance scenario

The release is not accepted until David can:

1. Start Today's Workout from Watch.
2. Hear Sara confirm the first approved target through AirPods.
3. Log sets from Watch.
4. Open the phone and continue with full current controls.
5. Log the next set from phone and see Watch update.
6. Receive a spoken proposal.
7. Reject it and verify nothing changes.
8. Approve a later proposal and verify only that exact target changes.
9. Complete from either device.
10. See one linked summary with strength and heart-rate data.

---

## 15. Observability and Diagnostics

Add structured workout events without storing unnecessary raw health samples:

- Session start attempt.
- Origin device.
- Mirror connected/disconnected.
- Command received/applied/replayed/conflicted.
- Projection version.
- Pending offline command count.
- HealthKit workout started/finished/linked.
- Coaching created/spoken/dropped/failed.
- Proposal created/approved/rejected/expired.
- Completion partial failure and retry.

Useful operational metrics:

- Start success by origin device.
- Median command acknowledgment time.
- Duplicate command replay count.
- Version conflict count.
- Watch reconnect count.
- HealthKit direct-link success rate.
- Same-day fallback match rate.
- Coaching playback success.
- Other-audio restoration failure.
- Workouts completed through Watch.

Place raw transport diagnostics under Advanced/System. Do not expose them as
normal Fitness content.

---

## 16. Rollout and Rollback

### 16.1 Rollout

1. Ship backend v2 and compatibility adapter disabled for Watch.
2. Migrate current phone path to v2 behind a flag.
3. Validate phone parity.
4. Enable Watch target installation.
5. Enable Watch start for David.
6. Enable Watch mutation commands.
7. Enable native coaching.
8. Enable proposal enforcement.
9. Observe several real workouts before removing legacy paths.

### 16.2 Rollback

At every phase:

- Watch feature flag can hide Watch entry and stop new Watch starts.
- Existing phone workout endpoints continue through compatibility adapter.
- Existing HealthKit background ingestion continues.
- Same-day external workout matching remains fallback.
- A Watch-created active session can be resumed/completed from phone.
- Disabling coaching never blocks set logging.

Do not remove old routes, polling, or same-day matching until real-device parity
and multiple live workouts are confirmed.

---

## 17. Acceptance Criteria

The implementation is complete only when:

- A workout can start from Watch without manually starting Apple's Workout app.
- A workout can start from iPhone and launch/wake the Watch workout.
- Watch records live heart rate through HealthKit.
- Phone retains the complete current workout UI and actions.
- Both devices control one backend active session.
- Duplicate delivery cannot duplicate a set.
- Temporary disconnection does not stop HealthKit tracking.
- Pending Watch actions reconcile after reconnection.
- Completing from either device ends the other.
- Exactly one Sara workout is linked to exactly one HealthKit workout.
- AirPods coaching ducks/interferes with YouTube Music only during the prompt and
  music resumes afterward.
- Coaching failure cannot block workout logging.
- Sara cannot apply any unapproved change.
- Approved changes are exact, durable, visible, and auditable.
- Existing nutrition, recovery, cardio, plans, progress, photos, workout history,
  and phone logging remain intact.

---

## 18. Expected File Map

Likely new files:

- `backend/alembic/versions/<next>_watch_workout_sync.py`
- `backend/app/services/workout_command_service.py`
- `backend/app/services/workout_proposal_service.py`
- `backend/app/models` or route schemas for v2 contracts
- `ios-app/modules/sara-workout-native/expo-module.config.json`
- `ios-app/modules/sara-workout-native/index.ts`
- `ios-app/modules/sara-workout-native/ios/SaraWorkoutNativeModule.swift`
- `ios-app/modules/sara-workout-native/ios/IPhoneWorkoutCoordinator.swift`
- `ios-app/modules/sara-workout-native/ios/WorkoutCoachingAudioCoordinator.swift`
- `ios-app/modules/sara-workout-native/ios/WorkoutWireModels.swift`
- `ios-app/targets/watch/expo-target.config.js`
- `ios-app/targets/watch/SaraWatchApp.swift`
- `ios-app/targets/watch/WorkoutManager.swift`
- `ios-app/targets/watch/WorkoutWireModels.swift`
- `ios-app/targets/watch/WorkoutCommandQueue.swift`
- `ios-app/targets/watch/views/WatchHomeView.swift`
- `ios-app/targets/watch/views/ActiveWorkoutView.swift`
- `ios-app/targets/watch/views/RestView.swift`
- `ios-app/targets/watch/views/ExerciseListView.swift`
- `ios-app/targets/watch/views/ProposalView.swift`
- `ios-app/targets/watch/views/WorkoutSummaryView.swift`
- `ios-app/src/services/watchWorkout.ts`
- `ios-app/src/services/workoutCoordinator.ts`

Likely modified files:

- `backend/app/routes/fitness.py`
- `backend/app/services/workout_session_service.py`
- `backend/app/routes/health_metrics.py`
- `ios-app/app.json`
- `ios-app/src/services/fitness.ts`
- `ios-app/src/services/healthKit.ts`
- `ios-app/src/services/backgroundHealthSync.ts`
- `ios-app/src/context/WorkoutModeContext.tsx`
- `ios-app/src/screens/fitness/WorkoutModeScreen.tsx`
- `ios-app/src/components/fitness/WorkoutPanel.tsx`
- `ios-app/src/components/AuthenticatedOverlays.tsx`
- `ios-app/src/services/voice.ts` only where the foreground chat path shares
  policy; native workout audio should remain separately owned.

This list is directional. The implementing agent must follow existing repository
ownership and avoid forcing unrelated refactors.

---

## 19. Apple and Expo Reference Architecture

Implementation should follow Apple's official multidevice workout model:

- Building a multidevice workout app:
  https://developer.apple.com/documentation/HealthKit/building-a-multidevice-workout-app
- `HKWorkoutSession` mirroring and remote messages:
  https://developer.apple.com/documentation/HealthKit/HKWorkoutSession
- Launching/waking the companion Watch app:
  https://developer.apple.com/documentation/healthkit/hkhealthstore/startwatchapp%28with%3Acompletion%3A%29
- `HKHealthStore` mirror start handler:
  https://developer.apple.com/documentation/HealthKit/HKHealthStore
- Temporary audio ducking:
  https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/duckothers
- Spoken prompt audio behavior:
  https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/interruptspokenaudioandmixwithothers

Build and credential behavior should follow Expo's official EAS documentation:

- EAS iOS builds use remote macOS build infrastructure:
  https://docs.expo.dev/build/introduction/
- Generated app-extension target and credential discovery:
  https://docs.expo.dev/build-reference/app-extensions/
- HealthKit and other entitlement synchronization:
  https://docs.expo.dev/build-reference/ios-capabilities/
- Individual Apple Developer account credential permissions:
  https://docs.expo.dev/app-signing/apple-developer-program-roles-and-permissions/

Do not substitute generic WatchConnectivity-only synchronization for HealthKit
workout mirroring. WatchConnectivity may be used for catalog/bootstrap support if
needed, but the active workout lifecycle should follow the HealthKit APIs built
for this purpose.

---

## 20. Final Implementation Principle

Sara is not a separate coach on the Watch and another assistant on the phone.

There is one Sara, one active workout, one approved plan, one physiological
record, and one conversation about what to do next. The Watch, phone, AirPods,
Live Activity, and backend are bodies and surfaces for that same state.

The implementation succeeds when David can move between them without thinking
about synchronization, without double-starting workouts, without losing current
phone flexibility, and without Sara ever crossing the approval boundary.
