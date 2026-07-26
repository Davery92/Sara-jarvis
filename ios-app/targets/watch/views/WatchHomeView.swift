import SwiftUI

/// Watch home (plan §8.1).
///
/// Priority order is fixed and not negotiable by content: Resume, then Today's
/// Workout, then other workouts, then a problem — and the problem only when
/// David can act on it. A Watch screen has room for about one decision, so it
/// spends it on the thing he is most likely to want.
///
/// This is not a Fitness dashboard. Nutrition, recovery, cardio and progress
/// stay on the phone; the Watch exists to start and control training (§8.1).
struct WatchHomeView: View {
    @EnvironmentObject private var manager: WorkoutManager
    @State private var showDiagnostics = false

    private var catalog: WatchCatalog? { manager.catalog }

    var body: some View {
        NavigationStack {
            List {
                if let projection = manager.projection, projection.status == "active" {
                    resumeSection(projection)
                }

                if let today = catalog?.todayTemplate {
                    Section("Today") {
                        NavigationLink {
                            PreStartView(template: today)
                        } label: {
                            TemplateRow(template: today, emphasised: true)
                        }
                    }
                }

                if let others = catalog?.others, !others.isEmpty {
                    Section("Other workouts") {
                        ForEach(others) { template in
                            NavigationLink {
                                PreStartView(template: template)
                            } label: {
                                TemplateRow(template: template, emphasised: false)
                            }
                        }
                    }
                }

                if catalog == nil {
                    // Never a dead end: say what is missing and what fixes it.
                    Section {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("No workouts yet")
                                .font(.footnote.weight(.semibold))
                            Text("Open Sara on your iPhone to sync your plan.")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                problemSection

                Section {
                    Button("Diagnostics") { showDiagnostics = true }
                        .font(.caption2)
                }
            }
            .navigationTitle("Sara")
            .navigationDestination(isPresented: $showDiagnostics) {
                WatchDiagnosticsView()
            }
        }
    }

    @ViewBuilder
    private func resumeSection(_ projection: WorkoutProjection) -> some View {
        Section {
            NavigationLink {
                ActiveWorkoutView()
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Resume")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.tint)
                    Text(projection.template.name)
                        .font(.caption)
                    Text("\(projection.progress.completedSets)/\(projection.progress.totalSets) sets")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    /// Only surfaced when it is actionable (§8.1) — "not connected" during a
    /// perfectly working offline set is noise, and noise trains David to ignore
    /// the one message that matters.
    @ViewBuilder
    private var problemSection: some View {
        if manager.pendingCommandCount > 0 {
            Section {
                Label("\(manager.pendingCommandCount) waiting to sync", systemImage: "arrow.triangle.2.circlepath")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
        if let error = manager.lastError {
            Section {
                Text(error)
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
    }
}

private struct TemplateRow: View {
    let template: WatchCatalog.TemplateSummary
    let emphasised: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(template.name)
                .font(emphasised ? .body.weight(.semibold) : .footnote)
            Text("\(template.exerciseCount) exercises")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}
