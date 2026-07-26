import SwiftUI
import HealthKit

/// Sara on the wrist (plan §7.1, §8).
///
/// On the core/native branch this is deliberately a build spike (§13 Phase 2):
/// one screen that proves the target installs, HealthKit authorizes, a real
/// workout session starts, live heart rate arrives, and exactly one HealthKit
/// workout is saved. Product screens land on the UI branch on top of the same
/// `WorkoutManager` — no throwaway code, just no product surface yet.
@main
struct SaraWatchApp: App {
    @StateObject private var workoutManager = WatchRoot.makeManager()

    var body: some Scene {
        WindowGroup {
            WatchRootView()
                .environmentObject(workoutManager)
                .task {
                    // Re-attach before drawing anything: the workout may have
                    // outlived the UI process, and offering "Start" on top of
                    // a running session is how you end up with two.
                    if #available(watchOS 10.0, *) {
                        await workoutManager.recoverIfNeeded()
                    }
                }
        }
    }
}

enum WatchRoot {
    @MainActor
    static func makeManager() -> WorkoutManager {
        if #available(watchOS 10.0, *) {
            return WorkoutManager()
        }
        // The mirroring APIs this whole design rests on are watchOS 10+.
        // Older watches get the diagnostic screen and an explanation rather
        // than a crash on launch.
        fatalError("Sara Watch requires watchOS 10 or later")
    }
}

struct WatchRootView: View {
    @EnvironmentObject private var manager: WorkoutManager

    var body: some View {
        if #available(watchOS 10.0, *) {
            // A workout in progress takes the whole screen. Raising a wrist
            // mid-set to find a menu instead of "Log Set" is the failure this
            // companion exists to avoid (§8.3).
            if manager.projection?.status == "active" || manager.completion != nil {
                NavigationStack { ActiveWorkoutView() }
            } else {
                WatchHomeView()
            }
        } else {
            VStack(spacing: 8) {
                Text("Sara").font(.headline)
                Text("Needs watchOS 10 or later.")
                    .font(.caption)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
