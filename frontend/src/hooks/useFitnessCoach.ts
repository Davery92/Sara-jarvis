/**
 * TanStack Query hooks for the Fitness Coach.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 7 / §7.
 *
 * Every key is scoped by the authenticated user id. That is not decoration:
 * Query caches live in memory across an account change, and a key of
 * `['fitness','profile']` would hand the next person who signs in the
 * previous one's height, goals and targets straight out of the cache. The
 * user id in the key makes that structurally impossible, and
 * `useClearFitnessCache` removes the old entries on logout so they are not
 * sitting in memory either.
 *
 * Invalidation is deliberately wider than "the thing I just wrote". A target
 * revision changes what the legacy `/api/fitness/goals` and phase endpoints
 * return — the old dashboard reads those — so accepting an edit has to
 * invalidate them too, or the two surfaces disagree until a reload.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query'
import { useCallback } from 'react'

import { fitnessCoachApi, FitnessCoachError } from '../api/fitnessCoach'
import { useAuthStore } from '../stores/authStore'
import type {
  AthleteGoal,
  CheckIn,
  CheckInPatch,
  Measurement,
  MeasurementInput,
  MeasurementPeriod,
  MeasurementPeriodInput,
  MeasurementType,
  MeasurementTypeInput,
  AthleteGoalInput,
  AthleteLimitation,
  AthleteLimitationInput,
  AthleteProfile,
  AthleteProfilePatch,
  ResolvedTargets,
  TargetRevision,
  TargetRevisionInput,
  TargetScope,
} from '../types/fitnessCoach'

/** Query keys, all scoped to one athlete. */
export const fitnessKeys = {
  all: (userId: string) => ['fitness-coach', userId] as const,
  profile: (userId: string) => ['fitness-coach', userId, 'profile'] as const,
  today: (userId: string) => ['fitness-coach', userId, 'today'] as const,
  goals: (userId: string, onDate?: string, history?: boolean) =>
    ['fitness-coach', userId, 'goals', onDate ?? 'today', history ?? false] as const,
  limitations: (userId: string, onDate?: string, history?: boolean) =>
    ['fitness-coach', userId, 'limitations', onDate ?? 'today', history ?? false] as const,
  targets: (userId: string, onDate?: string, dayType?: string) =>
    ['fitness-coach', userId, 'targets', onDate ?? 'today', dayType ?? 'auto'] as const,
  targetHistory: (userId: string, scope?: TargetScope, phaseId?: string) =>
    ['fitness-coach', userId, 'target-history', scope ?? 'all', phaseId ?? 'all'] as const,
}

/**
 * Legacy keys that a Coach write can invalidate.
 *
 * The old dashboard, nutrition view and plan view read `/api/fitness/goals`
 * and the phase endpoints directly. A target revision updates those rows in
 * the same transaction, so their cached copies are stale the moment a
 * revision lands.
 */
const LEGACY_FITNESS_KEYS = [
  ['fitness-goals'],
  ['fitness-dashboard'],
  ['fitness-phases'],
  ['fitness-today'],
] as const

function useAthleteId(): string | null {
  return useAuthStore((state) => state.user?.id ?? null)
}

/** `false` when nobody is signed in, so no query fires without an owner. */
function enabledFor(userId: string | null): boolean {
  return typeof userId === 'string' && userId.length > 0
}

// ── Reads ─────────────────────────────────────────────────────────────────

export function useAthleteProfile(): UseQueryResult<AthleteProfile, FitnessCoachError> {
  const userId = useAthleteId()
  return useQuery({
    queryKey: fitnessKeys.profile(userId ?? 'anonymous'),
    queryFn: () => fitnessCoachApi.getProfile(),
    enabled: enabledFor(userId),
    // The profile is stable data a person edits deliberately; re-fetching it
    // on every window focus is noise.
    staleTime: 60_000,
    retry: (failureCount, error) =>
      error.kind === 'network' && failureCount < 2,
  })
}

/**
 * The athlete's own calendar date.
 *
 * Used as the default for every date input. The browser's local date is not
 * authoritative: a travelling athlete's device and their configured timezone
 * disagree, and the server decides which day a check-in belongs to.
 */
export function useAthleteToday(): UseQueryResult<
  { athlete_local_date: string; timezone: string },
  FitnessCoachError
> {
  const userId = useAthleteId()
  return useQuery({
    queryKey: fitnessKeys.today(userId ?? 'anonymous'),
    queryFn: () => fitnessCoachApi.getToday(),
    enabled: enabledFor(userId),
    staleTime: 5 * 60_000,
  })
}

export function useGoals(opts?: { onDate?: string; history?: boolean }) {
  const userId = useAthleteId()
  return useQuery<AthleteGoal[], FitnessCoachError>({
    queryKey: fitnessKeys.goals(userId ?? 'anonymous', opts?.onDate, opts?.history),
    queryFn: () => fitnessCoachApi.listGoals(opts),
    enabled: enabledFor(userId),
  })
}

