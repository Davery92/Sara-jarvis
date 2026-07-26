import SwiftUI

/// Exercise list and jump (plan §8.5).
///
/// The phone lets David do exercises in any order and come back to one he
/// skipped because a machine was busy. That is not a phone convenience — it is
/// how the gym actually works — so the Watch has to preserve it or the wrist
/// becomes the surface you cannot finish a workout from.
///
/// The list needs the full exercise array, which the compact Watch projection
/// omits to keep per-set messages small. When it is absent this asks for it
/// rather than pretending the workout has one exercise.
struct ExerciseListView: View {
    @EnvironmentObject private var manager: WorkoutManager
    @Environment(\.dismiss) private var dismiss

    private var projection: WorkoutProjection? { manager.projection }

    var body: some View {
        List {
            if let exercises = projection?.exercises, !exercises.isEmpty {
                // One tuple parameter, taken whole. `{ index, exercise in }`
                // relies on closure tuple destructuring, which Swift dropped in
                // SE-0110 and rejects depending on how inference lands.
                ForEach(Array(exercises.enumerated()), id: \.offset) { entry in
                    Button {
                        manager.selectExercise(entry.offset)
                        dismiss()
                    } label: {
                        row(entry.element, index: entry.offset)
                    }
                }
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Loading exercises…")
                        .font(.footnote)
                    Text("Full list comes from your iPhone.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .task { manager.requestFullProjection() }
            }
        }
        .navigationTitle("Exercises")
    }

    private func row(_ exercise: WorkoutExercise, index: Int) -> some View {
        let isCurrent = index == projection?.cursor.exerciseIndex
        let completed = exercise.completedSets ?? 0
        let target = exercise.targetSets ?? 0
        // Three states, not two: done, partially done, untouched. A skipped
        // exercise with two sets in it must not read as finished.
        let isComplete = target > 0 && completed >= target
        let isPartial = completed > 0 && !isComplete

        return HStack(spacing: 6) {
            Image(systemName: isComplete ? "checkmark.circle.fill"
                  : isPartial ? "circle.lefthalf.filled" : "circle")
                .foregroundStyle(isComplete ? .green : isPartial ? .orange : .secondary)
                .font(.caption)

            VStack(alignment: .leading, spacing: 1) {
                Text(exercise.variant ?? exercise.name ?? "—")
                    .font(.caption)
                    .fontWeight(isCurrent ? .semibold : .regular)
                    .lineLimit(1)
                Text("\(completed)/\(target) sets")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if isCurrent {
                Image(systemName: "arrow.right.circle.fill")
                    .font(.caption2)
                    .foregroundStyle(.tint)
            }
        }
    }
}
