import {
  activate as activateNative,
  addLiveMetricsListener,
  addMirrorStateListener,
  addWorkoutMessageListener,
  endMirroredWorkout,
  isAvailable,
  sendWorkoutMessage,
  startWorkoutOnWatch,
  HKActivityType,
  HKLocationType,
  type MirrorStateEvent,
  type WorkoutMessageEvent,
} from '../../modules/sara-workout-native';
import { fitnessService } from './fitness';
import { workoutCoordinator } from './workoutCoordinator';
import {
  buildEnvelope,
  WORKOUT_SCHEMA_VERSION,
  type LiveMetrics,
  type WireEnvelope,
  type WorkoutCommand,
  type WorkoutProjection,
} from './workoutContracts';

/**
 * The phone's half of the Watch conversation (plan §4.2, §4.3, §7.4).
 *
 * The Watch owns HealthKit; the phone owns the network. So the Watch never
 * talks to Sara's backend directly — it mirrors a message to the phone, the
 * phone applies it through `workoutCoordinator` (the same path a phone tap
 * takes), and the resulting projection goes back. That is what makes "one
 * workout, two controllers" true rather than aspirational: there is exactly
 * one writer.
 *
 * Every inbound message is treated as untrusted input from a peer that may be
 * on a different build. Unknown kinds and unknown schema versions are logged
 * and dropped — never thrown — because the failure mode is a man mid-set with
 * a barbell (§5.3).
 */

type Diagnostic = {
  at: string;
  kind: string;
  detail?: string;
};

class WatchWorkoutBridge {
  private subscriptions: Array<() => void> = [];
  private started = false;
  private liveMetrics: LiveMetrics | null = null;
  private mirrorState: MirrorStateEvent = { mirroring: false, state: 'none' };
  private diagnostics: Diagnostic[] = [];
  private metricsListeners = new Set<(m: LiveMetrics | null) => void>();
  private mirrorListeners = new Set<(s: MirrorStateEvent) => void>();

  /**
   * Wire up native listeners. Call once, after authentication.
   *
   * Ordering matters: `activateNative()` installs the HealthKit mirror handler,
   * and any Watch-started workout that arrives before it is installed is simply
   * not seen. The native side buffers messages until JS subscribes, which is
   * why the listeners go on first.
   */
  start(): boolean {
    if (this.started) return true;
    if (!isAvailable()) {
      this.note('unavailable', 'SaraWorkoutNative not present on this build');
      return false;
    }

    this.subscriptions.push(
      addWorkoutMessageListener((event) => {
        void this.handleMessage(event);
      })
    );
    this.subscriptions.push(
      addLiveMetricsListener(({ envelope }) => {
        try {
          const parsed = JSON.parse(envelope) as WireEnvelope;
          this.liveMetrics = parsed.payload as LiveMetrics;
          this.metricsListeners.forEach((l) => l(this.liveMetrics));
        } catch {
          /* metrics are cosmetic; a bad frame is not worth surfacing */
        }
      })
    );
    this.subscriptions.push(
      addMirrorStateListener((state) => {
        this.mirrorState = state;
        this.mirrorListeners.forEach((l) => l(state));
        if (!state.mirroring) this.liveMetrics = null;
        this.note('mirror', state.state);
      })
    );

    activateNative();
    this.started = true;
    return true;
  }

  stop(): void {
    this.subscriptions.forEach((unsub) => unsub());
    this.subscriptions = [];
    this.started = false;
  }

  // ── Inbound (Watch -> phone) ────────────────────────────────────────────

  private async handleMessage(event: WorkoutMessageEvent): Promise<void> {
    if (!event.supported) {
      // The Watch is on a newer contract than this phone build. Dropping is
      // correct; guessing at the payload is how you log the wrong weight.
      this.note('schema_mismatch', `watch speaks v${event.schemaVersion}, phone v${WORKOUT_SCHEMA_VERSION}`);
      return;
    }

    let envelope: WireEnvelope;
    try {
      envelope = JSON.parse(event.envelope);
    } catch {
      this.note('undecodable', event.kind);
      return;
    }

    switch (envelope.kind) {
      case 'start_requested':
        await this.handleStartRequested(envelope);
        break;
      case 'command_requested':
        await this.handleCommandRequested(envelope);
        break;
      case 'healthkit_started':
      case 'healthkit_paused':
      case 'healthkit_resumed':
        await this.handleHealthKitState(envelope);
        break;
      case 'healthkit_finished':
        await this.handleHealthKitFinished(envelope);
        break;
      case 'watch_recovered_session':
        await this.handleWatchRecovered(envelope);
        break;
      case 'projection_requested':
        // The Watch opened its exercise list and needs the full array the
        // per-set messages leave out.
        await this.reply('projection_updated', workoutCoordinator.snapshot().projection, {}, { full: true });
        break;
      default:
        this.note('unknown_kind', String(envelope.kind));
    }
  }

