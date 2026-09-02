import ActivityKit
import WidgetKit
import SwiftUI

/// Generic ongoing-event Live Activity: workouts (count-up timer) and background
/// tasks ("Sara is working on…"). Lock screen + Dynamic Island.
@available(iOS 16.2, *)
struct SaraEventLiveActivity: Widget {
  var body: some WidgetConfiguration {
    ActivityConfiguration(for: SaraEventAttributes.self) { context in
      HStack(spacing: 12) {
        Image(systemName: icon(for: context.attributes.kind))
          .font(.title2)
          .foregroundStyle(.tint)
        VStack(alignment: .leading, spacing: 2) {
          Text(context.attributes.title).font(.headline).lineLimit(1)
          Text(isExpired(context) ? "Available" : context.state.subtitle)
            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
        Spacer()
        if context.state.startEpochMs > 0 && !isExpired(context) {
          Text(timerInterval: elapsedRange(context.state.startEpochMs), countsDown: false)
            .font(.title3).monospacedDigit().frame(width: 64).multilineTextAlignment(.trailing)
        }
      }
      .padding()
      .activityBackgroundTint(Color.black.opacity(0.55))
      .activitySystemActionForegroundColor(.white)
    } dynamicIsland: { context in
      DynamicIsland {
        DynamicIslandExpandedRegion(.leading) {
          Label(context.attributes.title, systemImage: icon(for: context.attributes.kind)).lineLimit(1)
        }
        DynamicIslandExpandedRegion(.trailing) {
          if context.state.startEpochMs > 0 {
            Text(timerInterval: elapsedRange(context.state.startEpochMs), countsDown: false)
              .monospacedDigit().frame(width: 56).multilineTextAlignment(.trailing)
          }
        }
        DynamicIslandExpandedRegion(.bottom) {
          VStack(alignment: .leading, spacing: 2) {
            Text(isExpired(context) ? "Available" : context.state.subtitle)
              .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            if !context.state.detail.isEmpty && !isExpired(context) {
              Text(context.state.detail).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
            }
          }
        }
      } compactLeading: {
        Image(systemName: icon(for: context.attributes.kind))
      } compactTrailing: {
        if context.state.startEpochMs > 0 {
          Text(timerInterval: elapsedRange(context.state.startEpochMs), countsDown: false)
            .monospacedDigit().frame(width: 44)
        }
      } minimal: {
        Image(systemName: icon(for: context.attributes.kind))
      }
    }
  }

  private func icon(for kind: String) -> String {
    switch kind {
    case "workout": return "figure.run"
    case "task": return "sparkles"
    default: return "bolt.fill"
    }
  }

  private func elapsedRange(_ startMs: Double) -> ClosedRange<Date> {
    let start = Date(timeIntervalSince1970: startMs / 1000.0)
    let now = Date()
    let lower = start <= now ? start : now
    return lower...now.addingTimeInterval(60 * 60 * 24)
  }

  private func isExpired(_ context: ActivityViewContext<SaraEventAttributes>) -> Bool {
    context.isStale || context.state.validUntilEpochMs <= Date().timeIntervalSince1970 * 1000
  }
}
