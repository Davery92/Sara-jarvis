import Foundation
import HealthKit
import os
import SwiftUI
import WatchConnectivity

/// Owns the primary `HKWorkoutSession` on the Watch (plan §7.3, §7.4).
///
/// The Watch holds the primary session — not the phone — because the sensors
/// and the workout runtime live here. The phone receives a *mirrored* session
/// and drives the Sara backend from it. That split is what removes David's
/// double-start: opening Sara on the wrist starts the real Apple workout, so
/// there is nothing left to start in Apple's Workout app.
///
/// Everything about Sara's plan (which exercise, what weight, whether a change
/// was approved) is backend state that arrives as a `WorkoutProjection`. This
/// class never invents it; the only state it originates is physiological.
@MainActor
public final class WorkoutManager: NSObject, ObservableObject {
    public static let shared = WorkoutManager()

    // MARK: - Published state

    @Published public private(set) var projection: WorkoutProjection?
    @Published public private(set) var heartRate: Double = 0
    @Published public private(set) var activeEnergy: Double = 0
    @Published public private(set) var elapsed: TimeInterval = 0
    @Published public private(set) var sessionState: HKWorkoutSessionState = .notStarted
    @Published public private(set) var isReachable = false
    @Published public private(set) var pendingCommandCount = 0
    @Published public private(set) var lastError: String?
    @Published public private(set) var coaching: WorkoutCoachingEvent?
    /// Last catalog the phone pushed. Lets the home screen render offline (§7.5).
    @Published public private(set) var catalog: WatchCatalog?
    /// Summary shown after Finish, kept until dismissed.
    @Published public private(set) var completion: WatchWorkoutSummary?

    /// Local optimism while the backend decides. Never a second Sara session —
    /// the Watch may show "Starting…", it may not invent a workout (§4.2).
    @Published public private(set) var isStarting = false

    /// The three independently-failing stages of a start (2026-07-27 plan §5.1).
    /// The UI reads `startState.headline` instead of guessing from booleans.
    @Published public private(set) var startState = WorkoutStartState()

    // MARK: - Private

    private let healthStore = HKHealthStore()
    private var connectivitySession: WCSession?
    private var session: HKWorkoutSession?
    private var builder: HKLiveWorkoutBuilder?
    /// A running local session is not proof that HealthKit mirroring attached.
    /// Keeping this separate prevents the start request from selecting a mirror
    /// that does not exist yet.
    private var mirrorAttached = false

    private let queue = WorkoutCommandQueue()
    private let recoveryStore = WatchWorkoutRecoveryStore()
    private let catalogStore = WatchCatalogStore()
    private let diagnosticsStore = WatchStartDiagnosticsStore()
    private let log = Logger(subsystem: "cloud.avery.sara-ios.watch", category: "WorkoutManager")

    /// Every envelope leaves through here, so a mirroring failure degrades to
    /// WatchConnectivity instead of taking the start down with it (§5.3).
    private lazy var transport = WorkoutWireTransport(
        mirroredSession: { [weak self] in
            guard self?.mirrorAttached == true else { return nil }
            return self?.session
        }
    )

    /// The start currently in flight, kept so it can be replayed on its own
    /// `startAttemptId` rather than re-issued as a second workout (§5.2 step 2).
    private var pendingStart: WatchPendingStart?
    private var startResponseTimeoutTask: Task<Void, Never>?
    private var mirrorRetryTask: Task<Void, Never>?
    private var isFinalizingHealthKit = false

    /// Rest countdown state, so the rest screen and its haptics don't depend on
    /// a message arriving at exactly the right second.
    @Published public private(set) var restRemaining: Int = 0
    private var restTimer: Timer?
    private var restWarningFired = false

    /// Cross-device messages are throttled independently of the 1 Hz UI so a
    /// long session does not burn the radio (and the battery) on telemetry
    /// nobody reads (§7.6).
    private static let metricsSendInterval: TimeInterval = 5
    private var lastMetricsSentAt: Date = .distantPast
    private var elapsedTimer: Timer?

    public var pendingCommands: [WorkoutCommandQueue.Entry] { queue.pending }

    public override init() {
        super.init()
        // Last catalog the phone pushed, so the home screen has something to
        // show before (or without) a fresh sync.
        catalog = catalogStore.load()
        if WCSession.isSupported() {
            let connectivitySession = WCSession.default
            self.connectivitySession = connectivitySession
            connectivitySession.delegate = self
            connectivitySession.activate()
        }
    }

    // MARK: - Authorization

    /// HealthKit types the Watch needs. Share (write) is required to save the
    /// workout at all; read is what makes live HR available during it.
    private static let sharedTypes: Set<HKSampleType> = {
        var types: Set<HKSampleType> = [HKQuantityType.workoutType()]
        if let energy = HKQuantityType.quantityType(forIdentifier: .activeEnergyBurned) { types.insert(energy) }
        if let distance = HKQuantityType.quantityType(forIdentifier: .distanceWalkingRunning) { types.insert(distance) }
        return types
    }()

    private static let readTypes: Set<HKObjectType> = {
        var types: Set<HKObjectType> = [HKQuantityType.workoutType()]
        for id in [HKQuantityTypeIdentifier.heartRate, .activeEnergyBurned, .distanceWalkingRunning] {
            if let t = HKQuantityType.quantityType(forIdentifier: id) { types.insert(t) }
        }
        return types
    }()

    /// Outcome of the pre-start authorization check (§5.2 step 1).
    ///
    /// HealthKit's sharing status is useful context, but it is not a reliable
    /// preflight gate on watchOS. The system can report `.sharingDenied` while
    /// its Settings UI shows the workout permission enabled. In that state the
    /// real workout session is the authoritative operational check.
    public enum AuthorizationOutcome: Equatable {
        case authorized
        case requiresOperationalCheck
        /// The request itself failed (HealthKit unavailable, transient error).
        case failed(String)

        var canAttemptWorkout: Bool {
            self == .authorized || self == .requiresOperationalCheck
        }
    }

    @discardableResult
    public func requestAuthorization() async -> Bool {
        await ensureAuthorization().canAttemptWorkout
    }

