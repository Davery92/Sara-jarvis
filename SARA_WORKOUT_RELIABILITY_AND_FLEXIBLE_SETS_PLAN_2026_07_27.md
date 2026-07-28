# Sara Workout Reliability and Flexible Sets Plan

Date: 2026-07-27

Status: Draft for David's approval. This is a product and implementation plan,
not authorization to change workout templates or prescriptions.

## 1. Outcome

Sara should provide one workout shared by the phone, Apple Watch, backend, and
Apple Health.

David must be able to:

- start the workout from either the phone or Watch;
- get Apple Watch heart-rate and workout tracking without starting Apple's
  Workout app separately;
- log normal working sets from either device;
- add an extra working set during the current workout;
- log one or more drop-set segments with their actual weight and reps;
- correct a mistaken set without corrupting progress, volume, or PR history;
- switch devices at any time without creating a second workout;
- continue safely through temporary phone, Watch, mirror, or network failures.

Sara may recommend an extra set, drop set, weight change, or other adjustment,
but she may not apply it until David explicitly approves it. A direct control
tap by David is already explicit approval for that current workout only.

## 2. What Failed Today

### 2.1 Evidence

During the failed Watch start:

- the phone and Watch catalog were current;
- the Watch/phone path successfully called `GET /v2/sync` every four seconds;
- the phone fetched `GET /v2/catalog` successfully;
- the backend received no `POST /v2/start`;
- no canonical Sara workout session was created.

Therefore this was not a template, authentication, date-resolution, or backend
start failure. It failed locally in the Watch start sequence before the backend
request.

### 2.2 Current start sequence

`WorkoutManager.startWorkout()` currently performs one all-or-nothing chain:

1. Construct an `HKWorkoutSession`.
2. Start HealthKit activity.
3. Begin live data collection.
4. Start HealthKit mirroring to the phone.
5. Send `start_requested` through the mirrored workout session.

Any error in steps 1-4 produces only `Couldn't start the workout`, tears down
HealthKit, and prevents step 5. Ordinary WatchConnectivity may be healthy while
this path still fails.

Two concrete weaknesses must be addressed:

- normal pre-start does not explicitly request/check Watch HealthKit
  authorization; only the diagnostics screen currently does;
- HealthKit mirroring is a hard prerequisite for creating the Sara session,
  even though catalog WatchConnectivity is already working.

The exact HealthKit error domain/code was not retained or shown. Instrumenting
that is the first implementation task, not an optional cleanup.

## 3. Current Capability Inventory

### Watch active workout

Available now:

- weight and rep steppers;
- Easy / Right / Hard effort;
- log set;
- rest countdown and stop;
- exercise list and jump;
- skip exercise;
- finish or abandon;
- proposal approval;
- live heart rate and active energy when HealthKit works.

Missing:

- add or remove a planned set;
- log a drop-set segment;
- see sets logged in this workout;
- undo, edit, or void a mistaken set;
- distinguish working, warm-up, and drop sets;
- choose a custom rest duration;
- useful start-stage errors and retry controls.

### Phone active workout

The active synchronized workout has normal logging, weight/reps, effort,
variant, rest, jump, skip, finish, and proposals. It also lacks canonical
add-set, drop-set, undo, and edit commands.

The older manual `WorkoutLogModal` can add rows, but it is a separate logging
flow. It does not mutate the live cross-device session and must not be used as
the implementation shortcut.

### Backend

The canonical command service supports:

- `log_set`;
- `select_exercise`;
- `set_variant`;
- `skip_exercise`;
- `rest_start` / `rest_stop`;
- `complete` / `abandon`;
- proposal resolution and HealthKit state.

It has no live commands for adding, revising, or voiding sets. The current
`log_set` implementation considers an exercise complete at its prescribed set
count and clamps subsequent set indexes to that count. Extra-set behavior
therefore requires a contract and state-model change, not only UI buttons.

`set_technique` in a template is currently a prescription hint. It does not
describe what David actually logged. Planned technique and performed set type
must remain separate concepts.

## 4. Product Rules

### 4.1 One workout

There is one backend session ID and one versioned projection. Phone and Watch
are controllers of that session, not separate workout implementations.

Apple Health has at most one workout linked to that Sara session.

### 4.2 User actions versus Sara recommendations

A direct David action applies immediately to the current workout:

- Add Set;
- Log Drop Set;
- Undo Set;
- Edit Set;
- change weight, reps, effort, variant, exercise order, or rest.

A Sara-originated change is always a proposal:

- "Add one more set";
- "Do a drop set";
- "Reduce the next set to 135 lb";
- "Skip this movement";
- "Carry this adjustment into future workouts."

