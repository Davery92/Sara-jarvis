import AsyncStorage from '@react-native-async-storage/async-storage';
import { fitnessService } from './fitness';
import {
  buildCommand,
  isNewerProjection,
  type CoachingEvent,
  type CommandResult,
  type OriginDevice,
  type WorkoutCommand,
  type WorkoutCommandKind,
  type WorkoutConflictDetail,
  type WorkoutProjection,
} from './workoutContracts';

/**
 * One place that owns "what workout is happening and what changed it"
 * (plan §9.1, §9.4).
 *
 * `WorkoutModeContext` used to be that place, but it assumed the phone was the
 * only writer: it polled every two seconds and treated whatever came back as
 * truth. With a Watch also issuing commands, three things have to be true that
 * polling alone cannot give you:
 *
 *  - A phone action and a Watch action must be the same kind of thing — same
 *    command id, same version check — so neither can silently overwrite the
 *    other (§9.4).
 *  - A command whose response was lost must be retried, not re-issued. Retry
 *    replays; re-issue double-logs.
 *  - A projection that arrives out of order must be dropped, not applied.
 *    Mirrored delivery is not ordered, and rolling the set count backwards
 *    mid-workout is worse than a moment of staleness.
 *
 * This is transport-agnostic on purpose. It talks to the backend over HTTP;
 * `watchWorkout.ts` feeds Watch-originated commands into the same methods.
 */

const PENDING_KEY = '@workout_pending_commands';
const PROJECTION_KEY = '@workout_last_projection';

/** A command awaiting a durable answer. */
interface PendingCommand {
  command: WorkoutCommand;
  attempts: number;
  lastError?: string;
}

export interface CoordinatorState {
  projection: WorkoutProjection | null;
  pendingCount: number;
  /** Last conflict, for the short reconciliation notice the UI shows (§9.4). */
  conflict: WorkoutConflictDetail | null;
  events: CoachingEvent[];
}

type Listener = (state: CoordinatorState) => void;

function conflictFrom(error: any): WorkoutConflictDetail | null {
  const detail = error?.response?.data?.detail ?? error?.detail;
  if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
    return detail as WorkoutConflictDetail;
  }
  return null;
}

class WorkoutCoordinator {
  private projection: WorkoutProjection | null = null;
  private pending: PendingCommand[] = [];
  private conflict: WorkoutConflictDetail | null = null;
  private events: CoachingEvent[] = [];
  private listeners = new Set<Listener>();
  private hydrated = false;
  private flushing = false;

