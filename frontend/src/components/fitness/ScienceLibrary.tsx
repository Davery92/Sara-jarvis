/**
 * Fitness → Coach → Science.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 28. Completion criteria: a small
 * accepted library supports real attributable retrieval; a refresh cannot
 * silently alter the evidence; the citation trail reconstructs what was
 * retrieved.
 *
 * Five things this screen is careful about:
 *
 * 1. **Ingested is not accepted.** A new record says `unreviewed`, in that
 *    word, with a line saying the coach cannot cite it yet. "Added to the
 *    library" would imply the opposite of what the curation step is for.
 * 2. **The queue comes first.** Unreviewed records sort to the top, because
 *    the page exists to get decisions made; sorting by date buries them.
 * 3. **Acceptance asks for limitations.** Not as a nicety — the server
 *    rejects an accept without them, and the form says why: every paper has
 *    limitations, and the ones left blank are the ones later misapplied.
 * 4. **An empty library says it is empty.** Coverage is shown per topic
 *    with the gaps named. "The research suggests" over nothing is the
 *    failure the whole step exists to prevent.
 * 5. **A refresh reports attempts, not just successes.** A run that failed
 *    shows as failed with its reason, beside the ones that worked.
 */
import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, BookOpen, Check, Search, X,
} from 'lucide-react'

import { scienceApi, type RegisterInput } from '../../api/fitnessScience'
import { useAuthStore } from '../../stores/authStore'
import type {
  EvidenceQuality,
  ScienceCurationAction,
  ScienceHit,
  ScienceRecord,
  ScienceStatus,
  ScienceTopic,
  SourceType,
} from '../../types/fitnessCoach'

const SECTION =
  'text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'
const CARD = 'rounded-xl border border-white/10 bg-white/[0.03] p-4'
const FIELD =
  'w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 ' +
  'text-[15px] text-slate-100 placeholder:text-slate-600 focus:outline-none ' +
  'focus:border-teal-400/50'
const PRIMARY =
  'px-4 py-2 rounded-lg bg-teal-500/90 hover:bg-teal-400 text-slate-950 ' +
  'text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed'
const GHOST =
  'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 ' +
  'hover:bg-white/[0.04] disabled:opacity-40'

const TOPICS: ScienceTopic[] = [
  'hypertrophy', 'strength', 'nutrition', 'sleep', 'recovery', 'cardio',
  'injury', 'supplements',
]

const SOURCE_TYPES: Array<{ value: SourceType; label: string }> = [
  { value: 'meta_analysis', label: 'Meta-analysis' },
  { value: 'systematic_review', label: 'Systematic review' },
  { value: 'rct', label: 'Randomised trial' },
  { value: 'observational', label: 'Observational' },
  { value: 'narrative_review', label: 'Narrative review' },
  { value: 'position_stand', label: 'Position stand' },
  { value: 'secondary', label: 'Secondary / synthesis' },
]

const STATUS_LABEL: Record<ScienceStatus, string> = {
  unreviewed: 'Waiting for review',
  accepted: 'Accepted',
  rejected: 'Rejected',
  superseded: 'Superseded',
  retracted: 'Retracted',
}

const STATUS_TONE: Record<ScienceStatus, string> = {
  unreviewed: 'text-amber-300/90 border-amber-400/70',
  accepted: 'text-teal-300/90 border-teal-400/70',
  rejected: 'text-slate-500 border-white/10',
  superseded: 'text-slate-500 border-white/10',
  retracted: 'text-rose-300/90 border-rose-400/70',
}

function Note({
  message, tone = 'warn',
}: { message: string; tone?: 'warn' | 'ok' }) {
  const colour = tone === 'ok'
    ? 'text-teal-300/90 border-teal-400/70'
    : 'text-amber-300/90 border-amber-400/70'
  return (
    <div
      className={`flex items-start gap-2 text-xs ${colour} border-l-2 pl-3 py-1`}
    >
      {tone === 'ok'
        ? <Check className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
        : <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />}
      <span>{message}</span>
    </div>
  )
}

