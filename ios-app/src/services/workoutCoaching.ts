import apiClient from './api';
import { fitnessService } from './fitness';
import { watchWorkout } from './watchWorkout';
import { workoutCoordinator } from './workoutCoordinator';
import {
  cancelCoaching,
  setWorkoutAudioPolicy,
  speakCoaching,
  suppressCoachingForProposal,
  addCoachingPlaybackListener,
} from '../../modules/sara-workout-native';
import { isExpired, type CoachingEvent, type WorkoutPolicy } from './workoutContracts';

/**
 * Sara's voice during a workout (plan §10.3-§10.5).
 *
 * The audio *session* work — ducking YouTube Music for one sentence and giving
 * it back — is native, because it has to work with the phone locked. What
 * lives here is the decision of what to say and when:
 *
 *  - Fetch Sara's real voice so coaching sounds like the same Sara as chat,
 *    with the on-device voice as the fallback rather than the default (§10.3).
 *  - Never speak the same event twice. Mirrored delivery plus polling means
 *    the same coaching event legitimately arrives more than once.
 *  - Never speak stale coaching. An event about the set before last is worse
 *    than silence (§10.4).
 *  - Never speak a proposal David has already answered.
 *
 * Every failure path here is silent-and-continue. Coaching that cannot be
 * spoken must never block or fail a logged set (§17).
 */

/** Small cache of fixed prompts, so countdowns don't wait on the network (§10.3). */
const PREFETCH_PHRASES = ['Rest complete.', 'Ten seconds.', "Let's go."];

class WorkoutCoachingService {
  private enabled = false;
  private spoken = new Set<string>();
  private resolvedProposals = new Set<string>();
  private audioCache = new Map<string, string>();
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private playbackUnsub: (() => void) | null = null;
  private lastVersionSeen = 0;
  /** Surfaced in the workout UI so the sentence is readable, not only audible. */
  private displayListeners = new Set<(event: CoachingEvent | null) => void>();
  private current: CoachingEvent | null = null;

  /**
   * Turn coaching on for a workout.
   *
   * `policy` decides whether anything is actually spoken — those are standing
   * approvals David granted, and Sara operating inside them is allowed while
   * widening them is not (§6.9).
   */
  async start(policy?: WorkoutPolicy): Promise<void> {
    const speaks =
      !!policy &&
      (policy.speak_routine_coaching || policy.speak_prs || policy.speak_proposals);
    this.enabled = speaks;
    setWorkoutAudioPolicy(speaks);

    if (!this.playbackUnsub) {
      this.playbackUnsub = addCoachingPlaybackListener((event) => {
        if (event.state === 'restore_failed') {
          // Music that never came back is the loudest possible bug. Worth a
          // log line even though we cannot fix it from here.
          console.warn('[WorkoutCoaching] other audio may still be ducked:', event.error);
        }
      });
    }

    if (speaks) void this.prefetchFixedPrompts();

    // Coaching arrives as backend events, deliberately decoupled from the set
    // acknowledgement (§6.7), so it is polled rather than awaited.
    if (!this.pollTimer) {
      this.pollTimer = setInterval(() => void this.poll(), 4000);
    }
  }

  stop(reason = 'workout ended'): void {
    this.enabled = false;
    cancelCoaching(reason);
    setWorkoutAudioPolicy(false);
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.playbackUnsub?.();
    this.playbackUnsub = null;
    this.spoken.clear();
    this.resolvedProposals.clear();
    this.lastVersionSeen = 0;
    this.setCurrent(null);
  }

  /** Subscribe to the sentence currently being said, for the on-screen line. */
  onDisplay(listener: (event: CoachingEvent | null) => void): () => void {
    this.displayListeners.add(listener);
    listener(this.current);
    return () => this.displayListeners.delete(listener);
  }

  /**
   * Stop speaking about a proposal once it has been answered.
   *
   * Called on approve AND reject: an approved proposal's pitch is now wrong
   * ("I recommend…" after the change already applied), and a rejected one's is
   * worse.
   */
  markProposalResolved(proposalId: string): void {
    this.resolvedProposals.add(proposalId);
    suppressCoachingForProposal(proposalId);
    if (this.current?.proposal_id === proposalId) this.setCurrent(null);
  }

  private async poll(): Promise<void> {
    try {
      const result = await fitnessService.v2Sync(this.lastVersionSeen || undefined);
      if (result.projection) {
        workoutCoordinator.applyProjection(result.projection);
        this.lastVersionSeen = Math.max(this.lastVersionSeen, result.projection.version);
      }
      for (const event of result.events ?? []) {
        await this.deliver(event);
      }
    } catch {
      // Offline. The next tick tries again; nothing is lost because events
      // stay on the backend until they expire.
    }
  }

  /** Show it, mirror it to the Watch, and speak it if allowed. */
  private async deliver(event: CoachingEvent): Promise<void> {
    if (this.spoken.has(event.event_id)) return;
    if (isExpired(event)) return;
    if (event.proposal_id && this.resolvedProposals.has(event.proposal_id)) return;

    this.spoken.add(event.event_id);
    this.setCurrent(event);

    void watchWorkout.broadcastCoaching({
      event_id: event.event_id,
      text: event.text,
      priority: event.priority,
      expires_at: event.expires_at,
      proposal_id: event.proposal_id,
    });

    if (!this.enabled || !event.speak) return;

    const audio = await this.audioFor(event.text);
    speakCoaching({
      eventId: event.event_id,
      text: event.text,
      priority: event.priority,
      expiresAt: event.expires_at,
      proposalId: event.proposal_id,
      audioBase64: audio,
    });
  }

  private setCurrent(event: CoachingEvent | null): void {
    this.current = event;
    this.displayListeners.forEach((l) => l(event));
  }

  /**
   * Sara's own voice, or null to let the device speak it.
   *
   * Returning null on any failure is the point: a TTS outage should cost the
   * timbre of the voice, not the coaching (§10.3 reliability layers).
   */
  private async audioFor(text: string): Promise<string | null> {
    const cached = this.audioCache.get(text);
    if (cached) return cached;
    try {
      const token = await apiClient.getToken();
      const response = await fetch(`${apiClient.baseURL}/api/voice-agent/speak`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ text }),
      });
      if (!response.ok) return null;

      const blob = await response.blob();
      const base64 = await new Promise<string | null>((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const result = reader.result as string;
          // Strip the `data:audio/...;base64,` prefix — native wants raw bytes.
          const comma = result.indexOf(',');
          resolve(comma >= 0 ? result.slice(comma + 1) : null);
        };
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });

      if (base64 && PREFETCH_PHRASES.includes(text)) {
        // Only the fixed phrases are worth keeping; caching every contextual
        // sentence would grow without bound across a workout.
        this.audioCache.set(text, base64);
      }
      return base64;
    } catch {
      return null;
    }
  }

  private async prefetchFixedPrompts(): Promise<void> {
    for (const phrase of PREFETCH_PHRASES) {
      if (!this.audioCache.has(phrase)) await this.audioFor(phrase);
    }
  }
}

export const workoutCoaching = new WorkoutCoachingService();
export default workoutCoaching;
