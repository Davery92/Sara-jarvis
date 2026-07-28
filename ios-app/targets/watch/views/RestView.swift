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
struct RestView: View {
    @EnvironmentObject private var manager: WorkoutManager
    @State private var showUndoConfirm = false

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

                setActions

                Button("Skip rest") { manager.stopRest() }
                    .font(.caption2)
                    .buttonStyle(.bordered)
            }
            .padding(.horizontal, 4)
        }
        .confirmationDialog("Undo last set?", isPresented: $showUndoConfirm) {
            Button("Undo", role: .destructive) { manager.undoLastSet() }
            Button("Keep it", role: .cancel) {}
        } message: {
            if let last = manager.lastLoggedSet {
                Text("\(Int(last.weight ?? 0)) × \(last.reps ?? 0) stops counting toward progress, volume and PRs.")
            }
        }
    }

    /// Add Drop / Add Set / Undo (§7.2).
    ///
    /// Rest is where these belong: it is the one moment David is looking at the
    /// Watch by choice, and each of them is a decision about the set he just
    /// did. Anything more elaborate — editing an arbitrary earlier set — stays
    /// on the phone; a wrist is for fast operations, not spreadsheet editing.
    @ViewBuilder
    private var setActions: some View {
        HStack(spacing: 4) {
            NavigationLink {
                DropSetView()
            } label: {
                Text("Drop")
                    .font(.caption2)
            }
            .disabled(manager.activeDropParent == nil)

            Button("+ Set") { manager.addWorkingSet(afterLastSet: true) }
                .font(.caption2)
                .buttonStyle(.bordered)

            Button("Undo") { showUndoConfirm = true }
                .font(.caption2)
                .buttonStyle(.bordered)
                .disabled(manager.lastLoggedSet == nil)
        }

        if let exercise, let target = exercise.targetSets, let prescribed = exercise.prescribedSets,
           target != prescribed {
            // The honest line: the extra set is today's, not the program's.
            Text("\(target) sets today · \(prescribed) prescribed")
                .font(.caption2)
                .foregroundStyle(.tertiary)
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
