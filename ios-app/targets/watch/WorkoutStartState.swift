import Foundation
import HealthKit
import WatchConnectivity

/// What is actually happening during a Watch start (plan §5.1, §5.4).
///
/// The failure this file exists to remove: `startWorkout()` was one
/// all-or-nothing chain, so a permissions problem, a mirroring problem and a
/// backend problem all produced the same four words — `Couldn't start the
/// workout` — with the real error thrown away. David could not tell which of
/// them had happened, and neither could anyone reading a bug report.
///
/// So the three things that can independently succeed or fail are tracked
/// independently. Then the UI can say which one is stuck, and the retry can
/// resume from the stage that failed rather than starting over.

// MARK: - Stages

/// The Apple workout on this wrist. Physiology lives or dies with this one.
public enum HealthKitPhase: String, Codable, Equatable {
    case idle
    case authorizing
    case starting
    case running
    case failed
    case ended
}

/// The canonical Sara session. Only the backend can move this to `active`.
public enum SaraSessionPhase: String, Codable, Equatable {
    case none
    case requesting
    case active
    case conflict
    case failed
}

/// How commands are currently reaching the phone.
///
/// `mirroring` is the best channel, but it is emphatically not a prerequisite:
/// treating it as one is exactly what made a start fail while ordinary
/// WatchConnectivity was healthy (§2.2).
public enum PhoneLinkPhase: String, Codable, Equatable {
    case mirroring
    case watchConnectivity
    case reconnecting
    case offline
}

// MARK: - Composite state

public struct WorkoutStartState: Equatable {
    public var healthKit: HealthKitPhase = .idle
    public var saraSession: SaraSessionPhase = .none
    public var phoneLink: PhoneLinkPhase = .offline
    /// The precise failure, when there is one. Shown verbatim under the
    /// headline sentence rather than replacing it.
    public var detail: String?

    public init() {}

    /// One sentence describing the true state (§5.1).
    ///
    /// Ordered by what David can act on: a permission problem first (only he
    /// can fix it), then progress, then degraded-but-working states. A workout
    /// that is running says so even when half the transport is down, because
    /// "your workout is fine, the phone is catching up" is a different message
    /// from "your workout did not start".
    public var headline: String {
        switch (healthKit, saraSession) {
        case (.failed, _):
            return detail ?? "Apple Health couldn't start the workout"
        case (.authorizing, _):
            return "Requesting Health access"
        case (.starting, _):
            return "Starting Apple workout"
        case (_, .conflict):
            return "Another workout is already active"
        case (.running, .requesting):
            return phoneLink == .offline
                ? "Apple workout running — connecting to Sara"
                : "Connecting to Sara"
        case (.running, .failed):
            return "Apple workout running — Sara unreachable"
        case (.running, .active):
            switch phoneLink {
            case .mirroring, .watchConnectivity: return "Workout running"
            case .reconnecting: return "Workout running — reconnecting phone"
            case .offline: return "Workout running — phone offline"
            }
        case (.ended, .active), (.idle, .active):
            return "Sara session active — heart-rate tracking unavailable"
        case (_, .failed):
            return detail ?? "Couldn't reach Sara"
        default:
            return "Ready"
        }
    }

    /// True when the Apple workout is running but Sara has not confirmed.
    ///
    /// This is the state that must never be silently discarded: real
    /// physiology is being collected for a workout the backend has not
    /// acknowledged yet (§5.2).
    public var isOrphanedHealthKit: Bool {
        healthKit == .running && saraSession != .active
    }

    /// Whether a Retry can plausibly help. A permission refusal cannot be
    /// retried from here — it needs the Health app — so offering Retry would
    /// be a button that does nothing.
    public var isRetryable: Bool {
        saraSession == .failed || saraSession == .conflict || phoneLink == .offline
    }
}

// MARK: - Pending start (§5.2 step 2)

/// A start attempt that has begun on this wrist but has not been confirmed by
/// the backend.
///
/// Persisted because the interesting case is the one where it is never
/// answered: the Apple workout is running and collecting real physiology, and
/// the Watch app may be relaunched before the phone comes back. Keeping the
/// original `attemptId` is what makes the eventual retry replay into the same
/// Sara session instead of creating a second workout.
public struct WatchPendingStart: Codable, Equatable {
    public let attemptId: String
    public let templateId: String
    public let templateName: String
    public let templateKind: String?
    public let healthkitStartedAt: Date
    public let activityType: UInt

    public init(
        attemptId: String,
        templateId: String,
        templateName: String,
        templateKind: String?,
        healthkitStartedAt: Date,
        activityType: UInt
    ) {
        self.attemptId = attemptId
        self.templateId = templateId
        self.templateName = templateName
        self.templateKind = templateKind
        self.healthkitStartedAt = healthkitStartedAt
        self.activityType = activityType
    }
}

// MARK: - Diagnostics record (§5.4)

