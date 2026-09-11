import Foundation
import HealthKit
import os

/// Finds and deletes the stray Apple workouts the pre-hygiene Watch app
/// authored (Watch HealthKit hygiene plan §Phase 2).
///
/// HealthKit only lets the source that authored an object delete it. These
/// workouts were authored by `cloud.avery.sara-ios.watch`, so this has to run
/// on the Watch — the iPhone app has no authorization to touch them, even
/// though it can read them.
///
/// "Stray" here means short: authored by this app and under `maxSeconds`.
/// Longer misattributed workouts (the accidental 99-minute one found in the
/// 2026-09-09 audit) are deliberately out of scope for automatic deletion —
/// a long workout might be real, and guessing wrong here is destructive.
enum WatchHealthCleanup {
    private static let log = Logger(subsystem: "cloud.avery.sara-ios.watch", category: "HealthCleanup")

    /// Workouts this app authored that are shorter than `maxSeconds`, newest
    /// first.
    static func findStrayWorkouts(
        healthStore: HKHealthStore,
        maxSeconds: TimeInterval = 600
    ) async throws -> [HKWorkout] {
        let sourcePredicate = HKQuery.predicateForObjects(from: HKSource.default())
        let durationPredicate = NSPredicate(format: "duration < %f", maxSeconds)
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [
            sourcePredicate, durationPredicate,
        ])
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: HKObjectType.workoutType(),
                predicate: predicate,
                limit: 200,
                sortDescriptors: [sort]
            ) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                continuation.resume(returning: (samples as? [HKWorkout]) ?? [])
            }
            healthStore.execute(query)
        }
    }

    /// Longer misattributed workouts, for the "review on phone" list — no
    /// delete button, since a long workout is plausibly a real one.
    static func findLongMisattributedWorkouts(
        healthStore: HKHealthStore,
        minSeconds: TimeInterval = 600
    ) async throws -> [HKWorkout] {
        let sourcePredicate = HKQuery.predicateForObjects(from: HKSource.default())
        let durationPredicate = NSPredicate(format: "duration >= %f", minSeconds)
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [
            sourcePredicate, durationPredicate,
        ])
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: HKObjectType.workoutType(),
                predicate: predicate,
                limit: 50,
                sortDescriptors: [sort]
            ) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                continuation.resume(returning: (samples as? [HKWorkout]) ?? [])
            }
            healthStore.execute(query)
        }
    }

    /// Delete every given workout. Returns how many actually deleted —
    /// `HKHealthStore.delete(_:)` succeeds per-object, so a partial failure
    /// still reports how much progress was made.
    @discardableResult
    static func delete(_ workouts: [HKWorkout], healthStore: HKHealthStore) async throws -> Int {
        var deleted = 0
        for workout in workouts {
            do {
                try await healthStore.delete(workout)
                deleted += 1
            } catch {
                log.error("Failed to delete stray workout \(workout.uuid.uuidString, privacy: .public): \(error.localizedDescription, privacy: .public)")
            }
        }
        return deleted
    }
}
