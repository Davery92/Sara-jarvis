import React, { useRef, useState } from 'react'
import { X, Upload, FileText, AlertTriangle, CheckCircle2, Loader2, ArrowLeft } from 'lucide-react'
import { APP_CONFIG } from '../../config'

/**
 * Plan Importer — upload a plan document (or paste text), parse it with the
 * in-house LLM, review the result, then apply (creates + activates a new
 * program; the old one is kept as history). Nothing is written until Apply.
 */

interface ParsedExercise { name: string }
interface ParsedTemplate { name: string; scheduled_days: string[]; exercises: ParsedExercise[] }
interface ParsedPhase { name: string; duration_weeks: number; deload_week: number | null }
interface ParsedPlan {
  program: { name: string; goal: string; duration_weeks: number | null; notes: string }
  phases: ParsedPhase[]
  templates: ParsedTemplate[]
  nutrition_guide: any | null
}

type Step = 'input' | 'parsing' | 'preview' | 'applying' | 'done'

interface Props {
  onClose: () => void
  onApplied: () => void
}

const DAY_ABBR: Record<string, string> = {
  monday: 'Mon', tuesday: 'Tue', wednesday: 'Wed', thursday: 'Thu', friday: 'Fri', saturday: 'Sat', sunday: 'Sun',
}

