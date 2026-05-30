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