The proposed state is never preselected or silently applied.

### 4.3 Current workout versus future plan

Adding a set or drop set changes only the live workout snapshot.

It does not mutate:

- the template;
- the active program;
- later workouts;
- the progression prescription.

After the workout, Sara may separately ask whether David wants to make a
repeated adjustment permanent. That requires a separate approval.

### 4.4 Counting rules

Recommended behavior:

- an extra working set increases the live exercise target and workout total;
- a drop-set series belongs to one working set;
- drop segments add reps and volume but do not each consume another prescribed
  working-set slot;
- warm-up sets add volume/history but do not consume a working-set slot;
- a voided set no longer counts toward progress, volume, PRs, or progression;
- edits recompute derived values rather than incrementally guessing.

## 5. Start Reliability Design

### 5.1 Replace the monolithic start with a state machine

Track these states independently:

- HealthKit: `idle`, `authorizing`, `starting`, `running`, `failed`, `ended`;
- Sara session: `none`, `requesting`, `active`, `conflict`, `failed`;
- phone link: `watch_connectivity`, `mirroring`, `reconnecting`, `offline`.

The UI can then say what is actually happening:

- "Requesting Health access";
- "Starting Apple workout";
- "Connecting to Sara";
- "Workout running - reconnecting phone";
- "Sara session active - heart-rate tracking unavailable";
- "Another workout is already active."

### 5.2 Watch-start sequence

1. Request and verify Watch HealthKit authorization in the normal start flow.
2. Generate and persist one `start_attempt_id` before any side effect.
3. Start the Watch `HKWorkoutSession` and live builder.
4. Once HealthKit is running, submit `start_requested` through the general
   Watch transport.
5. Attempt HealthKit mirroring concurrently as an enhancement, not as the only
   command transport.
6. Phone calls the idempotent backend `v2/start`.
7. Phone returns the accepted projection through any available Watch transport.
8. Watch enters the active workout screen.
9. Mirroring may attach or reattach without changing the Sara session ID.

If HealthKit cannot start, do not create a Sara session from a Watch-originated
start. Show the actual permission or HealthKit failure and a retry path.

If HealthKit starts but the phone/backend is temporarily unreachable, preserve
the Apple workout and queued start attempt. Show "Apple workout running,
connecting to Sara" with Retry and End controls. Do not silently discard it.

If the backend reports an existing active Sara session, offer Resume Existing
and cleanly end/discard the new orphan HealthKit attempt.

### 5.3 Dual transport

Create one `WorkoutWireTransport` abstraction used by all workout envelopes:

1. Prefer the mirrored `HKWorkoutSession` channel when attached.
2. Fall back to interactive `WCSession.sendMessage` when reachable.
3. Fall back to durable WatchConnectivity user-info transfer for commands.
4. Keep application context for latest replaceable state such as catalog and
   projection, not ordered mutations.

The existing command ID and start-attempt ID provide exactly-once backend
effects when any transport retries.

Phone native code must receive WatchConnectivity workout envelopes and emit
them to the same JavaScript handler currently used for mirrored messages.
Replies follow the same transport abstraction.

### 5.4 Diagnostics

Persist a bounded diagnostic record containing:

- stage;
- timestamp;
- build number;
- HealthKit authorization status;
- HealthKit session state;
- error domain, code, and localized description;
- WatchConnectivity activation/reachability;
- mirror state;
- start-attempt ID;
- whether the backend received/accepted it.

The normal screen shows a useful sentence. Advanced diagnostics shows the
technical record. A generic `Couldn't start` message is insufficient.

## 6. Flexible Set Model

### 6.1 Performed set fields

Add structured fields to `workout_log` rather than hiding core analytics in
free-form notes:

- `set_kind`: `working`, `warmup`, or `drop`;
- `parent_set_id`: root working set for a drop segment;
- `set_group_id`: stable ID shared by the working set and its drops;
- `group_sequence`: 0 for the working set, then 1..n for drops;
- `counts_toward_target`: true only for working sets;
- `voided_at` and `void_reason`;
- optional `revised_from_set_id` for an auditable correction.

Keep template `set_technique` as planned guidance. Store actual performance in
the fields above.

### 6.2 Live snapshot fields

Every exercise in the session snapshot should expose:

- `prescribed_sets`: immutable number copied from the template;
- `target_sets`: effective working-set target for this workout;
- `completed_working_sets`;
- `completed_drop_segments`;
- recent performed sets with IDs and kinds;
- planned `set_technique`;
- current variant and approved prescription.

The projection's total-set count uses effective working-set targets. Volume
includes all non-voided set kinds.

### 6.3 New commands

All commands use existing command IDs, expected versions, origin devices, and
the command ledger.

