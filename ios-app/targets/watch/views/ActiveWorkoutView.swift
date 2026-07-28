import SwiftUI

/// The wrist-raise screen (plan §8.3).
///
/// The design target is one number: after a set, when the weight and reps match
/// what was already approved, logging it must be a single deliberate tap. Every
/// other control is reachable but subordinate — a man who has just finished a
/// heavy set of squats is not going to navigate.
///
/// Weight and reps are held locally and seeded from the approved prescription.
/// They are seeded from `approvedWeight`, never `calculatedSuggestion`: Sara's
/// newer recommendation is a proposal, and pre-filling it would turn tapping
/// Log Set into silent consent (§6.8, §11.2).
struct ActiveWorkoutView: View {
    @EnvironmentObject private var manager: WorkoutManager

    @State private var weight: Double = 0
    @State private var reps: Int = 0
    @State private var seededFor: String?
    @State private var showExercises = false
    @State private var showFinishConfirm = false
    @State private var showAbandonConfirm = false

    private var projection: WorkoutProjection? { manager.projection }
    private var exercise: WorkoutExercise? { projection?.currentExercise }

    var body: some View {
        Group {
            if let summary = manager.completion {
                WorkoutSummaryView(summary: summary)
            } else if let proposal = projection?.pendingProposal {
                // An approval request outranks the set screen: it is the one
                // thing Sara is actively waiting on (§8.6).
                ProposalView(proposal: proposal)
            } else if manager.restRemaining > 0 {
                RestView()
            } else {
                setScreen
            }
        }
        // Called, not referenced: `seedIfNeeded` has a defaulted parameter, and
        // a function used as a value keeps its full `(Bool) -> Void` type
        // rather than picking up the default.
        .onAppear { seedIfNeeded() }
        .onChange(of: projection?.cursor.exerciseIndex) { _, _ in seedIfNeeded(force: true) }
        .onChange(of: projection?.cursor.setIndex) { _, _ in seedIfNeeded(force: true) }
        .sheet(isPresented: $showExercises) { ExerciseListView() }
    }

    // MARK: - Set screen

    private var setScreen: some View {
        ScrollView {
            VStack(spacing: 8) {
                header
                steppers
                logButton
                effortRow
                secondaryActions
            }
            .padding(.horizontal, 4)
        }
    }

    private var header: some View {
        VStack(spacing: 2) {
            Text(exercise?.variant ?? exercise?.name ?? "Workout")
                .font(.headline)
                .lineLimit(2)
                .multilineTextAlignment(.center)

            HStack(spacing: 8) {
                // Effective target, so an added set is immediately reachable
                // rather than reading "Set 4 of 3" (§7.2).
                Text("Set \(setNumber) of \(exercise?.targetSets ?? 0)")
                if manager.heartRate > 0 {
                    Label("\(Int(manager.heartRate))", systemImage: "heart.fill")
                        .foregroundStyle(.red)
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)

            if let target = exercise?.targetReps {
                Text("Target \(target) reps")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            if let target = exercise?.targetSets, let prescribed = exercise?.prescribedSets,
               target != prescribed {
                Text("\(prescribed) prescribed")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            if let drops = exercise?.completedDropSegments, drops > 0 {
                Text("\(drops) drop\(drops == 1 ? "" : "s") logged")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            if let previous = previousSetLine {
                Text(previous)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    /// Digital Crown drives weight — the natural gesture with a gloved or
    /// chalked hand — with plus/minus as the fallback for precision.
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
            log(effort: nil)
        } label: {
            Text("Log Set")
                .font(.body.weight(.semibold))
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
    }

    /// "Easy / Right / Hard" rather than a 1-10 RPE dial: it is what David
    /// actually thinks between sets, and a numeric scale on a wrist invites a
    /// wrong tap.
    private var effortRow: some View {
        HStack(spacing: 4) {
            ForEach(["easy", "right", "hard"], id: \.self) { effort in
                Button(effort.capitalized) { log(effort: effort) }
                    .font(.caption2)
                    .buttonStyle(.bordered)
            }
        }
    }

    private var secondaryActions: some View {
        VStack(spacing: 4) {
            Button("Exercises") { showExercises = true }
                .font(.caption2)
            Button("Skip") { manager.skipExercise() }
                .font(.caption2)
            Button("Finish") { showFinishConfirm = true }
                .font(.caption2)
            Button("Abandon", role: .destructive) { showAbandonConfirm = true }
                .font(.caption2)

            if manager.pendingCommandCount > 0 {
                Label("\(manager.pendingCommandCount) pending", systemImage: "arrow.triangle.2.circlepath")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
        .confirmationDialog("Finish workout?", isPresented: $showFinishConfirm) {
            Button("Finish") { Task { await manager.finishWorkout() } }
            Button("Keep going", role: .cancel) {}
        }
        // Abandonment is destructive and stays destructive on both surfaces
        // (§4.6) — the logged sets do not survive it.
        .confirmationDialog("Abandon workout?", isPresented: $showAbandonConfirm) {
            Button("Abandon", role: .destructive) { Task { await manager.abandonWorkout() } }
            Button("Keep going", role: .cancel) {}
        } message: {
            Text("Sets from this workout won't be saved.")
        }
    }

    // MARK: - Helpers

    private var setNumber: Int {
        (projection?.cursor.setIndex ?? 0) + 1
    }

    private var previousSetLine: String? {
        guard let last = exercise?.lastSession,
              let weights = last.weights, let reps = last.reps,
              let w = weights.last, let r = reps.last else { return nil }
        return "Last: \(Int(w)) × \(r)"
    }

    private func log(effort: String?) {
        WatchHaptics.setLogged()
        manager.logSet(weight: weight, reps: reps, effort: effort)
    }

    /// Seed the steppers once per set, from the approved prescription.
    ///
    /// Re-seeding on every projection would fight David's own adjustment
    /// mid-set; seeding on cursor movement is what makes the common path
    /// "raise wrist, tap Log Set".
    private func seedIfNeeded(force: Bool = false) {
        guard let projection else { return }
        let key = "\(projection.cursor.exerciseIndex)-\(projection.cursor.setIndex)"
        guard force || seededFor != key else { return }
        seededFor = key
        weight = exercise?.approvedWeight ?? weight
        reps = defaultReps
    }

    /// Lower bound of the target range + 1, matching what the backend fills in
    /// when a set arrives with no reps — so the wrist and the server agree.
    private var defaultReps: Int {
        guard let target = exercise?.targetReps else { return reps }
        if let dash = target.firstIndex(of: "-"), let lower = Int(target[target.startIndex..<dash]) {
            return lower + 1
        }
        return Int(target) ?? reps
    }
}