    /// Request in the normal start path rather than only in diagnostics.
    /// The returned sharing status is recorded, while the session itself is the
    /// operational check because watchOS can disagree with its Settings UI.
    public func ensureAuthorization() async -> AuthorizationOutcome {
        guard HKHealthStore.isHealthDataAvailable() else {
            return .failed("Health data isn't available on this Watch")
        }
        let workoutType = HKQuantityType.workoutType()
        do {
            if healthStore.authorizationStatus(for: workoutType) != .sharingAuthorized {
                startState.healthKit = .authorizing
                try await healthStore.requestAuthorization(toShare: Self.sharedTypes, read: Self.readTypes)
            }
        } catch {
            recordDiagnostic(stage: "authorize", error: error)
            return .failed(error.localizedDescription)
        }

        let status = healthStore.authorizationStatus(for: workoutType)
        recordDiagnostic(stage: "authorize", authorization: WorkoutStateDescribe.authorization(status))
        switch status {
        case .sharingAuthorized:
            return .authorized
        case .sharingDenied:
            // Do not block here. HealthKit has returned this stale value on a
            // physical Watch while every Sara permission is visibly enabled.
            // Starting the HKWorkoutSession and builder gives us a real error
            // if access is genuinely unavailable.
            recordDiagnostic(stage: "authorize_denied_trying_session", authorization: "denied")
            return .requiresOperationalCheck
        default:
            return .requiresOperationalCheck
        }
    }

    // MARK: - Activity mapping (§7.3)

    /// Sara's template kinds → Apple's activity types.
    ///
    /// Explicit rather than "always traditional strength": logging a Tabata as
    /// strength training corrupts the ring credit and the HR-zone attribution
    /// for the whole day.
    public static func activityType(for templateKind: String?) -> HKWorkoutActivityType {
        switch (templateKind ?? "").lowercased() {
        case "strength", "lifting", "traditional_strength": return .traditionalStrengthTraining
        case "cardio", "run", "running": return .running
        case "row", "rowing": return .rowing
        case "bike", "cycle", "cycling": return .cycling
        case "walk", "walking", "ruck": return .walking
        case "tabata", "hiit", "interval", "intervals": return .highIntensityIntervalTraining
        default: return .functionalStrengthTraining
        }
    }

    // MARK: - Start / recover

    /// Begin the real Apple workout, then ask the phone to make it canonical.
    ///
    /// Six stages, each of which can fail on its own and say so (§5.2):
    ///
    ///   1. request and *verify* Health authorization;
    ///   2. mint and persist one `startAttemptId` before any side effect;
    ///   3. start the HKWorkoutSession and live builder;
    ///   4. submit `start_requested` over whatever transport is available;
    ///   5. attach mirroring concurrently, as an enhancement;
    ///   6. the phone answers, and only then is there a Sara session.
    ///
    /// Step 5 used to sit between 3 and 4 as a hard prerequisite. That is the
    /// specific defect that made this fail on 2026-07-27 with WatchConnectivity
    /// working perfectly: no mirror, therefore no `start_requested`, therefore
    /// no backend session and nothing on screen but "Couldn't start" (§2.2).
    public func startWorkout(templateId: String, templateKind: String?, templateName: String) async {
        guard session == nil else {
            log.notice("startWorkout ignored — a session is already running")
            return
        }
        isStarting = true
        lastError = nil
        startState = WorkoutStartState()

        // ── 1. Authorization ────────────────────────────────────────────
        switch await ensureAuthorization() {
        case .authorized, .requiresOperationalCheck:
            break
        case .failed(let detail):
            failStart(healthKit: .failed, message: detail, stage: "authorize_failed")
            return
        }

        let configuration = HKWorkoutConfiguration()
        configuration.activityType = Self.activityType(for: templateKind)
        configuration.locationType = .indoor

        // ── 2. Idempotency key, before anything observable happens ───────
        let startDate = Date()
        let attempt = WatchPendingStart(
            attemptId: UUID().uuidString,
            templateId: templateId,
            templateName: templateName,
            templateKind: templateKind,
            healthkitStartedAt: startDate,
            activityType: configuration.activityType.rawValue
        )
        setPendingStart(attempt)

        // ── 3. The Apple workout ────────────────────────────────────────
        startState.healthKit = .starting
        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: configuration)
            let builder = session.associatedWorkoutBuilder()
            builder.dataSource = HKLiveWorkoutDataSource(healthStore: healthStore, workoutConfiguration: configuration)
            session.delegate = self
            builder.delegate = self

            self.session = session
            self.builder = builder

