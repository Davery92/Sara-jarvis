/**
 * Step 28 of FITNESS_COACH_IMPLEMENTATION_PLAN, at the UI.
 *
 * The plan asks for "frontend accepted/new distinction", and that is what
 * most of this file is about. The failure being prevented is a screen that
 * says "added to your library" after an upload: the paper is ingested, the
 * coach cannot cite it, and the person who uploaded it has no way to know
 * that from the message.
 *
 * Also pinned here:
 *
 * - **An empty library says it is empty**, per topic, with the gaps named.
 *   "The research suggests" over nothing is the failure the whole step
 *   exists to prevent.
 * - **Accepting asks for limitations**, because the server rejects an
 *   accept without them and a 422 is a worse way to learn that.
 * - **A failed refresh shows as failed**, beside the ones that worked. One
 *   timestamp would make a job that has failed every month look healthy.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ScienceLibrary from '../ScienceLibrary'
import type {
  ScienceCoverage, ScienceHit, ScienceRecord, ScienceRefreshRun,
} from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-science'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

function record(over: Partial<ScienceRecord> = {}): ScienceRecord {
  return {
    id: 'r1', title: 'Weekly set volume and hypertrophy',
    authors: 'Schoenfeld et al.', publication_year: 2026,
    journal: 'J Strength Cond Res', doi: '10.1234/volume',
    url: 'https://example.invalid/volume', source_type: 'rct',
    topics: ['hypertrophy'],
    population: 'n=43 resistance-trained men, 18-35',
    limitations: null, quality: null, status: 'unreviewed',
    visibility: 'owner', superseded_by_id: null, retracted_at: null,
    retraction_reason: null, discovered_by: 'url', current_revision: 1,
    created_at: '2026-10-01T12:00:00Z', extraction_state: 'embedded',
    chunk_count: 12, failure_category: null, failure_detail: null,
    extracted_chars: 14000, embedding_model: 'bge-m3', annotations: 0,
    ...over,
  }
}

function coverage(over: Partial<ScienceCoverage> = {}): ScienceCoverage {
  return {
    by_status: { unreviewed: 0, accepted: 0 },
    accepted_by_topic: {
      hypertrophy: 0, strength: 0, nutrition: 0, sleep: 0, recovery: 0,
      cardio: 0, injury: 0, supplements: 0,
    },
    accepted_total: 0,
    topics_with_no_evidence: [
      'cardio', 'hypertrophy', 'injury', 'nutrition', 'recovery', 'sleep',
      'strength', 'supplements',
    ],
    ranking_policy_version: 1,
    ...over,
  }
}

function hit(over: Partial<ScienceHit> = {}): ScienceHit {
  return {
    record_id: 'r1', revision: 1, chunk_id: 'c1',
    title: 'Weekly set volume and hypertrophy', authors: 'Schoenfeld et al.',
    publication_year: 2026, journal: 'JSCR', doi: '10.1234/volume',
    url: 'https://example.invalid/volume', source_type: 'rct',
    quality: 'moderate', topics: ['hypertrophy'],
    population: 'n=43 resistance-trained men',
    limitations: 'no women; twelve weeks only', section: 'Results',
    char_start: 0, char_end: 400,
    text: 'Muscle thickness increased more in the higher-volume group.',
    similarity: 0.81, lexical: 0.2, topic_match: 1, quality_weight: 0.6,
    applicability: 0, applicability_note: null, score: 1.2,
    ranking_policy_version: 1, ...over,
  }
}

interface Call { url: string; method: string; body?: unknown }

let calls: Call[] = []
let records: ScienceRecord[] = []
let coverageBody: ScienceCoverage = coverage()
let runs: ScienceRefreshRun[] = []
let registerBody: unknown = null
let registerStatus = 200
let searchHits: ScienceHit[] = []
let curateStatus = 200
let curateBody: unknown = null

function stubFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    let parsed: unknown = null
    if (typeof init?.body === 'string') {
      try { parsed = JSON.parse(init.body) } catch { parsed = init.body }
    } else if (init?.body instanceof FormData) {
      parsed = Object.fromEntries((init.body as FormData).entries())
    }
    calls.push({ url, method, body: parsed })

    const json = (status: number, payload: unknown) =>
      new Response(JSON.stringify(payload), {
        status, headers: { 'Content-Type': 'application/json' },
      })

    if (url.includes('/science/coverage')) return json(200, coverageBody)
    if (url.includes('/science/refresh-runs')) return json(200, runs)
    if (url.includes('/science/search')) {
      return json(200, {
        query: 'x', hits: searchHits, ranking_policy_version: 1,
        library: coverageBody,
      })
    }
    if (url.includes('/curate')) {
      return json(curateStatus, curateBody ?? {
        record_id: 'r1', from_status: 'unreviewed', to_status: 'accepted',
        event_id: 'e1', affected_review_ids: [],
      })
    }
    if (url.includes('/science/records/upload') && method === 'POST') {
      return json(registerStatus, registerBody ?? {
        record_id: 'r3', revision: 1, status: 'unreviewed',
        extraction_state: 'embedded', chunk_count: 41,
        duplicate_of: null, detail: null,
      })
    }
    if (url.includes('/science/records') && method === 'POST') {
      return json(registerStatus, registerBody ?? {
        record_id: 'r2', revision: 1, status: 'unreviewed',
        extraction_state: 'embedded', chunk_count: 9,
        duplicate_of: null, detail: null,
      })
    }
    if (url.includes('/science/records')) return json(200, records)
    return json(200, [])
  }) as unknown as typeof fetch
}

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  calls = []
  records = []
  coverageBody = coverage()
  runs = []
  registerBody = null
  registerStatus = 200
  searchHits = []
  curateStatus = 200
  curateBody = null
  stubFetch()
})

// ── Accepted vs new ──────────────────────────────────────────────────────

describe('accepted versus new', () => {
  it('says an empty library is empty rather than implying coverage', async () => {
    wrap(<ScienceLibrary />)
    // Wait for the content, not the container: the card renders "Loading…"
    // immediately and would satisfy a getByTestId straight away.
    await waitFor(() => expect(
      (screen.getByTestId('coverage').textContent ?? '')
        .includes('No accepted papers yet'),
    ).toBe(true))
    expect(screen.getByTestId('coverage').textContent)
      .toContain('will say so rather than answering')
  })

  it('names the topics with no accepted evidence', async () => {
    coverageBody = coverage({
      accepted_total: 2,
      accepted_by_topic: {
        hypertrophy: 2, strength: 0, nutrition: 0, sleep: 0, recovery: 0,
        cardio: 0, injury: 0, supplements: 0,
      },
      topics_with_no_evidence: ['nutrition', 'sleep'],
    })
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('gaps')).toBeTruthy())
    const text = screen.getByTestId('gaps').textContent ?? ''
    expect(text).toContain('nutrition, sleep')
    expect(text).toContain('will say the library is empty')
    expect(screen.getByTestId('topic-hypertrophy').textContent)
      .toContain('hypertrophy 2')
  })

  it('shows an unreviewed record as waiting, not as available', async () => {
    records = [record()]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('record-r1')).toBeTruthy())
    expect(screen.getByTestId('status-r1').textContent)
      .toContain('Waiting for review')
    expect(screen.getByTestId('record-r1').textContent)
      .toContain('Sara cannot cite this yet')
  })

  it('says registered-as-unreviewed, not added-to-your-library', async () => {
    // The whole point. "Added" would imply the coach can cite it.
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('register')).toBeTruthy())
    await userEvent.type(screen.getByTestId('record-title'), 'A paper')
    await userEvent.type(screen.getByTestId('record-doi'), '10.1234/x')
    await userEvent.click(screen.getByTestId('register'))

    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('Registered as unreviewed'),
    ).toBe(true))
    const text = screen.getByTestId('science-library').textContent ?? ''
    expect(text).toContain('Nothing can cite it until you accept it')
  })

  it('registers a PDF through the upload door, as multipart', async () => {
    // A file and a URL are the same act; only the transport differs. The
    // upload route takes multipart because image and document bytes never
    // go in a JSON body.
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('record-file')).toBeTruthy())

    const file = new File([new Uint8Array([37, 80, 68, 70])], 'volume.pdf', {
      type: 'application/pdf',
    })
    await userEvent.upload(screen.getByTestId('record-file'), file)
    await userEvent.type(screen.getByTestId('record-title'), 'A real paper')
    await userEvent.type(screen.getByTestId('record-doi'), '10.1234/real')
    await userEvent.click(screen.getByTestId('register'))

    await waitFor(() => expect(
      calls.some((call) => call.url.includes('/records/upload')),
    ).toBe(true))
    const posted = calls.find((call) => call.url.includes('/records/upload'))
    expect(posted?.method).toBe('POST')
    // FormData, not JSON: the stub records multipart entries as an object.
    expect(posted?.body).toMatchObject({
      title: 'A real paper',
      doi: '10.1234/real',
      source_type: 'rct',
      topics: 'hypertrophy',
    })
    // And the same "unreviewed" message, from the same mutation.
    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('Registered as unreviewed'),
    ).toBe(true))
  })

  it('uses the URL door when no file is picked', async () => {
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('register')).toBeTruthy())
    await userEvent.type(screen.getByTestId('record-title'), 'A paper')
    await userEvent.type(screen.getByTestId('record-url'), 'https://x.invalid/p')
    await userEvent.click(screen.getByTestId('register'))

    await waitFor(() => expect(
      calls.some((call) =>
        call.url.endsWith('/science/records') && call.method === 'POST'),
    ).toBe(true))
    expect(calls.some((call) => call.url.includes('/upload'))).toBe(false)
  })

  it('still requires a DOI or URL alongside a file', async () => {
    // A file on somebody's disk is not something a reader can check, so it
    // does not substitute for the identifier a citation points at.
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('record-file')).toBeTruthy())
    const file = new File([new Uint8Array([37, 80, 68, 70])], 'p.pdf', {
      type: 'application/pdf',
    })
    await userEvent.upload(screen.getByTestId('record-file'), file)
    await userEvent.type(screen.getByTestId('record-title'), 'A paper')
    expect(screen.getByTestId('register')).toBeDisabled()
  })

  it('says which door it will use', async () => {
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('record-file')).toBeTruthy())
    expect(screen.getByTestId('science-library').textContent)
      .toContain('without one, the URL below is fetched server-side')

    const file = new File([new Uint8Array([37])], 'volume.pdf', {
      type: 'application/pdf',
    })
    await userEvent.upload(screen.getByTestId('record-file'), file)
    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('Reading volume.pdf'),
    ).toBe(true))
  })

  it('reports a duplicate as a duplicate', async () => {
    registerBody = {
      record_id: 'r1', revision: 0, status: 'unreviewed',
      extraction_state: '', chunk_count: 0, duplicate_of: 'r1',
      detail: 'DOI 10.1234/x is already in the library.',
    }
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('register')).toBeTruthy())
    await userEvent.type(screen.getByTestId('record-title'), 'A paper')
    await userEvent.type(screen.getByTestId('record-doi'), '10.1234/x')
    await userEvent.click(screen.getByTestId('register'))
    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('already in the library'),
    ).toBe(true))
  })

  it('requires a DOI or a URL before registering', async () => {
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('register')).toBeTruthy())
    await userEvent.type(screen.getByTestId('record-title'), 'A paper')
    expect(screen.getByTestId('register')).toBeDisabled()
    await userEvent.type(screen.getByTestId('record-url'), 'https://x.invalid/p')
    expect(screen.getByTestId('register')).not.toBeDisabled()
  })

  it('says population is recorded rather than guessed', async () => {
    wrap(<ScienceLibrary />)
    await waitFor(() =>
      expect(screen.getByTestId('record-population')).toBeTruthy())
    const text = screen.getByTestId('science-library').textContent ?? ''
    expect(text).toContain('Recorded, never guessed')
    expect(text).toContain('not evidence about an untrained beginner')
  })
})

// ── Curation ─────────────────────────────────────────────────────────────

describe('curation', () => {
  it('will not submit an accept without limitations', async () => {
    records = [record()]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('expand-r1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('expand-r1'))

    await userEvent.type(
      screen.getByTestId('reason-r1'),
      'the volume gradient is the usable finding',
    )
    // Reason alone is not enough: the server rejects it, and a 422 is a
    // worse way to find that out.
    expect(screen.getByTestId('submit-r1')).toBeDisabled()
    await userEvent.type(
      screen.getByTestId('limitations-r1'), 'trained men only',
    )
    expect(screen.getByTestId('submit-r1')).not.toBeDisabled()
  })

  it('will not submit a reason under ten characters', async () => {
    records = [record()]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('expand-r1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('expand-r1'))
    await userEvent.type(screen.getByTestId('reason-r1'), 'good')
    await userEvent.type(screen.getByTestId('limitations-r1'), 'men only')
    expect(screen.getByTestId('submit-r1')).toBeDisabled()
  })

  it('says why the reason is required', async () => {
    records = [record()]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('expand-r1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('expand-r1'))
    const text = screen.getByTestId('curate-r1').textContent ?? ''
    expect(text).toContain('An accept with no reason is a click')
    expect(text).toContain('the ones left blank are the ones later misapplied')
  })

  it('sends the action, reason, limitations and revision', async () => {
    records = [record({ current_revision: 3 })]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('expand-r1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('expand-r1'))
    await userEvent.type(
      screen.getByTestId('reason-r1'), 'useful for the volume question',
    )
    await userEvent.type(
      screen.getByTestId('limitations-r1'), 'trained men, twelve weeks',
    )
    await userEvent.click(screen.getByTestId('submit-r1'))

    await waitFor(() => expect(
      calls.some((call) => call.url.includes('/curate')),
    ).toBe(true))
    const posted = calls.find((call) => call.url.includes('/curate'))
    expect(posted?.body).toMatchObject({
      action: 'accept',
      reason: 'useful for the volume question',
      limitations: 'trained men, twelve weeks',
      // The revision is explicit: accepting blind would accept text
      // nobody looked at.
      revision: 3,
    })
  })

  it('does not send limitations on a reject', async () => {
    records = [record()]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('expand-r1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('expand-r1'))
    await userEvent.click(screen.getByTestId('action-r1-reject'))
    await userEvent.type(
      screen.getByTestId('reason-r1'), 'the control group was not matched',
    )
    await userEvent.click(screen.getByTestId('submit-r1'))
    await waitFor(() => expect(
      calls.some((call) => call.url.includes('/curate')),
    ).toBe(true))
    const posted = calls.find((call) => call.url.includes('/curate'))
    expect((posted?.body as Record<string, unknown>).action).toBe('reject')
    expect((posted?.body as Record<string, unknown>).limitations)
      .toBeUndefined()
  })

  it('surfaces a refused transition instead of pretending it worked', async () => {
    records = [record()]
    curateStatus = 409
    curateBody = {
      detail: 'r1 is retracted; accept is not a transition from there.',
    }
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('expand-r1')).toBeTruthy())
    await userEvent.click(screen.getByTestId('expand-r1'))
    await userEvent.type(
      screen.getByTestId('reason-r1'), 'I would like to accept this one',
    )
    await userEvent.type(screen.getByTestId('limitations-r1'), 'men only')
    await userEvent.click(screen.getByTestId('submit-r1'))
    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('not a transition from there'),
    ).toBe(true))
  })

  it('shows a retraction with its reason', async () => {
    records = [record({
      status: 'retracted',
      retraction_reason: 'the journal withdrew it for data irregularities',
    })]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('record-r1')).toBeTruthy())
    expect(screen.getByTestId('record-r1').textContent)
      .toContain('withdrew it for data irregularities')
  })

  it('says a failed extraction cannot be accepted', async () => {
    records = [record({
      extraction_state: 'failed', failure_category: 'no_text',
      chunk_count: 0,
    })]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('record-r1')).toBeTruthy())
    const text = screen.getByTestId('record-r1').textContent ?? ''
    expect(text).toContain('extraction failed')
    expect(text).toContain('cannot be accepted')
  })

  it('marks a refresh-discovered record as queued and nothing more', async () => {
    records = [record({ discovered_by: 'refresh' })]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('found-r1')).toBeTruthy())
    expect(screen.getByTestId('found-r1').textContent)
      .toContain('queued this and did nothing else')
  })
})

// ── Search ───────────────────────────────────────────────────────────────

describe('search', () => {
  it('says the search covers accepted papers only', async () => {
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('search')).toBeTruthy())
    const text = screen.getByTestId('science-library').textContent ?? ''
    expect(text).toContain('Accepted papers only')
    expect(text).toContain('will not appear here however well it matches')
  })

  it('shows a hit with its population, limits and location', async () => {
    coverageBody = coverage({ accepted_total: 1 })
    searchHits = [hit()]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('search')).toBeTruthy())
    await userEvent.type(screen.getByTestId('search-query'), 'set volume')
    await userEvent.click(screen.getByTestId('search'))

    await waitFor(() => expect(screen.getByTestId('hit-c1')).toBeTruthy())
    const text = screen.getByTestId('hit-c1').textContent ?? ''
    expect(text).toContain('resistance-trained men')
    expect(text).toContain('no women; twelve weeks only')
    expect(text).toContain('Results')
    expect(text).toContain('10.1234/volume')
  })

  it('shows a population mismatch rather than hiding the hit', async () => {
    coverageBody = coverage({ accepted_total: 1 })
    searchHits = [hit({
      applicability: -0.5,
      applicability_note: 'studied trained, you are untrained',
    })]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('search')).toBeTruthy())
    await userEvent.type(screen.getByTestId('search-query'), 'set volume')
    await userEvent.click(screen.getByTestId('search'))
    await waitFor(() => expect(screen.getByTestId('mismatch-c1')).toBeTruthy())
    expect(screen.getByTestId('mismatch-c1').textContent)
      .toContain('studied trained, you are untrained')
  })

  it('says similarity is unavailable rather than showing zero', async () => {
    // Lexical-only fallback when the embedding backend is down. A 0.00
    // would read as "no match" for a hit that did match.
    coverageBody = coverage({ accepted_total: 1 })
    searchHits = [hit({ similarity: null, lexical: 0.4 })]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('search')).toBeTruthy())
    await userEvent.type(screen.getByTestId('search-query'), 'set volume')
    await userEvent.click(screen.getByTestId('search'))
    await waitFor(() => expect(screen.getByTestId('hit-c1')).toBeTruthy())
    expect(screen.getByTestId('hit-c1').textContent)
      .toContain('similarity unavailable')
  })

  it('says the library was empty when there was nothing to search', async () => {
    searchHits = []
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('search')).toBeTruthy())
    await userEvent.type(screen.getByTestId('search-query'), 'set volume')
    await userEvent.click(screen.getByTestId('search'))
    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('library is empty, so there was nothing to search'),
    ).toBe(true))
  })

  it('says nothing matched when the library is not empty', async () => {
    // The two are different answers to a coach, and one message for both
    // is how "no evidence found" becomes "the research is unclear".
    coverageBody = coverage({ accepted_total: 4 })
    searchHits = []
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('search')).toBeTruthy())
    await userEvent.type(screen.getByTestId('search-query'), 'set volume')
    await userEvent.click(screen.getByTestId('search'))
    await waitFor(() => expect(
      (screen.getByTestId('science-library').textContent ?? '')
        .includes('Nothing in the 4 accepted papers matches that'),
    ).toBe(true))
  })
})

// ── Refresh history ──────────────────────────────────────────────────────

describe('refresh history', () => {
  it('says a refresh never accepts or applies anything', async () => {
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('refresh-runs')).toBeTruthy())
    expect(screen.getByTestId('refresh-runs').textContent)
      .toContain('never accepts one and never changes a target')
  })

  it('shows a failed attempt as failed, with its reason', async () => {
    // One timestamp would make a job that has failed every month for four
    // months look healthy.
    runs = [
      {
        id: 'run-fail', attempted_at: '2026-10-01T03:00:00Z',
        finished_at: null, succeeded: false, queried_topics: ['sleep'],
        candidates_seen: 0, queued_unreviewed: 0, duplicates_skipped: 0,
        retractions_flagged: [], affected_review_ids: [],
        digest_sent: false, detail: 'discovery failed: search is down',
      },
      {
        id: 'run-ok', attempted_at: '2026-09-01T03:00:00Z',
        finished_at: '2026-09-01T03:04:00Z', succeeded: true,
        queried_topics: ['sleep'], candidates_seen: 6,
        queued_unreviewed: 2, duplicates_skipped: 4,
        retractions_flagged: [], affected_review_ids: [],
        digest_sent: true, detail: null,
      },
    ]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('run-run-fail')).toBeTruthy())
    expect(screen.getByTestId('run-run-fail').textContent)
      .toContain('attempt failed: discovery failed: search is down')
    expect(screen.getByTestId('run-run-ok').textContent)
      .toContain('2 queued, 4 already known')
  })

  it('flags retractions found by a refresh', async () => {
    runs = [{
      id: 'run-r', attempted_at: '2026-10-01T03:00:00Z',
      finished_at: '2026-10-01T03:02:00Z', succeeded: true,
      queried_topics: ['nutrition'], candidates_seen: 3,
      queued_unreviewed: 0, duplicates_skipped: 2,
      retractions_flagged: ['r1'], affected_review_ids: ['rev-1'],
      digest_sent: true, detail: null,
    }]
    wrap(<ScienceLibrary />)
    await waitFor(() => expect(screen.getByTestId('run-run-r')).toBeTruthy())
    expect(screen.getByTestId('run-run-r').textContent)
      .toContain('1 flagged as')
  })
})
