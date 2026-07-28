import Foundation
import os

/// Durable outbox for commands the Watch has issued but not yet had accepted
/// (plan §7.7).
///
/// The problem this solves: David logs a set at the far end of a gym, the phone
/// is in a bag, the link drops. The set must not be lost, and when the link
/// returns it must not be applied twice. Because every command carries a
/// `commandId` minted before the first send, replaying the queue verbatim is
/// safe — the backend replays the stored result rather than logging a second
/// set (§6.2).
///
/// Persisted to disk, not held in memory: the watchOS app can be suspended or
/// killed while the workout session keeps running in the background, and a
/// queue that dies with the UI process would silently drop David's sets.
public final class WorkoutCommandQueue {
    public struct Entry: Codable, Equatable {
        public let command: WorkoutCommand
        public var attempts: Int
        public var lastAttemptAt: Date?
        public var lastError: String?

        public init(command: WorkoutCommand) {
            self.command = command
            self.attempts = 0
            self.lastAttemptAt = nil
            self.lastError = nil
        }
    }

    private let log = Logger(subsystem: "cloud.avery.sara-ios.watch", category: "CommandQueue")
    private let fileURL: URL
    private let lock = NSLock()
    private var entries: [Entry] = []

    /// Beyond this the workout has plainly outrun the connection; the UI shows
    /// a pending badge rather than growing an unbounded backlog.
    public static let maxDepth = 200

    public init(filename: String = "workout-command-queue.json") {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent(filename)
        load()
    }

    // MARK: - Queue operations

    public var pendingCount: Int {
        lock.lock(); defer { lock.unlock() }
        return entries.count
    }

    public var pending: [Entry] {
        lock.lock(); defer { lock.unlock() }
        return entries
    }

    /// Enqueue unless this exact command is already waiting.
    ///
    /// Deduping on `commandId` matters because the retry loop and the UI can
    /// both enqueue the same command after a timeout.
    @discardableResult
    public func enqueue(_ command: WorkoutCommand) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !entries.contains(where: { $0.command.commandId == command.commandId }) else {
            return false
        }
        guard entries.count < Self.maxDepth else {
            log.error("Command queue full (\(Self.maxDepth)); dropping \(command.kind.rawValue)")
            return false
        }
        entries.append(Entry(command: command))
        persist()
        return true
    }

    /// Remove a command the backend has durably accepted (or replayed).
    public func acknowledge(commandId: String) {
        lock.lock(); defer { lock.unlock() }
        let before = entries.count
        entries.removeAll { $0.command.commandId == commandId }
        if entries.count != before { persist() }
    }

    /// Record a failed send so the UI can show "pending" and diagnostics can
    /// show why. The entry stays queued — dropping it would lose the set.
    public func recordFailure(commandId: String, error: String) {
        lock.lock(); defer { lock.unlock() }
        guard let idx = entries.firstIndex(where: { $0.command.commandId == commandId }) else { return }
        entries[idx].attempts += 1
        entries[idx].lastAttemptAt = Date()
        entries[idx].lastError = error
        persist()
    }

    /// Drop a command the backend has definitively refused.
    ///
    /// A conflict is terminal, not transient: retrying a command against a
    /// version that has already moved on will fail identically forever, and
    /// the projection the conflict carried is what the UI reconciles to.
    public func discard(commandId: String, reason: String) {
        lock.lock(); defer { lock.unlock() }
        log.notice("Discarding \(commandId, privacy: .public): \(reason, privacy: .public)")
        entries.removeAll { $0.command.commandId == commandId }
        persist()
    }

    /// Clear everything for a session that has ended. Commands for a finished
    /// workout can never usefully apply.
    public func clear(sessionId: String? = nil) {
        lock.lock(); defer { lock.unlock() }
        if let sessionId {
            entries.removeAll { $0.command.sessionId == sessionId }
        } else {
            entries.removeAll()
        }
        persist()
    }

    /// Commands to replay, oldest first — order matters because a `log_set`
    /// followed by a `select_exercise` is not the same workout as the reverse.
    public func replayBatch(limit: Int = 25) -> [WorkoutCommand] {
        lock.lock(); defer { lock.unlock() }
        return entries.prefix(limit).map(\.command)
    }

    // MARK: - Persistence

    private func persist() {
        do {
            let data = try JSONEncoder().encode(entries)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            log.error("Failed to persist command queue: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        do {
            entries = try JSONDecoder().decode([Entry].self, from: data)
            log.notice("Recovered \(self.entries.count) pending workout commands")
        } catch {
            // A queue we cannot read is worse than an empty one — a corrupt
            // file would otherwise block every future write.
            log.error("Discarding unreadable command queue: \(error.localizedDescription, privacy: .public)")
            entries = []
            try? FileManager.default.removeItem(at: fileURL)
        }
    }
}

/// What the Watch must survive its own relaunch with (§7.7).
///
/// The HealthKit workout keeps running when the watchOS UI is suspended, so on
/// relaunch the app has to re-attach to a workout already in progress rather
/// than offering to start a new one.
public struct WatchWorkoutRecoveryState: Codable, Equatable {
    public var sessionId: String?
    public var lastAcceptedVersion: Int?
    public var healthkitStartedAt: Date?
    public var healthkitActivityType: UInt?
    public var lastProjection: WorkoutProjection?
    /// A start the backend never answered. Survives relaunch so the Apple
    /// workout still running on the wrist can be reconnected to Sara with its
    /// original attempt id rather than becoming a second workout (§5.2).
    public var pendingStart: WatchPendingStart?

    public init(
        sessionId: String? = nil,
        lastAcceptedVersion: Int? = nil,
        healthkitStartedAt: Date? = nil,
        healthkitActivityType: UInt? = nil,
        lastProjection: WorkoutProjection? = nil,
        pendingStart: WatchPendingStart? = nil
    ) {
        self.sessionId = sessionId
        self.lastAcceptedVersion = lastAcceptedVersion
        self.healthkitStartedAt = healthkitStartedAt
        self.healthkitActivityType = healthkitActivityType
        self.lastProjection = lastProjection
        self.pendingStart = pendingStart
    }
}

public final class WatchWorkoutRecoveryStore {
    private let defaults: UserDefaults
    private let key = "sara.watch.workout.recovery"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func save(_ state: WatchWorkoutRecoveryState) {
        guard let data = try? JSONEncoder().encode(state) else { return }
        defaults.set(data, forKey: key)
    }

    public func load() -> WatchWorkoutRecoveryState? {
        guard let data = defaults.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(WatchWorkoutRecoveryState.self, from: data)
    }

    public func clear() {
        defaults.removeObject(forKey: key)
    }
}