            session.startActivity(with: startDate)
            try await builder.beginCollection(at: startDate)
            startState.healthKit = .running
            startElapsedTimer(from: startDate)
            persistRecovery(startedAt: startDate, activityType: configuration.activityType.rawValue)
            recordDiagnostic(stage: "healthkit_started", startAttemptId: attempt.attemptId)
        } catch {
            // The exact HealthKit failure, kept and shown. Retaining this was
            // the first implementation task in the plan, not a nicety (§2.2).
            let ns = error as NSError
            failStart(
                healthKit: .failed,
                message: "Apple Health: \(error.localizedDescription) (\(ns.domain) \(ns.code))",
                stage: "healthkit_start_failed",
                error: error
            )
            await teardown(discardingHealthKit: true)
            return
        }

        // ── 4. Ask Sara. Not gated on mirroring. ────────────────────────
        submitStartRequest(attempt)

        // ── 5. Mirroring, concurrently and retried ──────────────────────
        attachMirrorInBackground()
    }

    /// Start HealthKit after the paired iPhone asks watchOS to launch Sara.
    ///
    /// The Sara backend session already exists in this direction, so the Watch
    /// requests its projection instead of creating another session.
    public func startWorkoutFromPhone(configuration: HKWorkoutConfiguration) async {
        guard session == nil else {
            send(.watchRecoveredSession, payload: [:], sessionId: projection?.sessionId)
            attachMirrorInBackground()
            return
        }

        isStarting = true
        lastError = nil
        startState = WorkoutStartState()
        switch await ensureAuthorization() {
        case .authorized, .requiresOperationalCheck:
            break
        case .failed(let detail):
            failStart(
                healthKit: .failed,
                message: detail,
                stage: "phone_start_authorize_failed"
            )
            return
        }

        let startDate = Date()
        startState.healthKit = .starting
        startState.saraSession = .requesting
        do {
            try await startHealthKitSession(configuration: configuration, at: startDate)
            recordDiagnostic(stage: "phone_start_healthkit_started")
        } catch {
            let ns = error as NSError
            failStart(
                healthKit: .failed,
                message: "Apple Health: \(error.localizedDescription) (\(ns.domain) \(ns.code))",
                stage: "phone_start_healthkit_failed",
                error: error
            )
            await teardown(discardingHealthKit: true)
            return
        }

        send(.watchRecoveredSession, payload: [:], sessionId: nil)
        attachMirrorInBackground()
    }

    /// Send (or resend) the start request for an attempt already under way.
    ///
    /// Reuses `attemptId`, so a request that crossed a dying link is replayed
    /// by the backend into the same session rather than creating a second one.
    private func submitStartRequest(_ attempt: WatchPendingStart) {
        startResponseTimeoutTask?.cancel()
        startState.saraSession = .requesting
        let channel = send(.startRequested, payload: [
            "template_id": .string(attempt.templateId),
            "template_name": .string(attempt.templateName),
            "start_attempt_id": .string(attempt.attemptId),
            "healthkit_started_at": .string(ISO8601DateFormatter.sara.string(from: attempt.healthkitStartedAt)),
            "activity_type": .number(Double(attempt.activityType)),
        ], sessionId: nil, requiresDelivery: true)

        startState.phoneLink = transport.linkPhase
        recordDiagnostic(
            stage: "start_requested",
            transport: channel.rawValue,
            startAttemptId: attempt.attemptId
        )
        if channel == WorkoutWireTransport.Channel.none {
            // The Apple workout is real and still collecting. Say exactly that,
            // and keep the attempt so Retry resends the same id (§5.2).
            startState.saraSession = .failed
            startState.phoneLink = .offline
            startState.detail = "Your iPhone isn't reachable."
            lastError = "Apple workout running — couldn't reach Sara yet"
        }

        startResponseTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 12_000_000_000)
            guard let self, !Task.isCancelled,
                  self.pendingStart?.attemptId == attempt.attemptId,
                  self.startState.saraSession == .requesting
            else { return }
            self.isStarting = false
            self.startState.saraSession = .failed
            self.startState.detail = "Sara hasn't answered yet. Keep the iPhone unlocked and tap Retry."
            self.lastError = self.startState.detail
            self.recordDiagnostic(
                stage: "start_response_timeout",
                startAttemptId: attempt.attemptId,
                backendAccepted: false
            )
        }
    }

    /// Retry the stage that failed, without restarting the Apple workout.
    ///
    /// Restarting HealthKit would throw away the physiology collected so far
    /// and produce a second Apple workout for one session — the exact thing
    /// §12.1 measures.
    public func retryStart() {
        guard let attempt = pendingStart else { return }
        lastError = nil
        startState.detail = nil
        submitStartRequest(attempt)
        attachMirrorInBackground()
        Task { await flushQueue() }
    }

    /// Abandon a start that never reached Sara, cleanly.
    ///
    /// Leaves no orphan: the Apple workout is discarded rather than saved, so
    /// Health does not gain a workout Sara has no record of.
    public func discardOrphanStart() async {
        setPendingStart(nil)
        startState = WorkoutStartState()
        recordDiagnostic(stage: "orphan_discarded")
        await finalizeHealthKit(discard: true)
    }

    /// Attach the mirror out of band, retrying a few times.
    ///
    /// Mirroring is worth having — it is the lowest-latency channel and works
    /// with the phone app suspended — but it is an enhancement. Failure here
    /// downgrades the transport and is otherwise silent.
    private func attachMirrorInBackground() {
        mirrorRetryTask?.cancel()
        mirrorAttached = false
        // Inherits @MainActor from the enclosing type, so published state is
        // mutated on the main actor without hopping.
        mirrorRetryTask = Task { [weak self] in
            for attempt in 0..<3 {
                guard let self, !Task.isCancelled, let session = self.session else { return }
                do {
                    try await session.startMirroringToCompanionDevice()
                    self.mirrorAttached = true
                    self.startState.phoneLink = .mirroring
                    self.recordDiagnostic(stage: "mirror_attached", transport: "mirror")
                    if let pending = self.pendingStart,
                       self.startState.saraSession == .requesting
                        || self.startState.saraSession == .failed {
                        self.submitStartRequest(pending)
                    } else if self.pendingStart == nil, self.projection == nil,
                              self.startState.saraSession == .requesting {
                        self.send(.watchRecoveredSession, payload: [:], sessionId: nil)
                    }
                    return
                } catch {
                    self.mirrorAttached = false
                    self.startState.phoneLink = self.transport.linkPhase
                    self.recordDiagnostic(stage: "mirror_attach_failed", error: error)
                    // Back off rather than hammer: mirroring usually fails
                    // because the phone app has not been woken yet.
                    try? await Task.sleep(nanoseconds: UInt64(1 << attempt) * 2_000_000_000)
                }
            }
        }
    }

    /// Record a failed start and leave nothing running behind it.
    private func failStart(
        healthKit: HealthKitPhase, message: String, stage: String, error: Error? = nil
    ) {
        isStarting = false
        setPendingStart(nil)
        startState.healthKit = healthKit
        startState.saraSession = .failed
        startState.detail = message
        lastError = message
        recordDiagnostic(stage: stage, error: error)
        log.error("Start failed at \(stage, privacy: .public): \(message, privacy: .public)")
    }

    /// Append one bounded diagnostic entry (§5.4).
    private func recordDiagnostic(
        stage: String,
        error: Error? = nil,
        authorization: String? = nil,
        transport channel: String? = nil,
        startAttemptId: String? = nil,
        backendAccepted: Bool? = nil
    ) {
        diagnosticsStore.record(WorkoutStartDiagnostic(
            stage: stage,
            healthKitAuthorization: authorization ?? WorkoutStateDescribe.authorization(
                healthStore.authorizationStatus(for: HKQuantityType.workoutType())
            ),
            healthKitSessionState: session.map { WorkoutStateDescribe.session($0.state) } ?? "none",
            error: error,
            connectivityActivation: transport.activationDescription,
            connectivityReachable: transport.isReachable,
            mirrorState: startState.phoneLink.rawValue,
            transport: channel,
            startAttemptId: startAttemptId ?? pendingStart?.attemptId,
            backendAccepted: backendAccepted
        ))
    }

    /// Recent start diagnostics, newest first. Advanced screen only (§5.4).
    public var startDiagnostics: [WorkoutStartDiagnostic] { diagnosticsStore.load() }

    /// Plain-text dump of the diagnostic ring, for the developer export (§10 P0).
    public func exportDiagnostics() -> String { diagnosticsStore.export() }

    /// Re-attach after the Watch UI was killed while the workout kept running.
    public func recoverIfNeeded() async {
        guard session == nil else { return }
        do {
            guard let recovered = try await healthStore.recoverActiveWorkoutSession() else {
                // No live session — but there may still be unsent commands from
                // a workout the phone is holding.
                if let state = recoveryStore.load(), state.sessionId != nil {
                    projection = state.lastProjection
                    send(.watchRecoveredSession, payload: [:], sessionId: state.sessionId)
                }
                refreshPendingCount()
                return
            }
            attach(to: recovered)
            let state = recoveryStore.load()
            projection = state?.lastProjection
            startState.healthKit = .running
            startState.phoneLink = transport.linkPhase

            // A start that was never answered outlives the app. The Apple
            // workout has been collecting the whole time, so the attempt is
            // resubmitted with its ORIGINAL id — a fresh one would create a
            // second Sara session for one Apple workout (§5.2).
            if let pending = state?.pendingStart, state?.sessionId == nil {
                pendingStart = pending
                recordDiagnostic(stage: "start_resumed_after_relaunch",
                                 startAttemptId: pending.attemptId)
                submitStartRequest(pending)
                attachMirrorInBackground()
            } else {
                startState.saraSession = state?.sessionId == nil ? SaraSessionPhase.none : .active
            }

            send(.watchRecoveredSession, payload: [
                "last_accepted_version": state?.lastAcceptedVersion.map { .number(Double($0)) } ?? .null,
            ], sessionId: state?.sessionId)
            await flushQueue()
        } catch {
            log.error("Workout recovery failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func attach(to recovered: HKWorkoutSession) {
        mirrorAttached = false
        session = recovered
        recovered.delegate = self
        let builder = recovered.associatedWorkoutBuilder()
        builder.delegate = self
        self.builder = builder
        sessionState = recovered.state
        startElapsedTimer(from: recovered.startDate ?? Date())
        attachMirrorInBackground()
    }

    private func startHealthKitSession(
        configuration: HKWorkoutConfiguration,
        at startDate: Date
    ) async throws {
        let session = try HKWorkoutSession(
            healthStore: healthStore,
            configuration: configuration
        )
        let builder = session.associatedWorkoutBuilder()
        builder.dataSource = HKLiveWorkoutDataSource(
            healthStore: healthStore,
            workoutConfiguration: configuration
        )
        session.delegate = self
        builder.delegate = self

        self.session = session
        self.builder = builder
        mirrorAttached = false
        session.startActivity(with: startDate)
        try await builder.beginCollection(at: startDate)
        startState.healthKit = .running
        startElapsedTimer(from: startDate)
        persistRecovery(
            startedAt: startDate,
            activityType: configuration.activityType.rawValue
        )
    }

    // MARK: - Commands

    /// Queue a command, then try to send it. Queue-first is deliberate: if the
    /// send fails (or the app dies mid-send) the command survives and replays.
    public func issue(_ kind: WorkoutCommandKind, payload: [String: JSONValue] = [:]) {
        let command = WorkoutCommand(
            sessionId: projection?.sessionId,
            expectedVersion: projection?.version,
            originDevice: .watch,
            kind: kind,
            payload: payload
        )
        queue.enqueue(command)
        refreshPendingCount()
        transmit(command)
    }

    public func logSet(weight: Double, reps: Int, effort: String?) {
        var payload: [String: JSONValue] = [
            "weight": .number(weight),
            "reps": .number(Double(reps)),
        ]
        if let effort { payload["effort"] = .string(effort) }
        if let idx = projection?.cursor.exerciseIndex { payload["exercise_index"] = .number(Double(idx)) }
        issue(.logSet, payload: payload)
    }

    public func selectExercise(_ index: Int) {
        issue(.selectExercise, payload: ["exercise_index": .number(Double(index))])
    }

    public func skipExercise() { issue(.skipExercise) }
    public func stopRest() { issue(.restStop) }

    // MARK: - Flexible sets (§7.2)

    /// One more working set on the current exercise, this workout only.
    ///
    /// A direct tap is explicit approval for this workout and nothing else —
    /// the template, the program and next week are untouched (§4.2, §4.3).
    /// - Parameter afterLastSet: when true the set is added to the exercise of
    ///   the most recent working set rather than wherever the cursor now is.
    ///   The rest screen passes true, because finishing an exercise moves the
    ///   cursor on and "+ Set" there means one more of what was just done.
    public func addWorkingSet(exerciseIndex: Int? = nil, afterLastSet: Bool = false) {
        var payload: [String: JSONValue] = ["count": .number(1)]
        if afterLastSet, let anchor = activeDropParent {
            payload["after_set_id"] = .string(anchor.id)
        } else if let idx = exerciseIndex ?? projection?.cursor.exerciseIndex {
            payload["exercise_index"] = .number(Double(idx))
        }
        issue(.addSet, payload: payload)
    }

    /// Log one drop segment under the working set just performed.
    ///
    /// Drop segments do not consume a prescribed set and do not start a rest
    /// timer: a drop set is one continuous effort, and a countdown between
    /// segments would be telling David to do the opposite of the technique.
    public func logDropSegment(weight: Double, reps: Int, effort: String? = nil, parentSetId: String? = nil) {
        var payload: [String: JSONValue] = [
            "weight": .number(weight),
            "reps": .number(Double(reps)),
        ]
        if let effort { payload["effort"] = .string(effort) }
        // The parent set identifies the exercise. The cursor deliberately does
        // NOT: it has already moved on when the drop follows an exercise's
        // last set, and sending it would attach the segment to the next lift.
        if let parentSetId { payload["parent_set_id"] = .string(parentSetId) }
        issue(.logDropSegment, payload: payload)
    }

    /// Undo the most recent set. The wrist does exactly this and no more —
    /// arbitrary history editing belongs on the phone (§7.2, §13.3).
    public func undoLastSet(_ setId: String? = nil) {
        var payload: [String: JSONValue] = ["reason": .string("watch_undo")]
        if let setId { payload["set_id"] = .string(setId) }
        issue(.voidSet, payload: payload)
    }

    /// The most recent live set on the current exercise, if the projection
    /// carries one. Drives both the Undo confirmation and the drop-set seed.
    public var lastLoggedSet: PerformedSet? {
        guard let sets = projection?.performedSets else { return nil }
        return sets.filter { !$0.voided }.last
    }

    /// The working set a new drop segment would attach to.
    public var activeDropParent: PerformedSet? {
        guard let sets = projection?.performedSets else { return nil }
        return sets.last(where: { !$0.voided && $0.countsTowardTarget })
    }

    /// Ask the phone for the uncompacted projection.
    ///
    /// Per-set messages drop the exercise array to keep them small; the jump
    /// screen is the one place that needs it, so it asks rather than every set
    /// paying for it.
    public func requestFullProjection() {
        send(.projectionRequested, payload: [:], sessionId: projection?.sessionId)
    }

    public func resolve(proposal: WorkoutProposal, approve: Bool) {
        issue(approve ? .approveProposal : .rejectProposal,
              payload: ["proposal_id": .string(proposal.proposalId)])
    }

    /// Finish immediately on the wrist, even if the phone or backend is away.
    /// The durable command can reconcile later; keeping HealthKit and the
    /// active screen alive while waiting for an acknowledgement cannot.
    public func finishWorkout() async {
        let endingProjection = projection
        let sessionId = endingProjection?.sessionId
        issue(.complete)
        completion = localSummary(from: endingProjection)
        projection = nil
        startState.saraSession = .none
        await finalizeHealthKit(discard: false, sessionId: sessionId)
    }

    public func abandonWorkout() async {
        let sessionId = projection?.sessionId
        issue(.abandon)
        // The tap is explicit. Clear the active screen before the slower
        // HealthKit finalization and durable command delivery finish.
        projection = nil
        startState.saraSession = .none
        await finalizeHealthKit(
            discard: true,
            preserveTerminalCommand: true,
            sessionId: sessionId
        )
    }

    private func transmit(_ command: WorkoutCommand) {
        do {
            let payload = try WorkoutWire.encodePayload(command)
            send(.commandRequested, payload: payload, sessionId: command.sessionId)
        } catch {
            queue.recordFailure(commandId: command.commandId, error: error.localizedDescription)
            refreshPendingCount()
        }
    }

    /// Replay everything unacknowledged, in order, with the original ids.
    public func flushQueue() async {
        for command in queue.replayBatch() {
            transmit(command)
        }
        refreshPendingCount()
    }

    private func refreshPendingCount() {
        pendingCommandCount = queue.pendingCount
    }

    // MARK: - Transport

    /// Send one envelope over the best channel currently available (§5.3).
    ///
    /// The old version refused to send anything without a mirrored session,
    /// which meant a mirroring failure silently swallowed Start, every command
    /// and every HealthKit lifecycle message. Now the transport decides, and
    /// mutations fall through to the durable WatchConnectivity queue.
    @discardableResult
    private func send(
        _ kind: WireMessageKind,
        payload: [String: JSONValue],
        sessionId: String?,
        requiresDelivery: Bool = true
    ) -> WorkoutWireTransport.Channel {
        let envelope = WireEnvelope(kind: kind, sessionId: sessionId, payload: payload)
        let channel = transport.send(envelope, requiresDelivery: requiresDelivery)
        // Spelled out rather than `.none`: `Channel.none` and `Optional.none`
        // both answer to a leading dot, and this must mean the former.
        if channel == WorkoutWireTransport.Channel.none {
            log.notice("No channel for \(kind.rawValue, privacy: .public)")
        }
        isReachable = channel != WorkoutWireTransport.Channel.none
        startState.phoneLink = transport.linkPhase
        return channel
    }

    private func handle(_ envelope: WireEnvelope) {
        guard envelope.isSupportedSchema else {
            log.error("Ignoring schema \(envelope.schemaVersion) message — this build speaks \(saraWorkoutSchemaVersion)")
            lastError = "Update Sara on your Watch"
            return
        }

        switch envelope.kind {
        case .startAccepted, .projectionUpdated, .commandAccepted:
            if let commandId = envelope.payload["command_id"]?.stringValue {
                queue.acknowledge(commandId: commandId)
                refreshPendingCount()
            }
            // A PR earns its own haptic — it is the one moment mid-workout
            // worth interrupting for (§8.4).
            if let pr = envelope.payload["pr"]?.objectValue, !pr.isEmpty {
                WatchHaptics.personalRecord()
            }
            // Only `complete` carries one; it is what swaps the set screen for
            // the summary.
            if let summary = envelope.payload["summary"], summary != .null {
                completion = try? decode(WatchWorkoutSummary.self, from: summary)
            }
            applyProjection(from: envelope)
            isStarting = false
            if envelope.kind == .startAccepted || projection != nil {
                // Sara has a session for this attempt. The start is finished,
                // so nothing is left to retry or discard.
                startState.saraSession = .active
                startState.detail = nil
                if pendingStart != nil {
                    recordDiagnostic(stage: "start_accepted", backendAccepted: true)
                    setPendingStart(nil)
                }
                lastError = nil
            }

        case .catalogUpdated:
            do {
                let data = try WorkoutWire.encoder.encode(JSONValue.object(envelope.payload))
                let incoming = try WorkoutWire.decoder.decode(WatchCatalog.self, from: data)
                catalog = incoming
                catalogStore.save(incoming)
                if let active = incoming.activeProjection {
                    projection = active
                    persistRecovery(projection: active)
                    syncRestTimer(with: active.rest)
                    isStarting = false
                    startState.saraSession = .active
                    startState.detail = nil
                    if pendingStart != nil {
                        recordDiagnostic(stage: "catalog_recovered_start", backendAccepted: true)
                        setPendingStart(nil)
                    }
                    lastError = nil
                }
            } catch {
                log.error("Catalog decode failed: \(error.localizedDescription, privacy: .public)")
            }

        case .commandRejected:
            // A rejected command will never apply — retrying forever would
            // just keep the pending badge lit. Drop it and reconcile visibly.
            if let commandId = envelope.payload["command_id"]?.stringValue {
                queue.discard(commandId: commandId,
                              reason: envelope.payload["code"]?.stringValue ?? "rejected")
                refreshPendingCount()
            }
            lastError = envelope.payload["message"]?.stringValue ?? "That didn't apply"
            applyProjection(from: envelope)

        case .startConflict:
            isStarting = false
            startState.saraSession = .conflict
            startState.detail = envelope.payload["message"]?.stringValue
            lastError = envelope.payload["message"]?.stringValue ?? "Another workout is already running"
            recordDiagnostic(stage: "start_conflict", backendAccepted: false)
            applyProjection(from: envelope)
            // Note: the orphan HealthKit session is NOT torn down here.
            // §5.2 wants David offered Resume Existing or Discard — silently
            // ending the Apple workout takes that choice away, and silently
            // keeping it running leaves a workout with no owner.

        case .coachingEvent:
            if let event = try? WorkoutWire.decodePayload(WorkoutCoachingEvent.self, from: envelope),
               !event.isExpired() {
                coaching = event
            }

        case .proposalCreated, .proposalResolved:
            // Distinct from every other haptic: an approval request is the only
            // buzz that means "Sara is waiting on you" (§8.4).
            if envelope.kind == .proposalCreated { WatchHaptics.approvalRequested() }
            applyProjection(from: envelope)

        case .workoutEnded:
            // This is the iPhone's explicit terminal instruction. Ending the
            // mirrored session on the phone does not end the primary Watch
            // HealthKit session, so this message is durable and authoritative.
            let discarded = envelope.payload["discarded"] == .bool(true)
            let endingProjection = projection
            let sessionId = envelope.sessionId ?? endingProjection?.sessionId
            if discarded {
                completion = nil
            } else if let summary = envelope.payload["summary"], summary != .null {
                completion = try? decode(WatchWorkoutSummary.self, from: summary)
            } else {
                completion = localSummary(from: endingProjection)
            }
            if let sessionId {
                queue.clear(sessionId: sessionId)
                refreshPendingCount()
            }
            projection = nil
            startState.saraSession = .none
            Task {
                await finalizeHealthKit(
                    discard: discarded,
                    sessionId: sessionId
                )
            }

        case .finishConfirmed:
            // Deliberately does NOT decode the whole payload as a summary:
            // every field of WatchWorkoutSummary is optional, so decoding an
            // envelope that carries something else succeeds and produces an
            // all-nil summary — which is non-nil, and would strand the Watch
            // on a blank summary screen. Only an explicit `summary` key counts.
            if let summary = envelope.payload["summary"], summary != .null {
                completion = try? decode(WatchWorkoutSummary.self, from: summary)
            }
            // HealthKit has already been finalized when this acknowledgement
            // arrives; it confirms the UUID was linked and may enrich summary.

        case .unknown(let raw):
            // A newer phone build. Not an error worth interrupting a set for.
            log.notice("Ignoring unknown message kind \(raw, privacy: .public)")

        default:
            applyProjection(from: envelope)
        }
    }

    /// Any WatchConnectivity payload — message, user info, or application
    /// context — unwrapped through the one rule in `WorkoutWireTransport`.
    private func handleConnectivityPayload(_ payload: [String: Any]) {
        guard let envelope = WorkoutWireTransport.envelope(from: payload) else {
            log.error("Undecodable WatchConnectivity payload")
            return
        }
        isReachable = true
        handle(envelope)
    }

    /// Re-encode one `JSONValue` and decode it as a concrete type.
    ///
    /// The payload is heterogeneous by design, so this is the seam between the
    /// open wire format and the typed models.
    private func decode<T: Decodable>(_ type: T.Type, from value: JSONValue) throws -> T {
        try WorkoutWire.decoder.decode(T.self, from: WorkoutWire.encoder.encode(value))
    }

    private func applyProjection(from envelope: WireEnvelope) {
        guard let raw = envelope.payload["projection"], case .object = raw else { return }
        do {
            let data = try WorkoutWire.encoder.encode(raw)
            let incoming = try WorkoutWire.decoder.decode(WorkoutProjection.self, from: data)
            // Out-of-order delivery is normal on a mirrored link; an older
            // version arriving late must not roll the UI backwards.
            if let current = projection, incoming.version < current.version {
                log.notice("Dropping stale projection v\(incoming.version) (have v\(current.version))")
                return
            }
            projection = incoming
            if incoming.status == "active" {
                persistRecovery(projection: incoming)
            } else {
                // A late completion acknowledgement must not recreate the
                // recovery record after HealthKit has already been torn down.
                recoveryStore.clear()
            }
            syncRestTimer(with: incoming.rest)
        } catch {
            log.error("Projection decode failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    // MARK: - Rest countdown (§8.4)

    /// Drive the countdown locally from the backend's start time.
    ///
    /// The projection says *when* rest started and how long it runs; ticking it
    /// here rather than waiting for messages means the number on the wrist is
    /// right even when the phone is in a bag across the gym.
    private func syncRestTimer(with rest: WorkoutRestState) {
        guard rest.active,
              let startedAt = rest.startedAt.flatMap(ISO8601DateFormatter.saraDate(from:)),
              let duration = rest.durationSeconds else {
            stopRestTimer()
            return
        }
        let remaining = Int(Double(duration) - Date().timeIntervalSince(startedAt))
        guard remaining > 0 else {
            stopRestTimer()
            return
        }
        restRemaining = remaining
        restWarningFired = remaining <= 10
        guard restTimer == nil else { return }
        restTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tickRest(startedAt: startedAt, duration: duration) }
        }
    }

    private func tickRest(startedAt: Date, duration: Int) {
        let remaining = Int(Double(duration) - Date().timeIntervalSince(startedAt))
        restRemaining = max(0, remaining)

        let warnAt10 = catalog?.policy?.adaptiveRestEnabled ?? true
        if warnAt10, !restWarningFired, remaining <= 10, remaining > 0 {
            restWarningFired = true
            WatchHaptics.restWarning()
        }
        if remaining <= 0 {
            WatchHaptics.restComplete()
            stopRestTimer()
        }
    }

    private func stopRestTimer() {
        restTimer?.invalidate()
        restTimer = nil
        restRemaining = 0
        restWarningFired = false
    }

    public func dismissCompletion() {
        completion = nil
    }

    /// Take over the workout the backend says is already running (§5.2).
    ///
    /// The Apple session started for the refused attempt is discarded first:
    /// the existing Sara workout already has (or will get) its own HealthKit
    /// workout, and saving this one too would break "one Sara session, one
    /// Apple Health workout" (§12.1).
    public func resumeExistingWorkout() async {
        setPendingStart(nil)
        recordDiagnostic(stage: "start_conflict_resume_existing")
        await finalizeHealthKit(discard: true)
        startState = WorkoutStartState()
        startState.saraSession = projection == nil ? SaraSessionPhase.none : .active
        send(.projectionRequested, payload: [:], sessionId: projection?.sessionId)
    }

    // MARK: - HealthKit lifecycle

    private func finalizeHealthKit(
        discard: Bool,
        preserveTerminalCommand: Bool = false,
        sessionId explicitSessionId: String? = nil
    ) async {
        // State-bearing phone replies are deliberately fanned out over the
        // mirror and WatchConnectivity. The same terminal message can arrive
        // twice, but HealthKit collection may only be finalized once.
        guard !isFinalizingHealthKit else { return }
        isFinalizingHealthKit = true
        defer { isFinalizingHealthKit = false }

        let sessionId = explicitSessionId ?? projection?.sessionId
        guard let session else {
            await teardown(
                discardingHealthKit: discard,
                preserveTerminalCommand: preserveTerminalCommand,
                sessionId: sessionId
            )
            return
        }
        let endDate = Date()
        session.stopActivity(with: endDate)
        session.end()
        stopElapsedTimer()

        guard let builder else {
            await teardown(
                discardingHealthKit: discard,
                preserveTerminalCommand: preserveTerminalCommand,
                sessionId: sessionId
            )
            return
        }

        if discard {
            try? await builder.endCollection(at: endDate)
            builder.discardWorkout()
            send(.healthkitFinished, payload: ["discarded": .bool(true)], sessionId: sessionId)
            await teardown(
                discardingHealthKit: true,
                preserveTerminalCommand: preserveTerminalCommand,
                sessionId: sessionId
            )
            return
        }

        do {
            try await builder.endCollection(at: endDate)
            // Stamp the Sara session onto the workout's metadata so ingestion
            // can bind the two without guessing (§6.4).
            if let sessionId {
                try? await builder.addMetadata(["com.avery.sara.session_id": sessionId])
            }
            let workout = try await builder.finishWorkout()
            send(.healthkitFinished, payload: [
                "workout_uuid": .string(workout?.uuid.uuidString ?? ""),
                "ended_at": .string(ISO8601DateFormatter.sara.string(from: endDate)),
                "total_energy_kcal": .number(
                    workout?.statistics(for: HKQuantityType(.activeEnergyBurned))?
                        .sumQuantity()?.doubleValue(for: .kilocalorie()) ?? 0
                ),
            ], sessionId: sessionId)
        } catch {
            // The strength record is already safe on the backend; losing the
            // HealthKit finalize costs HR/calories, not the workout.
            lastError = "Couldn't save Health data"
            log.error("finishWorkout failed: \(error.localizedDescription, privacy: .public)")
        }
        await teardown(discardingHealthKit: false, sessionId: sessionId)
    }

    private func teardown(
        discardingHealthKit: Bool,
        preserveTerminalCommand: Bool = false,
        sessionId explicitSessionId: String? = nil
    ) async {
        mirrorRetryTask?.cancel()
        mirrorRetryTask = nil
        mirrorAttached = false
        session = nil
        builder = nil
        sessionState = .ended
        // A failed start is torn down too, and overwriting `.failed` with
        // `.ended` here would erase the one piece of state the error screen
        // needs — leaving David back at a bare "Couldn't start".
        if startState.healthKit != .failed {
            startState.healthKit = .ended
        }
        heartRate = 0
        activeEnergy = 0
        stopElapsedTimer()
        stopRestTimer()
        if discardingHealthKit, let sessionId = explicitSessionId ?? projection?.sessionId {
            queue.clear(
                sessionId: sessionId,
                preservingTerminalCommands: preserveTerminalCommand
            )
        }
        recoveryStore.clear()
        refreshPendingCount()
    }

    /// A local summary makes Finish visibly terminal without waiting for the
    /// phone. A later command acknowledgement replaces it with backend totals.
    private func localSummary(from projection: WorkoutProjection?) -> WatchWorkoutSummary {
        WatchWorkoutSummary(
            workoutName: projection?.template.name,
            durationMinutes: max(0, Int(elapsed / 60)),
            totalSets: projection?.progress.completedSets,
            totalVolume: projection?.progress.totalVolume,
            heartRate: nil,
            pendingProposalCount: projection?.pendingProposal == nil ? 0 : 1
        )
    }

    // MARK: - Elapsed / metrics

    private func startElapsedTimer(from start: Date) {
        stopElapsedTimer()
        elapsedTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.elapsed = Date().timeIntervalSince(start) }
        }
    }

    private func stopElapsedTimer() {
        elapsedTimer?.invalidate()
        elapsedTimer = nil
    }

    private func maybeSendMetrics() {
        let now = Date()
        guard now.timeIntervalSince(lastMetricsSentAt) >= Self.metricsSendInterval else { return }
        lastMetricsSentAt = now
        let metrics = WorkoutLiveMetrics(
            heartRate: heartRate > 0 ? heartRate : nil,
            activeEnergyKcal: activeEnergy > 0 ? activeEnergy : nil,
            elapsedSeconds: elapsed
        )
        guard let payload = try? WorkoutWire.encodePayload(metrics) else { return }
        // Telemetry: worthless late, so it never enters the durable queue —
        // otherwise a long offline stretch would fill it with stale heart rates
        // and delay the sets behind them.
        send(.liveMetrics, payload: payload, sessionId: projection?.sessionId, requiresDelivery: false)
    }

    // MARK: - Recovery persistence

    private func persistRecovery(
        projection: WorkoutProjection? = nil,
        startedAt: Date? = nil,
        activityType: UInt? = nil
    ) {
        var state = recoveryStore.load() ?? WatchWorkoutRecoveryState()
        if let projection {
            state.sessionId = projection.sessionId
            state.lastAcceptedVersion = projection.version
            state.lastProjection = projection
        }
        if let startedAt { state.healthkitStartedAt = startedAt }
        if let activityType { state.healthkitActivityType = activityType }
        recoveryStore.save(state)
    }

    /// Set (or clear) the unconfirmed start, in memory and on disk together.
    ///
    /// One function rather than two assignments because the two must never
    /// disagree: an attempt that survives on disk but not in memory would be
    /// retried with a fresh id after a relaunch, which is exactly how you get
    /// two Sara sessions for one Apple workout.
    private func setPendingStart(_ value: WatchPendingStart?) {
        if value == nil {
            startResponseTimeoutTask?.cancel()
            startResponseTimeoutTask = nil
        }
        pendingStart = value
        var state = recoveryStore.load() ?? WatchWorkoutRecoveryState()
        state.pendingStart = value
        recoveryStore.save(state)
    }
}

