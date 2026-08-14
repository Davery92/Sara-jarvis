import SwiftUI

/// Pre-start (plan §8.2).
///
/// The one screen between "I want to train" and a running workout. It shows
/// what David is about to do and gets out of the way.
///
/// The subtle rule: if Sara has an unapproved recommendation about this
/// workout, the *approved* version is what is shown and what Start uses. The
/// proposal is displayed separately, as a proposal. Presenting Sara's
/// preference as the default would make starting a workout an implicit
/// approval, which is precisely the boundary §2.4 forbids crossing.
struct PreStartView: View {
    let template: WatchCatalog.TemplateSummary

    @EnvironmentObject private var manager: WorkoutManager
    @Environment(\.dismiss) private var dismiss
    @State private var starting = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text(template.name)
                    .font(.headline)

                HStack(spacing: 6) {
                    Label("\(template.exerciseCount)", systemImage: "list.bullet")
                    if let estimate = estimatedMinutes {
                        Label("~\(estimate) min", systemImage: "clock")
                    }
                }
                .font(.caption2)
                .foregroundStyle(.secondary)

                if !template.exercises.isEmpty {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(template.exercises.prefix(4), id: \.self) { exercise in
                            Text(exercise.name ?? "—")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        if template.exercises.count > 4 {
                            Text("+\(template.exercises.count - 4) more")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    }
                }

                Button {
                    start()
                } label: {
                    if starting || manager.isStarting {
                        // Local optimism only. The Watch may say "Starting…"; it
                        // may not invent a Sara session (§4.2).
                        HStack(spacing: 6) {
                            ProgressView()
                            Text("Starting…")
                        }
                    } else {
                        Text("Start Workout")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(starting || manager.isStarting)

                startStatus
            }
            .padding(.horizontal, 4)
        }
        .onChange(of: manager.projection?.sessionId) { _, sessionId in
            // The backend accepted: hand straight over to the active screen so
            // the first set is one tap away.
            if sessionId != nil, starting {
                starting = false
                dismiss()
            }
        }
        .onChange(of: manager.isStarting) { _, isStarting in
            if !isStarting { starting = false }
        }
    }

    /// What is actually happening, and what David can do about it (§5.1, §5.2).
    ///
    /// Replaces a bare "Couldn't start the workout": the state machine knows
    /// which stage failed, so the screen names it and offers only the controls
    /// that can help. A denied permission gets instructions, not a Retry button
    /// that would do nothing.
    @ViewBuilder
    private var startStatus: some View {
        let state = manager.startState

        if state.healthKit == .failed || state.saraSession != SaraSessionPhase.none {
            VStack(alignment: .leading, spacing: 6) {
                Text(state.headline)
                    .font(.caption)
                    .foregroundStyle(state.healthKit == .failed ? .orange : .primary)

                if let detail = state.detail, detail != state.headline {
                    Text(detail)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                // The Apple workout is running and collecting real physiology
                // for a session Sara has not confirmed. Never discarded
                // silently — David chooses (§5.2).
                if state.isOrphanedHealthKit {
                    if state.saraSession == .conflict {
                        Button("Resume Existing") {
                            Task { await manager.resumeExistingWorkout() }
                        }
                        .font(.caption2)
                    }
                    if state.isRetryable {
                        Button("Retry") { manager.retryStart() }
                            .font(.caption2)
                    }
                    Button("End Apple Workout", role: .destructive) {
                        Task { await manager.discardOrphanStart() }
                    }
                    .font(.caption2)
                }
            }
        } else if let error = manager.lastError {
            Text(error)
                .font(.caption2)
                .foregroundStyle(.orange)
        }
    }

    /// Rough, and labelled as such. A wrong precise number is worse than an
    /// honest approximation.
    private var estimatedMinutes: Int? {
        let sets = template.exercises.compactMap(\.sets).reduce(0, +)
        guard sets > 0 else { return nil }
        return Int((Double(sets) * 2.5).rounded())
    }

    private func start() {
        starting = true
        Task {
            await manager.startWorkout(
                templateId: template.id,
                templateKind: "strength",
                templateName: template.name
            )
        }
    }
}
