/**
 * Fitness → Progress → Photos.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 26. Completion criteria: standard
 * captures work with no LLM; privacy and cleanup failures are tracked
 * truthfully.
 *
 * Five things this screen is careful about, because the subject is
 * somebody's body:
 *
 * 1. **Front/side/back are separate slots.** A comparison across views is
 *    not a change in the athlete, so the upload asks which view it is and
 *    the gallery groups by it.
 * 2. **Capture conditions are recorded, not inferred.** Lighting and
 *    distance dominate photo-to-photo difference. Asking once makes a later
 *    comparison honest; guessing makes it a lie.
 * 3. **A delete that could not remove the bytes says so.** The backend
 *    returns `deleted: false` with `pending_cleanup`, and this screen
 *    repeats that rather than showing a tick. "Deleted" when the file is
 *    still in storage is the one message it must not send.
 * 4. **Analysis is opt-in per photo, and only where a model can see.**
 *    Step 27's vision pass is offered only on a photo whose consent switch
 *    is on, and only when `/vision-capability` says a probed endpoint is
 *    reachable — a llama.cpp server started without `--mmproj` serves the
 *    same model over the same API and answers the text prompt alone, so a
 *    button that "worked" there would produce confident fiction. The legacy
 *    critique stays shown as what it is.
 * 5. **No body-fat number anywhere.** Not in a field, not in a label, not
 *    in a prompt, and not in a place to display one. A single photo cannot
 *    support one, the server has no field for it, and an estimate smuggled
 *    into prose is rejected before it reaches here.
 * 6. **An observation says how sure it is, and inconclusive is a result.**
 *    "These two cannot honestly be compared" is frequently the only true
 *    reading of two photos taken in different light. It is rendered as an
 *    answer, not as a failure to retry.
 */
import React, { useMemo, useRef, useState } from 'react'
import { AlertTriangle, Camera, Check, Eye, Trash2, X } from 'lucide-react'

import { photoAnalysisApi, progressPhotoApi } from '../../api/progressPhotos'
import { useAthleteToday, useMeasurementPeriods } from '../../hooks/useFitnessCoach'
import type {
  PhotoAnalysisRow, PhotoComparability, PhotoComparison, PhotoObservation,
  PhotoView, ProgressPhoto, VisionCapability,
} from '../../types/fitnessCoach'

const SECTION = 'text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'
const CARD = 'rounded-xl border border-white/10 bg-white/[0.03] p-4'
const FIELD =
  'w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-[15px] ' +
  'text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-400/50'
const PRIMARY =
  'px-4 py-2 rounded-lg bg-teal-500/90 hover:bg-teal-400 text-slate-950 ' +
  'text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed'
const GHOST =
  'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 ' +
  'hover:bg-white/[0.04] disabled:opacity-40'

const VIEWS: PhotoView[] = ['front', 'side', 'back', 'other']

const VIEW_LABEL: Record<PhotoView, string> = {
  front: 'Front', side: 'Side', back: 'Back', other: 'Other',
}

/** Common lighting descriptions, so two sessions can match on one. */
const LIGHTING_OPTIONS = [
  'window daylight', 'overhead room light', 'bathroom light',
  'gym lighting', 'flash',
]

function Note({ message, tone = 'warn' }: { message: string; tone?: 'warn' | 'ok' }) {
  const colour = tone === 'ok'
    ? 'text-teal-300/90 border-teal-400/70'
    : 'text-amber-300/90 border-amber-400/70'
  return (
    <div className={`flex items-start gap-2 text-xs ${colour} border-l-2 pl-3 py-1`}>
      {tone === 'ok'
        ? <Check className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
        : <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />}
      <span>{message}</span>
    </div>
  )
}

const CONFIDENCE_LABEL: Record<string, string> = {
  low: 'Low confidence', moderate: 'Moderate confidence', high: 'High confidence',
}

const VERDICT_LABEL: Record<string, string> = {
  comparable: 'Comparable',
  inconclusive: 'Inconclusive',
  not_comparable: 'Not comparable',
}

/**
 * One stored observation.
 *
 * Shows confidence and image quality as two separate facts, because they
 * are: a clear photo can support only a weak statement, and a confident
 * reading of a badly lit one needs to stay visible as exactly that.
 */