/** The accept form. Limitations are required, and it says why. */
function CurationForm({
  record, onDone, onError,
}: {
  record: ScienceRecord
  onDone: (message: string) => void
  onError: (message: string) => void
}) {
  const client = useQueryClient()
  const athleteId = useAuthStore((state) => state.user?.id)
  const [action, setAction] = useState<ScienceCurationAction>('accept')
  const [reason, setReason] = useState('')
  const [limitations, setLimitations] = useState(record.limitations ?? '')
  const [quality, setQuality] = useState<EvidenceQuality | ''>(
    record.quality ?? '',
  )

  const curate = useMutation({
    mutationFn: () => scienceApi.curate(record.id, {
      action, reason, revision: record.current_revision,
      limitations: action === 'accept' ? limitations : undefined,
      quality: quality || undefined,
    }),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ['science', athleteId] })
      onDone(
        `${record.title.slice(0, 40)} → ${
          String((result as Record<string, unknown>).to_status ?? action)
        }.`,
      )
      setReason('')
    },
    onError: (caught) => onError(
      caught instanceof Error ? caught.message : 'Could not record that.',
    ),
  })

  // The server requires both; disabling the button is kinder than a 422.
  const ready = reason.trim().length >= 10
    && (action !== 'accept' || limitations.trim().length > 0)

  return (
    <div className="space-y-2 pt-2" data-testid={`curate-${record.id}`}>
      <div className="flex flex-wrap gap-1.5">
        {(['accept', 'reject', 'retract'] as ScienceCurationAction[]).map(
          (option) => (
            <button
              key={option}
              className={`px-2.5 py-1 rounded-md text-[11px] border ${
                action === option
                  ? 'border-teal-400/70 text-teal-200'
                  : 'border-white/10 text-slate-400'
              }`}
              aria-pressed={action === option}
              onClick={() => setAction(option)}
              data-testid={`action-${record.id}-${option}`}
            >
              {option}
            </button>
          ),
        )}
      </div>

      <textarea
        className={`${FIELD} text-[13px]`}
        rows={2}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Why — what is this good for, and what are you accepting it despite?"
        data-testid={`reason-${record.id}`}
      />
      <p className="text-[10px] text-slate-600">
        At least ten characters. An accept with no reason is a click, and the
        reason is what you will need in six months.
      </p>

      {action === 'accept' && (
        <>
          <textarea
            className={`${FIELD} text-[13px]`}
            rows={2}
            value={limitations}
            onChange={(event) => setLimitations(event.target.value)}
            placeholder="What it cannot support — population, duration, design"
            data-testid={`limitations-${record.id}`}
          />
          <p className="text-[10px] text-slate-600">
            Required. Every paper has limitations, and the ones left blank are
            the ones later misapplied.
          </p>
          <select
            className={`${FIELD} text-[13px]`}
            value={quality}
            onChange={(event) =>
              setQuality(event.target.value as EvidenceQuality | '')}
            data-testid={`quality-${record.id}`}
          >
            <option value="">Grade (optional)</option>
            <option value="high">High</option>
            <option value="moderate">Moderate</option>
            <option value="low">Low</option>
          </select>
        </>
      )}

      <button
        className={PRIMARY}
        disabled={!ready || curate.isPending}
        onClick={() => curate.mutate()}
        data-testid={`submit-${record.id}`}
      >
        {curate.isPending ? 'Recording…' : `Record ${action}`}
      </button>
    </div>
  )
}

