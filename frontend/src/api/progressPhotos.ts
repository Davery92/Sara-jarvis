/**
 * Progress photo client.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 26. Separate from
 * `api/fitnessCoach.ts` because these routes live under
 * `/api/fitness/progress-photos` and predate the Coach API — the iOS app
 * reads the same endpoints, so their shapes are a contract rather than
 * something to fold in.
 *
 * Image bytes are never put in a JSON body. They go as multipart, and they
 * come back as an opaque URL the browser fetches with the session cookie:
 * a data URL would put somebody's body into every React render and into
 * whatever logs the console.
 */
import { APP_CONFIG } from '../config'
import type {
  PhotoComparability,
  PhotoDeleteResult,
  PhotoUploadInput,
  ProgressPhoto,
} from '../types/fitnessCoach'

const BASE = `${APP_CONFIG.apiUrl}/api/fitness/progress-photos`

export class PhotoError extends Error {
  status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'PhotoError'
    this.status = status
  }
}

async function failure(response: Response): Promise<PhotoError> {
  let detail = `Request failed (${response.status})`
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') detail = body.detail
  } catch {
    // Non-JSON error body. The status is still useful.
  }
  return new PhotoError(detail, response.status)
}

export const progressPhotoApi = {
  list: async (): Promise<ProgressPhoto[]> => {
    const response = await fetch(BASE, { credentials: 'include' })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  /**
   * Upload one photo.
   *
   * The server bounds the bytes, refuses anything it cannot decode, and
   * strips EXIF — so the client does not need to, and must not pretend it
   * has. Optional fields are omitted rather than sent empty, because an
   * empty `view` is different from no view.
   */
  upload: async (input: PhotoUploadInput): Promise<ProgressPhoto> => {
    const form = new FormData()
    form.append('file', input.file)
    if (input.view) form.append('view', input.view)
    if (input.periodId) form.append('period_id', input.periodId)
    if (input.notes) form.append('notes', input.notes)
    if (input.takenAt) form.append('taken_at', input.takenAt)
    if (input.capture_protocol) {
      form.append('capture_protocol', input.capture_protocol)
    }
    if (input.lighting) form.append('lighting', input.lighting)
    if (input.distanceCm != null) {
      form.append('distance_cm', String(input.distanceCm))
    }

    const response = await fetch(BASE, {
      method: 'POST', credentials: 'include', body: form,
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  /**
   * The URL for a photo's bytes. Fetched by the browser with the session
   * cookie, so the id alone is not enough to see it.
   */
  fileUrl: (photoId: string, variant: 'full' | 'thumb' = 'thumb'): string =>
    `${BASE}/${encodeURIComponent(photoId)}/file?variant=${variant}`,

  remove: async (photoId: string): Promise<PhotoDeleteResult> => {
    const response = await fetch(`${BASE}/${encodeURIComponent(photoId)}`, {
      method: 'DELETE', credentials: 'include',
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  setAnalysisConsent: async (
    photoId: string, consented: boolean,
  ): Promise<{ id: string; consent_analysis: boolean }> => {
    const form = new FormData()
    form.append('consented', String(consented))
    const response = await fetch(
      `${BASE}/${encodeURIComponent(photoId)}/analysis-consent`,
      { method: 'POST', credentials: 'include', body: form },
    )
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  /** Whether two capture sessions can honestly be compared. No model. */
  comparable: async (
    periodId: string, againstPeriodId: string, view = 'front',
  ): Promise<PhotoComparability> => {
    const query = new URLSearchParams({
      against_period_id: againstPeriodId, view,
    })
    const response = await fetch(
      `${BASE}/periods/${encodeURIComponent(periodId)}/comparable?${query}`,
      { credentials: 'include' },
    )
    if (!response.ok) throw await failure(response)
    return response.json()
  },
}
