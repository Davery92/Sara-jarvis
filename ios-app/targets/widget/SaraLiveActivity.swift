import ActivityKit
import WidgetKit
import SwiftUI

/// Live Activity for active timers — lock screen banner + Dynamic Island.
/// Uses Text(timerInterval:) so the countdown updates itself without the app
/// pushing per-second updates.
@available(iOS 16.2, *)
struct SaraTimerLiveActivity: Widget {
  var body: some WidgetConfiguration {
    ActivityConfiguration(for: SaraTimerAttributes.self) { context in
      // Lock screen / banner presentation
      HStack(spacing: 12) {
        Image(systemName: "timer")
          .font(.title2)
          .foregroundStyle(.tint)
        VStack(alignment: .leading, spacing: 2) {
          Text(context.attributes.title)
            .font(.headline)
            .lineLimit(1)
          Text("Sara timer")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        Spacer()
        Text(timerInterval: timerRange(context.state.endDate), countsDown: true)
          .font(.title2)
          .monospacedDigit()
          .frame(width: 72)
          .multilineTextAlignment(.trailing)
      }
      .padding()
      .activityBackgroundTint(Color.black.opacity(0.55))
      .activitySystemActionForegroundColor(.white)
    } dynamicIsland: { context in
      DynamicIsland {
        DynamicIslandExpandedRegion(.leading) {
          Label(context.attributes.title, systemImage: "timer")
            .lineLimit(1)
        }
        DynamicIslandExpandedRegion(.trailing) {
          Text(timerInterval: timerRange(context.state.endDate), countsDown: true)
            .monospacedDigit()
            .frame(width: 64)
            .multilineTextAlignment(.trailing)
        }
      } compactLeading: {
        Image(systemName: "timer")
      } compactTrailing: {
        Text(timerInterval: timerRange(context.state.endDate), countsDown: true)
          .monospacedDigit()
          .frame(width: 44)
      } minimal: {
        Image(systemName: "timer")
      }
      .widgetURL(URL(string: "sara://timers"))
    }
  }

  /// ClosedRange<Date> requires lowerBound <= upperBound; clamp if the timer
  /// already elapsed so SwiftUI never crashes.
  private func timerRange(_ end: Date) -> ClosedRange<Date> {
    let now = Date()
    return now <= end ? now...end : end...end
  }
}
