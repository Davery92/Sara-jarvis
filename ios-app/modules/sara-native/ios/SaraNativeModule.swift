import ExpoModulesCore
import WidgetKit

#if canImport(ActivityKit)
import ActivityKit
#endif

/**
 * SaraNativeModule
 *
 * Bridges two iOS capabilities to JS:
 *  - Widget data: writes key/values into the shared App Group so the WidgetKit
 *    extension can render Sara's state, then asks WidgetKit to refresh.
 *  - Live Activities: starts / ends ActivityKit timer activities.
 *
 * The App Group id must match the one declared in app.json entitlements and in
 * the widget target's expo-target.config.js.
 */
public class SaraNativeModule: Module {
  static let appGroup = "group.cloud.avery.sara-ios"

  public func definition() -> ModuleDefinition {
    Name("SaraNative")

    Function("setWidgetData") { (data: [String: String]) in
      guard let defaults = UserDefaults(suiteName: SaraNativeModule.appGroup) else { return }
      for (key, value) in data {
        defaults.set(value, forKey: key)
      }
      defaults.set(ISO8601DateFormatter().string(from: Date()), forKey: "updated_at")
      if #available(iOS 14.0, *) {
        WidgetCenter.shared.reloadAllTimelines()
      }
    }

    Function("reloadWidgets") {
      if #available(iOS 14.0, *) {
        WidgetCenter.shared.reloadAllTimelines()
      }
    }

    Function("areActivitiesEnabled") { () -> Bool in
      #if canImport(ActivityKit)
      if #available(iOS 16.2, *) {
        return ActivityAuthorizationInfo().areActivitiesEnabled
      }
      #endif
      return false
    }

    Function("startTimerActivity") { (timerId: String, title: String, endEpochMs: Double) -> String? in
      #if canImport(ActivityKit)
      if #available(iOS 16.2, *) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return nil }
        let endDate = Date(timeIntervalSince1970: endEpochMs / 1000.0)
        let attributes = SaraTimerAttributes(timerId: timerId, title: title)
        let state = SaraTimerAttributes.ContentState(endDate: endDate)
        do {
          let content = ActivityContent(state: state, staleDate: endDate)
          let activity = try Activity.request(attributes: attributes, content: content, pushType: nil)
          return activity.id
        } catch {
          return nil
        }
      }
      #endif
      return nil
    }

    Function("endTimerActivity") { (timerId: String) in
      #if canImport(ActivityKit)
      if #available(iOS 16.2, *) {
        Task {
          for activity in Activity<SaraTimerAttributes>.activities where activity.attributes.timerId == timerId {
            await activity.end(nil, dismissalPolicy: .immediate)
          }
        }
      }
      #endif
    }

    Function("endAllActivities") {
      #if canImport(ActivityKit)
      if #available(iOS 16.2, *) {
        Task {
          for activity in Activity<SaraTimerAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
          }
        }
      }
      #endif
    }
  }
}