const PlanImporter: React.FC<Props> = ({ onClose, onApplied }) => {
  const [step, setStep] = useState<Step>('input')
  const [file, setFile] = useState<File | null>(null)
  const [pastedText, setPastedText] = useState('')
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [parsed, setParsed] = useState<ParsedPlan | null>(null)
  const [sourceText, setSourceText] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [result, setResult] = useState<any | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const canParse = !!file || pastedText.trim().length > 20

  const handleParse = async () => {
    setError(null)
    setStep('parsing')
    try {
      const fd = new FormData()
      if (file) fd.append('file', file)
      else fd.append('text_input', pastedText)
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/import-plan/parse`, {
        method: 'POST', credentials: 'include', body: fd,
      })
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail.detail || `Parse failed (${resp.status})`)
      }
      const data = await resp.json()
      setParsed(data.parsed)
      setSourceText(data.source_text || '')
      setWarnings(data.warnings || [])
      setStep('preview')
    } catch (e: any) {
      setError(e.message || 'Failed to parse the document')
      setStep('input')
    }
  }

  const handleApply = async () => {
    if (!parsed) return
    setError(null)
    setStep('applying')
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/import-plan/apply`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: parsed, source_text: sourceText }),
      })
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail.detail || `Apply failed (${resp.status})`)
      }
      setResult(await resp.json())
      setStep('done')
      onApplied()
    } catch (e: any) {
      setError(e.message || 'Failed to apply the plan')
      setStep('preview')
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false)
    if (e.dataTransfer.files?.[0]) { setFile(e.dataTransfer.files[0]); setPastedText('') }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="assistant-panel rounded-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/10">
          <div className="flex items-center gap-2">
            {step === 'preview' && (
              <button onClick={() => setStep('input')} className="p-1 hover:bg-white/10 rounded" title="Back">
                <ArrowLeft className="w-5 h-5 text-slate-400" />
              </button>
            )}
            <h3 className="font-display text-xl font-semibold">Import a Plan</h3>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-white/10 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto">
          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg bg-rose-500/10 border border-rose-400/30 p-3 text-sm text-rose-200">
              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* ── Input step ── */}
          {step === 'input' && (
            <div className="space-y-4">
              <p className="text-sm text-slate-400">
                Upload a plan document (Markdown, text, or PDF) or paste it below. It will be parsed into a program,
                phases, workouts, and nutrition targets for you to review before anything changes.
              </p>

              <div
                onDragEnter={(e) => { e.preventDefault(); setDragActive(true) }}
                onDragLeave={(e) => { e.preventDefault(); setDragActive(false) }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={onDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
                  dragActive ? 'border-teal-400/60 bg-teal-500/5' : 'border-white/15 hover:border-teal-400/40 hover:bg-white/5'
                }`}
              >
                <input
                  ref={fileInputRef} type="file" className="hidden"
                  accept=".md,.markdown,.txt,.pdf,.docx,.doc,text/plain,text/markdown,application/pdf"
                  onChange={(e) => { if (e.target.files?.[0]) { setFile(e.target.files[0]); setPastedText('') } }}
                />
                {file ? (
                  <div className="flex items-center justify-center gap-2 text-slate-200">
                    <FileText className="w-5 h-5 text-teal-300" />
                    <span className="text-sm">{file.name}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); setFile(null) }}
                      className="ml-2 text-xs text-slate-400 hover:text-rose-300"
                    >remove</button>
                  </div>
                ) : (
                  <div className="text-slate-400">
                    <Upload className="w-7 h-7 mx-auto mb-2 text-slate-500" />
                    <p className="text-sm">Drop a file here or <span className="text-teal-300">browse</span></p>
                    <p className="text-xs text-slate-500 mt-1">.md · .txt · .pdf · .docx</p>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-3 text-xs text-slate-500">
                <div className="flex-1 h-px bg-white/10" /> or paste <div className="flex-1 h-px bg-white/10" />
              </div>

              <textarea
                value={pastedText}
                onChange={(e) => { setPastedText(e.target.value); if (e.target.value) setFile(null) }}
                placeholder="Paste your plan text here…"
                rows={6}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-teal-400/60 focus:ring-1 focus:ring-teal-400/30 text-white text-sm resize-y"
              />

              <div className="flex justify-end gap-3 pt-1">
                <button onClick={onClose} className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-slate-200 text-sm transition-colors">Cancel</button>
                <button
                  onClick={handleParse} disabled={!canParse}
                  className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >Parse</button>
              </div>
            </div>
          )}

          {/* ── Parsing / Applying spinners ── */}
          {(step === 'parsing' || step === 'applying') && (
            <div className="flex flex-col items-center justify-center py-12 text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin text-teal-300 mb-3" />
              <p className="text-sm">{step === 'parsing' ? 'Reading and parsing your plan…' : 'Applying the plan…'}</p>
              {step === 'parsing' && <p className="text-xs text-slate-500 mt-1">This can take a few seconds.</p>}
            </div>
          )}

          {/* ── Preview step ── */}
          {step === 'preview' && parsed && (
            <div className="space-y-5">
              {warnings.length > 0 && (
                <div className="rounded-lg bg-amber-500/5 border border-amber-400/20 p-3">
                  <div className="flex items-center gap-2 text-amber-200 text-sm font-medium mb-1">
                    <AlertTriangle className="w-4 h-4" /> Review these
                  </div>
                  <ul className="text-xs text-slate-300 list-disc pl-5 space-y-0.5">
                    {warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              <div>
                <span className="assistant-kicker text-teal-300">Program</span>
                <h4 className="font-display text-lg font-semibold mt-1">{parsed.program.name}</h4>
                <p className="text-xs text-slate-400 capitalize">{parsed.program.goal}
                  {parsed.program.duration_weeks ? ` · ${parsed.program.duration_weeks} weeks` : ''}
                  {' · starts next Monday'}</p>
              </div>

              <div>
                <span className="assistant-kicker text-teal-300">Phases ({parsed.phases.length})</span>
                <div className="mt-2 space-y-1.5">
                  {parsed.phases.map((p, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm">
                      <span className="text-slate-200">{p.name}{p.deload_week ? ' · deload' : ''}</span>
                      <span className="text-slate-500 text-xs">{p.duration_weeks} wk</span>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <span className="assistant-kicker text-teal-300">Weekly Workouts ({parsed.templates.length})</span>
                <div className="mt-2 space-y-1.5">
                  {parsed.templates.map((t, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm">
                      <span className="text-slate-200">{t.name}</span>
                      <span className="text-slate-500 text-xs">
                        {t.scheduled_days.map(d => DAY_ABBR[d] || d).join(', ') || '—'} · {t.exercises.length} exercises
                      </span>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-slate-500 mt-1.5">These run in every phase.</p>
              </div>

              <div className="flex items-center gap-2 text-sm text-slate-300">
                {parsed.nutrition_guide
                  ? <><CheckCircle2 className="w-4 h-4 text-teal-400" /> Nutrition guide detected — the Nutrition tab will update.</>
                  : <><AlertTriangle className="w-4 h-4 text-amber-300" /> No nutrition guide found — the Nutrition tab stays as-is.</>}
              </div>

              <div className="flex justify-end gap-3 pt-1 border-t border-white/10 mt-2 pt-4">
                <button onClick={() => setStep('input')} className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-slate-200 text-sm transition-colors">Discard</button>
                <button onClick={handleApply} className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-sm font-medium transition-colors">Apply Plan</button>
              </div>
            </div>
          )}

          {/* ── Done step ── */}
          {step === 'done' && result && (
            <div className="text-center py-8">
              <CheckCircle2 className="w-12 h-12 text-teal-400 mx-auto mb-3" />
              <h4 className="font-display text-lg font-semibold">Plan applied</h4>
              <p className="text-sm text-slate-400 mt-1">
                <span className="text-slate-200">{result.name}</span> is now active
                {result.start_date ? `, starting ${result.start_date}` : ''}.
              </p>
              <p className="text-xs text-slate-500 mt-2">
                {result.phases?.length} phases · {result.workouts?.length} workouts
                {result.nutrition_guide_updated ? ' · nutrition guide updated' : ''}. Your previous plan was kept as history.
              </p>
              <button onClick={onClose} className="mt-5 px-5 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-sm font-medium transition-colors">Done</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default PlanImporter
