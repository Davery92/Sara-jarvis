import SwiftUI

/// Completion screen (plan §8.7).
///
/// Heart rate and calories are shown as "finalizing" rather than omitted or
/// zeroed while HealthKit finishes saving. The Sara workout completes before
/// the HealthKit workout does, and rendering a confident 0 kcal for those few
/// seconds would be a lie about David's training (§4.5).
///
/// Detailed history and editing stay on the phone. This screen exists to say
/// "that's done, here's what it was" and get off the wrist.
@available(watchOS 10.0, *)
struct WorkoutSummaryView: View {
    let summary: WatchWorkoutSummary

    @EnvironmentObject private var manager: WorkoutManager

    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                Text(summary.workoutName ?? "Workout")
                    .font(.headline)
                    .multilineTextAlignment(.center)

                stat("Duration", summary.durationMinutes.map { "\($0) min" })
                stat("Sets", summary.totalSets.map(String.init))
                stat("Volume", summary.totalVolume.map { "\(Int($0)) lb" })

                if let hr = summary.heartRate {
                    stat("Avg HR", hr.avgHeartRate.map { "\($0) bpm" })
                    stat("Max HR", hr.maxHeartRate.map { "\($0) bpm" })
                    stat("Calories", hr.calories.map { "\($0) kcal" })
                } else {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("Finishing Health data…")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }

                if let pending = summary.pendingProposalCount, pending > 0 {
                    // Next-session progression is approved on the phone, out of
                    // the gym — this is a pointer, not a prompt (§6.8).
                    Text("\(pending) suggestion\(pending == 1 ? "" : "s") waiting on your iPhone")
                        .font(.caption2)
                        .foregroundStyle(.tint)
                        .multilineTextAlignment(.center)
                }

                Button("Done") { manager.dismissCompletion() }
                    .buttonStyle(.borderedProminent)
            }
            .padding(.horizontal, 4)
        }
        .onAppear { WatchHaptics.workoutComplete() }
    }

    @ViewBuilder
    private func stat(_ label: String, _ value: String?) -> some View {
        if let value {
            HStack {
                Text(label).font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Text(value).font(.caption).monospacedDigit()
            }
        }
    }
}
