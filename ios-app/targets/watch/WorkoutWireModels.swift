import Foundation

// MARK: - Sara cross-device workout wire contract (plan §5)
//
// This file is the single source of truth for what the Watch, the iPhone and
// the backend say to each other. It is duplicated verbatim into
// `modules/sara-workout-native/ios/` because the Watch app and the Expo module
// are separate compilation units with no shared framework;
// `ios-app/scripts/check-workout-contract-parity.mjs` compares this against
// its copy, the TypeScript mirror and the Python service, and fails when they
// drift apart.
//
// Two rules drive every decision here:
//
//  1. An unknown `schemaVersion` or message kind must degrade, never crash.
//    The Watch and the phone are updated independently, so at some point one
//    of them WILL receive something it has never heard of — mid-workout, on a
//    wrist, with a barbell overhead. Decoding is therefore total: unknown
//    kinds land in `.unknown(String)` and are reported to diagnostics.
//
//  2. Nothing here mutates state. These are messages about state the backend
//    owns; the projection is always the authority (§4.1).

public let saraWorkoutSchemaVersion = 1

// MARK: - Minimal JSON value

/// Heterogeneous payload container.
///
/// Command payloads are genuinely open-ended (a weight here, a proposal id
/// there), and a `[String: Any]` cannot be `Codable`. This keeps payloads
/// round-trippable without hand-writing a struct per command kind on both
/// platforms.
public enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        if let v = try? c.decode(Double.self) { self = .number(v); return }
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode([String: JSONValue].self) { self = .object(v); return }
        if let v = try? c.decode([JSONValue].self) { self = .array(v); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "Unsupported JSON value")
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    public var doubleValue: Double? {
        if case .number(let v) = self { return v }
        if case .string(let s) = self { return Double(s) }
        return nil
    }

    public var stringValue: String? {
        if case .string(let v) = self { return v }
        return nil
    }

    public var objectValue: [String: JSONValue]? {
        if case .object(let v) = self { return v }
        return nil
    }
}

// MARK: - Devices

public enum OriginDevice: String, Codable {
    case phone
    case watch
    case web
    case server
}

// MARK: - Projection (§5.1)

public struct WorkoutTemplateRef: Codable, Equatable {
    public let id: String?
    public let name: String
    public let isDeload: Bool

    enum CodingKeys: String, CodingKey {
        case id, name
        case isDeload = "is_deload"
    }
}

public struct WorkoutCursor: Codable, Equatable {
    public let exerciseIndex: Int
    public let setIndex: Int

    enum CodingKeys: String, CodingKey {
        case exerciseIndex = "exercise_index"
        case setIndex = "set_index"
    }
}

public struct WorkoutProgress: Codable, Equatable {
    public let completedSets: Int
    public let totalSets: Int
    public let totalVolume: Double

    enum CodingKeys: String, CodingKey {
        case completedSets = "completed_sets"
        case totalSets = "total_sets"
        case totalVolume = "total_volume"
    }
}

public struct LastSessionSummary: Codable, Equatable {
    public let weights: [Double]?
    public let reps: [Int]?
    public let avgRpe: Double?

    enum CodingKeys: String, CodingKey {
        case weights, reps
        case avgRpe = "avg_rpe"
    }
}

public struct WorkoutExercise: Codable, Equatable {
    public let name: String?
    public let variant: String?
    public let targetSets: Int?
    /// Free text like "8-10", not a number — the backend keeps the range.
    public let targetReps: String?
    public let targetRpe: Double?
    /// What David has agreed to lift. This is the number the UI prefills.
    public let approvedWeight: Double?
    /// What Sara currently recommends. Never used as a target until approved.
    public let calculatedSuggestion: Double?
    public let completedSets: Int?
    public let lastSession: LastSessionSummary?
    public let progressionNote: String?
    public let notes: String?
    public let isPerSide: Bool?
    public let supersetGroup: String?
    public let setTechnique: String?
    public let restSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case name, variant, notes
        case targetSets = "target_sets"
        case targetReps = "target_reps"
        case targetRpe = "target_rpe"
        case approvedWeight = "approved_weight"
        case calculatedSuggestion = "calculated_suggestion"
        case completedSets = "completed_sets"
        case lastSession = "last_session"
        case progressionNote = "progression_note"
        case isPerSide = "is_per_side"
        case supersetGroup = "superset_group"
        case setTechnique = "set_technique"
        case restSeconds = "rest_seconds"
    }
}

