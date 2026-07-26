import Foundation

/// The Watch's cached view of what David could start (plan §7.5).
///
/// Without this the Watch cannot show anything until the phone answers, which
/// means walking into the gym, raising a wrist, and waiting — the exact
/// friction the companion is meant to remove. So the phone pushes a compact
/// catalog on auth, on template change, and on foreground, and the Watch keeps
/// the last one on disk.
///
/// Deliberately thin. It carries enough to render a pre-start summary and
/// nothing more: the moment Start is pressed, the backend's snapshot is the
/// only authority, and cached template data must never be able to produce a
/// different workout (§7.5, last paragraph).
public struct WatchCatalog: Codable, Equatable {
    public struct TemplateSummary: Codable, Equatable, Identifiable {
        public let id: String
        public let name: String
        public let exerciseCount: Int
        public let exercises: [ExercisePreview]

        enum CodingKeys: String, CodingKey {
            case id, name, exercises
            case exerciseCount = "exercise_count"
        }
    }

    public struct ExercisePreview: Codable, Equatable, Hashable {
        public let name: String?
        public let sets: Int?
        public let reps: String?
    }

    public let schemaVersion: Int
    public let generatedAt: String
    public let todayTemplateId: String?
    public let templates: [TemplateSummary]
    public let policy: WatchWorkoutPolicy?

    enum CodingKeys: String, CodingKey {
        case templates, policy
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case todayTemplateId = "today_template_id"
    }

    /// Today's workout, when the phone knew of one. Falls back to the most
    /// recently updated template so the home screen is never empty.
    public var todayTemplate: TemplateSummary? {
        templates.first { $0.id == todayTemplateId } ?? templates.first
    }

    public var others: [TemplateSummary] {
        templates.filter { $0.id != todayTemplate?.id }
    }
}

/// Standing bounded approvals, mirrored to the Watch so its haptics and
/// wording match what David has actually agreed to (§6.9).
public struct WatchWorkoutPolicy: Codable, Equatable {
    public let adaptiveRestEnabled: Bool
    public let restRangeSeconds: [Int]
    public let autoStartRestAfterSet: Bool
    public let speakRoutineCoaching: Bool
    public let speakPrs: Bool
    public let speakProposals: Bool

    enum CodingKeys: String, CodingKey {
        case adaptiveRestEnabled = "adaptive_rest_enabled"
        case restRangeSeconds = "rest_range_seconds"
        case autoStartRestAfterSet = "auto_start_rest_after_set"
        case speakRoutineCoaching = "speak_routine_coaching"
        case speakPrs = "speak_prs"
        case speakProposals = "speak_proposals"
    }
}

public final class WatchCatalogStore {
    private let defaults: UserDefaults
    private let key = "sara.watch.workout.catalog"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func save(_ catalog: WatchCatalog) {
        guard let data = try? JSONEncoder().encode(catalog) else { return }
        defaults.set(data, forKey: key)
    }

    public func load() -> WatchCatalog? {
        guard let data = defaults.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(WatchCatalog.self, from: data)
    }
}
