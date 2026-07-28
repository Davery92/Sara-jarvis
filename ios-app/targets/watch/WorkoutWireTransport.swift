import Foundation
import HealthKit
import os
import WatchConnectivity

/// The one place a workout envelope leaves the Watch (plan §5.3).
///
/// Before this, every message went through `sendToRemoteWorkoutSession`, which
/// only exists once HealthKit mirroring is attached. That made mirroring a hard
/// prerequisite for *starting* — so a mirroring failure looked identical to a
/// dead phone, even with WatchConnectivity working perfectly.
///
/// Now there are three channels, tried in order of latency, and the caller says
/// only whether the message must survive a dropped link:
///
///  1. the mirrored `HKWorkoutSession` — lowest latency, works with the phone
///     app suspended, but only exists while mirroring is attached;
///  2. `WCSession.sendMessage` — interactive, needs the phone reachable *now*;
///  3. `WCSession.transferUserInfo` — durable, queued by the system, delivered
///     whenever the phone comes back. This is what stops a set logged at the
///     far end of a gym from evaporating.
///
/// Application context is deliberately NOT in that chain. It keeps only the
/// newest value, which is right for a catalog and catastrophically wrong for
/// an ordered sequence of commands — the second Log Set would overwrite the
/// first.
///
/// Exactly-once delivery is not this file's problem: every command carries a
/// `commandId` minted before the first send, so a message that goes out twice
/// over two channels replays on the backend rather than applying twice (§5.3
/// last paragraph).
public final class WorkoutWireTransport {

    /// Which channel a message actually left by. Recorded in diagnostics so a
    /// "the phone never got it" report can name the transport that lost it.
    public enum Channel: String {
        case mirror
        case interactive
        case durable
        case none
    }

    public enum TransportError: LocalizedError {
        case noChannelAvailable
        case encodingFailed

        public var errorDescription: String? {
            switch self {
            case .noChannelAvailable: return "No way to reach your iPhone right now."
            case .encodingFailed: return "Couldn't encode the workout message."
            }
        }
    }

    /// Key the phone unwraps a WatchConnectivity-delivered envelope from.
    /// Shared with `updateApplicationContext` so the phone has one unwrapping
    /// rule for all three WatchConnectivity shapes.
    public static let envelopeKey = "workoutEnvelope"

    private let log = Logger(subsystem: "cloud.avery.sara-ios.watch", category: "WireTransport")
    private let sessionProvider: () -> WCSession?
    /// The mirrored HealthKit session, when one is attached. Weak-by-closure so
    /// the transport never keeps a finished workout alive.
    private let mirroredSession: () -> HKWorkoutSession?

    public init(
        sessionProvider: @escaping () -> WCSession? = { WCSession.isSupported() ? WCSession.default : nil },
        mirroredSession: @escaping () -> HKWorkoutSession?
    ) {
        self.sessionProvider = sessionProvider
        self.mirroredSession = mirroredSession
    }

    // MARK: - State

    /// What the transport believes the link looks like right now (§5.1).
    public var linkPhase: PhoneLinkPhase {
        if mirroredSession() != nil { return .mirroring }
        guard let session = sessionProvider() else { return .offline }
        if session.activationState != .activated { return .reconnecting }
        return session.isReachable ? .watchConnectivity : .offline
    }

    public var activationDescription: String {
        sessionProvider().map { WorkoutStateDescribe.activation($0.activationState) } ?? "unsupported"
    }

    public var isReachable: Bool { sessionProvider()?.isReachable ?? false }

    // MARK: - Sending

    /// Send one envelope over the best available channel.
    ///
    /// `requiresDelivery` is the whole API surface for the caller: true for a
    /// mutation (falls back to the durable queue), false for telemetry like
    /// live metrics, which is worthless late and must never fill a queue.
    @discardableResult
    public func send(_ envelope: WireEnvelope, requiresDelivery: Bool) -> Channel {
        guard let data = try? WorkoutWire.encode(envelope) else {
            log.error("Encode failed for \(envelope.kind.rawValue, privacy: .public)")
            return .none
        }

        if let session = mirroredSession(), session.state == .running || session.state == .paused {
            session.sendToRemoteWorkoutSession(data: data) { [weak self] _, error in
                guard let self, let error else { return }
                self.log.error("Mirror send failed: \(error.localizedDescription, privacy: .public)")
                // "Attached" can become stale between the state check and the
                // asynchronous send. Keep the promised ladder intact instead
                // of waiting for a later queue replay to rescue this message.
                _ = self.sendViaWatchConnectivity(
                    envelope: envelope,
                    data: data,
                    requiresDelivery: requiresDelivery
                )
            }
            return .mirror
        }

        return sendViaWatchConnectivity(
            envelope: envelope,
            data: data,
            requiresDelivery: requiresDelivery
        )
    }

    @discardableResult
    private func sendViaWatchConnectivity(
        envelope: WireEnvelope,
        data: Data,
        requiresDelivery: Bool
    ) -> Channel {
        guard let session = sessionProvider(), session.activationState == .activated else {
            return .none
        }

        let payload: [String: Any] = [
            Self.envelopeKey: String(data: data, encoding: .utf8) ?? "",
            "kind": envelope.kind.rawValue,
            "schemaVersion": envelope.schemaVersion,
        ]

        if session.isReachable {
            session.sendMessage(payload, replyHandler: nil) { [weak self] error in
                guard let self else { return }
                self.log.error("Interactive send failed: \(error.localizedDescription, privacy: .public)")
                // Reachability can lapse between the check and the send. A
                // mutation must not be lost to that race, so it falls through
                // to the durable queue; telemetry is simply dropped.
                if requiresDelivery {
                    session.transferUserInfo(payload)
                }
            }
            return .interactive
        }

        guard requiresDelivery else { return .none }
        session.transferUserInfo(payload)
        return .durable
    }

    /// Replaceable latest-value state (catalog, projection snapshots).
    ///
    /// Separate from `send` on purpose: application context overwrites, which
    /// is correct for "the newest catalog" and wrong for anything ordered.
    public func updateContext(_ envelope: WireEnvelope) {
        guard let session = sessionProvider(), session.activationState == .activated,
              let data = try? WorkoutWire.encode(envelope),
              let json = String(data: data, encoding: .utf8)
        else { return }
        do {
            try session.updateApplicationContext([
                Self.envelopeKey: json,
                "sentAt": Date().timeIntervalSince1970,
            ])
        } catch {
            log.error("Context update failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    // MARK: - Receiving

    /// Pull an envelope out of any WatchConnectivity payload shape.
    ///
    /// `sendMessage`, `transferUserInfo` and `updateApplicationContext` all
    /// arrive as `[String: Any]` through different delegate callbacks; unwrapping
    /// them in one function is what keeps "the phone said something" a single
    /// code path on both sides.
    public static func envelope(from payload: [String: Any]) -> WireEnvelope? {
        guard let raw = payload[envelopeKey] as? String,
              let data = raw.data(using: .utf8) else { return nil }
        return try? WorkoutWire.decode(data)
    }
}
