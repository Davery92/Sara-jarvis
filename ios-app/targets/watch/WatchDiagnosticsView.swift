import SwiftUI
import HealthKit

/// The Phase 2 build-spike screen (plan §13 Phase 2).
///
/// It exists to answer, on a physical Watch, the questions that no amount of
/// Linux-side work can: does the target install, does HealthKit authorize,
/// does a real workout session start, does live heart rate arrive, does
/// exactly one HealthKit workout get saved, and do messages reach the phone?
///
/// It stays in the app after the product UI lands, reachable from
/// Advanced/System rather than the main flow (§15) — when a workout misbehaves
/// mid-session, "is the mirror connected and how many commands are pending" is
/// the first thing worth seeing.
struct WatchDiagnosticsView: View {
    @EnvironmentObject private var manager: WorkoutManager
    @State private var authorized: Bool?
    @State private var templateId: String = ""
    @State private var exported: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                header

                metric("Heart rate", manager.heartRate > 0 ? "\(Int(manager.heartRate)) bpm" : "—")
                metric("Active energy", manager.activeEnergy > 0 ? "\(Int(manager.activeEnergy)) kcal" : "—")
                metric("Elapsed", format(manager.elapsed))
                metric("HK session", describe(manager.sessionState))
                metric("Mirror", manager.isReachable ? "connected" : "not connected")
                metric("Pending", "\(manager.pendingCommandCount)")

                // The three stages, separately. Reading them together is what
                // tells you whether a failed start was permissions, HealthKit,
                // the link, or the backend (§5.1).
                Divider()
                metric("Health stage", manager.startState.healthKit.rawValue)
                metric("Sara stage", manager.startState.saraSession.rawValue)
                metric("Link", manager.startState.phoneLink.rawValue)
                Text(manager.startState.headline)
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                if let projection = manager.projection {
                    Divider()
                    metric("Sara session", String(projection.sessionId.prefix(8)))
                    metric("Version", "\(projection.version)")
                    metric("Exercise", projection.currentExercise?.name ?? "—")
                    metric(
                        "Sets",
                        "\(projection.progress.completedSets)/\(projection.progress.totalSets)"
                    )
                }

                if let coaching = manager.coaching {
                    Divider()
                    Text(coaching.text).font(.footnote)
                }

                if let error = manager.lastError {
                    Text(error)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }

                Divider()
                controls

                Divider()
                startLog
            }
            .padding(.horizontal, 4)
        }
        .task {
            if authorized == nil {
                authorized = await manager.requestAuthorization()
            }
        }
    }

    private var header: some View {
        HStack {
            Text("Sara Diagnostics").font(.headline)
            Spacer()
            Circle()
                .fill(authorized == true ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
                .accessibilityLabel(authorized == true ? "Health authorized" : "Health not authorized")
        }
    }

    @ViewBuilder
    private var controls: some View {
        if manager.sessionState == .running {
            Button("Log test set") {
                manager.logSet(weight: 100, reps: 8, effort: "right")
            }
            Button("Finish") {
                Task { await manager.finishWorkout() }
            }
            Button("Abandon", role: .destructive) {
                Task { await manager.abandonWorkout() }
            }
        } else {
            // Free text rather than a picker on purpose: the catalog sync that
            // feeds a real picker is Phase 4, and this screen must be usable
            // before it exists.
            TextField("Template id", text: $templateId)
            Button("Start workout") {
                Task {
                    await manager.startWorkout(
                        templateId: templateId,
                        templateKind: "strength",
                        templateName: "Diagnostic"
                    )
                }
            }
            .disabled(templateId.isEmpty || manager.isStarting)
        }
    }

    /// The persisted start-diagnostic ring (§5.4).
    ///
    /// Every failed start names its stage, the exact HealthKit error domain and
    /// code, the transport it went out on, and whether the backend ever
    /// answered. "Couldn't start" with nothing behind it is what made the
    /// 2026-07-27 failure unexplainable, and this is the record that fixes it.
    @ViewBuilder
    private var startLog: some View {
        let entries = manager.startDiagnostics
        HStack {
            Text("Start log").font(.caption.weight(.semibold))
            Spacer()
            Text("\(entries.count)").font(.caption2).foregroundStyle(.secondary)
        }

        if entries.isEmpty {
            Text("No start attempts recorded.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        } else {
            ForEach(entries.prefix(12)) { entry in
                VStack(alignment: .leading, spacing: 1) {
                    Text(entry.stage)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(entry.errorCode == nil ? Color.primary : Color.orange)
                    Text(entry.summary)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(4)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // Export writes the whole ring to the log, which is where it can be
            // pulled off the device — a Watch has nowhere useful to paste it.
            Button("Export to log") {
                exported = manager.exportDiagnostics()
                print(exported ?? "")
            }
            .font(.caption2)

            if exported != nil {
                Text("Written to the console log.")
                    .font(.system(size: 10))
                    .foregroundStyle(.green)
            }
        }
    }

    private func metric(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).font(.caption2).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.caption).monospacedDigit()
        }
    }

    private func format(_ interval: TimeInterval) -> String {
        guard interval > 0 else { return "—" }
        let total = Int(interval)
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    private func describe(_ state: HKWorkoutSessionState) -> String {
        switch state {
        case .notStarted: return "not started"
        case .running: return "running"
        case .paused: return "paused"
        case .ended: return "ended"
        case .prepared: return "prepared"
        case .stopped: return "stopped"
        @unknown default: return "unknown"
        }
    }
}
