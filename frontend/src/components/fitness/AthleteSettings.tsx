/**
 * Fitness → Settings: athlete profile, goal history, target history,
 * limitations.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 7. Deliberately works with every
 * LLM endpoint down — there is no model call anywhere in this view, which is
 * the point of shipping it before the Coach itself.
 *
 * Three UI rules this screen exists to honour:
 *
 * 1. **Unknown and zero look different.** An unset height renders as
 *    "Not set", never as 0 cm. A declined calculation sex renders as
 *    "Prefer not to say", not as a blank that invites re-asking.
 * 2. **Empty is not the same as cleared.** Clearing a numeric field sends an
 *    explicit `null`; leaving a field alone sends nothing at all. Submitting
 *    the whole form would make every untouched field an assertion.
 * 3. **Dates and units are explained next to the input**, not in a tooltip
 *    and not in implementation words. "kg per week (negative to lose)" is
 *    the label; `rate_basis` is not.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, Plus, X } from 'lucide-react'

import {
  useAthleteProfile,
  useAthleteToday,
  useCloseGoal,
  useCreateGoal,
  useCreateLimitation,
  useCreateTargetRevision,
  useGoals,
  useLimitations,
  usePatchProfile,
  useResolveLimitation,
  useTargetHistory,
} from '../../hooks/useFitnessCoach'
import type {
  AthleteProfilePatch,
  CalculationSex,
  GoalKind,
  Metric,
  RateBasis,
  TrainingLevel,
} from '../../types/fitnessCoach'

const SECTION = 'text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'
const LABEL = 'text-xs text-slate-400'
const FIELD =
  'w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-[15px] ' +
  'text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-400/50'
const PRIMARY =
  'px-4 py-2 rounded-lg bg-teal-500/90 hover:bg-teal-400 text-slate-950 ' +
  'text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed'
const GHOST =
  'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 ' +
  'hover:bg-white/[0.04] disabled:opacity-40'

const SEX_OPTIONS: Array<{ value: CalculationSex; label: string }> = [
  { value: 'unknown', label: 'Not given' },
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'prefer_not_to_say', label: 'Prefer not to say' },
]

const LEVEL_OPTIONS: Array<{ value: TrainingLevel; label: string }> = [
  { value: 'unknown', label: 'Not given' },
  { value: 'novice', label: 'Novice' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
]

const GOAL_KINDS: GoalKind[] = [
  'hypertrophy', 'strength', 'powerbuilding', 'gain', 'cut', 'recomp', 'maintenance',
]

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** "Not set" is a real answer and must never render as a zero. */
function renderOptional(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) return 'Not set'
  return unit ? `${value} ${unit}` : String(value)
}

function renderMetric(metric: Metric | null | undefined): string {
  if (!metric) return 'Not recorded'
  if (metric.value === null) {
    if (metric.unavailable_reason === 'unknown_unit') {
      return 'Recorded, but its unit was never saved'
    }
    return 'Not recorded'
  }
  const when = metric.observed_at
    ? new Date(metric.observed_at).toLocaleDateString()
    : null
  return `${metric.value} ${metric.unit}${when ? ` · ${when}` : ''}`
}

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-amber-300/90 border-l-2 border-amber-400/70 pl-3 py-1">
      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  )
}

function Chips({
  values,
  onChange,
  placeholder,
}: {
  values: string[]
  onChange: (next: string[]) => void
  placeholder: string
}) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const value = draft.trim()
    if (!value || values.includes(value)) {
      setDraft('')
      return
    }
    onChange([...values, value])
    setDraft('')
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span
            key={value}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/[0.06] text-xs text-slate-300"
          >
            {value}
            <button
              type="button"
              aria-label={`Remove ${value}`}
              onClick={() => onChange(values.filter((v) => v !== value))}
              className="text-slate-500 hover:text-slate-200"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        {values.length === 0 && <span className="text-xs text-slate-600">None</span>}
      </div>
      <div className="flex gap-2">
        <input
          className={FIELD}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button type="button" onClick={add} className={GHOST} aria-label="Add">
          <Plus className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