`add_set`

- payload: `exercise_index`, `count` (initially restricted to 1);
- increments only the live `target_sets`;
- reopens/selects an exercise if its old target was already completed;
- returns the full updated projection.

`remove_unlogged_set`

- decrements only target sets that have not been completed;
- never deletes a logged set;
- cannot reduce target below prescribed sets without a separate explicit
  "reduce current workout" action.

`log_drop_segment`

- payload: `exercise_index`, `parent_set_id`, `set_group_id`, `weight`, `reps`,
  optional effort/RPE and notes;
- validates that the parent belongs to this session and exercise;
- adds volume but does not advance the working-set cursor;
- does not automatically start a normal rest timer between drop segments.

`revise_set`

- payload: set ID plus corrected weight, reps, effort/RPE, kind, or notes;
- recomputes session totals and PR state transactionally;
- records revision provenance.

`void_set`

- payload: set ID and optional reason;
- provides Undo Last Set on Watch and set deletion/correction on phone;
- recomputes cursor, completion, volume, PRs, rest, and proposals.

### 6.4 Recalculation service

Create one deterministic `recalculate_workout_session(session_id)` service.
After add, revise, void, or replay it derives:

- exercise completed counts;
- cursor;
- workout complete state;
- total sets;
- total volume;
- PR records;
- progression inputs;
- pending coaching/proposals that became stale.

This prevents five command handlers from implementing subtly different math.

## 7. Interaction Design

All visible UI work belongs on the separate UI branch described in Section 9.

### 7.1 Phone

Keep the normal Log Set path unchanged and fast.

Add a compact set-actions menu near Log Set:

- Add Working Set;
- Add Drop Set;
- View/Edit Sets;
- Undo Last Set.

Add Working Set:

- immediately changes `3 sets` to `4 sets` for this workout;
- displays `4 sets (3 prescribed)` so the difference is honest;
- works before or after the original last set.

Add Drop Set:

- starts from the just-logged working set;
- pre-fills a lower weight as a convenience, never as a Sara-approved plan;
- lets David adjust weight and reps;
- logs Drop 1, then offers Add Another Drop or Done;
- suppresses normal rest until Done.

View/Edit Sets:

- shows working, warm-up, and drop rows grouped visually;
- allows correcting or voiding a row;
- makes revisions visible in history without presenting audit jargon.

### 7.2 Watch

Preserve one-tap normal logging.

After a working set, the rest screen offers:

- Add Drop;
- Add Set;
- Undo.

Add Drop opens the same weight/reps controls, seeded from the last set at a
lower weight. After logging:

- Add Another Drop;
- Done.

Add Set increments the current exercise by one and returns to its set screen.

Undo only targets the most recently logged set and requires a brief
confirmation. Full arbitrary set editing remains on the phone; the wrist is for
fast operations, not spreadsheet editing.

### 7.3 Cross-device behavior

Every accepted action updates the canonical projection. If David adds a set on
the Watch, the phone immediately shows the new target. If he starts a drop set
on the phone, the Watch shows the active group and can log the next segment.

Stale-version conflicts reconcile to the server projection and retain the
unsent local values so David can retry instead of re-entering them.

## 8. Sara Coaching and Approval

Add proposal kinds:

- `add_working_set`;
- `perform_drop_set`;
- `reduce_current_target_sets`;
- existing weight proposals remain unchanged.

Approval applies the exact proposed current-session mutation. Rejection changes
nothing. Proposals expire when the exercise/session state makes them stale.

Sara's coaching should understand:

- drop segments are intentionally lower weight and must not trigger a generic
  "you regressed" response;
- warm-ups do not drive progression;
- extra sets contribute fatigue and volume;
- only non-voided working sets drive prescribed-set completion;
- future-template changes require a separate post-workout conversation.

## 9. Branch and Delivery Structure

### Branch A: core, no product UI

Suggested branch: `feature/workout-core-reliability`

Contains:

- failure instrumentation;
- HealthKit authorization preflight;
- start state machine;
- dual Watch transport;
- database migration;
- canonical set model;
- new commands;
- recalculation service;
- shared TypeScript/Swift wire contracts;
- backend, native, and contract tests.

This branch must preserve the existing phone UI and be independently testable
through APIs and the Watch diagnostics screen.

### Branch B: UI only

Suggested branch: `feature/workout-flexible-sets-ui`

Created after Branch A's contract is stable.

Contains:

- phone set actions/history editor;
- Watch Add Set, Add Drop, and Undo controls;
- start/reconnect/error states;
- accessibility, haptics, wording, and layout;
- UI/view-model tests and screenshots.

It must not invent different workout math or bypass canonical commands.

### Integration

