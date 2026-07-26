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
        /// Set when this prompt is Sara asking for a decision. Once David has
        /// answered, anything still queued about it must not be spoken (§10.4).
        let proposalId: String?
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
    /// `enqueue` is called from the JS bridge thread while `finish` runs on the
    /// audio/main thread, so every touch of `queue` happens under the lock and
    /// playback is always started *outside* it — a non-recursive NSLock held
    /// across a callback that can re-enter is a deadlock waiting for a bad
    /// moment, and a bad moment here is mid-set.
    func enqueue(_ prompt: Prompt) {
        guard isEnabled else { return }

        queueLock.lock()

        guard !spokenEventIds.contains(prompt.eventId),
              !queue.contains(where: { $0.eventId == prompt.eventId }) else {
            queueLock.unlock()
            return
        }
        if let expires = prompt.expiresAt, expires < Date() {
            queueLock.unlock()
            log.notice("Dropping expired coaching \(prompt.eventId, privacy: .public)")
            observer?(prompt.eventId, "dropped", "expired")
            return
        }

        if prompt.isCritical {
            // A PR or an approval request outranks routine encouragement; the
            // routine line is dropped rather than queued behind it, because by
            // the time it played it would be describing an old set.
            queue.removeAll { !$0.isCritical }
            queue.insert(prompt, at: 0)
        } else {
            queue.append(prompt)
        }
        queueLock.unlock()

        pump()
    }

    /// Stop speaking about a proposal David has already answered.
    ///
    /// Drops anything queued for it as well as blocking future arrivals — a
    /// prompt sitting behind a longer one would otherwise still ask a question
    /// that has been answered.
    func suppress(proposalId: String) {
        queueLock.lock()
        suppressedProposalIds.insert(proposalId)
        queue.removeAll { $0.proposalId == proposalId }
        queueLock.unlock()
    }

    /// End of workout, or the feature turned off.
    func cancelAll(reason: String) {
        queueLock.lock()
        queue.removeAll()
        // Under the lock with everything else that touches it — a stuck
        // `isSpeaking` would silence coaching for the rest of the workout.
        isSpeaking = false
        queueLock.unlock()

        synthesizer.stopSpeaking(at: .immediate)
        player?.stop()
        player = nil
        deactivateSession()
        log.notice("Cancelled coaching audio: \(reason, privacy: .public)")
    }

    // MARK: - Playback

    /// Take the next speakable prompt and start it. Never called under the lock.
    private func pump() {
        var next: Prompt?

        queueLock.lock()
        while !isSpeaking, !queue.isEmpty {
            let candidate = queue.removeFirst()
            // Re-check at the moment of speaking: it may have sat behind a
            // longer prompt, or been answered while it waited.
            if let expires = candidate.expiresAt, expires < Date() {
                queueLock.unlock()
                observer?(candidate.eventId, "dropped", "expired")
                queueLock.lock()
                continue
            }
            if let proposalId = candidate.proposalId, suppressedProposalIds.contains(proposalId) {
                queueLock.unlock()
                observer?(candidate.eventId, "dropped", "answered")
                queueLock.lock()
                continue
            }
            isSpeaking = true
            spokenEventIds.insert(candidate.eventId)
            next = candidate
            break
        }
        queueLock.unlock()

        guard let prompt = next else { return }

        guard activateSession() else {
            queueLock.lock()
            isSpeaking = false
            queueLock.unlock()
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
        queueLock.lock()
        isSpeaking = false
        queueLock.unlock()

        player = nil
        currentEventId = nil
        // Deactivating between prompts rather than at the end of the workout is
        // what actually gives YouTube Music back (§10.2).
        deactivateSession()
        if let eventId {
            observer?(eventId, error == nil ? "finished" : "failed", error)
        }
        pump()
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
