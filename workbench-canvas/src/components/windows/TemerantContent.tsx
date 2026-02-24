import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2, Sparkles, RefreshCw, ScrollText, Swords } from 'lucide-react'
import {
  temerantApi,
  type TemerantAttribute,
  type TemerantDashboard,
  type TemerantJournalEntry,
  type TemerantOracleEvent,
  type TemerantStarterProfile,
  type TemerantTerm,
} from '../../services/api'
import type { TemerantWindowData } from '../../types'

interface TemerantContentProps {
  data: TemerantWindowData
  windowId: string
}

const ATTRIBUTE_META: Record<TemerantAttribute, { label: string; bar: string }> = {
  body: { label: 'Body', bar: 'bg-rose-500' },
  mind: { label: 'Mind', bar: 'bg-sky-500' },
  craft: { label: 'Craft', bar: 'bg-amber-500' },
  coin: { label: 'Coin', bar: 'bg-emerald-500' },
  name: { label: 'Name', bar: 'bg-violet-500' },
}

const QUICK_ACTIONS: Array<{ action_type: string; label: string }> = [
  { action_type: 'workout', label: 'Workout' },
  { action_type: 'study', label: 'Study' },
  { action_type: 'guitar', label: 'Guitar' },
  { action_type: 'coding', label: 'Coding' },
  { action_type: 'workday_complete', label: 'Workday' },
  { action_type: 'meditation', label: 'Meditation' },
]

const rankLabel = (rank: string) => {
  if (rank === 'relar') return 'Re\'lar'
  if (rank === 'elthe') return 'El\'the'
  return 'E\'lir'
}

const formatDate = (value?: string | null) => {
  if (!value) return 'n/a'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString()
}

