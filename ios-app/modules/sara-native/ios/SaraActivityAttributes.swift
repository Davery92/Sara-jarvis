import Foundation
import ActivityKit

/**
 * SaraTimerAttributes — the Live Activity contract for timers.
 *
 * ActivityKit matches a running activity to its widget UI by this type's NAME and
 * Codable shape, even though the app target and the widget extension are separate
 * modules. This struct is therefore intentionally DUPLICATED verbatim in the
 * widget target (targets/widget/SaraActivityAttributes.swift). Keep the two in sync.
 */
@available(iOS 16.2, *)
public struct SaraTimerAttributes: ActivityAttributes {
  public struct ContentState: Codable, Hashable {
    /// When the timer fires. Drives Text(timerInterval:) for a self-updating countdown.
    public var endDate: Date

    public init(endDate: Date) {
      self.endDate = endDate
    }
  }

  /// Stable id so the app can find & end the right activity.
  public var timerId: String
  /// Human label, e.g. "Tea" or "Pomodoro".
  public var title: String

  public init(timerId: String, title: String) {
    self.timerId = timerId
    self.title = title
  }
}

/// Generic ongoing-event Live Activity used for workouts and background tasks.
/// Also DUPLICATED in targets/widget/SaraActivityAttributes.swift — keep in sync.
@available(iOS 16.2, *)
public struct SaraEventAttributes: ActivityAttributes {
  public struct ContentState: Codable, Hashable {
    public var subtitle: String
    /// Epoch ms to count elapsed time up from; 0 = no timer shown.
    public var startEpochMs: Double

    public init(subtitle: String, startEpochMs: Double) {
      self.subtitle = subtitle
      self.startEpochMs = startEpochMs
    }
  }

  public var id: String
  public var kind: String // "workout" | "task"
  public var title: String

  public init(id: String, kind: String, title: String) {
    self.id = id
    self.kind = kind
    self.title = title
  }
}