export function useLimitations(opts?: { onDate?: string; history?: boolean }) {
  const userId = useAthleteId()
  return useQuery<AthleteLimitation[], FitnessCoachError>({
    queryKey: fitnessKeys.limitations(userId ?? 'anonymous', opts?.onDate, opts?.history),
    queryFn: () => fitnessCoachApi.listLimitations(opts),
    enabled: enabledFor(userId),
  })
}

export function useResolvedTargets(opts?: { onDate?: string; dayType?: string }) {
  const userId = useAthleteId()
  return useQuery<ResolvedTargets, FitnessCoachError>({
    queryKey: fitnessKeys.targets(userId ?? 'anonymous', opts?.onDate, opts?.dayType),
    queryFn: () => fitnessCoachApi.resolveTargets(opts),
    enabled: enabledFor(userId),
  })
}

export function useTargetHistory(opts?: {
  scope?: TargetScope
  phaseId?: string
  limit?: number
}) {
  const userId = useAthleteId()
  return useQuery<TargetRevision[], FitnessCoachError>({
    queryKey: fitnessKeys.targetHistory(userId ?? 'anonymous', opts?.scope, opts?.phaseId),
    queryFn: () => fitnessCoachApi.listTargetRevisions(opts),
    enabled: enabledFor(userId),
  })
}

// ── Writes ────────────────────────────────────────────────────────────────

function useInvalidateFitness() {
  const client = useQueryClient()
  const userId = useAthleteId()
  return useCallback(
    (options?: { includeLegacy?: boolean }) => {
      if (userId) {
        client.invalidateQueries({ queryKey: fitnessKeys.all(userId) })
      }
      if (options?.includeLegacy) {
        for (const key of LEGACY_FITNESS_KEYS) {
          client.invalidateQueries({ queryKey: key })
        }
      }
    },
    [client, userId],
  )
}

export function usePatchProfile(): UseMutationResult<
  AthleteProfile,
  FitnessCoachError,
  AthleteProfilePatch
> {
  const client = useQueryClient()
  const userId = useAthleteId()
  const invalidate = useInvalidateFitness()

  return useMutation({
    mutationFn: (patch: AthleteProfilePatch) => fitnessCoachApi.patchProfile(patch),
    onSuccess: (profile) => {
      // Seed the cache from the response rather than refetching: the
      // response IS the new state, including the incremented row_version
      // the next edit needs.
      if (userId) client.setQueryData(fitnessKeys.profile(userId), profile)
      invalidate()
    },
    onError: (error) => {
      // A version conflict means our cached profile is behind. Refetch so
      // the form can re-render against the real current values instead of
      // retrying against a stale version forever.
      if (error.kind === 'conflict' && userId) {
        client.invalidateQueries({ queryKey: fitnessKeys.profile(userId) })
      }
    },
    retry: false,
  })
}

export function useCreateGoal(): UseMutationResult<
  AthleteGoal,
  FitnessCoachError,
  AthleteGoalInput
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: (goal: AthleteGoalInput) => fitnessCoachApi.createGoal(goal),
    // A new primary goal closes the previous one, so the whole goal list and
    // any as-of view of it change, not just the new row.
    onSuccess: () => invalidate(),
    retry: false,
  })
}

export function useCloseGoal(): UseMutationResult<
  AthleteGoal,
  FitnessCoachError,
  { goalId: string; validUntil: string }
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: ({ goalId, validUntil }) => fitnessCoachApi.closeGoal(goalId, validUntil),
    onSuccess: () => invalidate(),
    retry: false,
  })
}

export function useCreateLimitation(): UseMutationResult<
  AthleteLimitation,
  FitnessCoachError,
  AthleteLimitationInput
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: (limitation: AthleteLimitationInput) =>
      fitnessCoachApi.createLimitation(limitation),
    onSuccess: () => invalidate(),
    retry: false,
  })
}

export function useResolveLimitation(): UseMutationResult<
  AthleteLimitation,
  FitnessCoachError,
  { limitationId: string; effectiveUntil?: string }
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: ({ limitationId, effectiveUntil }) =>
      fitnessCoachApi.resolveLimitation(limitationId, effectiveUntil),
    onSuccess: () => invalidate(),
    retry: false,
  })
}

export function useCreateTargetRevision(): UseMutationResult<
  TargetRevision,
  FitnessCoachError,
  TargetRevisionInput
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: (revision: TargetRevisionInput) =>
      fitnessCoachApi.createTargetRevision(revision),
    onSuccess: () => {
      // `includeLegacy`: the writer updated `fitness_phase`/`fitness_goals`
      // in the same transaction, which is what the old dashboard, nutrition
      // view and plan view read. Without this they show the previous macros
      // until a reload, and the two surfaces visibly disagree.
      invalidate({ includeLegacy: true })
    },
    retry: false,
  })
}

// ── Cache lifecycle ───────────────────────────────────────────────────────

/**
 * Drop this athlete's cached fitness data.
 *
 * Call on logout and on account change. `removeQueries`, not
 * `invalidateQueries`: invalidation marks data stale but leaves it in memory
 * and keeps rendering it until a refetch lands, which means one person's
 * bodyweight can be on screen after another has signed in.
 */
