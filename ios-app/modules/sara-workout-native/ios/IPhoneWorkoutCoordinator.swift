import Foundation
import HealthKit
import os

/// iPhone side of Apple's multidevice workout model (plan §7.2, §7.4).
///
/// The Watch owns the primary `HKWorkoutSession`; this owns the *mirror*. Three
/// jobs follow from that:
///
///  1. Launch or wake the Watch app when a workout starts on the phone, using
///     `startWatchApp(with:)`, so David never has to reach for his wrist.
///  2. Register `workoutSessionMirroringStartHandler` early enough that a
///     Watch-originated workout is noticed even when the phone's UI is not
///     running. This is why the lifecycle lives in native code and not in a
///     React hook — the JS layer simply is not alive at that moment.
///  3. Relay versioned messages both ways, buffering the ones that arrive
///     before JavaScript has attached a listener.
///
/// It never mutates workout state. Commands go to the backend; this moves
/// bytes and HealthKit lifecycle.
@available(iOS 17.0, *)
final class IPhoneWorkoutCoordinator: NSObject {

    /// Emitted to JS. Names match the `addListener` keys in `index.ts`.
    enum Event: String {
        case workoutMessage = "workoutMessage"
        case liveMetrics = "liveMetrics"
        case mirrorStateChanged = "mirrorStateChanged"
    }

    typealias Emitter = (Event, [String: Any]) -> Void

    private let healthStore = HKHealthStore()
    private let log = Logger(subsystem: "cloud.avery.sara-ios", category: "WorkoutMirror")
    private let stateQueue = DispatchQueue(label: "cloud.avery.sara.workout.mirror")

    private var mirroredSession: HKWorkoutSession?
    private var emit: Emitter?

    /// Messages that arrived before JS was listening.
    ///
    /// Without this, a Watch-started workout that wakes the app races the React
    /// tree: the `start_requested` lands, nothing is subscribed, and the set
    /// David is about to log has no session. Bounded so a long background
    /// stretch cannot grow without limit.
    private var pendingMessages: [[String: Any]] = []
    private static let maxPendingMessages = 64

    private(set) var isMirroring = false {
        didSet {
            guard isMirroring != oldValue else { return }
            dispatch(.mirrorStateChanged, ["mirroring": isMirroring])
        }
    }

    // MARK: - Lifecycle

    /// Install the mirror handler. Called once, as early as the app can manage.
    func activate(emitter: @escaping Emitter) {
        self.emit = emitter
        flushPending()

        healthStore.workoutSessionMirroringStartHandler = { [weak self] session in
            guard let self else { return }
            self.log.notice("Received mirrored workout session from Watch")
            self.attach(session)
        }
    }

    private func attach(_ session: HKWorkoutSession) {
        stateQueue.sync {
            self.mirroredSession = session
        }
        session.delegate = self
        isMirroring = true
        dispatch(.mirrorStateChanged, [
            "mirroring": true,
            "state": Self.describe(session.state),
            "activityType": session.workoutConfiguration.activityType.rawValue,
        ])
    }

    // MARK: - Starting from the phone (§4.3)

    /// Launch/wake the Watch app and have it begin the primary workout.
    ///
    /// Only a *request*: the Watch is the one that actually creates the
    /// HKWorkoutSession, and the mirror arrives asynchronously through the
    /// handler above. Callers treat this as "asked the Watch", never as
    /// "the Watch is tracking".
    func startWatchApp(activityType: UInt, locationType: Int, completion: @escaping (Result<Void, Error>) -> Void) {
        guard HKHealthStore.isHealthDataAvailable() else {
            completion(.failure(WorkoutMirrorError.healthDataUnavailable))
            return
        }
        let configuration = HKWorkoutConfiguration()
        configuration.activityType = HKWorkoutActivityType(rawValue: activityType) ?? .traditionalStrengthTraining
        configuration.locationType = HKWorkoutSessionLocationType(rawValue: locationType) ?? .indoor

        healthStore.startWatchApp(with: configuration) { success, error in
            if let error {
                completion(.failure(error))
            } else if !success {
                completion(.failure(WorkoutMirrorError.watchAppDidNotStart))
            } else {
                completion(.success(()))
            }
        }
    }

    // MARK: - Messaging

    func send(envelopeJSON: String, completion: @escaping (Result<Void, Error>) -> Void) {
        let session: HKWorkoutSession? = stateQueue.sync { mirroredSession }
        guard let session else {
            completion(.failure(WorkoutMirrorError.noMirroredSession))
            return
        }
        guard let data = envelopeJSON.data(using: .utf8) else {
            completion(.failure(WorkoutMirrorError.encodingFailed))
            return
        }
        session.sendToRemoteWorkoutSession(data: data) { _, error in
            if let error { completion(.failure(error)) } else { completion(.success(())) }
        }
    }

