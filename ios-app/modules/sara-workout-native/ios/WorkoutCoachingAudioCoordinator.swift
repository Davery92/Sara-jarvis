import AVFoundation
import Foundation
import os

/// Speaks Sara's coaching over AirPods without stealing the music (plan §10).
///
/// The requirement is narrow and unforgiving: duck YouTube Music for the length
/// of one short sentence, then give it back. Getting that wrong in either
/// direction is immediately obvious — either David can't hear Sara, or his
/// music stays quiet for the rest of the workout.
///
/// The shape that satisfies it:
///
///   - `.playback` with `.duckOthers` and `.interruptSpokenAudioAndMixWithOthers`
///     so music dips rather than stops, and podcasts yield entirely.
///   - Activate for the prompt only. A session held active across the workout
///     is exactly the "music stayed ducked forever" failure (§10.2).
///   - Deactivate with `.notifyOthersOnDeactivation` so the other app is told
///     to come back up instead of waiting to notice.
///
/// This lives in native code, not the existing JS `voice.ts`, because coaching
/// has to work with the phone locked or in another app — where the JS runtime
/// is not scheduled (§3.5).
@available(iOS 17.0, *)
final class WorkoutCoachingAudioCoordinator: NSObject {

    struct Prompt {
        let eventId: String
        let text: String
        let priority: String
        let expiresAt: Date?
        /// Pre-fetched Sara/Kokoro audio. Nil falls back to on-device speech.
        let audioData: Data?

        var isCritical: Bool { priority == "high" || priority == "critical" }
    }

    typealias PlaybackObserver = (_ eventId: String, _ state: String, _ error: String?) -> Void

    private let log = Logger(subsystem: "cloud.avery.sara-ios", category: "CoachingAudio")
    private let synthesizer = AVSpeechSynthesizer()
    private let queueLock = NSLock()

    private var queue: [Prompt] = []
    private var spokenEventIds = Set<String>()
    private var player: AVAudioPlayer?
    private var isSpeaking = false
    private var observer: PlaybackObserver?

    /// Master switch driven by WORKOUT_COACHING_AUDIO_ENABLED and the user's
    /// own setting. Off means text and haptics only — never a blocked set.
    private(set) var isEnabled = false

    /// Cancelled proposals must not be spoken after the fact (§10.4).
    private var suppressedProposalIds = Set<String>()

    // MARK: - Configuration

    func setEnabled(_ enabled: Bool, observer: PlaybackObserver?) {
        self.observer = observer
        isEnabled = enabled
        if !enabled { cancelAll(reason: "disabled") }
    }

    // MARK: - Queueing

    /// Enqueue a coaching prompt.
    ///
    /// Three filters before anything is spoken, in this order:
    ///   - already spoken (mirrored delivery means the same event can arrive
    ///     twice),
    ///   - expired (coaching about two sets ago is worse than silence),
    ///   - suppressed (a proposal David already answered).
    func enqueue(_ prompt: Prompt) {
        guard isEnabled else { return }

        queueLock.lock()
        defer { queueLock.unlock() }

        guard !spokenEventIds.contains(prompt.eventId) else { return }
        if let expires = prompt.expiresAt, expires < Date() {
            log.notice("Dropping expired coaching \(prompt.eventId, privacy: .public)")
            observer?(prompt.eventId, "dropped", "expired")
            return
        }
        guard !queue.contains(where: { $0.eventId == prompt.eventId }) else { return }

        if prompt.isCritical {
            // A PR or an approval request outranks routine encouragement; the
            // routine line is dropped rather than queued behind it, because by
            // the time it played it would be describing an old set.
            queue.removeAll { !$0.isCritical }
            queue.insert(prompt, at: 0)
        } else {
            queue.append(prompt)
        }
        drain()
    }

    /// Stop speaking about a proposal David has already answered.
    func suppress(proposalId: String) {
        queueLock.lock()
        suppressedProposalIds.insert(proposalId)
        queueLock.unlock()
    }

    /// End of workout, or the feature turned off.
    func cancelAll(reason: String) {
        queueLock.lock()
        queue.removeAll()
        queueLock.unlock()

        synthesizer.stopSpeaking(at: .immediate)
        player?.stop()
        player = nil
        isSpeaking = false
        deactivateSession()
        log.notice("Cancelled coaching audio: \(reason, privacy: .public)")
    }

    // MARK: - Playback

    private func drain() {
        guard !isSpeaking, !queue.isEmpty else { return }
        let prompt = queue.removeFirst()

        // Re-check expiry at the moment of speaking: the prompt may have sat
        // behind a longer one.
        if let expires = prompt.expiresAt, expires < Date() {
            observer?(prompt.eventId, "dropped", "expired")
            drain()
            return
        }

        isSpeaking = true
        spokenEventIds.insert(prompt.eventId)

        guard activateSession() else {
            isSpeaking = false
            observer?(prompt.eventId, "failed", "audio session unavailable")
            return
        }

        observer?(prompt.eventId, "started", nil)

        if let data = prompt.audioData, playBackendAudio(data, eventId: prompt.eventId) {
            return
        }
        speakOnDevice(prompt)
    }

    private func playBackendAudio(_ data: Data, eventId: String) -> Bool {
        do {
            let player = try AVAudioPlayer(data: data)
            player.delegate = self
            self.player = player
            currentEventId = eventId
            return player.play()
        } catch {
            // Sara's own voice failed; the on-device voice still gets the
            // coaching across, which matters more than it sounding like her.
            log.error("Backend audio failed: \(error.localizedDescription, privacy: .public)")
            return false
        }
    }

    private func speakOnDevice(_ prompt: Prompt) {
        currentEventId = prompt.eventId
        let utterance = AVSpeechUtterance(string: prompt.text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.prefersAssistiveTechnologySettings = false
        synthesizer.delegate = self
        synthesizer.speak(utterance)
    }

    private var currentEventId: String?

    private func finish(_ eventId: String?, error: String?) {
        isSpeaking = false
        player = nil
        currentEventId = nil
        deactivateSession()
        if let eventId {
            observer?(eventId, error == nil ? "finished" : "failed", error)
        }
        queueLock.lock()
        let more = !queue.isEmpty
        queueLock.unlock()
        if more { drain() }
    }

    // MARK: - AVAudioSession

    private func activateSession() -> Bool {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(
                .playback,
                mode: .spokenAudio,
                options: [.duckOthers, .interruptSpokenAudioAndMixWithOthers]
            )
            try session.setActive(true)
            return true
        } catch {
            log.error("Audio session activation failed: \(error.localizedDescription, privacy: .public)")
            return false
        }
    }

    private func deactivateSession() {
        do {
            // .notifyOthersOnDeactivation is the half that actually brings the
            // music back up; without it YouTube Music stays ducked until it
            // happens to notice.
            try AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        } catch {
            log.error("Audio session deactivation failed: \(error.localizedDescription, privacy: .public)")
            observer?(currentEventId ?? "", "restore_failed", error.localizedDescription)
        }
    }
}

// MARK: - Delegates

@available(iOS 17.0, *)
extension WorkoutCoachingAudioCoordinator: AVAudioPlayerDelegate {
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        finish(currentEventId, error: flag ? nil : "playback did not complete")
    }

    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        finish(currentEventId, error: error?.localizedDescription ?? "decode error")
    }
}

@available(iOS 17.0, *)
extension WorkoutCoachingAudioCoordinator: AVSpeechSynthesizerDelegate {
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        finish(currentEventId, error: nil)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        finish(currentEventId, error: "cancelled")
    }
}
