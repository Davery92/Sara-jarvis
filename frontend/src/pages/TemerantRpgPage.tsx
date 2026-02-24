import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  apiClient,
  ChatModel,
  TemerantRpgStateResponse,
  TemerantRpgTurnResponse,
  TemerantRpgJournalEntryResponse,
  TemerantRpgTermResponse,
} from '../api/client'

const Section = ({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) => (
  <section className="bg-card border border-card rounded-xl p-4">
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-base font-semibold text-white">{title}</h2>
      {right}
    </div>
    {children}
  </section>
)

const ATTRIBUTE_OPTIONS = ['body', 'mind', 'craft', 'voice', 'luck']

const STARTER_ACTIONS = [
  {
    label: 'Find a bed for the night',
    action: 'I ask around for the cheapest safe place to sleep before Admissions tomorrow morning.',
    attribute: 'voice',
    skill: 'streetwise',
  },
  {
    label: 'Scout the University gates',
    action: 'I walk the bridge and carefully observe the gates, guards, and students coming and going.',
    attribute: 'mind',
    skill: 'observation',
  },
  {
    label: 'Practice lute quietly',
    action: 'I sit somewhere quiet and practice three simple chord transitions until my fingers stop fumbling.',
    attribute: 'craft',
    skill: 'lute',
  },
]

function TemerantRpgPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [showHowItWorks, setShowHowItWorks] = useState(false)

  const [state, setState] = useState<TemerantRpgStateResponse | null>(null)
  const [journal, setJournal] = useState<TemerantRpgJournalEntryResponse[]>([])
  const [terms, setTerms] = useState<TemerantRpgTermResponse[]>([])
  const [lastTurn, setLastTurn] = useState<TemerantRpgTurnResponse | null>(null)
  const [availableModels, setAvailableModels] = useState<ChatModel[]>([])
  const [selectedModel, setSelectedModel] = useState('')

  const [createForm, setCreateForm] = useState({ character_name: 'Daveth of Andentown', origin: 'Commonwealth, Andentown', backstory: '' })
  const [action, setAction] = useState('')
  const [skill, setSkill] = useState('')
  const [attribute, setAttribute] = useState('mind')
  const [closeSummary, setCloseSummary] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      const [modelsResponse, modelSetting] = await Promise.all([
        apiClient.getChatModels(),
        apiClient.getTemerantRpgModelSetting(),
      ])
      setAvailableModels(modelsResponse.models || [])
      setSelectedModel(modelSetting.model || modelsResponse.default || '')
    } catch {
      setAvailableModels([])
      setSelectedModel('')
    }
    try {
      const s = await apiClient.getTemerantRpgState()
      setState(s)
      const [j, t] = await Promise.all([
        apiClient.listTemerantRpgJournal(10),
        apiClient.listTemerantRpgTerms(6),
      ])
      setJournal(j)
      setTerms(t)
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setState(null)
        setJournal([])
        setTerms([])
        return
      }
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to load Temerant RPG state.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const run = useCallback(async (fn: () => Promise<void>, ok?: string) => {
    setSubmitting(true)
    setError(null)
    setStatus(null)
    try {
      await fn()
      if (ok) setStatus(ok)
      await load()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Action failed.')
    } finally {
      setSubmitting(false)
    }
  }, [load])

  const openScene = state?.open_scene
  const relationships = useMemo(() => state?.relationships || [], [state])

  if (loading) {
    return <div className="flex-1 min-h-0 p-6"><div className="bg-card border border-card rounded-xl p-6 text-gray-300">Loading scene engine...</div></div>
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-4">
        <section className="bg-card border border-card rounded-xl p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-widest text-amber-300">A Life in Temerant</p>
              <h1 className="text-2xl font-semibold text-white">Scene-Based Solo RPG</h1>
              <p className="mt-1 text-sm text-gray-400">Persistent world. Consequences. Time slots. LLM-driven GM.</p>
              <button
                type="button"
                onClick={() => setShowHowItWorks((v) => !v)}
                className="mt-3 rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-100 hover:bg-gray-700"
              >
                {showHowItWorks ? 'Hide how it works' : 'How it works'}
              </button>
            </div>
            <div className="min-w-[260px]">
              <label className="block text-xs text-gray-400">RPG GM Model</label>
              <div className="mt-1 flex gap-2">
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="w-full rounded border border-gray-700 bg-gray-900 px-2 py-2 text-sm text-white"
                >
                  {availableModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.name} ({m.id})</option>
                  ))}
                </select>
                <button
                  disabled={submitting || !selectedModel}
                  onClick={() => run(async () => { await apiClient.updateTemerantRpgModelSetting(selectedModel) }, `RPG model set to ${selectedModel}.`)}
                  className="rounded bg-gray-700 px-3 py-2 text-xs text-white hover:bg-gray-600 disabled:opacity-50"
                >
                  Save
                </button>
              </div>
            </div>
          </div>
          {showHowItWorks && (
            <div className="mt-4 rounded border border-amber-800/40 bg-amber-950/20 p-4 text-sm text-amber-100">
              <p className="font-medium">Play loop</p>
              <p className="mt-1 text-amber-200/90">Open a scene, describe Daveth’s action, then the GM resolves outcomes with consequences. Close the scene to advance the day naturally.</p>
              <p className="mt-3 font-medium">What is tracked</p>
              <p className="mt-1 text-amber-200/90">Coin, conditions, skills, relationships, world state, and term progress. Nothing is free, and choices persist across scenes.</p>
              <p className="mt-3 font-medium">Time structure</p>
              <p className="mt-1 text-amber-200/90">Each day uses morning, afternoon, evening slots. Use `Advance Slot` between scenes when you want time to pass.</p>
              <p className="mt-3 font-medium">Growth</p>
              <p className="mt-1 text-amber-200/90">Skills improve through repeated practice over scenes. Admissions at term boundaries sets tuition based on your reputation and performance.</p>
            </div>
          )}
        </section>

        {!state && (
          <section className="rounded-xl border border-blue-800/40 bg-blue-950/20 p-4 text-sm text-blue-100">
            <p className="font-medium">Quick start</p>
            <p className="mt-1 text-blue-200/90">1) Create your character. 2) Open your first scene. 3) Write one specific action and resolve it.</p>
            <p className="mt-2 text-xs text-blue-300/90">Tip: Specific actions produce better GM responses than vague commands.</p>
          </section>
        )}

        {error && <div className="rounded-xl border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-300">{error}</div>}
        {status && <div className="rounded-xl border border-emerald-700/40 bg-emerald-900/20 px-4 py-3 text-sm text-emerald-300">{status}</div>}

        {!state && (
          <Section title="Create Character">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <input className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-white" placeholder="Character name" value={createForm.character_name} onChange={(e) => setCreateForm((p) => ({ ...p, character_name: e.target.value }))} />
              <input className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-white" placeholder="Origin" value={createForm.origin} onChange={(e) => setCreateForm((p) => ({ ...p, origin: e.target.value }))} />
              <textarea className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-white md:col-span-2" rows={4} value={createForm.backstory} onChange={(e) => setCreateForm((p) => ({ ...p, backstory: e.target.value }))} placeholder="Optional backstory override" />
            </div>
            <button
              disabled={submitting || !createForm.character_name.trim()}
              onClick={() => run(async () => { await apiClient.createTemerantRpgCharacter(createForm) }, 'Character created.')}
              className="mt-3 rounded bg-amber-600 px-4 py-2 text-sm text-white hover:bg-amber-500 disabled:opacity-50"
            >
              Begin
            </button>
          </Section>
        )}

        {state && (
          <>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
              <Section title={state.character.character_name}>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between"><span className="text-gray-400">Term</span><span className="text-white">{state.character.term_index}</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">Coin</span><span className="text-white">{state.character.coin_talents.toFixed(1)} talents</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">Slot</span><span className="text-white">{state.world.day_slot}</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">Date</span><span className="text-white">{state.world.local_date}</span></div>
                </div>
              </Section>

              <Section title="World">
                <div className="text-sm text-gray-300">
                  <p>{state.world.weather} in {state.world.location_hint}.</p>
                  {!!state.world.ambient_events?.length && (
                    <ul className="mt-2 list-disc list-inside text-xs text-gray-400">
                      {state.world.ambient_events.map((e) => <li key={e}>{e}</li>)}
                    </ul>
                  )}
                </div>
              </Section>

              <Section
                title="Time"
                right={
                  <button
                    disabled={submitting || !!openScene}
                    onClick={() => run(async () => { await apiClient.advanceTemerantRpgTime(1) }, 'Time advanced by one slot.')}
                    className="rounded bg-gray-800 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-50"
                  >
                    Advance Slot
                  </button>
                }
              >
                <p className="text-sm text-gray-400">{state.world.last_advance_summary || 'No recent time skip.'}</p>
              </Section>
            </div>

            <Section
              title={openScene ? `Scene ${openScene.scene_number}: ${openScene.title}` : 'Scene'}
              right={!openScene ? (
                <button
                  disabled={submitting}
                  onClick={() => run(async () => { await apiClient.openTemerantRpgScene() }, 'Scene opened.')}
                  className="rounded bg-amber-600 px-2.5 py-1.5 text-xs text-white hover:bg-amber-500 disabled:opacity-50"
                >
                  Open Scene
                </button>
              ) : undefined}
            >
              {!openScene && (
                <div className="space-y-3">
                  <p className="text-sm text-gray-400">No open scene. Open one to continue play.</p>
                  <div className="rounded border border-gray-800 bg-gray-900/60 p-3">
                    <p className="text-xs uppercase tracking-wide text-gray-400">Recommended flow</p>
                    <p className="mt-1 text-sm text-gray-300">Open a scene, take one concrete action, resolve it, then close the scene and advance time.</p>
                  </div>
                </div>
              )}
              {openScene && (
                <div className="space-y-3">
                  <pre className="whitespace-pre-wrap rounded border border-gray-800 bg-gray-900/70 p-3 text-sm text-gray-200 font-sans">{openScene.opening_text}</pre>

                  {lastTurn && (
                    <div className="rounded border border-teal-800/40 bg-teal-950/20 p-3">
                      <p className="text-xs uppercase tracking-wide text-teal-300">{lastTurn.outcome} ({lastTurn.total} vs {lastTurn.difficulty})</p>
                      <pre className="mt-1 whitespace-pre-wrap text-sm text-gray-200 font-sans">{lastTurn.response_text}</pre>
                    </div>
                  )}

                  <div className="rounded border border-gray-800 bg-gray-900/60 p-3">
                    <p className="text-xs uppercase tracking-wide text-gray-400">Starter actions</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {STARTER_ACTIONS.map((item) => (
                        <button
                          key={item.label}
                          type="button"
                          onClick={() => {
                            setAction(item.action)
                            setAttribute(item.attribute)
                            setSkill(item.skill)
                          }}
                          className="rounded border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-700"
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                    <select value={attribute} onChange={(e) => setAttribute(e.target.value)} className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white">
                      {ATTRIBUTE_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                    <input value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="Skill (optional): sympathy, tinkering..." className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white" />
                    <button
                      disabled={submitting || !action.trim()}
                      onClick={() => run(async () => {
                        const turn = await apiClient.actTemerantRpgScene(openScene.id, {
                          action: action.trim(),
                          attribute: attribute.trim() || undefined,
                          skill: skill.trim() || undefined,
                        })
                        setLastTurn(turn)
                        setAction('')
                      })}
                      className="rounded bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-500 disabled:opacity-50"
                    >
                      Resolve Action
                    </button>
                  </div>
                  <textarea value={action} onChange={(e) => setAction(e.target.value)} rows={3} placeholder="What does Daveth do right now? Be concrete. Example: I buy stale bread, then ask the innkeeper if any bunk costs less than a jot." className="w-full rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white" />

                  <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                    <input value={closeSummary} onChange={(e) => setCloseSummary(e.target.value)} placeholder="Scene summary (optional)" className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white md:col-span-2" />
                    <button
                      disabled={submitting}
                      onClick={() => run(async () => { await apiClient.closeTemerantRpgScene(openScene.id, closeSummary || undefined); setCloseSummary('') }, 'Scene closed.')}
                      className="rounded bg-gray-700 px-3 py-2 text-sm text-white hover:bg-gray-600 disabled:opacity-50"
                    >
                      Close Scene
                    </button>
                  </div>
                </div>
              )}
            </Section>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Section
                title="Admissions"
                right={
                  <button
                    disabled={submitting}
                    onClick={() => run(async () => { await apiClient.runTemerantRpgAdmissions() }, 'Admissions resolved for current term.')}
                    className="rounded bg-gray-800 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-50"
                  >
                    Run Admissions
                  </button>
                }
              >
                <div className="space-y-2 text-sm">
                  {terms.length === 0 && <p className="text-gray-400">No admissions records yet.</p>}
                  {terms.map((term) => (
                    <div key={term.id} className="rounded border border-gray-800 bg-gray-900/60 p-2">
                      <div className="flex justify-between text-xs text-gray-400">
                        <span>Term {term.term_index}</span>
                        <span>{term.month}</span>
                      </div>
                      <div className="mt-1 text-gray-200">{term.admissions_result} - {term.tuition_talents.toFixed(1)} talents</div>
                      <div className="text-xs text-gray-500">{term.summary}</div>
                    </div>
                  ))}
                </div>
              </Section>

              <Section
                title="Journal"
                right={
                  <button
                    disabled={submitting}
                    onClick={() => run(async () => { await apiClient.generateTemerantRpgJournal() }, 'Journal regenerated for current date.')}
                    className="rounded bg-gray-800 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-50"
                  >
                    Generate
                  </button>
                }
              >
                <div className="space-y-2">
                  {journal.length === 0 && <p className="text-sm text-gray-400">No journal entries yet.</p>}
                  {journal.map((entry) => (
                    <div key={entry.id} className="rounded border border-gray-800 bg-gray-900/60 p-2">
                      <div className="text-xs text-gray-400">{entry.local_date}</div>
                      <pre className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-gray-200 font-sans">{entry.summary_markdown}</pre>
                    </div>
                  ))}
                </div>
              </Section>
            </div>

            <Section title="Relationships">
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                {relationships.map((r) => (
                  <div key={r.npc_key} className="rounded border border-gray-800 bg-gray-900/60 p-3 text-sm">
                    <div className="text-white">{r.display_name}</div>
                    <div className="text-xs text-gray-400">Disposition: {r.disposition}</div>
                    <div className="text-xs text-gray-400">Trust: {r.trust}</div>
                    <div className="text-xs text-gray-400">Respect: {r.respect}</div>
                  </div>
                ))}
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  )
}

export default TemerantRpgPage
