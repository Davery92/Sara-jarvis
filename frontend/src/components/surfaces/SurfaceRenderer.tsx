/**
 * SurfaceRenderer — renders a surface's components from spec + state and emits
 * interaction events. No generated HTML/JS; every component is a typed block.
 */
import React, { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../../config'
import {
  SurfaceModel,
  SurfaceComponent,
  SurfaceEventPayload,
  ChecklistComponent,
  StepsComponent,
  TimerComponent,
  FileListComponent,
  TableComponent,
  FormComponent,
  ButtonsComponent,
  ProgressComponent,
} from './types'

interface Props {
  surface: SurfaceModel
  onEvent: (payload: SurfaceEventPayload) => void
}

export const SurfaceRenderer: React.FC<Props> = ({ surface, onEvent }) => {
  return (
    <div className="space-y-4">
      {surface.spec.components.map((comp, i) => (
        <ComponentView key={(comp as any).id || i} comp={comp} surface={surface} onEvent={onEvent} />
      ))}
    </div>
  )
}

const ComponentView: React.FC<{
  comp: SurfaceComponent
  surface: SurfaceModel
  onEvent: (p: SurfaceEventPayload) => void
}> = ({ comp, surface, onEvent }) => {
  const state = (surface.state || {})[(comp as any).id] || {}

  switch (comp.type) {
    case 'markdown':
      return (
        <div className="prose prose-invert prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{comp.text}</ReactMarkdown>
        </div>
      )

    case 'checklist':
      return <Checklist comp={comp} checked={state.checked || {}} onEvent={onEvent} />

    case 'steps':
      return <Steps comp={comp} done={state.done || {}} onEvent={onEvent} />

    case 'timer':
      return <Timer comp={comp} />

    case 'file_list':
      return <FileList comp={comp} />

    case 'table':
      return <TableView comp={comp} />

    case 'form':
      return <FormView comp={comp} initial={state.values} onEvent={onEvent} />

    case 'buttons':
      return <Buttons comp={comp} clicked={state.clicked} onEvent={onEvent} />

    case 'progress':
      return <Progress comp={comp} override={state.value} />

    default:
      return null
  }
}

const Checklist: React.FC<{
  comp: ChecklistComponent
  checked: Record<string, boolean>
  onEvent: (p: SurfaceEventPayload) => void
}> = ({ comp, checked, onEvent }) => (
  <div className="space-y-1.5">
    {comp.items.map((item) => {
      const isChecked = checked[item.id] ?? item.checked ?? false
      return (
        <label key={item.id} className="flex items-center gap-2.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={isChecked}
            onChange={(e) =>
              onEvent({
                component_id: comp.id,
                event: 'check',
                value: { item_id: item.id, checked: e.target.checked },
              })
            }
            className="w-4 h-4 rounded accent-teal-500"
          />
          <span className={isChecked ? 'text-gray-500 line-through' : 'text-gray-200'}>
            {item.label}
          </span>
        </label>
      )
    })}
  </div>
)

const Steps: React.FC<{
  comp: StepsComponent
  done: Record<string, boolean>
  onEvent: (p: SurfaceEventPayload) => void
}> = ({ comp, done, onEvent }) => (
  <ol className="space-y-2">
    {comp.steps.map((step, idx) => {
      const isDone = done[step.id] ?? step.done ?? false
      return (
        <li key={step.id} className="flex items-start gap-3">
          <button
            onClick={() =>
              onEvent({
                component_id: comp.id,
                event: 'step',
                value: { step_id: step.id, done: !isDone },
              })
            }
            className={`flex-shrink-0 w-6 h-6 rounded-full border text-xs flex items-center justify-center ${
              isDone
                ? 'bg-teal-500 border-teal-500 text-white'
                : 'border-gray-600 text-gray-400'
            }`}
          >
            {isDone ? '✓' : idx + 1}
          </button>
          <span className={isDone ? 'text-gray-500 line-through' : 'text-gray-200'}>
            {step.text}
          </span>
        </li>
      )
    })}
  </ol>
)

const Timer: React.FC<{ comp: TimerComponent }> = ({ comp }) => {
  const [remaining, setRemaining] = useState(comp.duration_seconds)
  const [running, setRunning] = useState(false)
  const [timerId, setTimerId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Visual countdown mirrors the real (server-side) timer that fires the
  // notification. Starting creates a real timer via the timer backend.
  useEffect(() => {
    if (!running) return
    if (remaining <= 0) {
      setRunning(false)
      return
    }
    const t = setTimeout(() => setRemaining((r) => r - 1), 1000)
    return () => clearTimeout(t)
  }, [running, remaining])

  const start = async () => {
    setBusy(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/timers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ title: comp.label || 'Timer', duration_seconds: comp.duration_seconds }),
      })
      if (res.ok) {
        const timer = await res.json()
        setTimerId(timer.id)
        setRemaining(comp.duration_seconds)
        setRunning(true)
      }
    } catch {
      // fall back to a visual-only countdown
      setRemaining(comp.duration_seconds)
      setRunning(true)
    } finally {
      setBusy(false)
    }
  }

  const cancel = async () => {
    setRunning(false)
    setRemaining(comp.duration_seconds)
    const id = timerId
    setTimerId(null)
    if (id) {
      try {
        await fetch(`${APP_CONFIG.apiUrl}/timers/${id}`, { method: 'DELETE', credentials: 'include' })
      } catch {
        // best-effort
      }
    }
  }

  const mm = String(Math.floor(remaining / 60)).padStart(2, '0')
  const ss = String(remaining % 60).padStart(2, '0')
  const active = running || timerId

  return (
    <div className="flex items-center gap-3 rounded-md bg-gray-800/60 border border-gray-700 px-3 py-2">
      <span className="text-gray-300 text-sm flex-1">{comp.label || 'Timer'}</span>
      <span className={`font-mono text-lg ${remaining <= 0 ? 'text-teal-400' : 'text-white'}`}>
        {remaining <= 0 ? 'Done' : `${mm}:${ss}`}
      </span>
      <button
        onClick={active ? cancel : start}
        disabled={busy}
        className={`px-2.5 py-1 rounded text-xs text-white disabled:opacity-50 ${
          active ? 'bg-gray-700 hover:bg-gray-600' : 'bg-teal-600 hover:bg-teal-500'
        }`}
      >
        {busy ? '…' : active ? 'Cancel' : 'Start'}
      </button>
    </div>
  )
}

