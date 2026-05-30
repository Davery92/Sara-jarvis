import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  apiClient,
  TemerantAttribute,
  TemerantCharacterResponse,
  TemerantDashboardResponse,
  TemerantJournalEntryResponse,
  TemerantLedgerEntryResponse,
  TemerantMappingRuleResponse,
  TemerantOracleEventResponse,
  TemerantStarterProfileResponse,
  TemerantTermResponse,
} from '../api/client'

const ATTRIBUTE_META: Record<TemerantAttribute, { label: string; color: string }> = {
  body: { label: 'Body', color: 'bg-red-500' },
  mind: { label: 'Mind', color: 'bg-blue-500' },
  craft: { label: 'Craft', color: 'bg-amber-500' },
  coin: { label: 'Coin', color: 'bg-emerald-500' },
  name: { label: 'Name', color: 'bg-violet-500' },
}

const QUICK_ACTIONS: Array<{ label: string; actionType: string; subtitle: string }> = [
  { label: 'Workout', actionType: 'workout', subtitle: 'Medica and Ketan training' },
  { label: 'Study', actionType: 'study', subtitle: 'Archives session' },
  { label: 'Guitar', actionType: 'guitar', subtitle: 'Eolian practice' },
  { label: 'Coding', actionType: 'coding', subtitle: 'Fishery artificing' },
  { label: 'Workday', actionType: 'workday_complete', subtitle: 'Guild commissions' },
  { label: 'Meditation', actionType: 'meditation', subtitle: 'Heart of Stone focus' },
]

const initialCreateForm = {
  character_name: '',
  backstory: '',
  origin: '',
}

const initialManualForm = {
  actionType: 'workout',
  quantity: '1',
  actionLabel: '',
  notes: '',
}

