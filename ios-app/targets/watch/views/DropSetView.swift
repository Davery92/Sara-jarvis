import SwiftUI

/// Log a drop segment from the wrist (plan §7.2).
///
/// Seeded from the working set just performed, at roughly 70% — a convenience,
/// not a prescription. Sara has no say in the number unless she proposed one
/// and David approved it, and even then he can move it here.
///
/// After each segment the screen stays put and offers "Add Another Drop",
/// because that is what a drop set actually is: one continuous effort with
/// successive reductions, not a sequence of separate sets with rest between.
struct DropSetView: View {
    @EnvironmentObject private var manager: WorkoutManager
    @Environment(\.dismiss) private var dismiss

    @State private var weight: Double = 0
    @State private var reps: Int = 0
    /// A named struct rather than a tuple: `ForEach` over an enumerated tuple
    /// array is a shape Swift only sometimes destructures, and this screen is
    /// not worth debugging on a wrist.
    private struct LoggedSegment: Identifiable {
        let id = UUID()
        let index: Int
        let weight: Double
        let reps: Int
    }
    @State private var loggedSegments: [LoggedSegment] = []
    @State private var seeded = false

    private var parent: PerformedSet? { manager.activeDropParent }

    /// Named after the set the segment attaches to, not the cursor: finishing
    /// an exercise moves the cursor on, and this screen would then be titled
    /// with a lift David is not doing.
    private var exerciseName: String { parent?.exercise ?? "Drop set" }

    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                header

                if parent == nil {
                    Text("Log the working set first — a drop hangs off one.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                } else {
                    steppers
                    logButton
                    Button(loggedSegments.isEmpty ? "Cancel" : "Done") { dismiss() }
                        .font(.caption2)
                }
            }
            .padding(.horizontal, 4)
        }
        .onAppear(perform: seedIfNeeded)
    }

    private var header: some View {
        VStack(spacing: 2) {
            Text(exerciseName)
                .font(.headline)
                .lineLimit(1)
            if let parent {
                Text("Off \(Int(parent.weight ?? 0)) × \(parent.reps ?? 0)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            // Each logged segment stays on screen: on a wrist there is no other
            // way to remember what the last drop was before choosing the next.
            ForEach(loggedSegments) { segment in
                Text("Drop \(segment.index): \(Int(segment.weight)) × \(segment.reps)")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    private var steppers: some View {
        VStack(spacing: 6) {
            HStack {
                Button { weight = max(0, weight - 5) } label: { Image(systemName: "minus") }
                    .buttonStyle(.bordered)
                Text("\(Int(weight)) lb")
                    .font(.title3.weight(.semibold))
                    .monospacedDigit()
                    .frame(maxWidth: .infinity)
                    .focusable()
                    .digitalCrownRotation(
                        $weight,
                        from: 0, through: 1000, by: 5,
                        sensitivity: .low,
                        isContinuous: false,
                        isHapticFeedbackEnabled: true
                    )
                Button { weight += 5 } label: { Image(systemName: "plus") }
                    .buttonStyle(.bordered)
            }
            HStack {
                Button { reps = max(0, reps - 1) } label: { Image(systemName: "minus") }
                    .buttonStyle(.bordered)
                Text("\(reps) reps")
                    .font(.body)
                    .monospacedDigit()
                    .frame(maxWidth: .infinity)
                Button { reps += 1 } label: { Image(systemName: "plus") }
                    .buttonStyle(.bordered)
            }
        }
    }

    private var logButton: some View {
        Button {
            WatchHaptics.setLogged()
            manager.logDropSegment(weight: weight, reps: reps, parentSetId: parent?.id)
            loggedSegments.append(
                LoggedSegment(index: loggedSegments.count + 1, weight: weight, reps: reps)
            )
            // Seed the next segment from this one — the natural next question
            // is "how much lighter again", not "what weight from scratch".
            weight = max(0, (weight * 0.75 / 5).rounded() * 5)
        } label: {
            Text(loggedSegments.isEmpty ? "Log Drop" : "Add Another Drop")
                .font(.body.weight(.semibold))
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(reps <= 0)
    }

    private func seedIfNeeded() {
        guard !seeded, let parent else { return }
        seeded = true
        weight = max(0, ((parent.weight ?? 0) * 0.7 / 5).rounded() * 5)
        reps = parent.reps ?? 8
    }
}
