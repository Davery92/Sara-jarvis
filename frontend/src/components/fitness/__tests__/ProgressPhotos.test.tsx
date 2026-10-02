/**
 * Step 26 of FITNESS_COACH_IMPLEMENTATION_PLAN, at the UI.
 *
 * The subject is somebody's body, so the claims being pinned are about
 * truthfulness rather than polish:
 *
 * - **A delete that could not remove the bytes does not say "deleted".**
 *   The backend returns `deleted: false` with `pending_cleanup`; this screen
 *   repeats that. "Deleted" while the file is still in storage is the one
 *   message it must not send.
 * - **The server's own rejection reason is shown.** It knows whether the
 *   file was too large, undecodable or the wrong type, and a generic
 *   "upload failed" leaves someone re-exporting a perfectly good photo.
 * - **Views are separate slots.** A front shot against a side shot is not a
 *   change in the athlete.
 * - **Analysis consent is per photo and off by default**, and says what off
 *   means.
 * - **No body-fat number anywhere**, and the legacy critique is labelled as
 *   free text rather than as a measurement.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProgressPhotos from '../ProgressPhotos'
import type { ProgressPhoto } from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-photos'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

function photo(over: Partial<ProgressPhoto> = {}): ProgressPhoto {
  return {
    id: 'p1', original_filename: 'IMG_0001.HEIC', mime_type: 'image/jpeg',
    file_size: 123456, width: 1200, height: 1600,
    taken_at: '2026-09-28T12:00:00Z', notes: 'end of week 3',
    bodyweight: null, bodyweight_unit: 'lbs',
    critique: null, critique_model: null, critiqued_at: null,
    has_critique: false, created_at: '2026-09-28T12:05:00Z',
    view: 'front', period_id: null, capture_protocol: null,
    lighting: 'window daylight', distance_cm: 200,
    bodyweight_observation_id: null, consent_analysis: false,
    analysis_status: null, ...over,
  }
}

interface Call { url: string; method: string; body?: FormData | null }

let calls: Call[] = []
let photos: ProgressPhoto[] = []
let uploadStatus = 200
let uploadBody: unknown = null
let deleteBody: unknown = null
let periods: Array<Record<string, unknown>> = []
let comparableBody: unknown = null

function stubFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    calls.push({
      url, method,
      body: init?.body instanceof FormData ? init.body : null,
    })
    const json = (status: number, payload: unknown) =>
      new Response(JSON.stringify(payload), {
        status, headers: { 'Content-Type': 'application/json' },
      })

    if (url.includes('/coach/today')) {
      return json(200, {
        athlete_local_date: '2026-10-02', timezone: 'America/New_York',
      })
    }
    if (url.includes('/coach/measurement-periods')) return json(200, periods)
    if (url.includes('/comparable')) {
      return json(200, comparableBody ?? {
        comparable: true, reason: null, photos: ['p1', 'p2'],
      })
    }
    if (url.includes('/analysis-consent')) {
      return json(200, { id: 'p1', consent_analysis: true })
    }
    if (url.includes('/progress-photos') && method === 'DELETE') {
      return json(200, deleteBody ?? {
        id: 'p1', deleted: true, cleanup_state: 'cleaned', message: 'Deleted.',
      })
    }
    if (url.includes('/progress-photos') && method === 'POST') {
      return json(uploadStatus, uploadBody ?? photo())
    }
    if (url.includes('/progress-photos')) return json(200, photos)
    return json(200, [])
  }) as unknown as typeof fetch
}

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

async function pickFile() {
  const input = screen.getByTestId('photo-file') as HTMLInputElement
  const file = new File([new Uint8Array([1, 2, 3])], 'front.jpg', {
    type: 'image/jpeg',
  })
  await userEvent.upload(input, file)
  return file
}

beforeEach(() => {
  calls = []
  photos = []
  uploadStatus = 200
  uploadBody = null
  deleteBody = null
  comparableBody = null
  periods = []
  stubFetch()
})

// ── Capture ───────────────────────────────────────────────────────────────

describe('capture', () => {
  it('offers front, side, back and other as separate slots', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('view-picker')).toBeTruthy())
    for (const view of ['front', 'side', 'back', 'other']) {
      expect(screen.getByTestId(`view-${view}`)).toBeTruthy()
    }
    expect(screen.getByTestId('view-front').getAttribute('aria-pressed'))
      .toBe('true')
  })

  it('says why the view and the conditions are being asked for', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('progress-photos')).toBeTruthy())
    const text = screen.getByTestId('progress-photos').textContent ?? ''
    expect(text).toContain('not a change in you')
    expect(text).toContain('makes a later comparison mean anything')
  })

  it('sends the view and the capture conditions with the upload', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-file')).toBeTruthy())

    await userEvent.click(screen.getByTestId('view-side'))
    await userEvent.type(screen.getByTestId('photo-lighting'), 'window daylight')
    await userEvent.type(screen.getByTestId('photo-distance'), '200')
    await pickFile()
    await userEvent.click(screen.getByTestId('photo-upload'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST')).toBe(true),
    )
    const form = calls.find((c) => c.method === 'POST')?.body as FormData
    expect(form.get('view')).toBe('side')
    expect(form.get('lighting')).toBe('window daylight')
    expect(form.get('distance_cm')).toBe('200')
    expect(form.get('file')).toBeTruthy()
  })

  it('omits an unset optional field rather than sending it empty', async () => {
    // An empty `view` is different from no view, and an empty string would
    // fail the server's enum check instead of meaning "not recorded".
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-file')).toBeTruthy())
    await pickFile()
    await userEvent.click(screen.getByTestId('photo-upload'))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST')).toBe(true),
    )
    const form = calls.find((c) => c.method === 'POST')?.body as FormData
    expect(form.has('lighting')).toBe(false)
    expect(form.has('distance_cm')).toBe(false)
    expect(form.has('period_id')).toBe(false)
  })

  it('refuses to upload with no file picked', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-upload')).toBeTruthy())
    await userEvent.click(screen.getByTestId('photo-upload'))
    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('Pick a photo first'),
    )
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it("shows the server's own rejection reason", async () => {
    // It knows whether the file was too large, undecodable or the wrong
    // type. A generic "upload failed" leaves someone re-exporting a
    // perfectly good photo.
    uploadStatus = 400
    uploadBody = { detail: 'that image is larger than 25 MB' }
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-file')).toBeTruthy())
    await pickFile()
    await userEvent.click(screen.getByTestId('photo-upload'))

    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('larger than 25 MB'),
    )
  })

  it('surfaces an undecodable-file rejection verbatim', async () => {
    uploadStatus = 400
    uploadBody = { detail: 'that file is not an image we can read' }
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-file')).toBeTruthy())
    await pickFile()
    await userEvent.click(screen.getByTestId('photo-upload'))
    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('not an image we can read'),
    )
  })

  it('attaches the photo to a measuring session when one is chosen', async () => {
    periods = [
      { id: 'per-1', measured_on: '2026-09-28', protocol: 'morning, fasted' },
      { id: 'per-2', measured_on: '2026-09-14', protocol: null },
    ]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-period')).toBeTruthy())
    await userEvent.selectOptions(screen.getByTestId('photo-period'), 'per-1')
    await pickFile()
    await userEvent.click(screen.getByTestId('photo-upload'))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST')).toBe(true),
    )
    const form = calls.find((c) => c.method === 'POST')?.body as FormData
    expect(form.get('period_id')).toBe('per-1')
  })
})

// ── Gallery ───────────────────────────────────────────────────────────────

describe('gallery', () => {
  it('groups by view', async () => {
    photos = [
      photo({ id: 'f1', view: 'front' }),
      photo({ id: 'f2', view: 'front' }),
      photo({ id: 's1', view: 'side' }),
    ]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('group-front')).toBeTruthy())
    expect(within(screen.getByTestId('group-front')).getByTestId('photo-f1'))
      .toBeTruthy()
    expect(within(screen.getByTestId('group-side')).getByTestId('photo-s1'))
      .toBeTruthy()
    expect(screen.queryByTestId('group-back')).toBeNull()
  })

  it('shows the capture conditions beside each photo', async () => {
    photos = [photo({ lighting: 'window daylight', distance_cm: 200 })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-conditions')).toBeTruthy())
    const text = screen.getByTestId('photo-conditions').textContent ?? ''
    expect(text).toContain('window daylight')
    expect(text).toContain('200 cm')
  })

  it('loads the image through a credentialed URL, never a data URI', async () => {
    // A data URL would put somebody's body into every React render and into
    // whatever logs the console.
    photos = [photo()]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-p1')).toBeTruthy())
    const img = within(screen.getByTestId('photo-p1')).getByRole('img')
    expect(img.getAttribute('src')).toContain('/progress-photos/p1/file')
    expect(img.getAttribute('src')).not.toContain('data:')
    expect(img.getAttribute('alt')).toContain('Front progress photo')
  })

  it('says the photos are private and unlooked-at when there are none', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('no-photos')).toBeTruthy())
    const text = screen.getByTestId('no-photos').textContent ?? ''
    expect(text).toContain('private to you')
    expect(text).toContain('unless you turn that on')
  })

  it('shows the weight as a link to the day, not as a typed number', async () => {
    photos = [photo({ bodyweight_observation_id: 'obs-1', bodyweight: 181.5 })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-weight-link')).toBeTruthy())
    expect(screen.getByTestId('photo-weight-link').textContent)
      .toContain('weight recorded that day')
    // The float is display context the backend never ingested; it is not
    // presented as the athlete's weight.
    expect(screen.getByTestId('photo-p1').textContent).not.toContain('181.5')
  })

  it('reports a load failure instead of showing an empty gallery', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/coach/today')) {
        return new Response(JSON.stringify({
          athlete_local_date: '2026-10-02', timezone: 'America/New_York',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.includes('/progress-photos')) {
        return new Response(JSON.stringify({ detail: 'storage unavailable' }), {
          status: 500, headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('[]', {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }) as unknown as typeof fetch

    wrap(<ProgressPhotos />)
    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('storage unavailable'),
    )
  })
})

// ── Deleting, truthfully ──────────────────────────────────────────────────

describe('deleting', () => {
  it('says deleted when the bytes are actually gone', async () => {
    photos = [photo()]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('delete-p1')).toBeTruthy())
    photos = []
    await userEvent.click(screen.getByTestId('delete-p1'))
    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('Deleted.'),
    )
  })

  it('does NOT say deleted when the stored file survived', async () => {
    // The one message this screen must not send. The athlete would believe
    // the photo is gone and it would still be in object storage.
    photos = [photo()]
    deleteBody = {
      id: 'p1', deleted: false, cleanup_state: 'pending_cleanup',
      message:
        'Removed from your gallery, but the stored image could not be ' +
        'deleted yet. It is queued for retry and will not appear anywhere ' +
        'in the meantime.',
    }
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('delete-p1')).toBeTruthy())
    photos = []
    await userEvent.click(screen.getByTestId('delete-p1'))

    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('could not be deleted yet'),
    )
    const text = screen.getByTestId('progress-photos').textContent ?? ''
    expect(text).toContain('queued for retry')
    // And the plain confirmation is absent.
    expect(text).not.toContain('Deleted.')
  })

  it('reports a failed delete rather than removing the photo locally', async () => {
    photos = [photo()]
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method ?? 'GET').toUpperCase()
      const json = (status: number, payload: unknown) =>
        new Response(JSON.stringify(payload), {
          status, headers: { 'Content-Type': 'application/json' },
        })
      if (url.includes('/coach/today')) {
        return json(200, {
          athlete_local_date: '2026-10-02', timezone: 'America/New_York',
        })
      }
      if (url.includes('/progress-photos') && method === 'DELETE') {
        return json(500, { detail: 'Could not delete that photo. It is unchanged.' })
      }
      if (url.includes('/progress-photos')) return json(200, photos)
      return json(200, [])
    }) as unknown as typeof fetch

    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('delete-p1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('delete-p1'))
    await waitFor(() =>
      expect(screen.getByTestId('progress-photos').textContent)
        .toContain('It is unchanged'),
    )
    // Still on screen, because it still exists.
    expect(screen.getByTestId('photo-p1')).toBeTruthy()
  })
})

// ── Consent ───────────────────────────────────────────────────────────────

describe('analysis consent', () => {
  it('is per photo and off by default, and says what off means', async () => {
    photos = [photo({ consent_analysis: false })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('consent-p1')).toBeTruthy())
    expect((screen.getByTestId('consent-p1') as HTMLInputElement).checked)
      .toBe(false)
    expect(screen.getByTestId('photo-p1').textContent)
      .toContain('nothing analyses it')
  })

  it('sends an explicit consent change', async () => {
    photos = [photo({ consent_analysis: false })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('consent-p1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('consent-p1'))
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes('/analysis-consent'))).toBe(true),
    )
    const form = calls.find((c) => c.url.includes('/analysis-consent'))
      ?.body as FormData
    expect(form.get('consented')).toBe('true')
  })

  it('offers no analysis action beyond the consent switch', async () => {
    // Step 27 adds the vision pass. Until then nothing may imply a model
    // has looked at the photo.
    photos = [photo({ consent_analysis: true })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('photo-p1')).toBeTruthy())
    const text = screen.getByTestId('photo-p1').textContent ?? ''
    expect(text).not.toContain('Analyse')
    expect(text).not.toContain('Analyze')
    expect(text).not.toContain('Compare with AI')
  })
})

// ── No numbers from a photo ───────────────────────────────────────────────

describe('no body composition', () => {
  it('shows no body-fat figure anywhere', async () => {
    photos = [photo({ has_critique: true, critique: 'Solid back width.' })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('progress-photos')).toBeTruthy())
    const text = (screen.getByTestId('progress-photos').textContent ?? '')
      .toLowerCase()
    expect(text).not.toContain('body fat')
    expect(text).not.toContain('body-fat')
    expect(text).not.toContain('lean mass')
    expect(text).not.toContain('bf%')
  })

  it('labels the legacy critique as free text, not a measurement', async () => {
    photos = [photo({
      has_critique: true, critique: 'Solid back width.',
      critique_model: 'qwen-vl',
    })]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('critique-p1')).toBeTruthy())
    const text = screen.getByTestId('critique-p1').textContent ?? ''
    expect(text).toContain('Older written critique')
    expect(text).toContain('not a measurement')
    expect(text).toContain('nothing in your records came from it')
  })
})

// ── Comparability ─────────────────────────────────────────────────────────

describe('comparing sessions', () => {
  beforeEach(() => {
    periods = [
      { id: 'per-1', measured_on: '2026-09-28', protocol: null },
      { id: 'per-2', measured_on: '2026-09-14', protocol: null },
    ]
  })

  it('appears only with two sessions to compare', async () => {
    periods = [{ id: 'per-1', measured_on: '2026-09-28', protocol: null }]
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('progress-photos')).toBeTruthy())
    expect(screen.queryByTestId('compare-picker')).toBeNull()
  })

  it('says a matched pair is comparable', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('compare-picker')).toBeTruthy())
    await userEvent.selectOptions(screen.getByTestId('compare-picker'), 'per-1')
    await waitFor(() =>
      expect(screen.getByTestId('comparison-result')).toBeTruthy(),
    )
    expect(screen.getByTestId('comparison-result').textContent)
      .toContain('comparable')
  })

  it('says why a pair is not comparable', async () => {
    comparableBody = {
      comparable: false,
      reason:
        'the lighting differs (window vs overhead), which changes the image ' +
        'more than a week of training does',
      photos: ['p1', 'p2'],
    }
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('compare-picker')).toBeTruthy())
    await userEvent.selectOptions(screen.getByTestId('compare-picker'), 'per-1')
    await waitFor(() =>
      expect(screen.getByTestId('comparison-result')).toBeTruthy(),
    )
    const text = screen.getByTestId('comparison-result').textContent ?? ''
    expect(text).toContain('Not comparable')
    expect(text).toContain('lighting differs')
  })

  it('says it analyses nothing', async () => {
    wrap(<ProgressPhotos />)
    await waitFor(() => expect(screen.getByTestId('compare-picker')).toBeTruthy())
    expect(screen.getByTestId('progress-photos').textContent)
      .toContain('does not analyse anything')
  })
})