const formatDate = (value?: string | null) => {
  if (!value) return 'n/a'
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (dateOnly) {
    const [, year, month, day] = dateOnly
    const localDate = new Date(Number(year), Number(month) - 1, Number(day))
    return localDate.toLocaleDateString()
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString()
}

const rankLabel = (rank?: string | null) => {
  if (!rank) return 'E\'lir'
  if (rank === 'relar') return 'Re\'lar'
  if (rank === 'elthe') return 'El\'the'
  return 'E\'lir'
}

const SectionCard = ({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) => (
  <section className="bg-card border border-card rounded-md p-4">
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-base font-semibold text-white">{title}</h2>
      {right}
    </div>
    {children}
  </section>
)

const TemerantGuideModal = ({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) => {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="w-full max-w-4xl max-h-[88vh] overflow-y-auto rounded-md border border-gray-700 bg-gray-950 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-800 bg-gray-950/95 px-5 py-4 backdrop-blur">
          <div>
            <h2 className="text-lg font-semibold text-white">Temerant Guide</h2>
            <p className="text-xs text-gray-400">How to use this page and what each control does.</p>
          </div>
          <button
            onClick={onClose}
            className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700"
          >
            Close
          </button>
        </div>

        <div className="space-y-5 px-5 py-5 text-sm text-gray-200">
          <section>
            <h3 className="text-sm font-semibold text-teal-300">1. Quick Start</h3>
            <ol className="mt-2 list-decimal list-inside space-y-1 text-gray-300">
              <li>Create your character using `Use Daveth Preset` or `Begin Term`.</li>
              <li>Log your real actions with `Quick Log` buttons during the day.</li>
              <li>Use `Manual Entry` for anything not covered by quick buttons.</li>
              <li>After logging, press `Roll Oracle` to generate a daily event.</li>
              <li>Resolve or dismiss the event, then press `Generate Today` in Journal.</li>
            </ol>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">2. Header Buttons</h3>
            <div className="mt-2 space-y-2 text-gray-300">
              <p><span className="font-medium text-white">Refresh:</span> Reloads all Temerant data from the backend.</p>
              <p><span className="font-medium text-white">How To Play:</span> Opens this instruction modal.</p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">3. Character Setup Buttons</h3>
            <div className="mt-2 space-y-2 text-gray-300">
              <p><span className="font-medium text-white">Use Daveth Preset:</span> Creates `Daveth of Andentown` with starting XP, coin, and backstory.</p>
              <p><span className="font-medium text-white">Begin Term:</span> Creates a custom character from the form values.</p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">4. Daily Logging Buttons</h3>
            <div className="mt-2 space-y-2 text-gray-300">
              <p><span className="font-medium text-white">Workout / Study / Guitar / Coding / Workday / Meditation:</span> Fast action logs that award XP to mapped attributes.</p>
              <p><span className="font-medium text-white">Submit Manual Log:</span> Logs a custom action type with quantity, label, and notes.</p>
              <p className="text-xs text-gray-400">Common manual action types: `deep_research`, `ship_feature`, `budget_adherence`, `social`, `mentorship`.</p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">5. Oracle Buttons</h3>
            <div className="mt-2 space-y-2 text-gray-300">
              <p><span className="font-medium text-white">Roll Oracle:</span> Rolls the daily oracle. Quiet days can return no event.</p>
              <p><span className="font-medium text-white">Resolve:</span> Marks the open oracle event as completed with optional notes.</p>
              <p><span className="font-medium text-white">Dismiss:</span> Closes the event without resolving it.</p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">6. Journal and Term Buttons</h3>
            <div className="mt-2 space-y-2 text-gray-300">
              <p><span className="font-medium text-white">Generate Today:</span> Rebuilds today’s journal summary from logs and oracle data.</p>
              <p><span className="font-medium text-white">Economy and Admissions panel:</span> Shows prior term outcomes, completion percent, and tuition history.</p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">7. Reading Panels</h3>
            <div className="mt-2 space-y-2 text-gray-300">
              <p><span className="font-medium text-white">Attributes:</span> Displays level, total XP, term XP, and today’s XP.</p>
              <p><span className="font-medium text-white">Recent Ledger:</span> Auditable log of XP events by date/source.</p>
              <p><span className="font-medium text-white">Mapping Rules:</span> Current source-to-attribute translation rules.</p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-teal-300">8. Recommended Daily Loop</h3>
            <ol className="mt-2 list-decimal list-inside space-y-1 text-gray-300">
              <li>Morning: open page, check rank progress and open oracle status.</li>
              <li>Day: log each meaningful action as it happens.</li>
              <li>Evening: roll oracle, resolve or dismiss event.</li>
              <li>End of day: generate journal and review ledger accuracy.</li>
            </ol>
          </section>
        </div>
      </div>
    </div>
  )
}

function TemerantPage() {
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  const [character, setCharacter] = useState<TemerantCharacterResponse | null>(null)
  const [dashboard, setDashboard] = useState<TemerantDashboardResponse | null>(null)
  const [currentTerm, setCurrentTerm] = useState<TemerantTermResponse | null>(null)
  const [termHistory, setTermHistory] = useState<TemerantTermResponse[]>([])
  const [oracleEvents, setOracleEvents] = useState<TemerantOracleEventResponse[]>([])
  const [journalEntries, setJournalEntries] = useState<TemerantJournalEntryResponse[]>([])
  const [mappingRules, setMappingRules] = useState<TemerantMappingRuleResponse[]>([])
  const [ledgerEntries, setLedgerEntries] = useState<TemerantLedgerEntryResponse[]>([])
  const [starterProfiles, setStarterProfiles] = useState<TemerantStarterProfileResponse[]>([])

  const [createForm, setCreateForm] = useState(initialCreateForm)
  const [manualForm, setManualForm] = useState(initialManualForm)
  const [oracleResolution, setOracleResolution] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [showGuide, setShowGuide] = useState(false)

  const loadTemerantData = useCallback(async () => {
    setError(null)

    try {
      const char = await apiClient.getTemerantCharacter()
      setCharacter(char)

      const [dashboardData, termData, historyData, eventsData, journalData, mappingData, ledgerData] = await Promise.all([
        apiClient.getTemerantDashboard(),
        apiClient.getTemerantCurrentTerm(),
        apiClient.listTemerantTermHistory(6),
        apiClient.listTemerantOracleEvents(undefined, 10),
        apiClient.listTemerantJournal({ limit: 7 }),
        apiClient.listTemerantMappings(),
        apiClient.listTemerantLedger({ limit: 8 }),
      ])

      setDashboard(dashboardData)
      setCurrentTerm(termData)
      setTermHistory(historyData)
      setOracleEvents(eventsData)
      setJournalEntries(journalData)
      setMappingRules(mappingData)
      setLedgerEntries(ledgerData)
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setCharacter(null)
        setDashboard(null)
        setCurrentTerm(null)
        setTermHistory([])
        setOracleEvents([])
        setJournalEntries([])
        setMappingRules([])
        setLedgerEntries([])
        return
      }
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Unable to load Temerant data right now.')
    }
  }, [])

  const loadInitial = useCallback(async () => {
    setLoading(true)
    try {
      const profiles = await apiClient.getTemerantStarterProfiles()
      setStarterProfiles(profiles)
    } catch {
      setStarterProfiles([])
    }
    await loadTemerantData()
    setLoading(false)
  }, [loadTemerantData])

  useEffect(() => {
    loadInitial()
  }, [loadInitial])

  useEffect(() => {
    if (!showGuide) return
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShowGuide(false)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [showGuide])

  const runWithRefresh = useCallback(
    async <T,>(
      operation: () => Promise<T>,
      successMessage?: string | ((result: T) => string | null | undefined)
    ) => {
      setSubmitting(true)
      setStatusMessage(null)
      setError(null)
      try {
        const result = await operation()
        if (typeof successMessage === 'function') {
          const msg = successMessage(result)
          if (msg) setStatusMessage(msg)
        } else if (successMessage) {
          setStatusMessage(successMessage)
        }
        setRefreshing(true)
        await loadTemerantData()
      } catch (err: any) {
        const detail = err?.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'Action failed.')
      } finally {
        setRefreshing(false)
        setSubmitting(false)
      }
    },
    [loadTemerantData]
  )

  const activeOracleEvent = useMemo(() => {
    if (dashboard?.oracle_event?.status === 'open') return dashboard.oracle_event
    return oracleEvents.find((event) => event.status === 'open') || null
  }, [dashboard, oracleEvents])

  const orderedAttributes = useMemo(() => {
    const attrs = dashboard?.attributes
    if (!attrs) return []
    return (['body', 'mind', 'craft', 'coin', 'name'] as TemerantAttribute[]).map((attr) => attrs[attr]).filter(Boolean)
  }, [dashboard])

  const davethProfile = useMemo(
    () => starterProfiles.find((profile) => profile.id === 'daveth_of_andentown') || null,
    [starterProfiles]
  )

  if (loading) {
    return (
      <div className="flex-1 min-h-0 p-6">
        <div className="bg-card border border-card rounded-md p-6 text-gray-300">Loading Temerant state...</div>
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6">
      <TemerantGuideModal open={showGuide} onClose={() => setShowGuide(false)} />
      <div className="max-w-6xl mx-auto space-y-4">
        <section className="bg-card border border-card rounded-md p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-widest text-teal-400">A Life in Temerant</p>
              <h1 className="text-2xl font-semibold text-white">Solo RPG Habit System</h1>
              <p className="text-sm text-gray-400 mt-1">
                Live your day. Log your habits. Let the University respond.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowGuide(true)}
                className="px-3 py-2 rounded border border-gray-700 bg-gray-900 text-sm text-gray-200 hover:bg-gray-800"
              >
                How To Play
              </button>
              <button
                onClick={() => runWithRefresh(async () => {}, undefined)}
                disabled={submitting || refreshing}
                className="px-3 py-2 rounded bg-gray-800 text-sm text-gray-200 hover:bg-gray-700 disabled:opacity-60"
              >
                {refreshing ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
          </div>
        </section>

        {error && (
          <div className="bg-red-900/20 border border-red-700/50 text-red-300 px-4 py-3 rounded-md text-sm">{error}</div>
        )}
        {statusMessage && (
          <div className="bg-emerald-900/20 border border-emerald-700/40 text-emerald-300 px-4 py-3 rounded-md text-sm">
            {statusMessage}
          </div>
        )}

        {!character && (
          <SectionCard title="Create Your Character">
            {davethProfile && (
              <div className="mb-4 rounded border border-teal-700/40 bg-teal-950/20 p-3">
                <div className="text-sm text-white font-medium">{davethProfile.name}</div>
                <p className="text-xs text-gray-300 mt-1">{davethProfile.description}</p>
                <button
                  disabled={submitting}
                  onClick={() =>
                    runWithRefresh(async () => {
                      await apiClient.createTemerantCharacter({
                        starter_profile: davethProfile.id,
                      })
                      setCreateForm(initialCreateForm)
                    }, 'Daveth profile applied. Character created.')
                  }
                  className="mt-3 px-3 py-2 rounded bg-teal-600 text-white text-sm hover:bg-teal-500 disabled:opacity-60"
                >
                  Use Daveth Preset
                </button>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="text-sm text-gray-300">
                Character Name
                <input
                  value={createForm.character_name}
                  onChange={(e) => setCreateForm((prev) => ({ ...prev, character_name: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white"
                  placeholder="Name in the Arcanum"
                />
              </label>
              <label className="text-sm text-gray-300">
                Origin
                <input
                  value={createForm.origin}
                  onChange={(e) => setCreateForm((prev) => ({ ...prev, origin: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white"
                  placeholder="Where are you from?"
                />
              </label>
              <label className="text-sm text-gray-300 md:col-span-2">
                Backstory
                <textarea
                  rows={3}
                  value={createForm.backstory}
                  onChange={(e) => setCreateForm((prev) => ({ ...prev, backstory: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white"
                  placeholder="Why did you come to the University?"
                />
              </label>
            </div>
            <div className="mt-4">
              <button
                disabled={!createForm.character_name.trim() || submitting}
                onClick={() =>
                  runWithRefresh(async () => {
                    await apiClient.createTemerantCharacter({
                      character_name: createForm.character_name.trim(),
                      backstory: createForm.backstory || undefined,
                      origin: createForm.origin || undefined,
                    })
                    setCreateForm(initialCreateForm)
                  }, 'Character created.')
                }
                className="px-4 py-2 rounded bg-teal-600 text-white text-sm hover:bg-teal-500 disabled:opacity-50"
              >
                Begin Term
              </button>
            </div>
          </SectionCard>
        )}

        {character && dashboard && (
          <>
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
              <SectionCard
                title={`${character.character_name} - ${rankLabel(character.current_rank)}`}
                right={<span className="text-xs text-gray-400">Date: {formatDate(dashboard.date)}</span>}
              >
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="bg-gray-900/70 rounded p-3 border border-gray-800">
                    <div className="text-gray-400">Coin</div>
                    <div className="text-white text-lg font-semibold">{character.coin_balance.toFixed(1)} talents</div>
                  </div>
                  <div className="bg-gray-900/70 rounded p-3 border border-gray-800">
                    <div className="text-gray-400">Categories Today</div>
                    <div className="text-white text-lg font-semibold">{dashboard.daily.categories_completed}/5</div>
                  </div>
                  <div className="bg-gray-900/70 rounded p-3 border border-gray-800">
                    <div className="text-gray-400">Alar Strength</div>
                    <div className="text-white text-lg font-semibold">{character.alar_strength}</div>
                  </div>
                  <div className="bg-gray-900/70 rounded p-3 border border-gray-800">
                    <div className="text-gray-400">Naming Affinity</div>
                    <div className="text-white text-lg font-semibold">{character.naming_affinity}</div>
                  </div>
                </div>
              </SectionCard>

              <SectionCard title="Rank Progress">
                {dashboard.rank_progress.next_rank ? (
                  <div className="space-y-2 text-sm">
                    <div className="text-gray-300">Next Rank: <span className="text-white">{rankLabel(dashboard.rank_progress.next_rank)}</span></div>
                    {Object.entries(dashboard.rank_progress.requirements).map(([key, value]) => (
                      <div key={key} className="flex justify-between border-b border-gray-800 pb-1">
                        <span className="text-gray-400">{key.replaceAll('_', ' ')}</span>
                        <span className="text-gray-200">{value}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">Final rank reached for current rule set.</p>
                )}
              </SectionCard>

              <SectionCard title="Current Term">
                {currentTerm ? (
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between"><span className="text-gray-400">Term</span><span className="text-white">{formatDate(currentTerm.term_month)}</span></div>
                    <div className="flex justify-between"><span className="text-gray-400">Completion</span><span className="text-white">{currentTerm.completion_pct.toFixed(1)}%</span></div>
                    <div className="flex justify-between"><span className="text-gray-400">Admissions</span><span className="text-white capitalize">{currentTerm.admissions_result}</span></div>
                    <div className="flex justify-between"><span className="text-gray-400">Tuition</span><span className="text-white">{currentTerm.tuition_talents} talents</span></div>
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">No term data yet.</p>
                )}
              </SectionCard>
            </div>

            <SectionCard title="Attributes">
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
                {orderedAttributes.map((attr) => {
                  const meta = ATTRIBUTE_META[attr.attribute]
                  const levelProgress = Math.min(100, ((attr.xp_total % 25) / 25) * 100)
                  return (
                    <div key={attr.attribute} className="bg-gray-900/70 rounded border border-gray-800 p-3">
                      <div className="flex items-center justify-between">
                        <div className="text-gray-200 font-medium">{meta.label}</div>
                        <div className="text-xs text-gray-400">Lv {attr.level}</div>
                      </div>
                      <div className="mt-2 text-sm text-gray-300">Total: {attr.xp_total}</div>
                      <div className="text-xs text-gray-400">Term: {attr.xp_term} | Today: {attr.xp_today}</div>
                      <div className="mt-2 h-2 bg-gray-800 rounded overflow-hidden">
                        <div className={`${meta.color} h-full`} style={{ width: `${levelProgress}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </SectionCard>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <SectionCard title="Quick Log">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {QUICK_ACTIONS.map((action) => (
                    <button
                      key={action.actionType}
                      disabled={submitting}
                      onClick={() =>
                        runWithRefresh(async () => {
                          await apiClient.createTemerantManualLog({
                            action_type: action.actionType,
                            action_label: action.label,
                            quantity: 1,
                          })
                        }, `${action.label} logged.`)
                      }
                      className="text-left px-3 py-3 rounded border border-gray-700 bg-gray-900 hover:bg-gray-800 disabled:opacity-60"
                    >
                      <div className="text-sm text-white font-medium">{action.label}</div>
                      <div className="text-xs text-gray-400">{action.subtitle}</div>
                    </button>
                  ))}
                </div>

                <div className="mt-4 pt-4 border-t border-gray-800 space-y-2">
                  <h3 className="text-sm font-medium text-gray-200">Manual Entry</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    <input
                      value={manualForm.actionType}
                      onChange={(e) => setManualForm((prev) => ({ ...prev, actionType: e.target.value }))}
                      className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                      placeholder="action_type (example: deep_research)"
                    />
                    <input
                      value={manualForm.quantity}
                      onChange={(e) => setManualForm((prev) => ({ ...prev, quantity: e.target.value }))}
                      className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                      placeholder="quantity"
                      type="number"
                      min="0"
                      step="0.5"
                    />
                    <input
                      value={manualForm.actionLabel}
                      onChange={(e) => setManualForm((prev) => ({ ...prev, actionLabel: e.target.value }))}
                      className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                      placeholder="Label (optional)"
                    />
                    <input
                      value={manualForm.notes}
                      onChange={(e) => setManualForm((prev) => ({ ...prev, notes: e.target.value }))}
                      className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                      placeholder="Notes (optional)"
                    />
                  </div>
                  <button
                    disabled={!manualForm.actionType.trim() || submitting}
                    onClick={() =>
                      runWithRefresh(async () => {
                        await apiClient.createTemerantManualLog({
                          action_type: manualForm.actionType.trim(),
                          action_label: manualForm.actionLabel || undefined,
                          notes: manualForm.notes || undefined,
                          quantity: Number(manualForm.quantity || '1'),
                        })
                        setManualForm(initialManualForm)
                      }, 'Manual action logged.')
                    }
                    className="px-3 py-2 rounded bg-teal-600 text-white text-sm hover:bg-teal-500 disabled:opacity-50"
                  >
                    Submit Manual Log
                  </button>
                </div>
              </SectionCard>

              <SectionCard
                title="Oracle"
                right={
                  <button
                    onClick={() =>
                      runWithRefresh(async () => {
                        return apiClient.rollTemerantOracle()
                      }, (event) =>
                        event
                          ? `Oracle event triggered: ${event.title}`
                          : 'Quiet day. No notable oracle event.'
                      )
                    }
                    disabled={submitting}
                    className="px-2.5 py-1.5 rounded bg-gray-800 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-60"
                  >
                    Roll Oracle
                  </button>
                }
              >
                {activeOracleEvent ? (
                  <div className="space-y-3">
                    <div className="border border-gray-700 bg-gray-900/70 rounded p-3">
                      <div className="flex items-center justify-between">
                        <div className="text-sm uppercase tracking-wide text-teal-400">{activeOracleEvent.tier}</div>
                        <div className="text-xs text-gray-500">{activeOracleEvent.category}</div>
                      </div>
                      <div className="mt-1 text-white font-medium">{activeOracleEvent.title}</div>
                      <p className="mt-1 text-sm text-gray-300">{activeOracleEvent.hook}</p>
                      {!!activeOracleEvent.options?.length && (
                        <ul className="mt-2 text-xs text-gray-400 list-disc list-inside">
                          {activeOracleEvent.options.map((option) => (
                            <li key={option}>{option}</li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <textarea
                      rows={2}
                      value={oracleResolution}
                      onChange={(e) => setOracleResolution(e.target.value)}
                      placeholder="Resolution notes (optional)"
                      className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                    />
                    <div className="flex gap-2">
                      <button
                        disabled={submitting}
                        onClick={() =>
                          runWithRefresh(async () => {
                            await apiClient.resolveTemerantOracleEvent(activeOracleEvent.id, {
                              status: 'resolved',
                              resolution: oracleResolution || undefined,
                            })
                            setOracleResolution('')
                          }, 'Oracle event resolved.')
                        }
                        className="px-3 py-2 rounded bg-emerald-600 text-white text-sm hover:bg-emerald-500 disabled:opacity-60"
                      >
                        Resolve
                      </button>
                      <button
                        disabled={submitting}
                        onClick={() =>
                          runWithRefresh(async () => {
                            await apiClient.resolveTemerantOracleEvent(activeOracleEvent.id, {
                              status: 'dismissed',
                              resolution: oracleResolution || undefined,
                            })
                            setOracleResolution('')
                          }, 'Oracle event dismissed.')
                        }
                        className="px-3 py-2 rounded bg-gray-700 text-white text-sm hover:bg-gray-600 disabled:opacity-60"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="text-sm text-gray-400">No open event. Roll the oracle after your daily logs.</p>
                    {dashboard.daily.oracle_roll_raw != null && (
                      <p className="text-xs text-gray-500">
                        Last roll: raw {dashboard.daily.oracle_roll_raw}
                        {dashboard.daily.oracle_roll_modified != null
                          ? `, modified ${dashboard.daily.oracle_roll_modified}`
                          : ''}
                      </p>
                    )}
                  </div>
                )}
              </SectionCard>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <SectionCard
                title="Journal (Last 7 Days)"
                right={
                  <button
                    onClick={() =>
                      runWithRefresh(async () => {
                        const today = new Date().toISOString().slice(0, 10)
                        await apiClient.generateTemerantJournal(today)
                      }, 'Journal regenerated for today.')
                    }
                    disabled={submitting}
                    className="px-2.5 py-1.5 rounded bg-gray-800 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-60"
                  >
                    Generate Today
                  </button>
                }
              >
                <div className="space-y-2">
                  {journalEntries.length === 0 && <p className="text-sm text-gray-400">No journal entries yet.</p>}
                  {journalEntries.map((entry) => (
                    <div key={entry.id} className="border border-gray-800 rounded p-3 bg-gray-900/60">
                      <div className="flex justify-between text-xs text-gray-400">
                        <span>{formatDate(entry.local_date)}</span>
                        <span>{entry.source_event_count} events</span>
                      </div>
                      <pre className="mt-2 text-xs text-gray-200 whitespace-pre-wrap font-sans line-clamp-4">{entry.summary_markdown}</pre>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard title="Economy and Admissions">
                <div className="space-y-2">
                  {termHistory.length === 0 && <p className="text-sm text-gray-400">No previous terms.</p>}
                  {termHistory.map((term) => (
                    <div key={term.id} className="grid grid-cols-4 gap-2 text-xs border border-gray-800 rounded p-2 bg-gray-900/60">
                      <div className="text-gray-300">{formatDate(term.term_month)}</div>
                      <div className="text-gray-400">{term.completion_pct.toFixed(1)}%</div>
                      <div className="text-gray-300 capitalize">{term.admissions_result}</div>
                      <div className="text-gray-200">{term.tuition_talents} talents</div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <SectionCard title="Recent Ledger">
                <div className="space-y-2 text-sm">
                  {ledgerEntries.length === 0 && <p className="text-gray-400">No ledger entries yet.</p>}
                  {ledgerEntries.map((entry) => (
                    <div key={entry.id} className="flex items-center justify-between border border-gray-800 rounded p-2 bg-gray-900/60">
                      <div>
                        <div className="text-gray-200">{ATTRIBUTE_META[entry.attribute].label}</div>
                        <div className="text-xs text-gray-500">{entry.meta?.action_type || entry.subdomain || entry.source_type}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-teal-300">+{entry.xp_delta} XP</div>
                        <div className="text-xs text-gray-500">{formatDate(entry.local_date)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard title="Mapping Rules">
                <div className="space-y-2 text-sm">
                  {mappingRules.length === 0 && <p className="text-gray-400">No mapping rules available.</p>}
                  {mappingRules.map((rule) => (
                    <div key={rule.id} className="flex items-center justify-between border border-gray-800 rounded p-2 bg-gray-900/60">
                      <div>
                        <div className="text-gray-200">{rule.source_kind}:{rule.source_ref || '*'}</div>
                        <div className="text-xs text-gray-500">{rule.target_subdomain || 'general'}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-gray-200">{rule.target_attribute} +{rule.xp_base}</div>
                        <div className="text-xs text-gray-500">{rule.enabled ? 'enabled' : 'disabled'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default TemerantPage