export default function ScienceLibrary() {
  const client = useQueryClient()
  const athleteId = useAuthStore((state) => state.user?.id)

  const [notice, setNotice] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [doi, setDoi] = useState('')
  const [sourceType, setSourceType] = useState<SourceType>('rct')
  const [topics, setTopics] = useState<ScienceTopic[]>(['hypertrophy'])
  const [population, setPopulation] = useState('')

  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<ScienceHit[] | null>(null)

  const records = useQuery({
    queryKey: ['science', athleteId, 'records'],
    queryFn: () => scienceApi.records(),
    enabled: Boolean(athleteId),
  })
  const coverage = useQuery({
    queryKey: ['science', athleteId, 'coverage'],
    queryFn: () => scienceApi.coverage(),
    enabled: Boolean(athleteId),
  })
  const runs = useQuery({
    queryKey: ['science', athleteId, 'runs'],
    queryFn: () => scienceApi.refreshRuns(),
    enabled: Boolean(athleteId),
  })

  const register = useMutation({
    mutationFn: (input: RegisterInput) => scienceApi.register(input),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ['science', athleteId] })
      if (result.duplicate_of) {
        setWarning(result.detail ?? 'Already in the library.')
        return
      }
      setTitle('')
      setUrl('')
      setDoi('')
      setPopulation('')
      // The word matters: "added" would imply the coach can cite it.
      setNotice(
        `Registered as unreviewed (${result.chunk_count} passages). ` +
        `Nothing can cite it until you accept it.`,
      )
    },
    onError: (caught) => setWarning(
      caught instanceof Error ? caught.message : 'Could not register that.',
    ),
  })

  const search = useMutation({
    mutationFn: () => scienceApi.search(query),
    onSuccess: (response) => setHits(response.hits),
    onError: (caught) => setWarning(
      caught instanceof Error ? caught.message : 'Could not search.',
    ),
  })

  const grouped = useMemo(() => {
    const all = records.data ?? []
    return {
      queue: all.filter((record) => record.status === 'unreviewed'),
      rest: all.filter((record) => record.status !== 'unreviewed'),
    }
  }, [records.data])

  const toggleTopic = (topic: ScienceTopic) => {
    setTopics((current) => current.includes(topic)
      ? current.filter((item) => item !== topic)
      : [...current, topic])
  }

  const accepted = coverage.data?.accepted_total ?? 0

  return (
    <div className="p-6 space-y-8 max-w-[900px]" data-testid="science-library">
      {/* ── Coverage ─────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Evidence on hand</h2>
        <div className={CARD} data-testid="coverage">
          {coverage.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : accepted === 0 ? (
            <Note message={
              'No accepted papers yet. Until you accept something, Sara has '
              + 'no library to cite and will say so rather than answering '
              + 'from memory.'
            } />
          ) : (
            <>
              <p className="text-sm text-slate-300" data-testid="accepted-total">
                {accepted} accepted {accepted === 1 ? 'paper' : 'papers'}.
              </p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {TOPICS.map((topic) => {
                  const count = coverage.data?.accepted_by_topic?.[topic] ?? 0
                  return (
                    <span
                      key={topic}
                      className={`px-2 py-0.5 rounded-md text-[11px] border ${
                        count > 0
                          ? 'border-teal-400/40 text-teal-200/90'
                          : 'border-white/10 text-slate-600'
                      }`}
                      data-testid={`topic-${topic}`}
                    >
                      {topic} {count}
                    </span>
                  )
                })}
              </div>
              {(coverage.data?.topics_with_no_evidence?.length ?? 0) > 0 && (
                <p
                  className="text-[11px] text-slate-500 mt-2"
                  data-testid="gaps"
                >
                  Nothing accepted on{' '}
                  {coverage.data?.topics_with_no_evidence.join(', ')}. Sara
                  will say the library is empty on those rather than filling
                  the gap.
                </p>
              )}
            </>
          )}
        </div>
      </section>

      {/* ── Register ─────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Add a source</h2>
        <div className={`${CARD} space-y-3`}>
          <input
            className={FIELD}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Title, as published"
            data-testid="record-title"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              className={FIELD}
              value={doi}
              onChange={(event) => setDoi(event.target.value)}
              placeholder="DOI (10.…)"
              data-testid="record-doi"
            />
            <input
              className={FIELD}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://…"
              data-testid="record-url"
            />
          </div>
          <select
            className={FIELD}
            value={sourceType}
            onChange={(event) =>
              setSourceType(event.target.value as SourceType)}
            data-testid="record-type"
          >
            {SOURCE_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <input
            className={FIELD}
            value={population}
            onChange={(event) => setPopulation(event.target.value)}
            placeholder="Who was studied — 'n=43 resistance-trained men, 18-35'"
            data-testid="record-population"
          />
          <p className="text-[10px] text-slate-600">
            Recorded, never guessed. A finding from trained men is not
            evidence about an untrained beginner, and retrieval can only see
            the mismatch if this is filled in.
          </p>
          <div className="flex flex-wrap gap-1.5" data-testid="topic-picker">
            {TOPICS.map((topic) => (
              <button
                key={topic}
                className={`px-2.5 py-1 rounded-md text-[11px] border ${
                  topics.includes(topic)
                    ? 'border-teal-400/70 text-teal-200'
                    : 'border-white/10 text-slate-400'
                }`}
                aria-pressed={topics.includes(topic)}
                onClick={() => toggleTopic(topic)}
                data-testid={`pick-${topic}`}
              >
                {topic}
              </button>
            ))}
          </div>
          <button
            className={PRIMARY}
            disabled={
              register.isPending || !title.trim()
              || (!doi.trim() && !url.trim()) || topics.length === 0
            }
            onClick={() => register.mutate({
              title: title.trim(),
              source_type: sourceType,
              topics,
              doi: doi.trim() || undefined,
              url: url.trim() || undefined,
              population: population.trim() || undefined,
            })}
            data-testid="register"
          >
            <BookOpen className="w-3.5 h-3.5 inline mr-1" />
            {register.isPending ? 'Fetching…' : 'Register as unreviewed'}
          </button>
          <p className="text-[10px] text-slate-600">
            A DOI or a URL is required — without one there is nothing to cite
            and no way to tell a duplicate from a new paper.
          </p>
        </div>
        {notice && <Note message={notice} tone="ok" />}
        {warning && <Note message={warning} />}
      </section>

      {/* ── The queue ────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>
          Waiting for review ({grouped.queue.length})
        </h2>
        {grouped.queue.length === 0 ? (
          <div className={CARD} data-testid="queue-empty">
            <p className="text-sm text-slate-500">Nothing waiting.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {grouped.queue.map((record) => (
              <div
                key={record.id}
                className={CARD}
                data-testid={`record-${record.id}`}
              >
                <RecordHeader record={record} />
                <button
                  className={GHOST}
                  onClick={() =>
                    setExpanded(expanded === record.id ? null : record.id)}
                  data-testid={`expand-${record.id}`}
                >
                  {expanded === record.id ? 'Close' : 'Review it'}
                </button>
                {expanded === record.id && (
                  <CurationForm
                    record={record}
                    onDone={(message) => {
                      setNotice(message)
                      setWarning(null)
                      setExpanded(null)
                    }}
                    onError={setWarning}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Search ───────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Search accepted evidence</h2>
        <div className={`${CARD} space-y-3`}>
          <div className="flex gap-2">
            <input
              className={FIELD}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="training frequency for hypertrophy"
              data-testid="search-query"
            />
            <button
              className={PRIMARY}
              disabled={query.trim().length < 3 || search.isPending}
              onClick={() => search.mutate()}
              data-testid="search"
            >
              <Search className="w-3.5 h-3.5 inline mr-1" />
              {search.isPending ? '…' : 'Search'}
            </button>
          </div>
          <p className="text-[10px] text-slate-600">
            Accepted papers only. An unreviewed one will not appear here
            however well it matches.
          </p>

          {hits !== null && hits.length === 0 && (
            <Note message={
              accepted === 0
                ? 'The library is empty, so there was nothing to search.'
                : `Nothing in the ${accepted} accepted papers matches that.`
            } />
          )}
          {hits?.map((hit) => (
            <div
              key={hit.chunk_id}
              className="border-l-2 border-white/10 pl-3 py-1 space-y-1"
              data-testid={`hit-${hit.chunk_id}`}
            >
              <p className="text-[13px] text-slate-200">
                {hit.title}
                {hit.publication_year ? ` (${hit.publication_year})` : ''}
              </p>
              <p className="text-[12px] text-slate-400">{hit.text}</p>
              {hit.population && (
                <p className="text-[11px] text-slate-500">
                  Population: {hit.population}
                </p>
              )}
              {hit.limitations && (
                <p className="text-[11px] text-slate-500">
                  Limits: {hit.limitations}
                </p>
              )}
              {hit.applicability_note && (
                <p
                  className="text-[11px] text-amber-300/90"
                  data-testid={`mismatch-${hit.chunk_id}`}
                >
                  Mismatch: {hit.applicability_note}
                </p>
              )}
              <p className="text-[10px] text-slate-600">
                {hit.section ?? 'unlabelled section'}
                {' · '}
                {hit.similarity === null
                  ? 'similarity unavailable (embedding backend down)'
                  : `similarity ${hit.similarity.toFixed(2)}`}
                {hit.doi ? ` · ${hit.doi}` : ''}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Curated ──────────────────────────────────────────────────── */}
      {grouped.rest.length > 0 && (
        <section className="space-y-3">
          <h2 className={SECTION}>Curated ({grouped.rest.length})</h2>
          <div className="space-y-2">
            {grouped.rest.map((record) => (
              <div
                key={record.id}
                className={CARD}
                data-testid={`record-${record.id}`}
              >
                <RecordHeader record={record} />
                {record.status === 'retracted' && record.retraction_reason && (
                  <p className="text-[11px] text-rose-300/90 mt-1">
                    Retracted: {record.retraction_reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Refresh history ──────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Monthly refresh</h2>
        <div className={CARD} data-testid="refresh-runs">
          {(runs.data?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-500">
              No refresh has run yet. A refresh queues papers for review — it
              never accepts one and never changes a target.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {runs.data?.map((run) => (
                <li
                  key={run.id}
                  className="text-[12px] flex items-start gap-2"
                  data-testid={`run-${run.id}`}
                >
                  {run.succeeded
                    ? <Check className="w-3 h-3 mt-1 text-teal-300/90" />
                    : <X className="w-3 h-3 mt-1 text-rose-300/90" />}
                  <span className="text-slate-400">
                    {run.attempted_at?.slice(0, 16).replace('T', ' ')}
                    {' — '}
                    {run.succeeded
                      ? `${run.queued_unreviewed} queued, ` +
                        `${run.duplicates_skipped} already known`
                      : `attempt failed${run.detail ? `: ${run.detail}` : ''}`}
                    {run.retractions_flagged.length > 0 && (
                      <span className="text-rose-300/90">
                        {' '}· {run.retractions_flagged.length} flagged as
                        retracted
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  )
}

function RecordHeader({ record }: { record: ScienceRecord }) {
  return (
    <div className="space-y-1">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[14px] text-slate-200">{record.title}</p>
        <span
          className={`text-[10px] px-2 py-0.5 rounded-md border flex-shrink-0 ${
            STATUS_TONE[record.status]
          }`}
          data-testid={`status-${record.id}`}
        >
          {STATUS_LABEL[record.status]}
        </span>
      </div>
      <p className="text-[11px] text-slate-500">
        {[
          record.authors,
          record.publication_year ? String(record.publication_year) : null,
          record.journal,
          record.source_type.replace(/_/g, ' '),
        ].filter(Boolean).join(' · ')}
      </p>
      {record.population && (
        <p className="text-[11px] text-slate-500">
          Population: {record.population}
        </p>
      )}
      {record.discovered_by === 'refresh' && (
        <p className="text-[10px] text-slate-600" data-testid={`found-${record.id}`}>
          Found by the monthly refresh. It queued this and did nothing else.
        </p>
      )}
      {record.extraction_state === 'failed' && (
        <p className="text-[11px] text-amber-300/90">
          Text extraction failed
          {record.failure_category ? ` (${record.failure_category})` : ''}.
          Nothing was embedded, so it cannot be accepted.
        </p>
      )}
      {record.status === 'unreviewed' && (
        <p className="text-[10px] text-slate-600">
          Sara cannot cite this yet.
          {record.chunk_count ? ` ${record.chunk_count} passages ready.` : ''}
        </p>
      )}
    </div>
  )
}