  /**
   * The Watch began a real Apple workout and wants a canonical Sara session.
   *
   * The Watch has ALREADY started collecting heart rate at this point — that is
   * the right order, because a backend round trip must not cost physiology. So
   * a conflict here is not just "no": the Watch has an orphan HealthKit session
   * it needs told about, which is what `start_conflict` triggers.
   */
  private async handleStartRequested(envelope: WireEnvelope): Promise<void> {
    const templateId = envelope.payload?.template_id as string | undefined;
    if (!templateId) {
      this.note('start_rejected', 'no template_id');
      await this.reply('start_conflict', null, {
        code: 'no_template',
        message: "Couldn't tell which workout that was.",
      });
      return;
    }

    const result = await workoutCoordinator.start(templateId, {
      startAttemptId: envelope.payload?.start_attempt_id as string | undefined,
      originDevice: 'watch',
      healthkitStartedAt: envelope.payload?.healthkit_started_at as string | undefined,
      onConflict: 'error',
    });

    if ('conflict' in result) {
      this.note('start_conflict', result.conflict.code);
      await this.reply('start_conflict', result.conflict.projection ?? null, {
        code: result.conflict.code,
        message: result.conflict.message,
      });
      return;
    }

    this.note('start_accepted', result.projection.session_id);
    await this.reply('start_accepted', result.projection);
  }

  /**
   * Apply a Watch command through the exact same path as a phone tap.
   *
   * The Watch minted the `command_id`, so its retries replay rather than
   * double-apply — the coordinator passes it through untouched.
   */
  private async handleCommandRequested(envelope: WireEnvelope): Promise<void> {
    const command = envelope.payload as unknown as WorkoutCommand;
    if (!command?.command_id || !command?.kind) {
      this.note('command_malformed');
      return;
    }

    try {
      const result = await fitnessService.v2Command(command);
      if (result.projection) workoutCoordinator.applyProjection(result.projection);
      await this.reply('command_accepted', result.projection ?? null, {
        command_id: command.command_id,
        status: result.status,
        pr: result.pr ?? null,
        rest_seconds: result.rest_seconds ?? 0,
        proposal: result.proposal ?? null,
      });
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      const code = detail?.code ?? 'send_failed';
      const message = detail?.message ?? 'That action failed.';
      this.note('command_rejected', `${command.kind}: ${code}`);
      // Report the refusal AND the current projection, so the Watch reconciles
      // visibly instead of retrying a command that can never apply.
      await this.reply('command_rejected', detail?.projection ?? null, {
        command_id: command.command_id,
        code,
        message,
      });
    }
  }

  private async handleHealthKitState(envelope: WireEnvelope): Promise<void> {
    if (!workoutCoordinator.sessionId) return;
    const state = envelope.kind.replace('healthkit_', '');
    await workoutCoordinator.reportHealthKitState({
      state: state === 'started' ? 'running' : state,
      started_at: envelope.payload?.started_at as string | undefined,
    });
  }

  /**
   * The Watch finalized its HealthKit workout. Bind the exact UUID to the Sara
   * session so the summary shows this workout's heart rate, not a same-day
   * guess (§4.5, §6.4).
   */
  private async handleHealthKitFinished(envelope: WireEnvelope): Promise<void> {
    const sessionId = envelope.session_id ?? workoutCoordinator.sessionId;
    const workoutUuid = envelope.payload?.workout_uuid as string | undefined;
    if (envelope.payload?.discarded) {
      this.note('healthkit_discarded');
      return;
    }
    if (!sessionId || !workoutUuid) {
      this.note('healthkit_unlinked', 'missing session or workout uuid');
      return;
    }
    try {
      await fitnessService.v2LinkHealthKit({
        session_id: sessionId,
        healthkit_workout_uuid: workoutUuid,
        ended_at: envelope.payload?.ended_at as string | undefined,
      });
      this.note('healthkit_linked', workoutUuid);
      await this.reply('finish_confirmed', workoutCoordinator.snapshot().projection);
    } catch (e: any) {
      // The strength record is already safe; a failed link costs HR/calories
      // and falls back to the same-day heuristic.
      this.note('healthkit_link_failed', e?.message);
    }
  }

  /** The Watch app relaunched onto a workout already in progress (§7.7). */
  private async handleWatchRecovered(envelope: WireEnvelope): Promise<void> {
    const state = await workoutCoordinator.sync();
    this.note('watch_recovered', state.projection?.session_id);
    await this.reply('projection_updated', state.projection);
  }

  // ── Outbound (phone -> Watch) ───────────────────────────────────────────

  private async reply(
    kind: string,
    projection: WorkoutProjection | null,
    extra: Record<string, unknown> = {},
    opts: { full?: boolean } = {}
  ): Promise<void> {
    const envelope = buildEnvelope(kind as any, projection?.session_id ?? null, {
      ...extra,
      projection: projection ? (opts.full ? projection : this.compact(projection)) : null,
    });
    try {
      await sendWorkoutMessage(envelope);
    } catch (e: any) {
      this.note('send_failed', `${kind}: ${e?.message}`);
    }
  }