export default function TemerantContent({ data }: TemerantContentProps) {
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [needsCharacter, setNeedsCharacter] = useState(false)

  const [dashboard, setDashboard] = useState<TemerantDashboard | null>(null)
  const [currentTerm, setCurrentTerm] = useState<TemerantTerm | null>(null)
  const [journal, setJournal] = useState<TemerantJournalEntry[]>([])
  const [oracleEvents, setOracleEvents] = useState<TemerantOracleEvent[]>([])
  const [starterProfiles, setStarterProfiles] = useState<TemerantStarterProfile[]>([])

  const [characterName, setCharacterName] = useState('')
  const [origin, setOrigin] = useState('')
  const [backstory, setBackstory] = useState('')
  const [resolution, setResolution] = useState('')

  const loadData = useCallback(async () => {
    setError(null)
    try {
      await temerantApi.getCharacter()
      setNeedsCharacter(false)

      const [nextDashboard, term, entries, events] = await Promise.all([
        temerantApi.getDashboard(),
        temerantApi.getCurrentTerm(),
        temerantApi.listJournal(4),
        temerantApi.listOracleEvents(undefined, 8),
      ])
      setDashboard(nextDashboard)
      setCurrentTerm(term)
      setJournal(entries)
      setOracleEvents(events)
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setNeedsCharacter(true)
        setDashboard(null)
        setCurrentTerm(null)
        setJournal([])
        setOracleEvents([])
      } else {
        const detail = err?.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'Temerant sync failed.')
      }
    }
  }, [])

  useEffect(() => {
    let active = true
    const run = async () => {
      setLoading(true)
      await Promise.all([
        loadData(),
        temerantApi
          .getStarterProfiles()
          .then((profiles) => {
            if (active) setStarterProfiles(profiles)
          })
          .catch(() => {
            if (active) setStarterProfiles([])
          }),
      ])
      if (active) setLoading(false)
    }
    run()
    return () => {
      active = false
    }
  }, [loadData])

  const activeOracle = useMemo(() => {
    if (dashboard?.oracle_event?.status === 'open') return dashboard.oracle_event
    return oracleEvents.find((e) => e.status === 'open') || null
  }, [dashboard, oracleEvents])

  const davethProfile = useMemo(
    () => starterProfiles.find((profile) => profile.id === 'daveth_of_andentown') || null,
    [starterProfiles]
  )

  const runAction = async (fn: () => Promise<void>, okMessage: string) => {
    setBusy(true)
    setStatus(null)
    setError(null)
    try {
      await fn()
      setStatus(okMessage)
      await loadData()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Action failed.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-canvas-muted">
        <Loader2 size={18} className="animate-spin mr-2" />
        Loading Temerant...
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-canvas-bg text-canvas-text">
      <div className="px-3 py-2 border-b border-canvas-border flex items-center gap-2">
        <Sparkles size={14} className="text-rose-400" />
        <div className="text-sm font-medium">Temerant</div>
        <div className="flex-1" />
        <button
          onClick={() => runAction(async () => {}, 'Refreshed.')}
          disabled={busy}
          className="p-1 rounded hover:bg-canvas-hover text-canvas-muted"
          title="Refresh"
        >
          <RefreshCw size={12} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {error && (
          <div className="text-xs text-red-300 bg-red-900/20 border border-red-900/30 rounded px-2 py-1.5">{error}</div>
        )}
        {status && (
          <div className="text-xs text-emerald-300 bg-emerald-900/20 border border-emerald-900/30 rounded px-2 py-1.5">{status}</div>
        )}

        {needsCharacter && (
          <div className="bg-canvas-surface border border-canvas-border rounded p-3 space-y-2">
            <div className="text-sm font-medium text-white">Create Character</div>
            {davethProfile && (
              <div className="rounded border border-rose-800/40 bg-rose-950/20 p-2 space-y-1.5">
                <div className="text-xs text-white font-medium">{davethProfile.name}</div>
                <div className="text-[11px] text-canvas-muted">{davethProfile.description}</div>
                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await temerantApi.createCharacter({
                        starter_profile: davethProfile.id,
                      })
                    }, 'Daveth profile applied.')
                  }
                  className="px-2 py-1 rounded bg-rose-600 text-white text-[11px] disabled:opacity-60"
                >
                  Use Daveth Preset
                </button>
              </div>
            )}
            <input
              value={characterName}
              onChange={(e) => setCharacterName(e.target.value)}
              placeholder="Character name"
              className="w-full px-2 py-1.5 rounded bg-canvas-bg border border-canvas-border text-sm"
            />
            <input
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="Origin (optional)"
              className="w-full px-2 py-1.5 rounded bg-canvas-bg border border-canvas-border text-sm"
            />
            <textarea
              value={backstory}
              onChange={(e) => setBackstory(e.target.value)}
              placeholder="Backstory (optional)"
              rows={3}
              className="w-full px-2 py-1.5 rounded bg-canvas-bg border border-canvas-border text-sm"
            />
            <button
              disabled={!characterName.trim() || busy}
              onClick={() =>
                runAction(async () => {
                  await temerantApi.createCharacter({
                    character_name: characterName.trim(),
                    origin: origin || undefined,
                    backstory: backstory || undefined,
                  })
                  setCharacterName('')
                  setOrigin('')
                  setBackstory('')
                }, 'Character created.')
              }
              className="px-3 py-1.5 rounded bg-rose-600 text-white text-xs disabled:opacity-60"
            >
              Begin Term
            </button>
          </div>
        )}

        {!needsCharacter && dashboard && (
          <>
            <div className="bg-canvas-surface border border-canvas-border rounded p-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-white">
                  {dashboard.character.character_name} - {rankLabel(dashboard.character.current_rank)}
                </div>
                <div className="text-[11px] text-canvas-muted">{formatDate(dashboard.date)}</div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div className="bg-canvas-bg rounded border border-canvas-border px-2 py-1.5">
                  <div className="text-canvas-muted">Coin</div>
                  <div className="text-white">{dashboard.character.coin_balance.toFixed(1)} talents</div>
                </div>
                <div className="bg-canvas-bg rounded border border-canvas-border px-2 py-1.5">
                  <div className="text-canvas-muted">Categories</div>
                  <div className="text-white">{dashboard.daily.categories_completed}/5</div>
                </div>
              </div>
            </div>

            <div className="bg-canvas-surface border border-canvas-border rounded p-3">
              <div className="text-xs text-canvas-muted mb-2">Attributes</div>
              <div className="space-y-2">
                {(Object.keys(ATTRIBUTE_META) as TemerantAttribute[]).map((key) => {
                  const row = dashboard.attributes[key]
                  if (!row) return null
                  const progress = Math.min(100, ((row.xp_total % 25) / 25) * 100)
                  return (
                    <div key={key}>
                      <div className="flex justify-between text-[11px] mb-0.5">
                        <span className="text-canvas-text">{ATTRIBUTE_META[key].label}</span>
                        <span className="text-canvas-muted">Lv {row.level} | +{row.xp_today} today</span>
                      </div>
                      <div className="h-1.5 bg-canvas-bg rounded overflow-hidden">
                        <div className={`h-full ${ATTRIBUTE_META[key].bar}`} style={{ width: `${progress}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="bg-canvas-surface border border-canvas-border rounded p-3">
              <div className="text-xs text-canvas-muted mb-2">Quick Log</div>
              <div className="grid grid-cols-2 gap-1.5">
                {QUICK_ACTIONS.map((action) => (
                  <button
                    key={action.action_type}
                    disabled={busy}
                    onClick={() =>
                      runAction(async () => {
                        await temerantApi.createManualLog({
                          action_type: action.action_type,
                          action_label: action.label,
                          quantity: 1,
                        })
                      }, `${action.label} logged.`)
                    }
                    className="px-2 py-1.5 rounded bg-canvas-bg border border-canvas-border text-xs hover:bg-canvas-hover disabled:opacity-60"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="bg-canvas-surface border border-canvas-border rounded p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-xs text-canvas-muted flex items-center gap-1">
                  <Swords size={12} />
                  Oracle
                </div>
                <button
                  onClick={() => runAction(async () => { await temerantApi.rollOracle() }, 'Oracle rolled.')}
                  disabled={busy}
                  className="px-2 py-1 rounded bg-canvas-bg border border-canvas-border text-[11px] hover:bg-canvas-hover disabled:opacity-60"
                >
                  Roll
                </button>
              </div>
              {activeOracle ? (
                <>
                  <div className="text-xs uppercase tracking-wide text-rose-400">{activeOracle.tier} - {activeOracle.category}</div>
                  <div className="text-sm text-white">{activeOracle.title}</div>
                  <div className="text-xs text-canvas-muted">{activeOracle.hook}</div>
                  <textarea
                    value={resolution}
                    onChange={(e) => setResolution(e.target.value)}
                    rows={2}
                    placeholder="Resolution notes"
                    className="w-full px-2 py-1.5 rounded bg-canvas-bg border border-canvas-border text-xs"
                  />
                  <div className="flex gap-1.5">
                    <button
                      disabled={busy}
                      onClick={() =>
                        runAction(async () => {
                          await temerantApi.resolveOracleEvent(activeOracle.id, { status: 'resolved', resolution: resolution || undefined })
                          setResolution('')
                        }, 'Oracle event resolved.')
                      }
                      className="px-2 py-1 rounded bg-emerald-600 text-white text-[11px] disabled:opacity-60"
                    >
                      Resolve
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        runAction(async () => {
                          await temerantApi.resolveOracleEvent(activeOracle.id, { status: 'dismissed', resolution: resolution || undefined })
                          setResolution('')
                        }, 'Oracle event dismissed.')
                      }
                      className="px-2 py-1 rounded bg-gray-700 text-white text-[11px] disabled:opacity-60"
                    >
                      Dismiss
                    </button>
                  </div>
                </>
              ) : (
                <div className="text-xs text-canvas-muted">No open oracle event.</div>
              )}
            </div>

            <div className="bg-canvas-surface border border-canvas-border rounded p-3 space-y-2">
              <div className="text-xs text-canvas-muted">Term and Journal</div>
              {currentTerm && (
                <div className="text-xs grid grid-cols-2 gap-1.5">
                  <div className="text-canvas-muted">Completion</div>
                  <div className="text-right text-canvas-text">{currentTerm.completion_pct.toFixed(1)}%</div>
                  <div className="text-canvas-muted">Admissions</div>
                  <div className="text-right text-canvas-text capitalize">{currentTerm.admissions_result}</div>
                  <div className="text-canvas-muted">Tuition</div>
                  <div className="text-right text-canvas-text">{currentTerm.tuition_talents} talents</div>
                </div>
              )}
              <div className="space-y-1.5">
                {journal.length === 0 && <div className="text-xs text-canvas-muted">No journal entries yet.</div>}
                {journal.map((entry) => (
                  <div key={entry.id} className="border border-canvas-border rounded px-2 py-1.5 bg-canvas-bg">
                    <div className="text-[11px] text-canvas-muted flex items-center justify-between">
                      <span className="flex items-center gap-1"><ScrollText size={11} /> {formatDate(entry.local_date)}</span>
                      <span>{entry.source_event_count} events</span>
                    </div>
                    <div className="text-[11px] text-canvas-text mt-1 line-clamp-3">{entry.summary_markdown}</div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
