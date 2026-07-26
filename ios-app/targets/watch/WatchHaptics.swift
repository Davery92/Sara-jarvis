import Foundation
import WatchKit

/// Named haptics for the workout (plan §8.4).
///
/// Under a barbell, the wrist is often the only channel that gets through —
/// eyes are elsewhere, AirPods have music in them. So each buzz has to *mean*
/// something distinct, and the mapping has to be defined in one place rather
/// than picked ad hoc at each call site.
///
/// The distinction that matters most is `approvalRequested`: it is the only
/// haptic that means "Sara is waiting on a decision from you". Everything else
/// is information. Reusing `.notification` for both would make the approval
/// boundary feel like noise, and an approval David does not notice is an
/// approval that expires unanswered — which is not consent (§2.4).
enum WatchHaptics {
    /// Ten seconds left. Advisory, easy to miss on purpose.
    static func restWarning() {
        WKInterfaceDevice.current().play(.click)
    }

    /// Rest is over — get back under the bar.
    static func restComplete() {
        WKInterfaceDevice.current().play(.stop)
    }

    /// A set landed. Deliberately the lightest of the set so it does not
    /// compete with anything that needs attention.
    static func setLogged() {
        WKInterfaceDevice.current().play(.click)
    }

    /// New personal record. The one celebratory buzz.
    static func personalRecord() {
        WKInterfaceDevice.current().play(.success)
    }

    /// Sara is asking for a decision. Distinct from everything else, because
    /// this is the only one that means "you need to answer".
    static func approvalRequested() {
        WKInterfaceDevice.current().play(.notification)
    }

    /// Something did not apply — a conflict, a refusal.
    static func failure() {
        WKInterfaceDevice.current().play(.failure)
    }

    /// Workout finished.
    static func workoutComplete() {
        WKInterfaceDevice.current().play(.success)
    }
}

/// End-of-workout figures the phone sends with `finish_confirmed` (§8.7).
///
/// Heart rate and calories may be absent at first: the HealthKit workout is
/// still finalizing when the Sara workout completes. The summary screen shows
/// what it has and fills the rest in when it arrives, rather than blocking
/// (§4.5).
public struct WatchWorkoutSummary: Codable, Equatable {
    public let workoutName: String?
    public let durationMinutes: Int?
    public let totalSets: Int?
    public let totalVolume: Double?
    public let heartRate: HeartRateSummary?
    public let pendingProposalCount: Int?

    public struct HeartRateSummary: Codable, Equatable {
        public let avgHeartRate: Int?
        public let maxHeartRate: Int?
        public let calories: Int?

        enum CodingKeys: String, CodingKey {
            case avgHeartRate = "avg_heart_rate"
            case maxHeartRate = "max_heart_rate"
            case calories
        }
    }

    enum CodingKeys: String, CodingKey {
        case workoutName = "workout_name"
        case durationMinutes = "duration_minutes"
        case totalSets = "total_sets"
        case totalVolume = "total_volume"
        case heartRate = "heart_rate"
        case pendingProposalCount = "pending_proposal_count"
    }
}
