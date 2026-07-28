import SwiftUI
import HealthKit
import WatchKit

final class SaraWatchExtensionDelegate: NSObject, WKApplicationDelegate {
    func handle(_ workoutConfiguration: HKWorkoutConfiguration) {
        Task { @MainActor in
            await WorkoutManager.shared.startWorkoutFromPhone(
                configuration: workoutConfiguration
            )
        }
    }
}

/// Sara on the wrist (plan §7.1, §8).
///
/// The target's deployment floor is watchOS 10 — `startMirroringToCompanionDevice`
/// and `sendToRemoteWorkoutSession`, which the whole cross-device design rests
/// on, are watchOS 10 APIs (§7.4). Nothing here carries an availability check
/// as a result: a runtime `#available` for a version the app cannot be
/// installed on is dead code that only forces awkward shapes around it.
///
/// `@MainActor` on the App is what lets `WorkoutManager` — which is main-actor
/// isolated so its `@Published` state can never be mutated off the main thread
/// after an `await` — be constructed in a property initialiser.
@main
@MainActor
struct SaraWatchApp: App {
    @WKApplicationDelegateAdaptor(SaraWatchExtensionDelegate.self)
    private var extensionDelegate
    @StateObject private var workoutManager = WorkoutManager.shared

    var body: some Scene {
        WindowGroup {
            WatchRootView()
                .environmentObject(workoutManager)
                .task {
                    // Re-attach before drawing anything: the workout may have
                    // outlived the UI process, and offering "Start" on top of
                    // a running session is how you end up with two.
                    await workoutManager.recoverIfNeeded()
                }
        }
    }
}

struct WatchRootView: View {
    @EnvironmentObject private var manager: WorkoutManager

    var body: some View {
        // A workout in progress takes the whole screen. Raising a wrist mid-set
        // to find a menu instead of "Log Set" is the failure this companion
        // exists to avoid (§8.3).
        if manager.projection?.status == "active" || manager.completion != nil {
            NavigationStack { ActiveWorkoutView() }
        } else {
            WatchHomeView()
        }
    }
}