const FileList: React.FC<{ comp: FileListComponent }> = ({ comp }) => (
  <div className="space-y-1.5">
    {comp.files.map((f, i) => {
      const href = f.artifact_id
        ? `${APP_CONFIG.apiUrl}/api/artifacts/${f.artifact_id}/download`
        : f.job_id
        ? `${APP_CONFIG.apiUrl}/api/workspace/files/${f.job_id}/${encodeURIComponent(f.filename || f.name)}`
        : undefined
      return (
        <a
          key={i}
          href={href}
          className="flex items-center gap-2 rounded-md bg-gray-800/60 border border-gray-700 px-3 py-2 hover:border-teal-500"
        >
          <span className="material-icons text-gray-400 text-lg">description</span>
          <span className="text-gray-200 text-sm flex-1 truncate">{f.name}</span>
          <span className="material-icons text-teal-400 text-lg">download</span>
        </a>
      )
    })}
  </div>
)

const TableView: React.FC<{ comp: TableComponent }> = ({ comp }) => (
  <div className="overflow-x-auto">
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr>
          {comp.columns.map((c) => (
            <th key={c.key} className="text-left px-3 py-1.5 border-b border-gray-700 text-gray-400">
              {c.title}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {comp.rows.map((row, i) => (
          <tr key={i}>
            {comp.columns.map((c) => (
              <td key={c.key} className="px-3 py-1.5 border-b border-gray-800 text-gray-200">
                {String(row[c.key] ?? '')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)

const FormView: React.FC<{
  comp: FormComponent
  initial?: Record<string, any>
  onEvent: (p: SurfaceEventPayload) => void
}> = ({ comp, initial, onEvent }) => {
  const [values, setValues] = useState<Record<string, any>>(
    initial || Object.fromEntries(comp.fields.map((f) => [f.id, f.value ?? ''])),
  )
  const submitted = !!initial

  const set = (id: string, v: any) => setValues((prev) => ({ ...prev, [id]: v }))

  return (
    <div className="space-y-3">
      {comp.fields.map((f) => (
        <div key={f.id}>
          <label className="block text-xs text-gray-400 mb-1">{f.label}</label>
          {f.kind === 'textarea' ? (
            <textarea
              value={values[f.id] ?? ''}
              placeholder={f.placeholder}
              onChange={(e) => set(f.id, e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm"
            />
          ) : f.kind === 'select' ? (
            <select
              value={values[f.id] ?? ''}
              onChange={(e) => set(f.id, e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm"
            >
              <option value="">Select…</option>
              {(f.options || []).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : f.kind === 'checkbox' ? (
            <input
              type="checkbox"
              checked={!!values[f.id]}
              onChange={(e) => set(f.id, e.target.checked)}
              className="w-4 h-4 accent-teal-500"
            />
          ) : (
            <input
              type={f.kind === 'number' ? 'number' : 'text'}
              value={values[f.id] ?? ''}
              placeholder={f.placeholder}
              onChange={(e) => set(f.id, e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm"
            />
          )}
        </div>
      ))}
      <button
        onClick={() => onEvent({ component_id: comp.id, event: 'submit', value: { values } })}
        className="px-3 py-1.5 rounded bg-teal-600 hover:bg-teal-500 text-white text-sm"
      >
        {submitted ? 'Resubmit' : comp.submit_label || 'Submit'}
      </button>
    </div>
  )
}

const Buttons: React.FC<{
  comp: ButtonsComponent
  clicked?: string
  onEvent: (p: SurfaceEventPayload) => void
}> = ({ comp, onEvent }) => (
  <div className="flex flex-wrap gap-2">
    {comp.buttons.map((b) => (
      <button
        key={b.id}
        onClick={() => onEvent({ component_id: comp.id, event: 'click', value: { button_id: b.id } })}
        className={`px-3 py-1.5 rounded text-sm ${
          b.style === 'danger'
            ? 'bg-red-600 hover:bg-red-500 text-white'
            : b.style === 'primary'
            ? 'bg-teal-600 hover:bg-teal-500 text-white'
            : 'bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700'
        }`}
      >
        {b.label}
      </button>
    ))}
  </div>
)

const Progress: React.FC<{ comp: ProgressComponent; override?: number }> = ({ comp, override }) => {
  const value = override ?? comp.value ?? 0
  const max = comp.max ?? 100
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div>
      {comp.label && <p className="text-xs text-gray-400 mb-1">{comp.label}</p>}
      <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
        <div className="h-full bg-teal-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default SurfaceRenderer