Merge core first. Rebase UI onto the merged core, run the complete matrix, then
produce one iPhone/Watch build. Do not maintain a temporary phone-only set model.

## 10. Implementation Phases

### P0: reproduce and observe

- add stage-specific start diagnostics;
- reproduce permission denied, mirror unavailable, phone locked/backgrounded,
  and WatchConnectivity-only start;
- record the exact error that caused today's failure;
- add a developer command to export the bounded diagnostic log.

Exit: every failed start names its failed stage and leaves no unknown orphan.

### P1: reliable Watch start

- implement authorization preflight;
- implement the start state machine;
- add WatchConnectivity command/reply transport;
- make mirroring attach/retry independently;
- persist/replay start attempts;
- implement conflict and partial-success recovery.

Exit: Watch start succeeds even when HealthKit mirroring is temporarily
unavailable, provided HealthKit itself and WatchConnectivity work.

### P2: canonical flexible-set backend

- migration and backfill;
- performed-set model;
- effective target fields;
- recalculation service;
- add/remove/log-drop/revise/void commands;
- projection and API contract updates.

Exit: API-level tests prove the model without any new UI.

### P3: phone controller

- add session-only Add Set;
- drop-set workflow;
- performed-set list;
- edit and undo;
- reconcile conflicts without losing typed values.

Exit: the phone provides full control even if the Watch is absent.

### P4: Watch controller

- add set, drop segment, add another, done, and undo;
- display effective versus prescribed set count;
- support offline queue and reconnect;
- retain normal one-tap logging.

Exit: a complete flexible workout can be run from the Watch while the phone
remains optional as a larger editor.

### P5: Sara intelligence

- proposal types and approval UI;
- technique-aware coaching;
- post-workout proposal for future template changes;
- exclude warm-up/drop/voided sets from inappropriate progression logic.

Exit: Sara can recommend flexibility without taking control from David.

### P6: physical-device validation and rollout

- build and sign on the Mac using the documented Tailscale workflow;
- install parent app first and direct Watch app only when needed;
- run the acceptance matrix below;
- perform one short disposable physical workout;
- perform one real gym session with phone fallback available;
- monitor command and HealthKit linkage for 24 hours.

## 11. Required Tests

### Start matrix

- Watch start with phone foreground, backgrounded, locked, and freshly killed;
- phone start with Watch available and unavailable;
- HealthKit not determined, granted, denied, and later granted;
- mirroring success, delay, disconnect, and reconnect;
- WatchConnectivity success and durable fallback;
- backend/network unavailable then restored;
- repeated Start taps and replayed attempts;
- pre-existing active workout conflict;
- Watch app relaunch during active workout;
- exactly one Sara session and one Apple Health workout.

### Set matrix

- add a set before the prescribed last set;
- add a set after the exercise originally completed;
- add on Watch and log it on phone, and vice versa;
- one and multiple drop segments;
- drop segment after an extra set;
- volume includes drop/warm-up work while target progress does not;
- undo normal, extra, and drop sets;
- revise weight/reps after a PR;
- recompute PR and progression after void/revision;
- duplicate and out-of-order commands;
- simultaneous phone/Watch actions with stale versions;
- finish while commands are queued;
- abandon removes/discards according to the existing product rule.

### Approval matrix

- user actions apply immediately only to the live session;
- Sara recommendation remains pending;
- approval applies exactly once;
- rejection applies nothing;
- no current-session action mutates a future template;
- explicit post-workout approval is required for future changes.

## 12. Acceptance Criteria

The release is ready when:

1. Ten consecutive Watch starts create one Apple workout and one Sara session.
2. At least one start succeeds with mirroring intentionally unavailable.
3. A permission failure explains how to recover and creates no backend session.
4. Phone and Watch show the same exercise, effective set target, and logs.
5. An extra set added on either device is immediately available on the other.
6. A three-segment drop set preserves each weight/reps pair and counts as one
   working set for progress.
7. Undo/edit recomputes progress, volume, PRs, and coaching correctly.
8. Duplicate commands never duplicate sets or target increments.
9. Sara cannot add work or change future programming without approval.
10. A full gym workout remains usable from the phone if Watch tracking fails.

## 13. Product Decisions to Confirm

Recommended defaults:

1. Drop-set structure: log each weight reduction as its own weight/reps segment,
   grouped under the working set.
2. Add Set scope: current workout only; future workouts require a separate
   approval.
3. Watch editing: Add Set, Add Drop, and Undo Last Set on Watch; full arbitrary
   history editing on phone.
4. Include warm-up sets in this model now because the same counting and
   progression rules are otherwise likely to require another migration.

David should confirm or change these four decisions before P2 contracts are
frozen.