function Observation({ row }: { row: PhotoAnalysisRow }) {
  if (row.status === 'failed' || row.status === 'source_gone') {
    return (
      <div className="text-[11px] text-slate-500" data-testid="observation-failed">
        Sara looked and could not describe it honestly
        {row.failure_category ? ` (${row.failure_category.replace(/_/g, ' ')})` : ''}.
        Nothing was stored.
      </div>
    )
  }

  const output = row.output as PhotoObservation | PhotoComparison | null
  if (!output) return null
  const verdict = (output as PhotoComparison).verdict
  const reason = (output as PhotoComparison).inconclusive_reason

  return (
    <div
      className="space-y-1.5 text-[11px] border-l-2 border-white/10 pl-3"
      data-testid={`observation-${row.analysis_id}`}
    >
      {verdict && (
        <p
          className={
            verdict === 'comparable' ? 'text-teal-300/90' : 'text-amber-300/90'
          }
          data-testid="observation-verdict"
        >
          {VERDICT_LABEL[verdict] ?? verdict}
          {reason ? ` — ${reason}` : ''}
        </p>
      )}

      <p className="text-slate-300">{output.summary}</p>

      {output.regions.length > 0 && (
        <ul className="space-y-0.5 text-slate-400">
          {output.regions.map((region, index) => (
            <li key={`${region.region}-${index}`}>
              <span className="text-slate-500">{region.region}:</span>{' '}
              {region.observation}
            </li>
          ))}
        </ul>
      )}

      {output.limitations.length > 0 && (
        <ul className="text-slate-500 space-y-0.5" data-testid="observation-limits">
          {output.limitations.map((limitation, index) => (
            <li key={index}>· {limitation}</li>
          ))}
        </ul>
      )}

      <p className="text-[10px] text-slate-600">
        {CONFIDENCE_LABEL[output.confidence] ?? output.confidence}
        {' · '}image {output.image_quality}
        {output.confidence_basis ? ` · ${output.confidence_basis}` : ''}
      </p>
      <p className="text-[10px] text-slate-600">
        Described by {row.model_actual ?? 'a local model'}. A description, not
        a measurement — nothing in your records came from it.
        {!row.vision_verified && (
          <span className="block text-amber-300/80">
            This ran on an endpoint that had not passed the vision check, so
            it may describe the prompt rather than the photo.
          </span>
        )}
      </p>
    </div>
  )
}