public struct WorkoutRestState: Codable, Equatable {
    public let active: Bool
    public let startedAt: String?
    public let durationSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case active
        case startedAt = "started_at"
        case durationSeconds = "duration_seconds"
    }
}

public struct WorkoutHealthKitState: Codable, Equatable {
    public let state: String?
    public let workoutUuid: String?
    public let activityType: String?
    public let startedAt: String?
    public let endedAt: String?

    enum CodingKeys: String, CodingKey {
        case state
        case workoutUuid = "workout_uuid"
        case activityType = "activity_type"
        case startedAt = "started_at"
        case endedAt = "ended_at"
    }
}

public struct WorkoutProposal: Codable, Equatable {
    public let proposalId: String
    public let sessionId: String?
    public let kind: String
    public let scope: [String: JSONValue]?
    public let currentValue: [String: JSONValue]?
    public let proposedValue: [String: JSONValue]?
    public let reason: String?
    public let status: String
    public let expiresAt: String?

    enum CodingKeys: String, CodingKey {
        case kind, scope, reason, status
        case proposalId = "proposal_id"
        case sessionId = "session_id"
        case currentValue = "current_value"
        case proposedValue = "proposed_value"
        case expiresAt = "expires_at"
    }

    /// Convenience for the "65 → 60 lb" line the approval screens show.
    public var weightChange: (current: Double, proposed: Double)? {
        guard let c = currentValue?["weight"]?.doubleValue,
              let p = proposedValue?["weight"]?.doubleValue else { return nil }
        return (c, p)
    }
}

/// The complete renderable state. Both devices draw from this and nothing else.
public struct WorkoutProjection: Codable, Equatable {
    public let schemaVersion: Int
    public let sessionId: String
    public let version: Int
    public let status: String
    public let startedAt: String?
    public let originDevice: String?
    public let template: WorkoutTemplateRef
    public let cursor: WorkoutCursor
    public let progress: WorkoutProgress
    public let currentExercise: WorkoutExercise?
    /// Absent in the compact form the Watch receives — it renders from
    /// `currentExercise`, and asks for the full list only for the jump screen.
    public let exercises: [WorkoutExercise]?
    public let rest: WorkoutRestState
    public let healthkit: WorkoutHealthKitState?
    public let pendingProposal: WorkoutProposal?
    public let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case version, status, template, cursor, progress, exercises, rest, healthkit
        case schemaVersion = "schema_version"
        case sessionId = "session_id"
        case startedAt = "started_at"
        case originDevice = "origin_device"
        case currentExercise = "current_exercise"
        case pendingProposal = "pending_proposal"
        case updatedAt = "updated_at"
    }
}

// MARK: - Command envelope (§5.2)

public enum WorkoutCommandKind: String, Codable {
    case logSet = "log_set"
    case selectExercise = "select_exercise"
    case setVariant = "set_variant"
    case skipExercise = "skip_exercise"
    case restStart = "rest_start"
    case restStop = "rest_stop"
    case complete
    case abandon
    case approveProposal = "approve_proposal"
    case rejectProposal = "reject_proposal"
    case healthkitState = "healthkit_state"
    case setPolicy = "set_policy"
}

