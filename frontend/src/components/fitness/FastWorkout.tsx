/**
 * One-screen set logging, on the workout v2 protocol.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 14 / §7. The requirement is one
 * action per set: no modal per set, no navigation between exercises to log
 * one, and nothing to wait for before the next set can be entered.
 *
 * Design points that are decisions, not layout:
 *
 * - **The weight prefills from `approved_weight`, never from
 *   `calculated_suggestion`.** That distinction *is* the approval boundary:
 *   a suggestion is what Sara currently recommends, and putting it under the
 *   bar without being asked would make a recommendation into an instruction.
 *   The suggestion is shown beside the input with a one-tap "use it".
 * - **Durable success is immediate and independent of coaching prose.** The
 *   set appears as logged the moment the command is acknowledged. A model
 *   outage shows up as a missing sentence later, never as a stalled logger.
 * - **A failed send keeps the typed values and offers a retry** that resends
 *   the same command id. The entry is never silently cleared, because the
 *   athlete is holding a bar and cannot retype it.
 * - **A conflict refreshes rather than retries.** Another device moved the
 *   state, so the command was computed against a baseline that no longer
 *   exists.
 * - **Rest counts down from the server's timestamp**, so this screen and the
 *   Watch agree.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, Check, Copy, RotateCcw, Timer, Trophy, X,
} from 'lucide-react'

import { useWorkoutCommands, type LogSetInput } from '../../hooks/useWorkoutCommands'
import type { PerformedSet, ProjectionExercise } from '../../types/workoutV2'

const SECTION = 'text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'
const LABEL = 'text-xs text-slate-400'
const FIELD =
  'w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-3 text-lg ' +
  'text-slate-100 text-center tabular-nums placeholder:text-slate-600 ' +
  'focus:outline-none focus:border-teal-400/50'
const PRIMARY =
  'px-5 py-3 rounded-lg bg-teal-500/90 hover:bg-teal-400 text-slate-950 ' +
  'text-base font-medium disabled:opacity-40 disabled:cursor-not-allowed'
const GHOST =
  'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 ' +
  'hover:bg-white/[0.04] disabled:opacity-40'

function Note({ kind, children }: { kind: 'warn' | 'info'; children: React.ReactNode }) {
  const tone = kind === 'warn'
    ? 'text-amber-300/90 border-amber-400/70'
    : 'text-slate-400 border-white/15'
  return (
    <div className={`flex items-start gap-2 text-xs border-l-2 pl-3 py-1 ${tone}`}>
      {kind === 'warn' && <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />}
      <span>{children}</span>
    </div>
  )
}

function setLine(set: PerformedSet): string {
  const load = set.weight === null ? '—' : String(set.weight)
  const reps = set.reps === null ? '—' : String(set.reps)
  const effort = set.rpe === null ? '' : ` @ ${set.rpe}`
  const kind = set.set_kind === 'working' ? '' : ` (${set.set_kind})`
  return `${load} × ${reps}${effort}${kind}`
}

function previousLine(exercise: ProjectionExercise | null): string | null {
  const last = exercise?.last_session
  if (!last?.weights?.length) return null
  const weights = last.weights
  const reps = last.reps ?? []
  const pairs = weights.map((w, i) => `${w}×${reps[i] ?? '—'}`)
  const rpe = last.avg_rpe ? ` @ ~${last.avg_rpe}` : ''
  return `${pairs.join(', ')}${rpe}`
}

export default function FastWorkout({ onClose }: { onClose?: () => void }) {
  const workout = useWorkoutCommands()
  const {
    projection, isSending, unsentError, currentExerciseSets, restRemaining,
  } = workout

  const [weight, setWeight] = useState('')
  const [reps, setReps] = useState('')
  const [rir, setRir] = useState('')
  const [justLogged, setJustLogged] = useState<string | null>(null)
  const weightRef = useRef<HTMLInputElement | null>(null)

  const exercise = projection?.current_exercise ?? null
  const exerciseIndex = projection?.cursor.exercise_index ?? 0

  // Prefill from what the athlete has AGREED to lift. `calculated_suggestion`
  // is deliberately not used here — see the module comment.
  useEffect(() => {
    if (weight !== '' || !exercise) return
    if (exercise.approved_weight !== null) {
      setWeight(String(exercise.approved_weight))
    }
  }, [exercise, weight])

  useEffect(() => {
    if (reps !== '' || !exercise?.target_reps) return
    // A range like "8-10" prefills its lower bound: the athlete can always
    // type more, and prefilling the top would flatter the entry.
    const lower = exercise.target_reps.split('-')[0]?.trim()
    if (lower && /^\d+$/.test(lower)) setReps(lower)
  }, [exercise, reps])

  // Clearing on exercise change rather than carrying values across: 225 on
  // bench is not 225 on an overhead press.
  const exerciseKey = exercise?.variant || exercise?.name || ''
  const previousKey = useRef(exerciseKey)
  useEffect(() => {
    if (previousKey.current === exerciseKey) return
    previousKey.current = exerciseKey
    setWeight('')
    setReps('')
    setRir('')
  }, [exerciseKey])

  const numeric = (raw: string): number | undefined => {
    if (raw.trim() === '') return undefined
    const value = Number(raw)
    return Number.isFinite(value) ? value : undefined
  }

  const canLog = numeric(reps) !== undefined

  const submit = async () => {
    if (!canLog) return
    const parsedWeight = numeric(weight)
    const input: LogSetInput = {
      exerciseIndex,
      reps: numeric(reps),
      ...(parsedWeight !== undefined
        ? {
            // The integer for the legacy contract, and the real value beside
            // it: 227.5 must not read back as 227 to a trend calculation.
            weight: Math.round(parsedWeight),
            ...(Number.isInteger(parsedWeight)
              ? {}
              : { loadValue: parsedWeight, loadUnit: 'lb' as const }),
          }
        : {}),
      ...(numeric(rir) !== undefined ? { rir: numeric(rir) } : {}),
    }
    try {
      const result = await workout.logSet(input)
      const loggedId = (result.logged as { id?: string } | undefined)?.id ?? null
      setJustLogged(loggedId)
      // The inputs stay: the next set is usually the same weight, and
      // retyping it between sets is the friction this screen removes.
      setRir('')
      weightRef.current?.focus()
    } catch {
      // Deliberately swallowed here. The entered values stay on screen and
      // the error is rendered from `unsentError` / `workout.error` below,
      // which is the whole point — this is the moment where losing the
      // typed numbers would be worst.
    }
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Enter logs. A gym screen is operated with one thumb or one hand, and a
    // separate reach to a button per set is the friction being removed.
    if (event.key === 'Enter' && canLog && !isSending) {
      event.preventDefault()
      void submit()
    }
  }

  if (workout.isLoading) {
    return <div className="p-6 text-sm text-slate-500">Loading your workout…</div>
  }

  if (!projection) {
    return (
      <div className="p-6 space-y-3 max-w-[740px]">
        <p className="text-sm text-slate-400">No workout running.</p>
        {workout.error && <Note kind="warn">{workout.error.message}</Note>}
      </div>
    )
  }

  const prescribed = exercise?.prescribed_sets ?? null
  const target = exercise?.target_sets ?? null
  const suggestion = exercise?.calculated_suggestion ?? null
  const previous = previousLine(exercise)

  return (
    <div className="p-6 space-y-6 max-w-[740px]">
      {/* Header */}
      <div className="flex items-baseline gap-3">
        <h1 className="font-display text-xl font-semibold text-white">
          {projection.template.name}
        </h1>
        <span className="text-xs text-slate-500">
          {projection.progress.completed_sets} of {projection.progress.total_sets} sets
        </span>
        {projection.template.is_deload && (
          <span className="text-[11px] text-amber-300/80">deload</span>
        )}
        {onClose && (
          <button type="button" className={`${GHOST} ml-auto`} onClick={onClose}>
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {unsentError && (
        <div className="space-y-2">
          <Note kind="warn">
            {unsentError.message} Your entry is still here.
          </Note>
          <div className="flex gap-2">
            <button
              type="button"
              className={PRIMARY}
              disabled={isSending}
              onClick={() => void workout.retryPending()}
            >
              <RotateCcw className="w-4 h-4 inline mr-1.5" />
              {isSending ? 'Retrying…' : 'Try again'}
            </button>
            <button type="button" className={GHOST} onClick={workout.dismissPending}>
              Leave it
            </button>
          </div>
          <p className="text-[11px] text-slate-600">
            Trying again resends the same set, so it cannot be recorded twice.
          </p>
        </div>
      )}

      {workout.error?.kind === 'conflict' && (
        <Note kind="warn">
          {workout.error.message} The numbers above are the current ones.
        </Note>
      )}

      {/* ── Exercise list ─────────────────────────────────────────────── */}
      {(projection.exercises?.length ?? 0) > 0 && (
        <section className="space-y-1">
          <h2 className={SECTION}>Today</h2>
          {projection.exercises!.map((item, index) => {
            const isCurrent = index === exerciseIndex
            const done = item.completed_sets
            const want = item.target_sets ?? 0
            return (
              <button
                key={`${item.name}-${index}`}
                type="button"
                onClick={() => void workout.selectExercise(index)}
                className={`w-full text-left flex items-baseline gap-3 py-2 px-2 -mx-2 rounded-lg tap-target ${
                  isCurrent
                    ? 'bg-white/[0.06] border-l-2 border-teal-300'
                    : 'hover:bg-white/[0.04]'
                }`}
              >
                <span className="text-[15px] text-slate-200 flex-1">
                  {item.variant || item.name}
                </span>
                <span className="text-xs text-slate-500 tabular-nums">
                  {done}/{want}
                  {item.prescribed_sets !== null
                    && item.prescribed_sets !== undefined
                    && item.prescribed_sets !== want
                    && ` (${item.prescribed_sets} prescribed)`}
                </span>
                {done >= want && want > 0 && (
                  <Check className="w-3.5 h-3.5 text-teal-300/70" />
                )}
              </button>
            )
          })}
        </section>
      )}

      {/* ── Entry ─────────────────────────────────────────────────────── */}
      {exercise && (
        <section className="space-y-3">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[15px] text-white">
              {exercise.variant || exercise.name}
            </h2>
            <span className="text-xs text-slate-500">
              {exercise.completed_sets}/{target ?? '—'}
              {prescribed !== null && prescribed !== target
                && ` (${prescribed} prescribed)`}
              {exercise.target_reps && ` · ${exercise.target_reps} reps`}
              {exercise.target_rpe && ` @ RPE ${exercise.target_rpe}`}
            </span>
          </div>

          {previous && (
            <p className="text-xs text-slate-500">Last time: {previous}</p>
          )}
          {exercise.progression_note && (
            <p className="text-xs text-slate-500">{exercise.progression_note}</p>
          )}

          <div className="grid grid-cols-3 gap-3">
            <label className="space-y-1">
              <span className={LABEL}>Weight</span>
              <input
                ref={weightRef}
                aria-label="Weight"
                className={FIELD}
                type="number"
                step="0.5"
                inputMode="decimal"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
                onKeyDown={onKeyDown}
              />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Reps</span>
              <input
                aria-label="Reps"
                className={FIELD}
                type="number"
                inputMode="numeric"
                value={reps}
                onChange={(e) => setReps(e.target.value)}
                onKeyDown={onKeyDown}
              />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>RIR</span>
              <input
                aria-label="Reps in reserve"
                className={FIELD}
                type="number"
                step="0.5"
                inputMode="decimal"
                placeholder="—"
                value={rir}
                onChange={(e) => setRir(e.target.value)}
                onKeyDown={onKeyDown}
              />
            </label>
          </div>

          {suggestion !== null && String(suggestion) !== weight && (
            <p className="text-xs text-slate-500">
              Sara suggests {suggestion}
              <button
                type="button"
                className="ml-2 text-teal-300/80 hover:text-teal-200 underline"
                onClick={() => setWeight(String(suggestion))}
              >
                use it
              </button>
              <span className="block text-[11px] text-slate-600">
                A suggestion, not a target — nothing changes until you take it.
              </span>
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={PRIMARY}
              disabled={!canLog || isSending}
              onClick={() => void submit()}
            >
              {isSending ? 'Logging…' : 'Log set'}
            </button>
            <button
              type="button"
              className={GHOST}
              disabled={isSending || currentExerciseSets.every(
                (set) => set.voided || set.set_kind !== 'working',
              )}
              onClick={() => void workout.duplicateLastSet()}
            >
              <Copy className="w-3.5 h-3.5 inline mr-1.5" />
              Same again
            </button>
            <button
              type="button"
              className={GHOST}
              disabled={isSending}
              onClick={() => void workout.addSet(exerciseIndex)}
            >
              + Set
            </button>
            {restRemaining !== null ? (
              <span className="inline-flex items-center gap-1.5 text-sm text-teal-300/80 tabular-nums">
                <Timer className="w-4 h-4" />
                {Math.floor(restRemaining / 60)}:
                {String(restRemaining % 60).padStart(2, '0')}
                <button type="button" className={GHOST}
                        onClick={() => void workout.restStop()}>
                  skip
                </button>
              </span>
            ) : (
              <button
                type="button"
                className={GHOST}
                disabled={isSending}
                onClick={() => void workout.restStart(exercise.rest_seconds ?? undefined)}
              >
                <Timer className="w-3.5 h-3.5 inline mr-1.5" />
                Rest
              </button>
            )}
          </div>
        </section>
      )}

      {/* ── This exercise's sets ──────────────────────────────────────── */}
      <section className="space-y-1">
        <h2 className={SECTION}>Logged</h2>
        {currentExerciseSets.length === 0 && (
          <p className="text-sm text-slate-500">Nothing logged for this one yet.</p>
        )}
        {currentExerciseSets.map((set) => (
          <div
            key={set.id}
            className="flex items-baseline gap-3 py-1.5 px-2 -mx-2 rounded-lg hover:bg-white/[0.04]"
          >
            <span
              className={`text-[15px] tabular-nums ${
                set.voided ? 'text-slate-600 line-through' : 'text-slate-200'
              }`}
            >
              {setLine(set)}
            </span>
            {set.is_pr && !set.voided && (
              <Trophy className="w-3.5 h-3.5 text-amber-300/80" />
            )}
            {justLogged === set.id && (
              <span className="text-[11px] text-teal-300/80">saved</span>
            )}
            {set.voided ? (
              <span className="text-[11px] text-slate-600">
                {set.void_reason || 'removed'}
              </span>
            ) : (
              <button
                type="button"
                className={`${GHOST} ml-auto`}
                disabled={isSending}
                onClick={() => void workout.voidSet(set.id, 'removed on web')}
              >
                Undo
              </button>
            )}
          </div>
        ))}
      </section>

      {/* ── Finish ────────────────────────────────────────────────────── */}
      <section className="space-y-2">
        {projection.progress.completed_sets < projection.progress.total_sets && (
          <Note kind="info">
            {projection.progress.total_sets - projection.progress.completed_sets} of
            the sets this workout asked for are not logged. Finishing now records
            it as it stands — Sara will not fill them in.
          </Note>
        )}
        <button
          type="button"
          className={PRIMARY}
          disabled={isSending}
          onClick={() => void workout.finish()}
        >
          Finish workout
        </button>
      </section>
    </div>
  )
}