export default function ProgressPhotos() {
  const todayQuery = useAthleteToday()
  const periodsQuery = useMeasurementPeriods()
  const athleteToday = todayQuery.data?.athlete_local_date ?? ''

  const [photos, setPhotos] = useState<ProgressPhoto[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const [view, setView] = useState<PhotoView>('front')
  const [periodId, setPeriodId] = useState('')
  const [lighting, setLighting] = useState('')
  const [distance, setDistance] = useState('')
  const [notes, setNotes] = useState('')

  const [comparison, setComparison] = useState<PhotoComparability | null>(null)
  const [comparePair, setComparePair] = useState<[string, string] | null>(null)

  const [capability, setCapability] = useState<VisionCapability | null>(null)
  const [analyses, setAnalyses] = useState<PhotoAnalysisRow[]>([])
  const [analysing, setAnalysing] = useState<string | null>(null)

  const load = React.useCallback(async () => {
    setLoadError(null)
    try {
      setPhotos(await progressPhotoApi.list())
    } catch (caught) {
      setPhotos([])
      setLoadError(
        caught instanceof Error ? caught.message : 'Could not load photos.',
      )
    }
  }, [])

  const loadAnalyses = React.useCallback(async () => {
    try {
      setAnalyses(await photoAnalysisApi.list())
    } catch {
      // Observations are an extra, not the screen. A failure to list them
      // must not take down the gallery or the upload form — §27.5: an
      // analysis failure cannot block capture.
      setAnalyses([])
    }
  }, [])

  React.useEffect(() => { void load() }, [load])
  React.useEffect(() => { void loadAnalyses() }, [loadAnalyses])

  React.useEffect(() => {
    // Asked once. If no probed endpoint is reachable, the affordance is
    // hidden entirely rather than offered and failing — and "Sara cannot
    // see photos right now" becomes a visible fact.
    let cancelled = false
    photoAnalysisApi.capability()
      .then((result) => { if (!cancelled) setCapability(result) })
      .catch(() => {
        if (!cancelled) {
          setCapability({
            available: false, model: null, endpoint: null,
            detail: 'Could not check whether a vision model is available.',
          })
        }
      })
    return () => { cancelled = true }
  }, [])

  const byPhoto = useMemo(() => {
    const groups: Record<string, PhotoAnalysisRow[]> = {}
    for (const row of analyses) {
      if (row.kind !== 'single') continue
      groups[row.source_photo_id] = groups[row.source_photo_id] ?? []
      groups[row.source_photo_id].push(row)
    }
    return groups
  }, [analyses])

  const byView = useMemo(() => {
    const groups: Record<string, ProgressPhoto[]> = {}
    for (const photo of photos ?? []) {
      const key = photo.view ?? 'other'
      groups[key] = groups[key] ?? []
      groups[key].push(photo)
    }
    return groups
  }, [photos])

  const periods = periodsQuery.data ?? []

  const upload = async () => {
    const file = fileInput.current?.files?.[0]
    if (!file) {
      setUploadError('Pick a photo first.')
      return
    }
    setBusy(true)
    setUploadError(null)
    setNotice(null)
    try {
      await progressPhotoApi.upload({
        file,
        view,
        periodId: periodId || undefined,
        notes: notes || undefined,
        takenAt: athleteToday ? `${athleteToday}T12:00:00Z` : undefined,
        lighting: lighting || undefined,
        distanceCm: distance ? Number(distance) : undefined,
      })
      if (fileInput.current) fileInput.current.value = ''
      setNotes('')
      setNotice(`${VIEW_LABEL[view]} photo saved.`)
      await load()
    } catch (caught) {
      // The server's own words: it knows whether the file was too large,
      // undecodable or the wrong type, and a generic "upload failed" would
      // leave someone guessing.
      setUploadError(
        caught instanceof Error ? caught.message : 'Could not save that photo.',
      )
    } finally {
      setBusy(false)
    }
  }

  const remove = async (photo: ProgressPhoto) => {
    setWarning(null)
    setNotice(null)
    try {
      const result = await progressPhotoApi.remove(photo.id)
      await load()
      if (result.deleted) {
        setNotice('Deleted.')
      } else {
        // The bytes are still in storage. Saying "deleted" here would be
        // the one message this screen must not send.
        setWarning(result.message)
      }
    } catch (caught) {
      setWarning(
        caught instanceof Error ? caught.message : 'Could not delete that.',
      )
    }
  }

  const toggleConsent = async (photo: ProgressPhoto) => {
    try {
      await progressPhotoApi.setAnalysisConsent(
        photo.id, !photo.consent_analysis,
      )
      await load()
    } catch (caught) {
      setWarning(
        caught instanceof Error ? caught.message : 'Could not change that.',
      )
    }
  }

  const analyse = async (photo: ProgressPhoto) => {
    setWarning(null)
    setNotice(null)
    setAnalysing(photo.id)
    try {
      const result = await photoAnalysisApi.analyse(photo.id)
      await loadAnalyses()
      if (result.status === 'complete' || result.status === 'inconclusive') {
        setNotice(result.duplicate ? 'Already described.' : 'Described.')
      } else {
        // The server's category, not a generic failure: "the model is
        // unreachable" and "the model tried to state a body-fat number"
        // call for completely different reactions.
        setWarning(result.detail ?? 'Could not describe that photo.')
      }
    } catch (caught) {
      setWarning(
        caught instanceof Error ? caught.message : 'Could not describe that.',
      )
    } finally {
      setAnalysing(null)
    }
  }

  const checkComparable = async (a: string, b: string) => {
    setComparison(null)
    setComparePair([a, b])
    try {
      setComparison(await progressPhotoApi.comparable(a, b, view))
    } catch (caught) {
      setWarning(
        caught instanceof Error ? caught.message : 'Could not compare those.',
      )
    }
  }

  return (
    <div className="p-6 space-y-8 max-w-[860px]" data-testid="progress-photos">
      {/* ── Capture ──────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className={SECTION}>Add a photo</h2>
          <p className="text-xs text-slate-500 mt-1">
            Front, side and back are tracked separately — a front shot
            against a side shot is not a change in you. Recording the
            lighting and distance is what makes a later comparison mean
            anything.
          </p>
        </div>

        <div className={CARD}>
          <div className="flex flex-wrap gap-1.5 mb-3" data-testid="view-picker">
            {VIEWS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setView(option)}
                data-testid={`view-${option}`}
                aria-pressed={view === option}
                className={`px-3 py-1.5 rounded-lg text-sm border ${
                  view === option
                    ? 'border-teal-400/40 bg-teal-400/[0.08] text-teal-200'
                    : 'border-white/10 text-slate-400 hover:text-slate-200'
                }`}
              >
                {VIEW_LABEL[option]}
              </button>
            ))}
          </div>

          <label className="block text-xs text-slate-400 mb-1" htmlFor="photo-file">
            Photo
          </label>
          <input
            id="photo-file"
            ref={fileInput}
            type="file"
            accept="image/*"
            className="text-sm text-slate-300 mb-3"
            data-testid="photo-file"
          />

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-slate-400">
              Session (optional)
              <select
                className={FIELD}
                value={periodId}
                onChange={(e) => setPeriodId(e.target.value)}
                data-testid="photo-period"
              >
                <option value="">Not part of a measuring session</option>
                {periods.map((period) => (
                  <option key={period.id} value={period.id}>
                    {period.measured_on}
                    {period.protocol ? ` · ${period.protocol}` : ''}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-xs text-slate-400">
              Lighting
              <input
                className={FIELD}
                list="photo-lighting-options"
                value={lighting}
                onChange={(e) => setLighting(e.target.value)}
                placeholder="window daylight"
                data-testid="photo-lighting"
              />
              <datalist id="photo-lighting-options">
                {LIGHTING_OPTIONS.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            </label>

            <label className="text-xs text-slate-400">
              Camera distance (cm)
              <input
                className={FIELD}
                type="number"
                min={30}
                max={1000}
                value={distance}
                onChange={(e) => setDistance(e.target.value)}
                placeholder="200"
                data-testid="photo-distance"
              />
            </label>

            <label className="text-xs text-slate-400">
              Notes
              <input
                className={FIELD}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="end of week 3"
                data-testid="photo-notes"
              />
            </label>
          </div>

          <div className="flex items-center gap-2 mt-3">
            <button
              className={PRIMARY}
              onClick={upload}
              disabled={busy}
              data-testid="photo-upload"
            >
              <Camera className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              {busy ? 'Saving…' : 'Save photo'}
            </button>
            {athleteToday && (
              <span className="text-[11px] text-slate-500">
                dated {athleteToday}
              </span>
            )}
          </div>

          {uploadError && <div className="mt-2"><Note message={uploadError} /></div>}
          {notice && <div className="mt-2"><Note message={notice} tone="ok" /></div>}
        </div>
      </section>

      {warning && <Note message={warning} />}
      {loadError && <Note message={loadError} />}

      {/* ── Gallery ──────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className={SECTION}>Your photos</h2>

        {photos === null ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : photos.length === 0 ? (
          <div className={CARD} data-testid="no-photos">
            <p className="text-sm text-slate-300">No photos yet.</p>
            <p className="text-xs text-slate-500 mt-1">
              These are private to you. Nothing looks at them unless you turn
              that on per photo.
            </p>
          </div>
        ) : (
          VIEWS.filter((option) => (byView[option] ?? []).length > 0).map(
            (option) => (
              <div key={option} className="space-y-2" data-testid={`group-${option}`}>
                <h3 className="text-xs text-slate-400">
                  {VIEW_LABEL[option]}
                  <span className="text-slate-600 ml-1.5">
                    {(byView[option] ?? []).length}
                  </span>
                </h3>
                <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
                  {(byView[option] ?? []).map((photo) => (
                    <div
                      key={photo.id}
                      className="rounded-xl border border-white/10 overflow-hidden bg-white/[0.02]"
                      data-testid={`photo-${photo.id}`}
                    >
                      <img
                        src={progressPhotoApi.fileUrl(photo.id, 'thumb')}
                        alt={
                          `${VIEW_LABEL[option]} progress photo` +
                          (photo.taken_at
                            ? ` taken ${photo.taken_at.slice(0, 10)}`
                            : '')
                        }
                        className="w-full aspect-[3/4] object-cover bg-slate-900"
                        loading="lazy"
                      />
                      <div className="p-2.5 space-y-1.5">
                        <p className="text-[11px] text-slate-400">
                          {(photo.taken_at ?? photo.created_at ?? '').slice(0, 10)}
                        </p>
                        {photo.lighting && (
                          <p className="text-[11px] text-slate-500" data-testid="photo-conditions">
                            {photo.lighting}
                            {photo.distance_cm ? ` · ${photo.distance_cm} cm` : ''}
                          </p>
                        )}
                        {photo.notes && (
                          <p className="text-[11px] text-slate-500">{photo.notes}</p>
                        )}
                        {/* The reference, not the typed float. */}
                        {photo.bodyweight_observation_id && (
                          <p className="text-[11px] text-slate-500" data-testid="photo-weight-link">
                            weight recorded that day
                          </p>
                        )}

                        <label className="flex items-start gap-1.5 text-[11px] text-slate-400">
                          <input
                            type="checkbox"
                            checked={photo.consent_analysis}
                            onChange={() => toggleConsent(photo)}
                            data-testid={`consent-${photo.id}`}
                            className="mt-0.5"
                          />
                          <span>
                            Let Sara look at this one
                            {!photo.consent_analysis && (
                              <span className="block text-slate-600">
                                Off: nothing analyses it.
                              </span>
                            )}
                          </span>
                        </label>

                        {/* The legacy critique, labelled as what it is. */}
                        {photo.has_critique && (
                          <details data-testid={`critique-${photo.id}`}>
                            <summary className="cursor-pointer text-[11px] text-slate-500">
                              Older written critique
                            </summary>
                            <p className="text-[11px] text-slate-400 mt-1">
                              {photo.critique}
                            </p>
                            <p className="text-[10px] text-slate-600 mt-1">
                              Written by {photo.critique_model ?? 'a model'}. Free
                              text, not a measurement — nothing in your records
                              came from it.
                            </p>
                          </details>
                        )}

                        {/* Observations, newest first. */}
                        {(byPhoto[photo.id] ?? []).map((row) => (
                          <Observation key={row.analysis_id} row={row} />
                        ))}

                        {/* The affordance appears only where it can work:
                            consent on, and a probed endpoint reachable. */}
                        {photo.consent_analysis && capability?.available && (
                          <button
                            className={`${GHOST} w-full justify-center`}
                            onClick={() => analyse(photo)}
                            disabled={analysing === photo.id}
                            data-testid={`analyse-${photo.id}`}
                          >
                            <Eye className="w-3.5 h-3.5 inline mr-1" />
                            {analysing === photo.id
                              ? 'Looking…'
                              : (byPhoto[photo.id] ?? []).length > 0
                                ? 'Describe again'
                                : 'Describe what Sara sees'}
                          </button>
                        )}
                        {photo.consent_analysis && capability
                          && !capability.available && (
                          <p
                            className="text-[10px] text-slate-600"
                            data-testid={`no-vision-${photo.id}`}
                          >
                            Sara cannot see photos right now — no verified
                            vision model is reachable.
                          </p>
                        )}

                        <button
                          className={`${GHOST} w-full justify-center`}
                          onClick={() => remove(photo)}
                          data-testid={`delete-${photo.id}`}
                        >
                          <Trash2 className="w-3.5 h-3.5 inline mr-1" />
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ),
          )
        )}
      </section>

      {/* ── Comparison readiness ─────────────────────────────────────── */}
      {periods.length >= 2 && (
        <section className="space-y-3">
          <div>
            <h2 className={SECTION}>Compare two sessions</h2>
            <p className="text-xs text-slate-500 mt-1">
              This checks whether a comparison would be honest — same view,
              same lighting, similar distance. It does not analyse anything.
            </p>
          </div>
          <div className={CARD}>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className={FIELD + ' max-w-[14rem]'}
                defaultValue=""
                onChange={(e) => {
                  const other = periods.find((p) => p.id !== e.target.value)
                  if (e.target.value && other) {
                    void checkComparable(e.target.value, other.id)
                  }
                }}
                data-testid="compare-picker"
              >
                <option value="">Pick a session…</option>
                {periods.map((period) => (
                  <option key={period.id} value={period.id}>
                    {period.measured_on}
                  </option>
                ))}
              </select>
            </div>
            {comparison && (
              <div className="mt-3" data-testid="comparison-result">
                {comparison.comparable ? (
                  <Note
                    tone="ok"
                    message={
                      'Those two are comparable — same view and conditions.'
                    }
                  />
                ) : (
                  <Note
                    message={
                      `Not comparable: ${comparison.reason ?? 'the conditions differ'}.`
                    }
                  />
                )}
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
