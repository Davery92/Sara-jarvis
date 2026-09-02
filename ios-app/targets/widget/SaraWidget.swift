import WidgetKit
import SwiftUI

// MARK: - Shared

private let kAppGroup = "group.cloud.avery.sara-ios"

/// Static gradient "orb" — the widget can't animate, so this is the still
/// counterpart to the in-app smoke orb (cool teal/cyan/indigo).
struct MoodOrb: View {
  var size: CGFloat
  var body: some View {
    Circle()
      .fill(
        RadialGradient(
          gradient: Gradient(colors: [
            Color(red: 0.37, green: 0.92, blue: 0.83),
            Color(red: 0.13, green: 0.83, blue: 0.93),
            Color(red: 0.51, green: 0.55, blue: 0.97),
          ]),
          center: .center,
          startRadius: 1,
          endRadius: size / 1.3
        )
      )
      .frame(width: size, height: size)
  }
}

extension View {
  /// iOS 17 requires an explicit widget container background; older OSes don't.
  @ViewBuilder
  func saraWidgetBackground() -> some View {
    if #available(iOS 17.0, *) {
      self.containerBackground(for: .widget) { Color(.systemBackground) }
    } else {
      self
    }
  }
}

// MARK: - Timeline

struct SaraEntry: TimelineEntry {
  let date: Date
  let state: String
  let headline: String
  let detail: String?
  let revision: Int64
  let updatedAt: Date
  let validUntil: Date
  let nextEventTitle: String?
  let nextEventTime: Date?
}

struct SaraProvider: TimelineProvider {
  func placeholder(in context: Context) -> SaraEntry {
    SaraEntry(date: Date(), state: "observing", headline: "Keeping an eye on things.",
              detail: nil, revision: 1, updatedAt: Date(), validUntil: Date().addingTimeInterval(600),
              nextEventTitle: "Standup", nextEventTime: Date().addingTimeInterval(3600))
  }

  func getSnapshot(in context: Context, completion: @escaping (SaraEntry) -> Void) {
    completion(readEntry())
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<SaraEntry>) -> Void) {
    let entry = readEntry()
    let expiry = max(Date().addingTimeInterval(60), entry.validUntil)
    let periodic = Date().addingTimeInterval(5 * 60)
    let next = min(expiry, periodic)
    completion(Timeline(entries: [entry], policy: .after(next)))
  }

  private func readEntry() -> SaraEntry {
    let d = UserDefaults(suiteName: kAppGroup)
    let formatter = ISO8601DateFormatter()
    let validUntil = d?.string(forKey: "presence_valid_until").flatMap(formatter.date) ?? Date.distantPast
    let updatedAt = d?.string(forKey: "presence_updated_at").flatMap(formatter.date) ?? Date.distantPast
    let expired = validUntil <= Date()
    let state = expired ? "resting" : (d?.string(forKey: "presence_state") ?? "resting")
    let headline = expired ? "Available" : (d?.string(forKey: "presence_headline") ?? "Available")
    let detailRaw = expired ? nil : d?.string(forKey: "presence_detail")
    let detail = (detailRaw?.isEmpty == false) ? detailRaw : nil
    let revision = Int64(d?.string(forKey: "presence_revision") ?? "0") ?? 0
    let evTitleRaw = d?.string(forKey: "next_event_title")
    let evTitle = (evTitleRaw?.isEmpty == false) ? evTitleRaw : nil
    var evDate: Date? = nil
    if let iso = d?.string(forKey: "next_event_time"), !iso.isEmpty {
      evDate = ISO8601DateFormatter().date(from: iso)
    }
    return SaraEntry(date: Date(), state: state, headline: headline, detail: detail,
                     revision: revision, updatedAt: updatedAt, validUntil: validUntil,
                     nextEventTitle: evTitle, nextEventTime: evDate)
  }
}

// MARK: - Views

struct SaraWidgetView: View {
  @Environment(\.widgetFamily) var family
  let entry: SaraEntry

  var body: some View {
    switch family {
    case .accessoryInline:
      Text("Sara · \(nextEventShort)")
    case .accessoryCircular:
      VStack(spacing: 0) {
        MoodOrb(size: 22)
      }
    case .accessoryRectangular:
      VStack(alignment: .leading, spacing: 2) {
        Text("Sara").font(.headline)
        if let title = entry.nextEventTitle, let time = entry.nextEventTime {
          Text("\(title) · \(time, style: .time)").font(.caption2)
        } else {
          Text(entry.headline).font(.caption2).lineLimit(2)
        }
      }
    case .systemMedium:
      mediumView
    default: // systemSmall
      smallView
    }
  }

  private var nextEventShort: String {
    if let title = entry.nextEventTitle { return title }
    return "Sara"
  }

  private var smallView: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        MoodOrb(size: 26)
        Spacer()
      }
      Text("Sara").font(.headline)
      Text(entry.state.capitalized).font(.caption).foregroundStyle(.secondary)
      Spacer(minLength: 0)
      if let title = entry.nextEventTitle, let time = entry.nextEventTime {
        Text("Next: \(title)").font(.caption2).lineLimit(1)
        Text(time, style: .time).font(.caption2).foregroundStyle(.secondary)
      } else {
        Text(entry.headline).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    .saraWidgetBackground()
  }

  private var mediumView: some View {
    HStack(alignment: .top, spacing: 12) {
      VStack(alignment: .leading, spacing: 4) {
        MoodOrb(size: 34)
        Text("Sara").font(.headline)
        Text(entry.state.capitalized).font(.caption).foregroundStyle(.secondary)
      }
      Divider()
      VStack(alignment: .leading, spacing: 6) {
        if let title = entry.nextEventTitle, let time = entry.nextEventTime {
          Text("Next up").font(.caption2).foregroundStyle(.secondary)
          Text(title).font(.subheadline).bold().lineLimit(1)
          Text(time, style: .time).font(.caption).foregroundStyle(.secondary)
        }
        Text(entry.headline).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        if let detail = entry.detail {
          Text(detail).font(.caption2).foregroundStyle(.tertiary).lineLimit(2)
        }
        Spacer(minLength: 0)
      }
      Spacer(minLength: 0)
    }
    .padding(14)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .saraWidgetBackground()
  }
}

// MARK: - Widget

struct SaraStatusWidget: Widget {
  var body: some WidgetConfiguration {
    StaticConfiguration(kind: "SaraStatusWidget", provider: SaraProvider()) { entry in
      SaraWidgetView(entry: entry)
    }
    .configurationDisplayName("Sara")
    .description("Sara's current state and your next event.")
    .supportedFamilies([
      .systemSmall, .systemMedium,
      .accessoryRectangular, .accessoryCircular, .accessoryInline,
    ])
  }
}
