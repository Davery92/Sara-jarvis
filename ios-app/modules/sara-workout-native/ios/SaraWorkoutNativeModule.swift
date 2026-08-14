import ExpoModulesCore
import Foundation
import HealthKit

/// JS bridge for the multidevice workout lifecycle and coaching audio
/// (plan §7.2).
///
/// Kept apart from `SaraNative` on purpose: that module writes widget data and
/// pokes ActivityKit — stateless calls with no lifecycle. This one owns a
/// mirrored HealthKit session and an audio session that must survive the JS
/// runtime being suspended. Folding them together would mean the widget module
/// could never be reasoned about without also reasoning about a live workout.
public class SaraWorkoutNativeModule: Module {

    private var coordinator: Any?
    private var audio: Any?

    @available(iOS 17.0, *)
    private var typedCoordinator: IPhoneWorkoutCoordinator {
        if let existing = coordinator as? IPhoneWorkoutCoordinator { return existing }
        let created = IPhoneWorkoutCoordinator()
        coordinator = created
        return created
    }

    @available(iOS 17.0, *)
    private var typedAudio: WorkoutCoachingAudioCoordinator {
        if let existing = audio as? WorkoutCoachingAudioCoordinator { return existing }
        let created = WorkoutCoachingAudioCoordinator()
        audio = created
        return created
    }

    public func definition() -> ModuleDefinition {
        Name("SaraWorkoutNative")

        Events("workoutMessage", "liveMetrics", "mirrorStateChanged", "coachingPlaybackChanged")

        OnCreate {
            guard #available(iOS 17.0, *) else { return }
            self.typedCoordinator.bootstrap()
        }

        /// Install the mirror handler.
        ///
        /// Must be called once, as early after authentication as possible: a
        /// workout started on the Watch arrives through this handler, and if
        /// nothing is installed the phone simply never learns about it (§7.2).
        Function("activate") { () -> Bool in
            guard #available(iOS 17.0, *) else { return false }
            self.typedCoordinator.activate { [weak self] event, body in
                self?.sendEvent(event.rawValue, body)
            }
            return true
        }

        Function("isSupported") { () -> Bool in
            guard #available(iOS 17.0, *) else { return false }
            return HKHealthStore.isHealthDataAvailable()
        }

        /// Ask the Watch to start the primary workout session.
        ///
        /// Resolves when the Watch app has been asked, NOT when it is tracking.
        /// The caller learns that from the `mirrorStateChanged` event — the
        /// distinction is what keeps §4.3's partial-success handling honest.
        AsyncFunction("startWorkoutOnWatch") { (activityType: Int, locationType: Int, promise: Promise) in
            guard #available(iOS 17.0, *) else {
                promise.reject("UNSUPPORTED", "Requires iOS 17 or later")
                return
            }
            self.typedCoordinator.startWatchApp(
                activityType: UInt(activityType),
                locationType: locationType
            ) { result in
                switch result {
                case .success:
                    promise.resolve(["requested": true])
                case .failure(let error):
                    promise.reject("WATCH_START_FAILED", error.localizedDescription)
                }
            }
        }

        /// Send an already-encoded envelope to the Watch.
        ///
        /// Takes a JSON string rather than a dictionary so the wire contract is
        /// built and validated in exactly one place (the TypeScript models),
        /// with Swift moving opaque bytes.
        /// `requiresDelivery` picks the transport ladder's floor: true falls
        /// through to the durable WatchConnectivity queue, false gives up when
        /// the Watch is unreachable. Projections need the former, live metrics
        /// need the latter (§5.3).
        AsyncFunction("sendWorkoutMessage") { (envelopeJSON: String, requiresDelivery: Bool, promise: Promise) in
            guard #available(iOS 17.0, *) else {
                promise.reject("UNSUPPORTED", "Requires iOS 17 or later")
                return
            }
            self.typedCoordinator.send(
                envelopeJSON: envelopeJSON,
                requiresDelivery: requiresDelivery
            ) { result in
                switch result {
                case .success: promise.resolve(true)
                case .failure(let error): promise.reject("SEND_FAILED", error.localizedDescription)
                }
            }
        }

        AsyncFunction("updateWatchApplicationContext") { (envelopeJSON: String, promise: Promise) in
            guard #available(iOS 17.0, *) else {
                promise.reject("UNSUPPORTED", "Requires iOS 17 or later")
                return
            }
            self.typedCoordinator.updateApplicationContext(envelopeJSON: envelopeJSON) { result in
                switch result {
                case .success: promise.resolve(true)
                case .failure(let error): promise.reject("CONTEXT_UPDATE_FAILED", error.localizedDescription)
                }
            }
        }

        /// Mirror state for a JS layer that just mounted or came back from the
        /// background.
        Function("getMirroredWorkoutState") { () -> [String: Any] in
            guard #available(iOS 17.0, *) else { return ["mirroring": false, "state": "unsupported"] }
            return self.typedCoordinator.snapshot()
        }

        AsyncFunction("endMirroredWorkout") { (reason: String, promise: Promise) in
            guard #available(iOS 17.0, *) else {
                promise.resolve(false)
                return
            }
            self.typedCoordinator.endMirroredWorkout(reason: reason)
            promise.resolve(true)
        }

        // MARK: - Coaching audio (§10)

        Function("setWorkoutAudioPolicy") { (enabled: Bool) -> Bool in
            guard #available(iOS 17.0, *) else { return false }
            self.typedAudio.setEnabled(enabled) { [weak self] eventId, state, error in
                self?.sendEvent("coachingPlaybackChanged", [
                    "eventId": eventId,
                    "state": state,
                    "error": error as Any,
                ])
            }
            return enabled
        }

        /// Queue one short spoken prompt.
        ///
        /// `audioBase64` carries pre-fetched Sara/Kokoro audio so coaching
        /// sounds like the same Sara as chat; when it is absent the on-device
        /// voice speaks `text` instead. Either way this returns immediately —
        /// speech never gates a set (§6.7).
        Function("speakCoaching") { (
            eventId: String,
            text: String,
            priority: String,
            expiresAtEpochMs: Double?,
            proposalId: String?,
            audioBase64: String?
        ) -> Bool in
            guard #available(iOS 17.0, *) else { return false }
            let expires = expiresAtEpochMs.map { Date(timeIntervalSince1970: $0 / 1000.0) }
            let data = audioBase64.flatMap { Data(base64Encoded: $0) }
            self.typedAudio.enqueue(.init(
                eventId: eventId,
                text: text,
                priority: priority,
                expiresAt: expires,
                // Carried so a prompt queued behind a longer one can be dropped
                // the moment David answers the question it is about (§10.4).
                proposalId: proposalId,
                audioData: data
            ))
            return true
        }

        /// Stop speaking about a proposal that has been answered.
        Function("suppressCoachingForProposal") { (proposalId: String) in
            guard #available(iOS 17.0, *) else { return }
            self.typedAudio.suppress(proposalId: proposalId)
        }

        Function("cancelCoaching") { (reason: String) in
            guard #available(iOS 17.0, *) else { return }
            self.typedAudio.cancelAll(reason: reason)
        }
    }
}
