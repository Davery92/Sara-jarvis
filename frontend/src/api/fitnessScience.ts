/**
 * Curated science library client.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 28. Separate from
 * `api/fitnessCoach.ts` because the library's own concerns — ingestion,
 * curation, retrieval — have nothing to do with check-ins and targets, and
 * a reader of either should not have to page through the other.
 *
 * The one thing this client must never do is blur ingested with accepted.
 * `register` returns `status: 'unreviewed'`, and the UI shows that word:
 * "added to the library" would imply the coach can now cite it, which is
 * exactly what the curation step exists to withhold.
 */
import { APP_CONFIG } from '../config'
import type {
  EvidenceQuality,
  ScienceCurationAction,
  ScienceCoverage,
  ScienceIngestResult,
  ScienceRecord,
  ScienceRefreshRun,
  ScienceSearchResponse,
  ScienceStatus,
  ScienceTopic,
  SourceType,
} from '../types/fitnessCoach'

const BASE = `${APP_CONFIG.apiUrl}/api/fitness/science`

export class ScienceError extends Error {
  status?: number
  code?: string

  constructor(message: string, status?: number, code?: string) {
    super(message)
    this.name = 'ScienceError'
    this.status = status
    this.code = code
  }
}

async function failure(response: Response): Promise<ScienceError> {
  let detail = `Request failed (${response.status})`
  let code: string | undefined
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') {
      detail = body.detail
    } else if (body?.detail && typeof body.detail === 'object') {
      // The ingest refusals carry a category — "no_text" and
      // "fetch_blocked" call for completely different reactions, and a
      // generic message would send someone re-exporting a fine PDF.
      detail = body.detail.message ?? detail
      code = body.detail.code
    }
  } catch {
    // Non-JSON body. The status is still useful.
  }
  return new ScienceError(detail, response.status, code)
}

export interface RegisterInput {
  title: string
  source_type: SourceType
  topics: ScienceTopic[]
  url?: string
  doi?: string
  authors?: string
  publication_year?: number
  journal?: string
  population?: string
  limitations?: string
  quality?: EvidenceQuality
  notes?: string
}

export const scienceApi = {
  records: async (status?: ScienceStatus): Promise<ScienceRecord[]> => {
    const query = status ? `?${new URLSearchParams({ status })}` : ''
    const response = await fetch(`${BASE}/records${query}`, {
      credentials: 'include',
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  coverage: async (): Promise<ScienceCoverage> => {
    const response = await fetch(`${BASE}/coverage`, { credentials: 'include' })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  /** Register by URL. Fetched server-side under the SSRF and size bounds. */
  register: async (input: RegisterInput): Promise<ScienceIngestResult> => {
    const response = await fetch(`${BASE}/records`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  upload: async (
    file: File, input: RegisterInput,
  ): Promise<ScienceIngestResult> => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', input.title)
    form.append('source_type', input.source_type)
    form.append('topics', input.topics.join(','))
    if (input.doi) form.append('doi', input.doi)
    if (input.url) form.append('url', input.url)
    if (input.authors) form.append('authors', input.authors)
    if (input.publication_year != null) {
      form.append('publication_year', String(input.publication_year))
    }
    if (input.journal) form.append('journal', input.journal)
    if (input.population) form.append('population', input.population)
    if (input.limitations) form.append('limitations', input.limitations)
    if (input.quality) form.append('quality', input.quality)
    if (input.notes) form.append('notes', input.notes)

    const response = await fetch(`${BASE}/records/upload`, {
      method: 'POST', credentials: 'include', body: form,
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  /**
   * One curation decision. The reason is required by the server and by a
   * CHECK constraint, so the form cannot make it optional.
   */
  curate: async (
    recordId: string,
    payload: {
      action: ScienceCurationAction
      reason: string
      revision: number
      limitations?: string
      quality?: EvidenceQuality
      superseded_by_id?: string
    },
  ): Promise<Record<string, unknown>> => {
    const response = await fetch(
      `${BASE}/records/${encodeURIComponent(recordId)}/curate`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  history: async (recordId: string): Promise<Array<Record<string, unknown>>> => {
    const response = await fetch(
      `${BASE}/records/${encodeURIComponent(recordId)}/history`,
      { credentials: 'include' },
    )
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  search: async (
    query: string, topics?: ScienceTopic[],
  ): Promise<ScienceSearchResponse> => {
    const params = new URLSearchParams({ q: query })
    if (topics?.length) params.set('topics', topics.join(','))
    const response = await fetch(`${BASE}/search?${params}`, {
      credentials: 'include',
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },

  refreshRuns: async (): Promise<ScienceRefreshRun[]> => {
    const response = await fetch(`${BASE}/refresh-runs`, {
      credentials: 'include',
    })
    if (!response.ok) throw await failure(response)
    return response.json()
  },
}