public struct WorkoutCommand: Codable, Equatable {
    public let schemaVersion: Int
    /// Generated on the originating device BEFORE sending. This is the whole
    /// idempotency story: a retry reuses it and replays instead of applying
    /// twice, which is what makes a double-tapped Log Set safe.
    public let commandId: String
    public let sessionId: String?
    /// Stale UI detector — the backend refuses rather than clobbering a change
    /// the other device made in between.
    public let expectedVersion: Int?
    public let originDevice: OriginDevice
    public let kind: WorkoutCommandKind
    public let createdAt: String
    public let payload: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case kind, payload
        case schemaVersion = "schema_version"
        case commandId = "command_id"
        case sessionId = "session_id"
        case expectedVersion = "expected_version"
        case originDevice = "origin_device"
        case createdAt = "created_at"
    }

    public init(
        commandId: String = UUID().uuidString,
        sessionId: String?,
        expectedVersion: Int?,
        originDevice: OriginDevice,
        kind: WorkoutCommandKind,
        createdAt: String = ISO8601DateFormatter().string(from: Date()),
        payload: [String: JSONValue] = [:]
    ) {
        self.schemaVersion = saraWorkoutSchemaVersion
        self.commandId = commandId
        self.sessionId = sessionId
        self.expectedVersion = expectedVersion
        self.originDevice = originDevice
        self.kind = kind
        self.createdAt = createdAt
        self.payload = payload
    }
}

// MARK: - Coaching event (§5.4)

public struct WorkoutCoachingEvent: Codable, Equatable {
    public let eventId: String
    public let sessionId: String
    public let afterVersion: Int?
    public let kind: String
    public let text: String
    public let speak: Bool
    public let priority: String
    public let expiresAt: String?
    public let proposalId: String?

    enum CodingKeys: String, CodingKey {
        case kind, text, speak, priority
        case eventId = "event_id"
        case sessionId = "session_id"
        case afterVersion = "after_version"
        case expiresAt = "expires_at"
        case proposalId = "proposal_id"
    }

    /// Coaching about a set two sets ago is worse than silence (§10.4).
    public func isExpired(now: Date = Date()) -> Bool {
        guard let expiresAt, let date = ISO8601DateFormatter.saraDate(from: expiresAt) else {
            return false
        }
        return date < now
    }
}

// MARK: - Live metrics (§7.6)

public struct WorkoutLiveMetrics: Codable, Equatable {
    public let heartRate: Double?
    public let activeEnergyKcal: Double?
    public let elapsedSeconds: Double?
    public let capturedAt: String

    enum CodingKeys: String, CodingKey {
        case heartRate = "heart_rate"
        case activeEnergyKcal = "active_energy_kcal"
        case elapsedSeconds = "elapsed_seconds"
        case capturedAt = "captured_at"
    }

    public init(heartRate: Double?, activeEnergyKcal: Double?, elapsedSeconds: Double?,
                capturedAt: String = ISO8601DateFormatter.sara.string(from: Date())) {
        self.heartRate = heartRate
        self.activeEnergyKcal = activeEnergyKcal
        self.elapsedSeconds = elapsedSeconds
        self.capturedAt = capturedAt
    }
}

// MARK: - Wire envelope (§5.3)

public enum WireMessageKind: RawRepresentable, Codable, Equatable {
    // Watch -> iPhone
    case startRequested
    case commandRequested
    case liveMetrics
    case healthkitStarted
    case healthkitPaused
    case healthkitResumed
    case healthkitFinished
    case watchRecoveredSession
    /// Ask for the uncompacted projection. Per-set messages omit the exercise
    /// list to keep the radio quiet; the Watch asks explicitly when it opens
    /// the jump screen.
    case projectionRequested
    // iPhone -> Watch
    case startAccepted
    case startConflict
    case commandAccepted
    case commandRejected
    case projectionUpdated
    case coachingEvent
    case proposalCreated
    case proposalResolved
    case finishConfirmed
    case catalogUpdated
    /// Anything this build has never heard of. Kept rather than thrown so a
    /// newer peer cannot take an active workout down (§5.3).
    case unknown(String)

    public init?(rawValue: String) {
        switch rawValue {
        case "start_requested": self = .startRequested
        case "command_requested": self = .commandRequested
        case "live_metrics": self = .liveMetrics
        case "healthkit_started": self = .healthkitStarted
        case "healthkit_paused": self = .healthkitPaused
        case "healthkit_resumed": self = .healthkitResumed
        case "healthkit_finished": self = .healthkitFinished
        case "watch_recovered_session": self = .watchRecoveredSession
        case "projection_requested": self = .projectionRequested
        case "start_accepted": self = .startAccepted
        case "start_conflict": self = .startConflict
        case "command_accepted": self = .commandAccepted
        case "command_rejected": self = .commandRejected
        case "projection_updated": self = .projectionUpdated
        case "coaching_event": self = .coachingEvent
        case "proposal_created": self = .proposalCreated
        case "proposal_resolved": self = .proposalResolved
        case "finish_confirmed": self = .finishConfirmed
        case "catalog_updated": self = .catalogUpdated
        default: self = .unknown(rawValue)
        }
    }

