/**
 * Typed, credentialed client for `/api/fitness/coach`.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 7. Uses `APP_CONFIG.apiUrl` and
 * `credentials: 'include'`, matching how the existing fitness components talk
 * to the backend — the cookie is the session, so omitting credentials would
 * 401 every call.
 *
 * Error normalization is the main thing this file adds. A FastAPI 422 arrives
 * as a nested `detail` array of Pydantic errors, and a 409 from this API
 * arrives as a `detail` object carrying the current version or revision id.
 * Rendering either raw puts `loc: ["body","height_cm"]` in front of a person.
 * `FitnessApiError` turns both into something a form can show and a mutation
 * can reconcile from.
 */
import { APP_CONFIG } from '../config'
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
  Metric,
  AthleteGoalInput,
  AthleteLimitation,
  AthleteLimitationInput,
  AthleteProfile,
  AthleteProfilePatch,
  FitnessApiError,
  FitnessErrorKind,
  ResolvedTargets,
  TargetRevision,
  TargetRevisionInput,
  TargetScope,
} from '../types/fitnessCoach'

const BASE = `${APP_CONFIG.apiUrl}/api/fitness/coach`

export class FitnessCoachError extends Error implements FitnessApiError {
  kind: FitnessErrorKind
  status?: number
  currentVersion?: number
  currentRevisionId?: string
  fieldErrors?: Record<string, string>

  constructor(error: FitnessApiError) {
    super(error.message)
    this.name = 'FitnessCoachError'
    this.kind = error.kind
    this.status = error.status
    this.currentVersion = error.currentVersion
    this.currentRevisionId = error.currentRevisionId
    this.fieldErrors = error.fieldErrors
  }
}

function kindFor(status: number): FitnessErrorKind {
  if (status === 401 || status === 403) return 'unauthenticated'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 422 || status === 400) return 'validation'
  return 'server'
}

/** Turn one Pydantic error into "Height: must be a positive number". */
function fieldLabel(loc: unknown[]): string {
  const parts = loc.filter(
    (p) => typeof p === 'string' && p !== 'body' && p !== 'query',
  ) as string[]
  const last = parts[parts.length - 1] ?? 'value'
  return last
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

async function normalizeError(response: Response): Promise<FitnessCoachError> {
  const kind = kindFor(response.status)
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // A non-JSON error body (a proxy's HTML 502, say) must not become the
    // message a person reads.
  }

  const detail = (body as { detail?: unknown } | null)?.detail

  // A 409 from this API carries what the client needs to reconcile, instead
  // of forcing a blind retry that would discard the other device's edit.
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>
    return new FitnessCoachError({
      kind,
      status: response.status,
      message: typeof d.message === 'string'
        ? d.message
        : 'That change could not be applied.',
      currentVersion: typeof d.current_version === 'number' ? d.current_version : undefined,
      currentRevisionId: typeof d.current_revision_id === 'string'
        ? d.current_revision_id
        : undefined,
    })
  }

  // A 422 arrives as an array of Pydantic errors.
  if (Array.isArray(detail)) {
    const fieldErrors: Record<string, string> = {}
    for (const item of detail) {
      if (!item || typeof item !== 'object') continue
      const e = item as { loc?: unknown[]; msg?: string }
      const label = fieldLabel(e.loc ?? [])
      if (e.msg) fieldErrors[label] = e.msg
    }
    const first = Object.entries(fieldErrors)[0]
    return new FitnessCoachError({
      kind: 'validation',
      status: response.status,
      message: first ? `${first[0]}: ${first[1]}` : 'Some values were not accepted.',
      fieldErrors,
    })
  }

  const messages: Record<FitnessErrorKind, string> = {
    unauthenticated: 'You need to sign in again.',
    not_found: 'That is no longer there.',
    conflict: 'Something else changed this while you were editing it.',
    validation: 'Some values were not accepted.',
    server: 'Sara could not complete that. Nothing was saved.',
    network: 'Could not reach Sara.',
  }
  return new FitnessCoachError({
    kind,
    status: response.status,
    message: typeof detail === 'string' ? detail : messages[kind],
  })
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch (cause) {
    // A failed fetch is a network fact, not a server error, and the
    // difference matters: one is worth retrying, the other is not.
    throw new FitnessCoachError({
      kind: 'network',
      message: 'Could not reach Sara. Your entry has not been saved.',
    })
  }
  if (!response.ok) throw await normalizeError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

// ── Profile ───────────────────────────────────────────────────────────────