export function useClearFitnessCache(): (userId?: string) => void {
  const client = useQueryClient()
  const currentId = useAthleteId()
  return useCallback(
    (userId?: string) => {
      const id = userId ?? currentId
      if (id) client.removeQueries({ queryKey: fitnessKeys.all(id) })
      else client.removeQueries({ queryKey: ['fitness-coach'] })
    },
    [client, currentId],
  )
}

// ── Check-ins ─────────────────────────────────────────────────────────────

export const checkInKeys = {
  day: (userId: string, logDate: string) =>
    ['fitness-coach', userId, 'check-in', logDate] as const,
}

export function useCheckIn(logDate: string | undefined) {
  const userId = useAthleteId()
  return useQuery<CheckIn, FitnessCoachError>({
    queryKey: checkInKeys.day(userId ?? 'anonymous', logDate ?? 'unset'),
    queryFn: () => fitnessCoachApi.getCheckIn(logDate as string),
    enabled: enabledFor(userId) && Boolean(logDate),
    // A day's wearable data arrives through the morning; a short stale time
    // means opening Today after a sync shows the new reading.
    staleTime: 30_000,
  })
}

export function usePatchCheckIn(
  logDate: string | undefined,
): UseMutationResult<CheckIn, FitnessCoachError, CheckInPatch> {
  const client = useQueryClient()
  const userId = useAthleteId()
  return useMutation({
    mutationFn: (patch: CheckInPatch) =>
      fitnessCoachApi.patchCheckIn(logDate as string, patch),
    onSuccess: (checkIn) => {
      if (userId && logDate) {
        // The response IS the new state, including the incremented
        // row_version the next edit needs for its concurrency check.
        client.setQueryData(checkInKeys.day(userId, logDate), checkIn)
        // A delegated weight/sleep value became an observation, which the
        // targets and measurement views read too.
        client.invalidateQueries({ queryKey: fitnessKeys.all(userId) })
      }
    },
    onError: (error) => {
      if (error.kind === 'conflict' && userId && logDate) {
        client.invalidateQueries({ queryKey: checkInKeys.day(userId, logDate) })
      }
    },
    retry: false,
  })
}

// ── Measurements ──────────────────────────────────────────────────────────

export const measurementKeys = {
  types: (userId: string) => ['fitness-coach', userId, 'measurement-types'] as const,
  periods: (userId: string) =>
    ['fitness-coach', userId, 'measurement-periods'] as const,
  list: (userId: string, typeCode?: string) =>
    ['fitness-coach', userId, 'measurements', typeCode ?? 'all'] as const,
  change: (userId: string, typeCode: string, side: string) =>
    ['fitness-coach', userId, 'measurement-change', typeCode, side] as const,
}

export function useMeasurementTypes() {
  const userId = useAthleteId()
  return useQuery<MeasurementType[], FitnessCoachError>({
    queryKey: measurementKeys.types(userId ?? 'anonymous'),
    queryFn: () => fitnessCoachApi.listMeasurementTypes(),
    enabled: enabledFor(userId),
    // Global seeds plus the athlete's own definitions: stable data.
    staleTime: 10 * 60_000,
  })
}

export function useMeasurementPeriods() {
  const userId = useAthleteId()
  return useQuery<MeasurementPeriod[], FitnessCoachError>({
    queryKey: measurementKeys.periods(userId ?? 'anonymous'),
    queryFn: () => fitnessCoachApi.listMeasurementPeriods(),
    enabled: enabledFor(userId),
  })
}

export function useMeasurements(typeCode?: string) {
  const userId = useAthleteId()
  return useQuery<Measurement[], FitnessCoachError>({
    queryKey: measurementKeys.list(userId ?? 'anonymous', typeCode),
    queryFn: () => fitnessCoachApi.listMeasurements({ typeCode }),
    enabled: enabledFor(userId),
  })
}

export function useCreateMeasurementType(): UseMutationResult<
  MeasurementType,
  FitnessCoachError,
  MeasurementTypeInput
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: (type: MeasurementTypeInput) =>
      fitnessCoachApi.createMeasurementType(type),
    onSuccess: () => invalidate(),
    retry: false,
  })
}

export function useCreateMeasurementPeriod(): UseMutationResult<
  MeasurementPeriod,
  FitnessCoachError,
  MeasurementPeriodInput
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: (period: MeasurementPeriodInput) =>
      fitnessCoachApi.createMeasurementPeriod(period),
    onSuccess: () => invalidate(),
    retry: false,
  })
}

export function useLogMeasurement(): UseMutationResult<
  Measurement,
  FitnessCoachError,
  MeasurementInput
> {
  const invalidate = useInvalidateFitness()
  return useMutation({
    mutationFn: (measurement: MeasurementInput) =>
      fitnessCoachApi.logMeasurement(measurement),
    // A new reading changes the listing, the period's contents and the
    // comparable-change figure.
    onSuccess: () => invalidate(),
    retry: false,
  })
}