export default function AthleteSettings() {
  const profileQuery = useAthleteProfile()
  const todayQuery = useAthleteToday()
  const patchProfile = usePatchProfile()

  const profile = profileQuery.data
  const athleteToday = todayQuery.data?.athlete_local_date ?? ''

  // Only edited fields go into the patch. An untouched field is absent, not
  // echoed back — echoing would make it an assertion and could overwrite a
  // change another device made in the meantime.
  const [edits, setEdits] = useState<AthleteProfilePatch>({})
  const dirty = Object.keys(edits).length > 0

  // Clear pending edits once a save lands, so the form shows server truth.
  useEffect(() => {
    if (patchProfile.isSuccess) setEdits({})
  }, [patchProfile.isSuccess])

  const set = <K extends keyof AthleteProfilePatch>(
    key: K,
    value: AthleteProfilePatch[K],
  ) => setEdits((prev) => ({ ...prev, [key]: value }))

  /** `''` clears the field (explicit null); otherwise parse. */
  const setNumber = (key: 'height_cm' | 'training_experience_years' | 'preferred_duration_minutes') =>
    (raw: string) => {
      if (raw === '') {
        set(key, null)
        return
      }
      const parsed = Number(raw)
      if (!Number.isFinite(parsed)) return
      set(key, parsed)
    }

  const valueOf = <K extends keyof AthleteProfilePatch>(
    key: K,
    fallback: AthleteProfilePatch[K],
  ): AthleteProfilePatch[K] => (key in edits ? edits[key] : fallback)

  const save = () => {
    if (!dirty || !profile) return
    patchProfile.mutate({ ...edits, expected_version: profile.row_version })
  }

  const conflict = patchProfile.error?.kind === 'conflict'

  if (profileQuery.isLoading) {
    return <div className="p-6 text-sm text-slate-500">Loading your settings…</div>
  }
  if (profileQuery.isError) {
    return (
      <div className="p-6 max-w-[740px]">
        <ErrorNote message={profileQuery.error.message} />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-10 max-w-[740px]">
      {/* ── Profile ───────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-baseline justify-between">
          <h2 className={SECTION}>About you</h2>
          {athleteToday && (
            <span className="text-xs text-slate-500">
              Your date: {athleteToday}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500">
          Everything here is optional. Sara leaves out any calculation that needs
          something you have not given, rather than guessing a value for it.
        </p>

        {conflict && (
          <ErrorNote
            message={
              `Someone else changed your profile while this form was open` +
              (patchProfile.error?.currentVersion
                ? ` (now at version ${patchProfile.error.currentVersion})`
                : '') +
              `. Your values were not saved — reload to see the current ones.`
            }
          />
        )}
        {patchProfile.isError && !conflict && (
          <ErrorNote message={patchProfile.error.message} />
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="space-y-1">
            <span className={LABEL}>Height, in centimetres</span>
            <input
              className={FIELD}
              type="number"
              step="0.5"
              inputMode="decimal"
              placeholder="Not set"
              value={valueOf('height_cm', profile?.height_cm ?? null) ?? ''}
              onChange={(e) => setNumber('height_cm')(e.target.value)}
            />
            <span className="text-[11px] text-slate-600">
              Clear the box to remove it.
            </span>
          </label>

          <label className="space-y-1">
            <span className={LABEL}>Date of birth</span>
            <input
              className={FIELD}
              type="date"
              value={valueOf('date_of_birth', profile?.date_of_birth ?? null) ?? ''}
              onChange={(e) =>
                set('date_of_birth', e.target.value === '' ? null : e.target.value)
              }
            />
          </label>

          <label className="space-y-1">
            <span className={LABEL}>Sex, for formulas that need it</span>
            <select
              className={FIELD}
              value={valueOf('calculation_sex', profile?.calculation_sex ?? 'unknown')}
              onChange={(e) => set('calculation_sex', e.target.value as CalculationSex)}
            >
              {SEX_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <span className="text-[11px] text-slate-600">
              "Prefer not to say" is a permanent answer — Sara will not ask again,
              and skips the formulas that would need it.
            </span>
          </label>

          <label className="space-y-1">
            <span className={LABEL}>Training level</span>
            <select
              className={FIELD}
              value={valueOf('training_level', profile?.training_level ?? 'unknown')}
              onChange={(e) => set('training_level', e.target.value as TrainingLevel)}
            >
              {LEVEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="space-y-1">
            <span className={LABEL}>Years training</span>
            <input
              className={FIELD}
              type="number"
              step="0.5"
              inputMode="decimal"
              placeholder="Not set"
              value={
                valueOf(
                  'training_experience_years',
                  profile?.training_experience_years ?? null,
                ) ?? ''
              }
              onChange={(e) => setNumber('training_experience_years')(e.target.value)}
            />
          </label>

          <label className="space-y-1">
            <span className={LABEL}>Usual session length, in minutes</span>
            <input
              className={FIELD}
              type="number"
              inputMode="numeric"
              placeholder="Not set"
              value={
                valueOf(
                  'preferred_duration_minutes',
                  profile?.preferred_duration_minutes ?? null,
                ) ?? ''
              }
              onChange={(e) => setNumber('preferred_duration_minutes')(e.target.value)}
            />
          </label>

          <label className="space-y-1">
            <span className={LABEL}>Your timezone</span>
            <input
              className={FIELD}
              placeholder="America/New_York"
              value={valueOf('timezone', profile?.timezone ?? '') ?? ''}
              onChange={(e) => set('timezone', e.target.value)}
            />
            <span className="text-[11px] text-slate-600">
              Decides which calendar day a log belongs to — not your browser.
            </span>
          </label>

          <div className="space-y-1">
            <span className={LABEL}>Current weight</span>
            <div className="px-3 py-2 text-[15px] text-slate-300">
              {renderMetric(profile?.current_weight)}
            </div>
            <span className="text-[11px] text-slate-600">
              Read from your logged weigh-ins. Not something you set here.
            </span>
          </div>
        </div>

        <div className="space-y-4 pt-2">
          <div className="space-y-1">
            <span className={LABEL}>Days you can train</span>
            <div className="flex flex-wrap gap-1.5">
              {WEEKDAYS.map((day) => {
                const selected = (
                  valueOf('available_days', profile?.available_days ?? []) as string[]
                ).includes(day)
                return (
                  <button
                    key={day}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      const current = valueOf(
                        'available_days', profile?.available_days ?? [],
                      ) as string[]
                      set(
                        'available_days',
                        selected
                          ? current.filter((d) => d !== day)
                          : [...current, day],
                      )
                    }}
                    className={`px-2.5 py-1 rounded-md text-xs tap-target ${
                      selected
                        ? 'bg-teal-500/20 text-teal-200 border border-teal-400/40'
                        : 'bg-white/[0.04] text-slate-400 border border-white/10'
                    }`}
                  >
                    {day}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-1">
            <span className={LABEL}>Equipment you have</span>
            <Chips
              values={valueOf('equipment', profile?.equipment ?? []) as string[]}
              onChange={(next) => set('equipment', next)}
              placeholder="barbell, cable stack, …"
            />
          </div>

          <div className="space-y-1">
            <span className={LABEL}>Foods you avoid</span>
            <Chips
              values={
                valueOf(
                  'dietary_restrictions', profile?.dietary_restrictions ?? [],
                ) as string[]
              }
              onChange={(next) => set('dietary_restrictions', next)}
              placeholder="shellfish, …"
            />
          </div>

          <label className="flex items-start gap-3 pt-1">
            <input
              type="checkbox"
              className="mt-1"
              checked={Boolean(
                valueOf('monitoring_consent', profile?.monitoring_consent ?? false),
              )}
              onChange={(e) => set('monitoring_consent', e.target.checked)}
            />
            <span className="text-sm text-slate-300">
              Let Sara look at this data between conversations
              <span className="block text-[11px] text-slate-600">
                Off by default. Turning it off does not delete anything; it stops
                Sara reviewing it on her own.
              </span>
            </span>
          </label>
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            className={PRIMARY}
            disabled={!dirty || patchProfile.isPending}
            onClick={save}
          >
            {patchProfile.isPending ? 'Saving…' : 'Save changes'}
          </button>
          {dirty && (
            <button type="button" className={GHOST} onClick={() => setEdits({})}>
              Discard
            </button>
          )}
          {!dirty && patchProfile.isSuccess && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <Check className="w-3.5 h-3.5" /> Saved
            </span>
          )}
        </div>
      </section>

      <GoalsSection athleteToday={athleteToday} />
      <TargetsSection athleteToday={athleteToday} />
      <LimitationsSection athleteToday={athleteToday} />
    </div>
  )
}

// ── Goals ─────────────────────────────────────────────────────────────────

function GoalsSection({ athleteToday }: { athleteToday: string }) {
  const history = useGoals({ history: true })
  const createGoal = useCreateGoal()
  const closeGoal = useCloseGoal()
  const [open, setOpen] = useState(false)

  const [kind, setKind] = useState<GoalKind>('hypertrophy')
  const [isPrimary, setIsPrimary] = useState(true)
  const [rateBasis, setRateBasis] = useState<RateBasis>('none')
  const [rate, setRate] = useState('')
  const [validFrom, setValidFrom] = useState('')
  const [rationale, setRationale] = useState('')

  useEffect(() => {
    if (athleteToday && !validFrom) setValidFrom(athleteToday)
  }, [athleteToday, validFrom])

  const submit = () => {
    const parsed = rate === '' ? null : Number(rate)
    createGoal.mutate(
      {
        kind,
        is_primary: isPrimary,
        priority: isPrimary ? 1 : 2,
        rationale: rationale.trim() || null,
        rate_basis: rateBasis,
        target_rate_kg_week:
          rateBasis === 'absolute' && parsed !== null ? parsed : null,
        target_rate_percent_week:
          rateBasis === 'percent' && parsed !== null ? parsed : null,
        strength_targets: {},
        valid_from: validFrom,
      },
      {
        onSuccess: () => {
          setOpen(false)
          setRate('')
          setRationale('')
        },
      },
    )
  }

  const goals = history.data ?? []

  return (
    <section className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className={SECTION}>Goals</h2>
        <button type="button" className={GHOST} onClick={() => setOpen((v) => !v)}>
          {open ? 'Cancel' : 'Add a goal'}
        </button>
      </div>
      <p className="text-xs text-slate-500">
        A new main goal ends the one before it — the old one stays here with its
        dates, so Sara can still explain what you were training for in March.
      </p>

      {createGoal.isError && <ErrorNote message={createGoal.error.message} />}

      {open && (
        <div className="space-y-3 border-l-2 border-teal-400/40 pl-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className={LABEL}>Goal</span>
              <select
                className={FIELD}
                value={kind}
                onChange={(e) => setKind(e.target.value as GoalKind)}
              >
                {GOAL_KINDS.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Starts on</span>
              <input
                className={FIELD}
                type="date"
                value={validFrom}
                onChange={(e) => setValidFrom(e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Rate of change</span>
              <select
                className={FIELD}
                value={rateBasis}
                onChange={(e) => setRateBasis(e.target.value as RateBasis)}
              >
                <option value="none">No target rate</option>
                <option value="absolute">Kilograms per week</option>
                <option value="percent">Percent of bodyweight per week</option>
              </select>
            </label>
            {rateBasis !== 'none' && (
              <label className="space-y-1">
                <span className={LABEL}>
                  {rateBasis === 'absolute' ? 'kg per week' : '% per week'}
                </span>
                <input
                  className={FIELD}
                  type="number"
                  step="0.05"
                  inputMode="decimal"
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                />
                <span className="text-[11px] text-slate-600">
                  Negative to lose, positive to gain.
                </span>
              </label>
            )}
          </div>
          <label className="space-y-1 block">
            <span className={LABEL}>Why, in your own words</span>
            <input
              className={FIELD}
              value={rationale}
              placeholder="upper-body thickness"
              onChange={(e) => setRationale(e.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={isPrimary}
              onChange={(e) => setIsPrimary(e.target.checked)}
            />
            This is my main goal
          </label>
          <button
            type="button"
            className={PRIMARY}
            disabled={!validFrom || createGoal.isPending}
            onClick={submit}
          >
            {createGoal.isPending ? 'Saving…' : 'Save goal'}
          </button>
        </div>
      )}

      <div className="space-y-1">
        {goals.length === 0 && (
          <p className="text-sm text-slate-500">No goals recorded yet.</p>
        )}
        {goals.map((goal) => {
          const current = !goal.valid_until
          return (
            <div
              key={goal.id}
              className="flex items-baseline justify-between gap-3 py-2 px-2 -mx-2 rounded-lg hover:bg-white/[0.04]"
            >
              <div>
                <div className="text-[15px] text-slate-200">
                  {goal.kind}
                  {goal.is_primary && (
                    <span className="ml-2 text-[11px] text-teal-300/80">main</span>
                  )}
                </div>
                <div className="text-xs text-slate-500">
                  {goal.valid_from} → {goal.valid_until ?? 'now'}
                  {goal.rate_basis === 'absolute' &&
                    goal.target_rate_kg_week !== null &&
                    ` · ${goal.target_rate_kg_week} kg/week`}
                  {goal.rate_basis === 'percent' &&
                    goal.target_rate_percent_week !== null &&
                    ` · ${goal.target_rate_percent_week} %/week`}
                </div>
                {goal.rationale && (
                  <div className="text-xs text-slate-600 italic">{goal.rationale}</div>
                )}
              </div>
              {current && athleteToday && (
                <button
                  type="button"
                  className={GHOST}
                  disabled={closeGoal.isPending}
                  onClick={() =>
                    closeGoal.mutate({ goalId: goal.id, validUntil: athleteToday })
                  }
                >
                  End today
                </button>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ── Targets ───────────────────────────────────────────────────────────────

function TargetsSection({ athleteToday }: { athleteToday: string }) {
  const history = useTargetHistory()
  const createRevision = useCreateTargetRevision()
  const [open, setOpen] = useState(false)
  const [calories, setCalories] = useState('')
  const [protein, setProtein] = useState('')
  const [carbs, setCarbs] = useState('')
  const [fat, setFat] = useState('')
  const [validFrom, setValidFrom] = useState('')

  useEffect(() => {
    if (athleteToday && !validFrom) setValidFrom(athleteToday)
  }, [athleteToday, validFrom])

  const numberOrNull = (raw: string) => (raw === '' ? null : Number(raw))

  const submit = () => {
    createRevision.mutate(
      {
        scope: 'default',
        valid_from: validFrom,
        training: {
          calories: numberOrNull(calories),
          protein_g: numberOrNull(protein),
          carbs_g: numberOrNull(carbs),
          fat_g: numberOrNull(fat),
        },
      },
      { onSuccess: () => setOpen(false) },
    )
  }

  const revisions = history.data ?? []

  return (
    <section className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className={SECTION}>Nutrition targets</h2>
        <button type="button" className={GHOST} onClick={() => setOpen((v) => !v)}>
          {open ? 'Cancel' : 'Change targets'}
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Each change keeps the one before it, with the dates it applied. That is how
        Sara can tell you how you did in a week without using this week's numbers
        to judge it.
      </p>

      {createRevision.isError && <ErrorNote message={createRevision.error.message} />}

      {open && (
        <div className="space-y-3 border-l-2 border-teal-400/40 pl-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <label className="space-y-1">
              <span className={LABEL}>Calories</span>
              <input className={FIELD} type="number" inputMode="numeric"
                     value={calories} onChange={(e) => setCalories(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Protein, g</span>
              <input className={FIELD} type="number" inputMode="numeric"
                     value={protein} onChange={(e) => setProtein(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Carbs, g</span>
              <input className={FIELD} type="number" inputMode="numeric"
                     value={carbs} onChange={(e) => setCarbs(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Fat, g</span>
              <input className={FIELD} type="number" inputMode="numeric"
                     value={fat} onChange={(e) => setFat(e.target.value)} />
            </label>
          </div>
          <label className="space-y-1 block max-w-[220px]">
            <span className={LABEL}>Applies from</span>
            <input className={FIELD} type="date" value={validFrom}
                   onChange={(e) => setValidFrom(e.target.value)} />
            <span className="text-[11px] text-slate-600">
              Earlier days keep the targets they had.
            </span>
          </label>
          <button type="button" className={PRIMARY}
                  disabled={!validFrom || createRevision.isPending} onClick={submit}>
            {createRevision.isPending ? 'Saving…' : 'Save targets'}
          </button>
        </div>
      )}

      <div className="space-y-1">
        {revisions.length === 0 && (
          <p className="text-sm text-slate-500">
            No target history yet. Sara will say "not recorded" rather than guess
            for any day before your first entry.
          </p>
        )}
        {revisions.map((revision) => (
          <div
            key={revision.id}
            className="flex items-baseline justify-between gap-3 py-2 px-2 -mx-2 rounded-lg hover:bg-white/[0.04]"
          >
            <div>
              <div className="text-[15px] text-slate-200">
                {renderOptional(revision.training.calories, 'kcal')}
                {' · '}
                {renderOptional(revision.training.protein_g, 'g protein')}
              </div>
              <div className="text-xs text-slate-500">
                {revision.valid_from} → {revision.valid_until ?? 'now'}
                {' · '}
                {revision.scope === 'phase' ? 'this block' : 'default'}
                {' · v'}{revision.version}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── Limitations ───────────────────────────────────────────────────────────

function LimitationsSection({ athleteToday }: { athleteToday: string }) {
  const active = useLimitations()
  const createLimitation = useCreateLimitation()
  const resolveLimitation = useResolveLimitation()
  const [open, setOpen] = useState(false)
  const [area, setArea] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<'' | 'mild' | 'moderate' | 'severe'>('')
  const [from, setFrom] = useState('')

  useEffect(() => {
    if (athleteToday && !from) setFrom(athleteToday)
  }, [athleteToday, from])

  const submit = () => {
    createLimitation.mutate(
      {
        area: area.trim(),
        description: description.trim() || null,
        excluded_exercise_ids: [],
        modified_exercise_ids: [],
        severity_flag: severity === '' ? null : severity,
        effective_from: from,
      },
      {
        onSuccess: () => {
          setOpen(false)
          setArea('')
          setDescription('')
          setSeverity('')
        },
      },
    )
  }

  const limitations = active.data ?? []

  return (
    <section className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className={SECTION}>Things to work around</h2>
        <button type="button" className={GHOST} onClick={() => setOpen((v) => !v)}>
          {open ? 'Cancel' : 'Add one'}
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Describe what hurts and when. Sara treats this as something you told her,
        not as a diagnosis, and will not name a condition for it.
      </p>

      {createLimitation.isError && <ErrorNote message={createLimitation.error.message} />}

      {open && (
        <div className="space-y-3 border-l-2 border-teal-400/40 pl-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className={LABEL}>Where</span>
              <input className={FIELD} value={area} placeholder="right shoulder"
                     onChange={(e) => setArea(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Since</span>
              <input className={FIELD} type="date" value={from}
                     onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className="space-y-1 sm:col-span-2">
              <span className={LABEL}>What happens</span>
              <input className={FIELD} value={description}
                     placeholder="aches on overhead pressing"
                     onChange={(e) => setDescription(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>How bad</span>
              <select className={FIELD} value={severity}
                      onChange={(e) => setSeverity(e.target.value as typeof severity)}>
                <option value="">Not saying</option>
                <option value="mild">Mild</option>
                <option value="moderate">Moderate</option>
                <option value="severe">Severe</option>
              </select>
            </label>
          </div>
          <button type="button" className={PRIMARY}
                  disabled={!area.trim() || !from || createLimitation.isPending}
                  onClick={submit}>
            {createLimitation.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      <div className="space-y-1">
        {limitations.length === 0 && (
          <p className="text-sm text-slate-500">Nothing recorded.</p>
        )}
        {limitations.map((limitation) => (
          <div
            key={limitation.id}
            className="flex items-baseline justify-between gap-3 py-2 px-2 -mx-2 rounded-lg hover:bg-white/[0.04]"
          >
            <div>
              <div className="text-[15px] text-slate-200">{limitation.area}</div>
              <div className="text-xs text-slate-500">
                since {limitation.effective_from}
                {limitation.severity_flag && ` · ${limitation.severity_flag}`}
              </div>
              {limitation.description && (
                <div className="text-xs text-slate-600">{limitation.description}</div>
              )}
            </div>
            <button
              type="button"
              className={GHOST}
              disabled={resolveLimitation.isPending}
              onClick={() =>
                resolveLimitation.mutate({
                  limitationId: limitation.id,
                  effectiveUntil: athleteToday || undefined,
                })
              }
            >
              Better now
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