// MARK: - WCSessionDelegate

extension WorkoutManager: WCSessionDelegate {
    nonisolated public func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        Task { @MainActor in
            if let error {
                self.log.error("WatchConnectivity activation failed: \(error.localizedDescription, privacy: .public)")
                return
            }
            self.isReachable = session.isReachable
            self.startState.phoneLink = self.transport.linkPhase
            if !session.receivedApplicationContext.isEmpty {
                self.handleConnectivityPayload(session.receivedApplicationContext)
            }
            if let pending = self.pendingStart,
               self.startState.saraSession == .failed || self.startState.saraSession == .requesting {
                self.submitStartRequest(pending)
            }
            if self.pendingStart == nil, self.projection == nil,
               self.session != nil, self.startState.saraSession == .requesting {
                self.send(.watchRecoveredSession, payload: [:], sessionId: nil)
            }
            // Activation can complete after a start was queued. Anything the
            // durable queue is holding goes now rather than on the next tap.
            await self.flushQueue()
        }
    }

    nonisolated public func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        Task { @MainActor in
            self.handleConnectivityPayload(applicationContext)
        }
    }

    /// Interactive reply from the phone (§5.3 channel 2).
    nonisolated public func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor in
            self.handleConnectivityPayload(message)
        }
    }

    /// Durable reply — delivered whenever the phone came back (§5.3 channel 3).
    nonisolated public func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        Task { @MainActor in
            self.handleConnectivityPayload(userInfo)
        }
    }

    nonisolated public func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in
            self.isReachable = session.isReachable
            self.startState.phoneLink = self.transport.linkPhase
            guard session.isReachable else { return }
            // The start is not a queued set command. It has its own durable
            // idempotency key and must be replayed when the phone returns.
            if let pending = self.pendingStart,
               self.startState.saraSession == .requesting
                || self.startState.saraSession == .failed {
                self.submitStartRequest(pending)
            }
            await self.flushQueue()
        }
    }
}

