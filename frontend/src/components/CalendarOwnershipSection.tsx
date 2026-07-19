import { useEffect, useState, useCallback } from 'react'
import { APP_CONFIG } from '../config'

interface CalRow {
  calendar: string
  events: number
  mapped_owner: string | null
  acknowledged: boolean
}

interface CalendarsResponse {
  calendars: CalRow[]
  self_name: string
  family_members: Record<string, string>
  aliases: Record<string, string>
}

/**
 * Phase-3 calendar ownership panel: list each synced calendar with an owner
 * dropdown (You / a family member / Family / Per-event / Unmapped), writing to
 * PUT /calendar/ownership.
 */
export default function CalendarOwnershipSection() {
  const [data, setData] = useState<CalendarsResponse | null>(null)
  const [owners, setOwners] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const load = useCallback(async () => {
    const r = await fetch(`${APP_CONFIG.apiUrl}/calendar/calendars`, { credentials: 'include' })
    if (!r.ok) return
    const j: CalendarsResponse = await r.json()
    setData(j)
    const init: Record<string, string> = {}
    j.calendars.forEach(c => { init[c.calendar.toLowerCase()] = c.mapped_owner ?? '' })
    setOwners(init)
  }, [])

  useEffect(() => { load() }, [load])

  const ownerOptions = (): { value: string; label: string }[] => {
    const opts = [
      { value: '', label: 'Unmapped (ask me)' },
      { value: 'self', label: `You (${data?.self_name || 'David'})` },
      { value: 'family', label: 'Family / shared' },
      { value: 'per_event', label: 'Per-event (from title)' },
    ]
    Object.keys(data?.family_members || {}).forEach(name =>
      opts.push({ value: name, label: name }))
    return opts
  }

  const save = async () => {
    if (!data) return
    setSaving(true); setMsg(null)
    // Build calendar_owners from non-empty selections; empty => leave unmapped.
    const calendar_owners: Record<string, string> = {}
    Object.entries(owners).forEach(([cal, owner]) => { if (owner) calendar_owners[cal] = owner })
    try {
      const r = await fetch(`${APP_CONFIG.apiUrl}/calendar/ownership`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ calendar_owners }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setMsg('Saved. New attributions apply on the next sync + backfill.')
      await load()
    } catch (e: any) {
      setMsg(`Failed: ${e.message}`)
    } finally { setSaving(false) }
  }

  if (!data) return null

  return (
    <section className="mt-12">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Calendar ownership</h2>
        <button onClick={save} disabled={saving}
          className="text-xs px-3 py-1 rounded bg-teal-500/20 text-teal-200 hover:bg-teal-500/30 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
      <p className="text-xs text-slate-500 mb-3">
        Who owns each synced calendar. Events on someone else's calendar won't be narrated as yours.
      </p>
      <div className="space-y-2">
        {data.calendars.map(c => (
          <div key={c.calendar} className="flex items-center gap-3 rounded-lg bg-white/5 border border-white/10 p-2">
            <div className="flex-1 min-w-0">
              <div className="text-sm text-slate-100 truncate">{c.calendar}</div>
              <div className="text-xs text-slate-500">{c.events} events{c.acknowledged ? ' · left unmapped' : ''}</div>
            </div>
            <select
              value={owners[c.calendar.toLowerCase()] ?? ''}
              onChange={e => setOwners(o => ({ ...o, [c.calendar.toLowerCase()]: e.target.value }))}
              className="text-sm bg-slate-800 border border-white/10 rounded px-2 py-1 text-slate-100">
              {ownerOptions().map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        ))}
      </div>
      {msg && <div className="text-xs text-slate-400 mt-2">{msg}</div>}
    </section>
  )
}