    public var rawValue: String {
        switch self {
        case .startRequested: return "start_requested"
        case .commandRequested: return "command_requested"
        case .liveMetrics: return "live_metrics"
        case .healthkitStarted: return "healthkit_started"
        case .healthkitPaused: return "healthkit_paused"
        case .healthkitResumed: return "healthkit_resumed"
        case .healthkitFinished: return "healthkit_finished"
        case .watchRecoveredSession: return "watch_recovered_session"
        case .projectionRequested: return "projection_requested"
        case .startAccepted: return "start_accepted"
        case .startConflict: return "start_conflict"
        case .commandAccepted: return "command_accepted"
        case .commandRejected: return "command_rejected"
        case .projectionUpdated: return "projection_updated"
        case .coachingEvent: return "coaching_event"
        case .proposalCreated: return "proposal_created"
        case .proposalResolved: return "proposal_resolved"
        case .finishConfirmed: return "finish_confirmed"
        case .catalogUpdated: return "catalog_updated"
        case .unknown(let raw): return raw
        }
    }

    public var isUnknown: Bool {
        if case .unknown = self { return true }
        return false
    }
}

public struct WireEnvelope: Codable, Equatable {
    public let schemaVersion: Int
    public let messageId: String
    public let sessionId: String?
    public let kind: WireMessageKind
    public let sentAt: String
    public let payload: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case kind, payload
        case schemaVersion = "schema_version"
        case messageId = "message_id"
        case sessionId = "session_id"
        case sentAt = "sent_at"
    }

    public init(
        kind: WireMessageKind,
        sessionId: String?,
        payload: [String: JSONValue] = [:],
        messageId: String = UUID().uuidString,
        sentAt: String = ISO8601DateFormatter.sara.string(from: Date())
    ) {
        self.schemaVersion = saraWorkoutSchemaVersion
        self.messageId = messageId
        self.sessionId = sessionId
        self.kind = kind
        self.sentAt = sentAt
        self.payload = payload
    }

    /// True when this build is too old to interpret the message safely.
    /// Callers surface it in diagnostics and drop the message.
    public var isSupportedSchema: Bool { schemaVersion == saraWorkoutSchemaVersion }
}

// MARK: - Codec

public enum WorkoutWire {
    public static let encoder: JSONEncoder = JSONEncoder()
    public static let decoder: JSONDecoder = JSONDecoder()

    public static func encode(_ envelope: WireEnvelope) throws -> Data {
        try encoder.encode(envelope)
    }

    /// Decoding never throws on an unknown *kind* — only on genuinely malformed
    /// data. A message from a newer build arrives as `.unknown` and is ignored.
    public static func decode(_ data: Data) throws -> WireEnvelope {
        try decoder.decode(WireEnvelope.self, from: data)
    }

    /// Pull a typed body out of an envelope payload.
    public static func decodePayload<T: Decodable>(_ type: T.Type, from envelope: WireEnvelope) throws -> T {
        let data = try encoder.encode(envelope.payload)
        return try decoder.decode(T.self, from: data)
    }

    public static func encodePayload<T: Encodable>(_ value: T) throws -> [String: JSONValue] {
        let data = try encoder.encode(value)
        return try decoder.decode([String: JSONValue].self, from: data)
    }
}

public extension ISO8601DateFormatter {
    /// Python's `datetime.isoformat()` emits fractional seconds only when the
    /// value happens to carry microseconds, so the backend legitimately sends
    /// both shapes. A formatter configured for one silently returns nil for the
    /// other — which would turn every `expiresAt` check into "never expires"
    /// and let Sara speak coaching from two sets ago. Parse with both.
    static let sara: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static let saraNoFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func saraDate(from string: String) -> Date? {
        sara.date(from: string) ?? saraNoFraction.date(from: string)
    }
}