/// One start attempt, recorded in enough detail to explain a failure later.
///
/// Everything here is something that was genuinely unknown after the failed
/// start on 2026-07-27: which stage it died at, what HealthKit actually said,
/// whether WatchConnectivity was even activated, and whether the backend ever
/// saw the attempt.
public struct WorkoutStartDiagnostic: Codable, Equatable, Identifiable {
    public var id: String = UUID().uuidString
    public var at: Date = Date()
    public var stage: String
    public var buildNumber: String?
    public var healthKitAuthorization: String?
    public var healthKitSessionState: String?
    public var errorDomain: String?
    public var errorCode: Int?
    public var errorDescription: String?
    public var connectivityActivation: String?
    public var connectivityReachable: Bool?
    public var mirrorState: String?
    public var transport: String?
    public var startAttemptId: String?
    /// nil = unknown (never got an answer), which is itself the finding.
    public var backendAccepted: Bool?

    public init(
        stage: String,
        buildNumber: String? = Bundle.main.infoDictionary?["CFBundleVersion"] as? String,
        healthKitAuthorization: String? = nil,
        healthKitSessionState: String? = nil,
        error: Error? = nil,
        connectivityActivation: String? = nil,
        connectivityReachable: Bool? = nil,
        mirrorState: String? = nil,
        transport: String? = nil,
        startAttemptId: String? = nil,
        backendAccepted: Bool? = nil
    ) {
        self.stage = stage
        self.buildNumber = buildNumber
        self.healthKitAuthorization = healthKitAuthorization
        self.healthKitSessionState = healthKitSessionState
        if let error {
            let ns = error as NSError
            self.errorDomain = ns.domain
            self.errorCode = ns.code
            self.errorDescription = error.localizedDescription
        }
        self.connectivityActivation = connectivityActivation
        self.connectivityReachable = connectivityReachable
        self.mirrorState = mirrorState
        self.transport = transport
        self.startAttemptId = startAttemptId
        self.backendAccepted = backendAccepted
    }

    /// One exportable line. Deliberately flat text: it has to survive being
    /// read off a wrist, or dictated into a message.
    public var summary: String {
        var parts = [stage]
        if let errorDomain, let errorCode {
            parts.append("\(errorDomain) \(errorCode)")
        }
        if let errorDescription { parts.append(errorDescription) }
        if let transport { parts.append("via \(transport)") }
        if let healthKitAuthorization { parts.append("auth=\(healthKitAuthorization)") }
        if let mirrorState { parts.append("mirror=\(mirrorState)") }
        if let backendAccepted { parts.append("backend=\(backendAccepted ? "accepted" : "refused")") }
        return parts.joined(separator: " · ")
    }
}

/// A bounded on-disk ring of recent start diagnostics.
///
/// Bounded because this runs on a watch and must never grow without limit;
/// persisted because the most interesting failures are the ones where the app
/// was relaunched before anyone could look.
public final class WatchStartDiagnosticsStore {
    private let defaults: UserDefaults
    private let key = "sara.watch.workout.startDiagnostics"
    private let limit: Int
    private let lock = NSLock()

    public init(defaults: UserDefaults = .standard, limit: Int = 40) {
        self.defaults = defaults
        self.limit = limit
    }

    public func record(_ entry: WorkoutStartDiagnostic) {
        lock.lock(); defer { lock.unlock() }
        var entries = loadUnlocked()
        entries.insert(entry, at: 0)
        if entries.count > limit { entries.removeLast(entries.count - limit) }
        if let data = try? JSONEncoder().encode(entries) {
            defaults.set(data, forKey: key)
        }
    }

    public func load() -> [WorkoutStartDiagnostic] {
        lock.lock(); defer { lock.unlock() }
        return loadUnlocked()
    }

    public func clear() {
        lock.lock(); defer { lock.unlock() }
        defaults.removeObject(forKey: key)
    }

    /// Everything, oldest last, as plain text for the export command (§10 P0).
    public func export() -> String {
        let entries = load()
        guard !entries.isEmpty else { return "No start diagnostics recorded." }
        let formatter = ISO8601DateFormatter()
        return entries
            .map { "\(formatter.string(from: $0.at))  \($0.summary)" }
            .joined(separator: "\n")
    }

    private func loadUnlocked() -> [WorkoutStartDiagnostic] {
        guard let data = defaults.data(forKey: key),
              let entries = try? JSONDecoder().decode([WorkoutStartDiagnostic].self, from: data)
        else { return [] }
        return entries
    }
}

// MARK: - Describers

public enum WorkoutStateDescribe {
    public static func authorization(_ status: HKAuthorizationStatus) -> String {
        switch status {
        case .notDetermined: return "notDetermined"
        case .sharingDenied: return "denied"
        case .sharingAuthorized: return "authorized"
        @unknown default: return "unknown"
        }
    }

    public static func session(_ state: HKWorkoutSessionState) -> String {
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

    public static func activation(_ state: WCSessionActivationState) -> String {
        switch state {
        case .notActivated: return "notActivated"
        case .inactive: return "inactive"
        case .activated: return "activated"
        @unknown default: return "unknown"
        }
    }
}