    /// Current mirror state, for a JS layer that just woke up.
    func snapshot() -> [String: Any] {
        let session: HKWorkoutSession? = stateQueue.sync { mirroredSession }
        return [
            "mirroring": session != nil,
            "state": session.map { Self.describe($0.state) } ?? "none",
            "activityType": session?.workoutConfiguration.activityType.rawValue as Any,
            "startDate": session?.startDate?.timeIntervalSince1970 as Any,
            "pendingMessages": stateQueue.sync { pendingMessages.count },
        ]
    }

    /// End the mirror from the phone (e.g. David finished in the app).
    func endMirroredWorkout(reason: String) {
        let session: HKWorkoutSession? = stateQueue.sync { mirroredSession }
        guard let session else { return }
        log.notice("Ending mirrored workout: \(reason, privacy: .public)")
        session.end()
        stateQueue.sync { mirroredSession = nil }
        isMirroring = false
    }

    // MARK: - Emission

    private func dispatch(_ event: Event, _ body: [String: Any]) {
        guard let emit else {
            guard event == .workoutMessage else { return }
            stateQueue.sync {
                if pendingMessages.count >= Self.maxPendingMessages {
                    pendingMessages.removeFirst()
                }
                pendingMessages.append(body)
            }
            return
        }
        emit(event, body)
    }

    private func flushPending() {
        let buffered: [[String: Any]] = stateQueue.sync {
            let copy = pendingMessages
            pendingMessages.removeAll()
            return copy
        }
        guard !buffered.isEmpty, let emit else { return }
        log.notice("Replaying \(buffered.count) buffered workout messages to JS")
        for body in buffered { emit(.workoutMessage, body) }
    }

    static func describe(_ state: HKWorkoutSessionState) -> String {
        switch state {
        case .notStarted: return "notStarted"
        case .prepared: return "prepared"
        case .running: return "running"
        case .paused: return "paused"
        case .stopped: return "stopped"
        case .ended: return "ended"
        @unknown default: return "unknown"
        }
    }
}

// MARK: - HKWorkoutSessionDelegate

@available(iOS 17.0, *)
extension IPhoneWorkoutCoordinator: HKWorkoutSessionDelegate {
    func workoutSession(
        _ workoutSession: HKWorkoutSession,
        didChangeTo toState: HKWorkoutSessionState,
        from fromState: HKWorkoutSessionState,
        date: Date
    ) {
        dispatch(.mirrorStateChanged, [
            "mirroring": toState != .ended,
            "state": Self.describe(toState),
            "changedAt": date.timeIntervalSince1970,
        ])
        if toState == .ended {
            stateQueue.sync { mirroredSession = nil }
            isMirroring = false
        }
    }

    func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        log.error("Mirrored session failed: \(error.localizedDescription, privacy: .public)")
        dispatch(.mirrorStateChanged, [
            "mirroring": false,
            "state": "failed",
            "error": error.localizedDescription,
        ])
        stateQueue.sync { mirroredSession = nil }
        isMirroring = false
    }

    func workoutSession(
        _ workoutSession: HKWorkoutSession,
        didReceiveDataFromRemoteWorkoutSession data: [Data]
    ) {
        for blob in data {
            guard let json = String(data: blob, encoding: .utf8) else {
                log.error("Dropped non-UTF8 remote message")
                continue
            }
            // Routed to JS as an opaque envelope string: parsing belongs in one
            // place (the TypeScript contract), not duplicated in Swift where it
            // would be the second thing to drift.
            guard let envelope = try? WorkoutWire.decode(blob) else {
                log.error("Dropped undecodable remote message")
                continue
            }
            if envelope.kind == .liveMetrics {
                // Metrics are high-frequency and never mutate anything, so they
                // get their own channel and skip the message pipeline.
                dispatch(.liveMetrics, ["envelope": json])
                continue
            }
            dispatch(.workoutMessage, [
                "envelope": json,
                "kind": envelope.kind.rawValue,
                "sessionId": envelope.sessionId as Any,
                "schemaVersion": envelope.schemaVersion,
                "supported": envelope.isSupportedSchema,
            ])
        }
    }
}

enum WorkoutMirrorError: LocalizedError {
    case healthDataUnavailable
    case watchAppDidNotStart
    case noMirroredSession
    case encodingFailed

    var errorDescription: String? {
        switch self {
        case .healthDataUnavailable: return "Health data isn't available on this device."
        case .watchAppDidNotStart: return "Couldn't wake Sara on your Watch."
        case .noMirroredSession: return "No workout is mirrored from the Watch."
        case .encodingFailed: return "Couldn't encode the workout message."
        }
    }
}