  /**
   * Trim the projection for the wrist.
   *
   * The full exercise list is the bulk of the payload and the Watch renders
   * from `current_exercise`; sending it on every set would burn the radio for
   * a screen nobody is looking at. The Watch asks for the list explicitly when
   * it opens the jump screen.
   */
  private compact(projection: WorkoutProjection): WorkoutProjection {
    const { exercises, ...rest } = projection;
    return rest as WorkoutProjection;
  }

  /** Push a projection to the Watch after a phone-originated change (§4.4). */
  async broadcast(projection: WorkoutProjection | null): Promise<void> {
    if (!this.mirrorState.mirroring) return;
    await this.reply('projection_updated', projection);
  }

  async broadcastCoaching(event: {
    event_id: string;
    text: string;
    priority: string;
    expires_at: string | null;
    proposal_id: string | null;
  }): Promise<void> {
    if (!this.mirrorState.mirroring) return;
    const envelope = buildEnvelope('coaching_event', workoutCoordinator.sessionId, event as any);
    await sendWorkoutMessage(envelope).catch(() => undefined);
  }

  // ── Phone-originated start (§4.3) ───────────────────────────────────────

  /**
   * Wake the Watch so a phone-started workout is tracked too.
   *
   * Best effort by design: the backend session already exists and the workout
   * is fully usable from the phone. A failure here means "no heart rate", not
   * "no workout", so it returns a flag for a Retry affordance rather than
   * throwing (§4.3 partial success).
   */
  async launchWatch(templateKind?: string): Promise<{ requested: boolean; error?: string }> {
    if (!isAvailable()) return { requested: false, error: 'unsupported' };
    try {
      const activityType = this.activityTypeFor(templateKind);
      const result = await startWorkoutOnWatch(activityType, HKLocationType.indoor);
      this.note('watch_launch', result.requested ? 'requested' : 'refused');
      return result;
    } catch (e: any) {
      this.note('watch_launch_failed', e?.message);
      return { requested: false, error: e?.message ?? 'unknown' };
    }
  }

  /**
   * Sara's template kinds map to Apple's activity types explicitly (§7.3):
   * logging a Tabata as strength training misattributes the whole day's HR
   * zones and ring credit.
   */
  private activityTypeFor(kind?: string): number {
    switch ((kind ?? '').toLowerCase()) {
      case 'strength':
      case 'lifting':
        return HKActivityType.traditionalStrengthTraining;
      case 'tabata':
      case 'hiit':
      case 'interval':
      case 'intervals':
        return HKActivityType.highIntensityIntervalTraining;
      case 'run':
      case 'running':
        return HKActivityType.running;
      case 'row':
      case 'rowing':
        return HKActivityType.rowing;
      case 'bike':
      case 'cycling':
        return HKActivityType.cycling;
      case 'walk':
      case 'walking':
      case 'ruck':
        return HKActivityType.walking;
      default:
        return HKActivityType.functionalStrengthTraining;
    }
  }

  async endWatchWorkout(reason: string): Promise<void> {
    await endMirroredWorkout(reason).catch(() => undefined);
  }

  /** Refresh the Watch's cached template catalog (§7.5). */
  async syncCatalog(): Promise<void> {
    if (!this.mirrorState.mirroring) return;
    try {
      const catalog = await fitnessService.v2Catalog();
      await sendWorkoutMessage(
        buildEnvelope('catalog_updated', catalog.active_projection?.session_id ?? null, catalog as any)
      );
    } catch (e: any) {
      this.note('catalog_sync_failed', e?.message);
    }
  }

  // ── Observation ─────────────────────────────────────────────────────────

  onLiveMetrics(listener: (m: LiveMetrics | null) => void): () => void {
    this.metricsListeners.add(listener);
    listener(this.liveMetrics);
    return () => this.metricsListeners.delete(listener);
  }

  onMirrorState(listener: (s: MirrorStateEvent) => void): () => void {
    this.mirrorListeners.add(listener);
    listener(this.mirrorState);
    return () => this.mirrorListeners.delete(listener);
  }

  get isWatchTracking(): boolean {
    return this.mirrorState.mirroring && this.mirrorState.state === 'running';
  }

  get currentMetrics(): LiveMetrics | null {
    return this.liveMetrics;
  }

  /** Recent transport events. Belongs under Advanced/System, not Fitness (§15). */
  get recentDiagnostics(): Diagnostic[] {
    return this.diagnostics;
  }

  private note(kind: string, detail?: string): void {
    this.diagnostics.unshift({ at: new Date().toISOString(), kind, detail });
    if (this.diagnostics.length > 50) this.diagnostics.pop();
    if (__DEV__) console.log(`[WatchWorkout] ${kind}${detail ? `: ${detail}` : ''}`);
  }
}

export const watchWorkout = new WatchWorkoutBridge();
export default watchWorkout;