export const fitnessCoachApi = {
  getProfile: () => request<AthleteProfile>('/profile'),

  /**
   * Send only what changed.
   *
   * Spreading a whole profile object in here would turn every untouched
   * field into an assertion, and an absent-vs-cleared distinction the
   * backend carefully preserves would be lost at the boundary.
   */
  patchProfile: (patch: AthleteProfilePatch) =>
    request<AthleteProfile>('/profile', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  /** The athlete's own calendar date. The browser's is not authoritative. */
  getToday: () =>
    request<{ athlete_local_date: string; timezone: string }>('/today'),

  // ── Goals ───────────────────────────────────────────────────────────────

  listGoals: (opts?: { onDate?: string; history?: boolean }) =>
    request<AthleteGoal[]>(
      `/goals${query({ on_date: opts?.onDate, history: opts?.history })}`,
    ),

  createGoal: (goal: AthleteGoalInput) =>
    request<AthleteGoal>('/goals', { method: 'POST', body: JSON.stringify(goal) }),

  closeGoal: (goalId: string, validUntil: string) =>
    request<AthleteGoal>(`/goals/${encodeURIComponent(goalId)}/close`, {
      method: 'POST',
      body: JSON.stringify({ valid_until: validUntil }),
    }),

  // ── Limitations ─────────────────────────────────────────────────────────

  listLimitations: (opts?: { onDate?: string; history?: boolean }) =>
    request<AthleteLimitation[]>(
      `/limitations${query({ on_date: opts?.onDate, history: opts?.history })}`,
    ),

  createLimitation: (limitation: AthleteLimitationInput) =>
    request<AthleteLimitation>('/limitations', {
      method: 'POST',
      body: JSON.stringify(limitation),
    }),

  resolveLimitation: (limitationId: string, effectiveUntil?: string) =>
    request<AthleteLimitation>(
      `/limitations/${encodeURIComponent(limitationId)}/resolve`,
      { method: 'POST', body: JSON.stringify({ effective_until: effectiveUntil ?? null }) },
    ),

  // ── Targets ─────────────────────────────────────────────────────────────

  resolveTargets: (opts?: { onDate?: string; dayType?: string }) =>
    request<ResolvedTargets>(
      `/targets${query({ on_date: opts?.onDate, day_type: opts?.dayType })}`,
    ),

  listTargetRevisions: (opts?: { scope?: TargetScope; phaseId?: string; limit?: number }) =>
    request<TargetRevision[]>(
      `/targets/history${query({
        scope: opts?.scope,
        phase_id: opts?.phaseId,
        limit: opts?.limit,
      })}`,
    ),

  createTargetRevision: (revision: TargetRevisionInput) =>
    request<TargetRevision>('/targets', {
      method: 'POST',
      body: JSON.stringify(revision),
    }),

  // ── Check-ins ───────────────────────────────────────────────────────────

  getCheckIn: (logDate: string) =>
    request<CheckIn>(`/check-ins/${encodeURIComponent(logDate)}`),

  /**
   * Send only what changed.
   *
   * An omitted key is left alone; an explicit `null` clears that field. A
   * caller that spreads the whole check-in back in would turn every
   * untouched answer into an assertion and could erase the wearable's
   * morning reading.
   */
  patchCheckIn: (logDate: string, patch: CheckInPatch) =>
    request<CheckIn>(`/check-ins/${encodeURIComponent(logDate)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  // ── Measurements ────────────────────────────────────────────────────────

  listMeasurementTypes: () => request<MeasurementType[]>('/measurement-types'),

  createMeasurementType: (type: MeasurementTypeInput) =>
    request<MeasurementType>('/measurement-types', {
      method: 'POST',
      body: JSON.stringify(type),
    }),

  listMeasurementPeriods: (limit?: number) =>
    request<MeasurementPeriod[]>(`/measurement-periods${query({ limit })}`),

  createMeasurementPeriod: (period: MeasurementPeriodInput) =>
    request<MeasurementPeriod>('/measurement-periods', {
      method: 'POST',
      body: JSON.stringify(period),
    }),

  listMeasurements: (opts?: {
    typeCode?: string
    startDate?: string
    endDate?: string
    limit?: number
  }) =>
    request<Measurement[]>(
      `/measurements${query({
        type_code: opts?.typeCode,
        start_date: opts?.startDate,
        end_date: opts?.endDate,
        limit: opts?.limit,
      })}`,
    ),

  logMeasurement: (measurement: MeasurementInput) =>
    request<Measurement>('/measurements', {
      method: 'POST',
      body: JSON.stringify(measurement),
    }),

  /** The change between the two most recent *comparable* readings. */
  measurementChange: (typeCode: string, opts?: { site?: string; side?: string }) =>
    request<Metric>(
      `/measurements/${encodeURIComponent(typeCode)}/change${query({
        site: opts?.site,
        side: opts?.side,
      })}`,
    ),
}

export type FitnessCoachApi = typeof fitnessCoachApi