  // ── Subscription ────────────────────────────────────────────────────────

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => {
      this.listeners.delete(listener);
    };
  }

  snapshot(): CoordinatorState {
    return {
      projection: this.projection,
      pendingCount: this.pending.length,
      conflict: this.conflict,
      events: this.events,
    };
  }

  private emit(): void {
    const state = this.snapshot();
    this.listeners.forEach((l) => l(state));
  }

  // ── Persistence ─────────────────────────────────────────────────────────

  /**
   * Restore the queue and last projection from disk.
   *
   * The phone can be killed mid-workout (backgrounded during a long set, then
   * evicted). Losing the queue would lose the sets it holds.
   */
  async hydrate(): Promise<void> {
    if (this.hydrated) return;
    this.hydrated = true;
    try {
      const [rawPending, rawProjection] = await Promise.all([
        AsyncStorage.getItem(PENDING_KEY),
        AsyncStorage.getItem(PROJECTION_KEY),
      ]);
      if (rawPending) this.pending = JSON.parse(rawPending);
      if (rawProjection) this.projection = JSON.parse(rawProjection);
      this.emit();
    } catch (e) {
      // An unreadable queue is worse than an empty one — it would block every
      // future write.
      console.warn('[WorkoutCoordinator] hydrate failed, starting clean:', e);
      this.pending = [];
    }
  }

  private async persist(): Promise<void> {
    try {
      await AsyncStorage.setItem(PENDING_KEY, JSON.stringify(this.pending));
      if (this.projection) {
        await AsyncStorage.setItem(PROJECTION_KEY, JSON.stringify(this.projection));
      } else {
        await AsyncStorage.removeItem(PROJECTION_KEY);
      }
    } catch (e) {
      console.warn('[WorkoutCoordinator] persist failed:', e);
    }
  }

  // ── Projection ──────────────────────────────────────────────────────────

  /** Apply a projection from any source, dropping stale ones. */
  applyProjection(incoming: WorkoutProjection | null): boolean {
    if (!incoming) {
      if (!this.projection) return false;
      this.projection = null;
      void this.persist();
      this.emit();
      return true;
    }
    if (!isNewerProjection(incoming, this.projection)) return false;
    this.projection = incoming;
    void this.persist();
    this.emit();
    return true;
  }

  get sessionId(): string | null {
    return this.projection?.session_id ?? null;
  }

  get version(): number | null {
    return this.projection?.version ?? null;
  }

  clearConflict(): void {
    if (!this.conflict) return;
    this.conflict = null;
    this.emit();
  }

  // ── Start ───────────────────────────────────────────────────────────────

  /**
   * Start a workout, or surface the conflict so the user chooses.
   *
   * `startAttemptId` is stable across retries so a start that times out
   * in-flight resumes the session it already created instead of making a
   * second one (§4.3).
   */
  async start(
    templateId: string,
    opts: {
      startAttemptId?: string;
      originDevice?: OriginDevice;
      healthkitStartedAt?: string;
      onConflict?: 'error' | 'abandon';
    } = {}
  ): Promise<{ status: string; projection: WorkoutProjection } | { conflict: WorkoutConflictDetail }> {
    try {
      const result = await fitnessService.v2Start({
        template_id: templateId,
        start_attempt_id: opts.startAttemptId,
        origin_device: opts.originDevice ?? 'phone',
        healthkit_started_at: opts.healthkitStartedAt,
        on_conflict: opts.onConflict ?? 'error',
      });
      this.applyProjection(result.projection);
      this.conflict = null;
      this.emit();
      return result;
    } catch (e: any) {
      const conflict = conflictFrom(e);
      if (conflict) {
        this.conflict = conflict;
        if (conflict.projection) this.applyProjection(conflict.projection);
        this.emit();
        return { conflict };
      }
      throw e;
    }
  }

  // ── Commands ────────────────────────────────────────────────────────────

  /**
   * Issue a command: queue it, then try to send.
   *
   * Queue-first is deliberate. If the app dies between "user tapped Log Set"
   * and "backend answered", the command survives and replays with its original
   * id — which the backend recognises and does not apply twice.
   */
  async issue(
    kind: WorkoutCommandKind,
    payload: Record<string, unknown> = {},
    originDevice: OriginDevice = 'phone'
  ): Promise<CommandResult | { conflict: WorkoutConflictDetail }> {
    const command = buildCommand(kind, {
      sessionId: this.sessionId,
      expectedVersion: this.version,
      originDevice,
      payload,
    });
    this.pending.push({ command, attempts: 0 });
    await this.persist();
    this.emit();
    return this.send(command);
  }

  /** Send (or resend) one already-queued command. */
  private async send(command: WorkoutCommand): Promise<CommandResult | { conflict: WorkoutConflictDetail }> {
    try {
      const result = await fitnessService.v2Command(command);
      this.acknowledge(command.command_id);
      if (result.projection) this.applyProjection(result.projection);
      this.conflict = null;
      this.emit();
      return result;
    } catch (e: any) {
      const conflict = conflictFrom(e);
      if (conflict) {
        // Terminal: this command can never apply against a version that has
        // already moved on. Retrying forever would just pin the pending badge.
        this.discard(command.command_id);
        this.conflict = conflict;
        if (conflict.projection) this.applyProjection(conflict.projection);
        this.emit();
        return { conflict };
      }
      // Transient (offline, timeout) — keep it queued.
      this.recordFailure(command.command_id, e?.message ?? 'network error');
      throw e;
    }
  }

  private acknowledge(commandId: string): void {
    this.pending = this.pending.filter((p) => p.command.command_id !== commandId);
    void this.persist();
  }

  private discard(commandId: string): void {
    this.pending = this.pending.filter((p) => p.command.command_id !== commandId);
    void this.persist();
  }

  private recordFailure(commandId: string, error: string): void {
    const entry = this.pending.find((p) => p.command.command_id === commandId);
    if (entry) {
      entry.attempts += 1;
      entry.lastError = error;
      void this.persist();
    }
    this.emit();
  }

  /** Replay everything unacknowledged, oldest first. Order is meaningful. */
  async flush(): Promise<void> {
    if (this.flushing || this.pending.length === 0) return;
    this.flushing = true;
    try {
      for (const entry of [...this.pending]) {
        try {
          await this.send(entry.command);
        } catch {
          // Still offline — stop rather than burning the rest of the queue on
          // the same failure.
          break;
        }
      }
    } finally {
      this.flushing = false;
    }
  }

  // ── Convenience wrappers ────────────────────────────────────────────────

  logSet(params: {
    weight?: number;
    reps?: number;
    rpe?: number;
    effort?: string;
    notes?: string;
    exerciseIndex?: number;
  }) {
    return this.issue('log_set', {
      weight: params.weight,
      reps: params.reps,
      rpe: params.rpe,
      effort: params.effort,
      notes: params.notes,
      exercise_index: params.exerciseIndex ?? this.projection?.cursor.exercise_index,
    });
  }

  /**
   * One more working set on this exercise, this workout only.
   *
   * A direct tap is explicit approval for the live session and nothing beyond
   * it: the template, the program and next week's prescription are untouched
   * (§4.3). Making it permanent is a separate question asked afterwards.
   */
  addWorkingSet(exerciseIndex?: number, count = 1) {
    return this.issue('add_set', {
      exercise_index: exerciseIndex ?? this.projection?.cursor.exercise_index,
      count,
    });
  }

  /** Give back a target set that hasn't been performed. Never deletes a log. */
  removeUnloggedSet(exerciseIndex?: number, count = 1) {
    return this.issue('remove_unlogged_set', {
      exercise_index: exerciseIndex ?? this.projection?.cursor.exercise_index,
      count,
    });
  }

  /**
   * Log one weight reduction under the working set just performed.
   *
   * Adds volume and history without consuming a prescribed set, and without
   * starting a rest timer — a drop set is one continuous effort (§6.3).
   */
  logDropSegment(params: {
    weight: number;
    reps: number;
    effort?: string;
    rpe?: number;
    notes?: string;
    parentSetId?: string;
    exerciseIndex?: number;
  }) {
    return this.issue('log_drop_segment', {
      weight: params.weight,
      reps: params.reps,
      effort: params.effort,
      rpe: params.rpe,
      notes: params.notes,
      parent_set_id: params.parentSetId,
      exercise_index: params.exerciseIndex ?? this.projection?.cursor.exercise_index,
    });
  }

  /** Correct a logged set. PRs and totals are recomputed, not patched (§6.4). */
  reviseSet(setId: string, changes: {
    weight?: number;
    reps?: number;
    rpe?: number;
    effort?: string;
    notes?: string;
    setKind?: 'working' | 'warmup' | 'drop';
  }) {
    return this.issue('revise_set', {
      set_id: setId,
      weight: changes.weight,
      reps: changes.reps,
      rpe: changes.rpe,
      effort: changes.effort,
      notes: changes.notes,
      set_kind: changes.setKind,
    });
  }

  /**
   * Strike a set from everything that counts, keeping the record of it.
   *
   * Omitting `setId` undoes the most recent set, which is what the Watch's
   * one-tap Undo means. Voiding a working set takes its drop segments with it.
   */
  voidSet(setId?: string, reason = 'user_undo') {
    return this.issue('void_set', { set_id: setId, reason });
  }

  /** Live (non-voided) sets for the current exercise, oldest first. */
  performedSetsFor(exerciseName: string | null | undefined) {
    const sets = this.projection?.performed_sets ?? [];
    if (!exerciseName) return sets.filter((s) => !s.voided);
    return sets.filter((s) => !s.voided && s.exercise === exerciseName);
  }

  selectExercise(index: number) {
    return this.issue('select_exercise', { exercise_index: index });
  }

  setVariant(index: number, variant: string | null) {
    return this.issue('set_variant', { exercise_index: index, variant });
  }

  skipExercise() {
    return this.issue('skip_exercise');
  }

  startRest(durationSeconds: number) {
    return this.issue('rest_start', { duration_seconds: durationSeconds });
  }

  stopRest() {
    return this.issue('rest_stop');
  }

  complete(healthkitWorkoutUuid?: string) {
    return this.issue('complete', healthkitWorkoutUuid
      ? { healthkit_workout_uuid: healthkitWorkoutUuid }
      : {});
  }

  abandon() {
    return this.issue('abandon');
  }

  /** Approve or reject exactly one recommendation. Nothing else moves (§11.3). */
  resolveProposal(proposalId: string, approve: boolean, originDevice: OriginDevice = 'phone') {
    return this.issue(
      approve ? 'approve_proposal' : 'reject_proposal',
      { proposal_id: proposalId },
      originDevice
    );
  }

  /** Report the Watch's HealthKit lifecycle onto the canonical session. */
  reportHealthKitState(payload: {
    state: string;
    workout_uuid?: string;
    activity_type?: string;
    started_at?: string;
    ended_at?: string;
  }) {
    return this.issue('healthkit_state', payload, 'watch');
  }

  // ── Reconciliation ──────────────────────────────────────────────────────

  /**
   * Pull the authoritative state. Used on cold start, on foreground, and as
   * the fallback when mirrored messages are not arriving (§4.4).
   */
  async sync(): Promise<CoordinatorState> {
    try {
      const result = await fitnessService.v2Sync(this.projection?.version ?? undefined);
      this.applyProjection(result.projection);
      if (result.events?.length) {
        this.events = result.events;
        this.emit();
      }
    } catch (e) {
      console.warn('[WorkoutCoordinator] sync failed:', e);
    }
    return this.snapshot();
  }

  /** Drop everything for a workout that has ended. */
  reset(): void {
    this.projection = null;
    this.pending = [];
    this.events = [];
    this.conflict = null;
    void this.persist();
    void AsyncStorage.removeItem(PROJECTION_KEY);
    this.emit();
  }

  consumeEvents(): CoachingEvent[] {
    const events = this.events;
    this.events = [];
    return events;
  }
}

export const workoutCoordinator = new WorkoutCoordinator();
export default workoutCoordinator;
