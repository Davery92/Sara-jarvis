import Foundation
import HealthKit
import os
import SwiftUI

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
@available(watchOS 10.0, *)
@MainActor
public final class WorkoutManager: NSObject, ObservableObject {

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

    // MARK: - Private

    private let healthStore = HKHealthStore()
    private var session: HKWorkoutSession?
    private var builder: HKLiveWorkoutBuilder?

    private let queue = WorkoutCommandQueue()
    private let recoveryStore = WatchWorkoutRecoveryStore()
    private let catalogStore = WatchCatalogStore()
    private let log = Logger(subsystem: "cloud.avery.sara-ios.watch", category: "WorkoutManager")

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

    public func requestAuthorization() async -> Bool {
        guard HKHealthStore.isHealthDataAvailable() else { return false }
        do {
            try await healthStore.requestAuthorization(toShare: Self.sharedTypes, read: Self.readTypes)
            return true
        } catch {
            lastError = "Health access unavailable"
            log.error("HealthKit auth failed: \(error.localizedDescription, privacy: .public)")
            return false
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
    /// Order matters. HealthKit starts FIRST so no physiology is lost while the
    /// backend round-trip happens; if the backend then refuses (another workout
    /// is active), `handleStartConflict` ends this local session rather than
    /// leaving a headless Apple workout running.
    public func startWorkout(templateId: String, templateKind: String?, templateName: String) async {
        guard session == nil else {
            log.notice("startWorkout ignored — a session is already running")
            return
        }
        isStarting = true
        lastError = nil

        let configuration = HKWorkoutConfiguration()
        configuration.activityType = Self.activityType(for: templateKind)
        configuration.locationType = .indoor

        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: configuration)
            let builder = session.associatedWorkoutBuilder()
            builder.dataSource = HKLiveWorkoutDataSource(healthStore: healthStore, workoutConfiguration: configuration)
            session.delegate = self
            builder.delegate = self

            self.session = session
            self.builder = builder

            let startDate = Date()
            session.startActivity(with: startDate)
            try await builder.beginCollection(at: startDate)

            // Mirror to the phone so it can drive the backend and play coaching
            // audio even while its UI is not open (§7.4).
            try await session.startMirroringToCompanionDevice()

            startElapsedTimer(from: startDate)
            persistRecovery(startedAt: startDate, activityType: configuration.activityType.rawValue)

            send(.startRequested, payload: [
                "template_id": .string(templateId),
                "template_name": .string(templateName),
                "start_attempt_id": .string(UUID().uuidString),
                "healthkit_started_at": .string(ISO8601DateFormatter.sara.string(from: startDate)),
                "activity_type": .number(Double(configuration.activityType.rawValue)),
            ], sessionId: nil)
        } catch {
            isStarting = false
            lastError = "Couldn't start the workout"
            log.error("Failed to start workout: \(error.localizedDescription, privacy: .public)")
            await teardown(discardingHealthKit: true)
        }
    }

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
            send(.watchRecoveredSession, payload: [
                "last_accepted_version": state?.lastAcceptedVersion.map { .number(Double($0)) } ?? .null,
            ], sessionId: state?.sessionId)
            await flushQueue()
        } catch {
            log.error("Workout recovery failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func attach(to recovered: HKWorkoutSession) {
        session = recovered
        recovered.delegate = self
        let builder = recovered.associatedWorkoutBuilder()
        builder.delegate = self
        self.builder = builder
        sessionState = recovered.state
        startElapsedTimer(from: recovered.startDate ?? Date())
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

    /// Finish: end the Sara workout first, then finalize HealthKit and hand the
    /// phone the exact workout UUID so the two records bind (§4.5).
    public func finishWorkout() async {
        issue(.complete)
        await finalizeHealthKit(discard: false)
    }

    public func abandonWorkout() async {
        issue(.abandon)
        await finalizeHealthKit(discard: true)
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

    private func send(_ kind: WireMessageKind, payload: [String: JSONValue], sessionId: String?) {
        guard let session else {
            log.notice("Dropping \(kind.rawValue, privacy: .public) — no mirrored session yet")
            return
        }
        let envelope = WireEnvelope(kind: kind, sessionId: sessionId, payload: payload)
        do {
            let data = try WorkoutWire.encode(envelope)
            session.sendToRemoteWorkoutSession(data: data) { [weak self] _, error in
                guard let error else { return }
                Task { @MainActor in
                    self?.isReachable = false
                    self?.log.error("Send failed: \(error.localizedDescription, privacy: .public)")
                }
            }
            isReachable = true
        } catch {
            log.error("Encode failed for \(kind.rawValue, privacy: .public): \(error.localizedDescription, privacy: .public)")
        }
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
            applyProjection(from: envelope)
            isStarting = false

        case .catalogUpdated:
            do {
                let data = try WorkoutWire.encoder.encode(JSONValue.object(envelope.payload))
                let incoming = try WorkoutWire.decoder.decode(WatchCatalog.self, from: data)
                catalog = incoming
                catalogStore.save(incoming)
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
            lastError = envelope.payload["message"]?.stringValue ?? "Another workout is already running"
            applyProjection(from: envelope)
            Task { await handleStartConflict() }

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

        case .finishConfirmed:
            if let summary = try? WorkoutWire.decodePayload(WatchWorkoutSummary.self, from: envelope) {
                completion = summary
            }
            Task { await finalizeHealthKit(discard: false) }

        case .unknown(let raw):
            // A newer phone build. Not an error worth interrupting a set for.
            log.notice("Ignoring unknown message kind \(raw, privacy: .public)")

        default:
            applyProjection(from: envelope)
        }
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
            persistRecovery(projection: incoming)
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

    /// The backend refused our Start because another workout is active. The
    /// local HealthKit session we optimistically began has no Sara workout to
    /// belong to, so discard it rather than leave an orphan running.
    private func handleStartConflict() async {
        await finalizeHealthKit(discard: true)
    }

    // MARK: - HealthKit lifecycle

    private func finalizeHealthKit(discard: Bool) async {
        guard let session, let builder else { return }
        let endDate = Date()
        session.stopActivity(with: endDate)
        session.end()
        stopElapsedTimer()

        if discard {
            try? await builder.endCollection(at: endDate)
            builder.discardWorkout()
            send(.healthkitFinished, payload: ["discarded": .bool(true)], sessionId: projection?.sessionId)
            await teardown(discardingHealthKit: true)
            return
        }

        do {
            try await builder.endCollection(at: endDate)
            // Stamp the Sara session onto the workout's metadata so ingestion
            // can bind the two without guessing (§6.4).
            if let sessionId = projection?.sessionId {
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
            ], sessionId: projection?.sessionId)
        } catch {
            // The strength record is already safe on the backend; losing the
            // HealthKit finalize costs HR/calories, not the workout.
            lastError = "Couldn't save Health data"
            log.error("finishWorkout failed: \(error.localizedDescription, privacy: .public)")
        }
        await teardown(discardingHealthKit: false)
    }

    private func teardown(discardingHealthKit: Bool) async {
        session = nil
        builder = nil
        sessionState = .ended
        heartRate = 0
        activeEnergy = 0
        stopElapsedTimer()
        stopRestTimer()
        if discardingHealthKit, let sessionId = projection?.sessionId {
            queue.clear(sessionId: sessionId)
        }
        recoveryStore.clear()
        refreshPendingCount()
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
        send(.liveMetrics, payload: payload, sessionId: projection?.sessionId)
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
}

// MARK: - HKWorkoutSessionDelegate

@available(watchOS 10.0, *)
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

@available(watchOS 10.0, *)
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
