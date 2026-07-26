import SwiftUI

/// Rest screen (plan §8.4).
///
/// Rest is the one part of a workout where David is looking at the Watch on
/// purpose, so this screen earns its space: a countdown big enough to read
/// across a rack, live heart rate to see recovery happening, and what is coming
/// next so the decision is already made when the timer ends.
///
/// The countdown is driven locally by `WorkoutManager` from the backend's start
/// time, not by inbound messages, so it stays right when the phone is in a bag
/// on the other side of the gym.
@available(watchOS 10.0, *)
struct RestView: View {
    @EnvironmentObject private var manager: WorkoutManager

    private var projection: WorkoutProjection? { manager.projection }
    private var exercise: WorkoutExercise? { projection?.currentExercise }

    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                Text(formatted)
                    .font(.system(size: 44, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(manager.restRemaining <= 10 ? .orange : .primary)
                    .contentTransition(.numericText())

                if manager.heartRate > 0 {
                    Label("\(Int(manager.heartRate)) bpm", systemImage: "heart.fill")
                        .font(.caption)
                        .foregroundStyle(.red)
                }

                if let next = nextTargetLine {
                    Text(next)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                if let proposal = projection?.pendingProposal {
                    // Rest is the right moment to ask — David is standing
                    // still and can actually think about it.
                    NavigationLink {
                        ProposalView(proposal: proposal)
                    } label: {
                        Label("Sara has a suggestion", systemImage: "sparkles")
                            .font(.caption2)
                    }
                }

                Button("Skip rest") { manager.stopRest() }
                    .font(.caption2)
                    .buttonStyle(.bordered)
            }
            .padding(.horizontal, 4)
        }
    }

    private var formatted: String {
        let remaining = max(0, manager.restRemaining)
        return String(format: "%d:%02d", remaining / 60, remaining % 60)
    }

    private var nextTargetLine: String? {
        guard let exercise else { return nil }
        let name = exercise.variant ?? exercise.name ?? "Next"
        guard let weight = exercise.approvedWeight else { return name }
        let reps = exercise.targetReps.map { " × \($0)" } ?? ""
        return "\(name) — \(Int(weight)) lb\(reps)"
    }
}
