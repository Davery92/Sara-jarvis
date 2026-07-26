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

                if let error = manager.lastError {
                    Text(error)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
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
