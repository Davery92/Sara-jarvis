import Foundation
import ActivityKit

/**
 * DUPLICATE of modules/sara-native/ios/SaraActivityAttributes.swift.
 *
 * ActivityKit matches a running activity (started by the app) to this widget UI
 * by the attributes type's NAME + Codable shape. The app target and this widget
 * extension are separate modules, so the type must be declared in BOTH. Keep the
 * two files identical.
 */
@available(iOS 16.2, *)
public struct SaraTimerAttributes: ActivityAttributes {
  public struct ContentState: Codable, Hashable {
    public var endDate: Date

    public init(endDate: Date) {
      self.endDate = endDate
    }
  }

  public var timerId: String
  public var title: String

  public init(timerId: String, title: String) {
    self.timerId = timerId
    self.title = title
  }
}
