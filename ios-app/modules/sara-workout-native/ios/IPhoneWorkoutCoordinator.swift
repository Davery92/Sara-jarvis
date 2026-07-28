import Foundation
import HealthKit
import os
import WatchConnectivity

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
    private let connectivitySession = WCSession.isSupported() ? WCSession.default : nil
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
    private var pendingApplicationContext: [String: Any]?
    private static let maxPendingMessages = 64

    /// Key both sides wrap a workout envelope in, whichever WatchConnectivity
    /// shape carries it. Matches `WorkoutWireTransport.envelopeKey` on the Watch.
    static let envelopeKey = "workoutEnvelope"

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

        connectivitySession?.delegate = self
        connectivitySession?.activate()

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

    /// Reply to the Watch over the best channel available (plan §5.3).
    ///
    /// Same three-channel ladder the Watch uses, for the same reason: the Watch
    /// can perfectly well have started a workout over WatchConnectivity with no
    /// mirror attached, and a reply that can only travel through the mirror
    /// would leave it stuck on "Connecting to Sara" forever.
    ///
    /// `requiresDelivery` distinguishes a projection (must arrive) from
    /// telemetry (worthless late, must never fill the durable queue).
    func send(
        envelopeJSON: String,
        requiresDelivery: Bool,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard let data = envelopeJSON.data(using: .utf8) else {
            completion(.failure(WorkoutMirrorError.encodingFailed))
            return
        }

        let session: HKWorkoutSession? = stateQueue.sync { mirroredSession }
        if let session, session.state == .running || session.state == .paused {
            session.sendToRemoteWorkoutSession(data: data) { _, error in
                if let error { completion(.failure(error)) } else { completion(.success(())) }
            }
            return
        }

        guard let connectivitySession, connectivitySession.activationState == .activated else {
            completion(.failure(WorkoutMirrorError.noMirroredSession))
            return
        }
        let payload: [String: Any] = [Self.envelopeKey: envelopeJSON]

        if connectivitySession.isReachable {
            connectivitySession.sendMessage(payload, replyHandler: nil) { [weak self] error in
                // Reachability can lapse between the check and the send. A
                // projection must not be lost to that race, so it falls through
                // to the durable queue — the completion has already resolved,
                // because the caller's job (hand it to the transport) is done.
                self?.log.error("Interactive reply failed: \(error.localizedDescription, privacy: .public)")
                if requiresDelivery {
                    connectivitySession.transferUserInfo(payload)
                }
            }
            completion(.success(()))
            return
        }

        guard requiresDelivery else {
            completion(.failure(WorkoutMirrorError.watchUnreachable))
            return
        }
        connectivitySession.transferUserInfo(payload)
        completion(.success(()))
    }

    /// Persist the latest pre-workout state for delivery through WatchConnectivity.
    /// Application context exists before a workout and retains only the newest catalog.
    func updateApplicationContext(
        envelopeJSON: String,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard let connectivitySession else {
            completion(.failure(WorkoutMirrorError.watchConnectivityUnavailable))
            return
        }
        let context: [String: Any] = [
            "workoutEnvelope": envelopeJSON,
            "sentAt": Date().timeIntervalSince1970,
        ]
        guard connectivitySession.activationState == .activated else {
            stateQueue.sync { pendingApplicationContext = context }
            connectivitySession.activate()
            completion(.success(()))
            return
        }
        do {
            try connectivitySession.updateApplicationContext(context)
            completion(.success(()))
        } catch {
            completion(.failure(error))
        }
    }

    private func flushPendingApplicationContext(to session: WCSession) {
        let context: [String: Any]? = stateQueue.sync {
            defer { pendingApplicationContext = nil }
            return pendingApplicationContext
        }
        guard let context else { return }
        do {
            try session.updateApplicationContext(context)
        } catch {
            log.error("Queued Watch context failed: \(error.localizedDescription, privacy: .public)")
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

// MARK: - WCSessionDelegate

@available(iOS 17.0, *)
extension IPhoneWorkoutCoordinator: WCSessionDelegate {
    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        if let error {
            log.error("WatchConnectivity activation failed: \(error.localizedDescription, privacy: .public)")
        } else {
            log.notice("WatchConnectivity activated: \(activationState.rawValue)")
            if activationState == .activated {
                flushPendingApplicationContext(to: session)
            }
        }
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    // MARK: - Inbound WatchConnectivity (§5.3)
    //
    // The Watch reaches the phone through three channels, and until now the
    // phone only listened on one of them (the mirrored HealthKit session). That
    // is why a Watch start with no mirror produced nothing at all on this side:
    // the message was sent, and there was no delegate method to receive it.

    /// Interactive message — the Watch is reachable right now.
    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        route(message)
    }

    /// Interactive message with a reply handler. Answered immediately so the
    /// Watch's send does not time out; the real reply travels as its own
    /// envelope once the backend has answered.
    func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        route(message)
        replyHandler(["received": true])
    }

    /// Durable transfer — queued by the system while the phone was away.
    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        route(userInfo)
    }

    /// Unwrap a WatchConnectivity payload and emit it on the same JS channel
    /// mirrored messages use, so `watchWorkout.ts` has exactly one handler.
    private func route(_ payload: [String: Any]) {
        guard let json = payload[Self.envelopeKey] as? String,
              let data = json.data(using: .utf8),
              let envelope = try? WorkoutWire.decode(data) else {
            log.error("Dropped undecodable WatchConnectivity payload")
            return
        }
        if envelope.kind == .liveMetrics {
            dispatch(.liveMetrics, ["envelope": json])
            return
        }
        dispatch(.workoutMessage, [
            "envelope": json,
            "kind": envelope.kind.rawValue,
            "sessionId": envelope.sessionId as Any,
            "schemaVersion": envelope.schemaVersion,
            "supported": envelope.isSupportedSchema,
            "transport": "watchConnectivity",
        ])
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
                "transport": "mirror",
            ])
        }
    }
}

enum WorkoutMirrorError: LocalizedError {
    case healthDataUnavailable
    case watchAppDidNotStart
    case noMirroredSession
    case encodingFailed
    case watchConnectivityUnavailable
    case watchUnreachable

    var errorDescription: String? {
        switch self {
        case .healthDataUnavailable: return "Health data isn't available on this device."
        case .watchAppDidNotStart: return "Couldn't wake Sara on your Watch."
        case .noMirroredSession: return "No way to reach your Watch right now."
        case .encodingFailed: return "Couldn't encode the workout message."
        case .watchConnectivityUnavailable: return "Watch connectivity isn't available."
        case .watchUnreachable: return "Your Watch isn't reachable."
        }
    }
}