// MARK: - HKWorkoutSessionDelegate

extension WorkoutManager: HKWorkoutSessionDelegate {
    nonisolated public func workoutSession(
        _ workoutSession: HKWorkoutSession,
        didChangeTo toState: HKWorkoutSessionState,
        from fromState: HKWorkoutSessionState,
        date: Date
    ) {
        Task { @MainActor in
            self.sessionState = toState
            switch toState {
            case .running:
                self.send(.healthkitStarted, payload: [
                    "started_at": .string(ISO8601DateFormatter.sara.string(from: date)),
                ], sessionId: self.projection?.sessionId)
            case .paused:
                self.send(.healthkitPaused, payload: [:], sessionId: self.projection?.sessionId)
            default:
                break
            }
        }
    }

    nonisolated public func workoutSession(
        _ workoutSession: HKWorkoutSession,
        didFailWithError error: Error
    ) {
        Task { @MainActor in
            self.lastError = "Workout tracking stopped"
            self.log.error("Session failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    nonisolated public func workoutSession(
        _ workoutSession: HKWorkoutSession,
        didReceiveDataFromRemoteWorkoutSession data: [Data]
    ) {
        Task { @MainActor in
            for blob in data {
                do {
                    self.handle(try WorkoutWire.decode(blob))
                } catch {
                    // One malformed message must not take the workout down.
                    self.log.error("Undecodable remote message: \(error.localizedDescription, privacy: .public)")
                }
            }
        }
    }
}

// MARK: - HKLiveWorkoutBuilderDelegate

extension WorkoutManager: HKLiveWorkoutBuilderDelegate {
    nonisolated public func workoutBuilderDidCollectEvent(_ workoutBuilder: HKLiveWorkoutBuilder) {}

    nonisolated public func workoutBuilder(
        _ workoutBuilder: HKLiveWorkoutBuilder,
        didCollectDataOf collectedTypes: Set<HKSampleType>
    ) {
        Task { @MainActor in
            for type in collectedTypes {
                guard let quantityType = type as? HKQuantityType,
                      let statistics = workoutBuilder.statistics(for: quantityType) else { continue }

                switch quantityType {
                case HKQuantityType(.heartRate):
                    let unit = HKUnit.count().unitDivided(by: .minute())
                    self.heartRate = statistics.mostRecentQuantity()?.doubleValue(for: unit) ?? self.heartRate
                case HKQuantityType(.activeEnergyBurned):
                    self.activeEnergy = statistics.sumQuantity()?.doubleValue(for: .kilocalorie()) ?? self.activeEnergy
                default:
                    break
                }
            }
            self.maybeSendMetrics()
        }
    }
}
