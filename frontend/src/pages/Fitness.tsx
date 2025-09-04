import { useState, useEffect, useRef } from 'react'
import { apiClient } from '../api/client'

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

type ChatOnboardingSession = {
  session_id: string
  stage: string
  message: string
  progress: number
  can_go_back: boolean
  completed: boolean
  plan_draft_id?: string
  conversation_history: ChatMessage[]
}

type PlanDraft = {
  plan_id: string
  phases: string[]
  weeks: number
  days: { title: string; duration_min?: number; blocks: { exercises: string[]; sets?: number; reps?: string; rpe?: string; rest?: number }[] }[]
}

export default function Fitness() {
  // Chat Onboarding
  const [chatSession, setChatSession] = useState<ChatOnboardingSession | null>(null)
  const [currentMessage, setCurrentMessage] = useState<string>('')
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [showChatOnboarding, setShowChatOnboarding] = useState<boolean>(true)
  
  // Onboarding/Plan
  const [daysPerWeek, setDaysPerWeek] = useState(3)
  const [sessionLen, setSessionLen] = useState(60)
  const [equipment, setEquipment] = useState<string>('barbell,rack,bench')
  const [style, setStyle] = useState<string>('')
  const [draft, setDraft] = useState<PlanDraft | null>(null)
  const [startDate, setStartDate] = useState<string>('')
  const [startTime, setStartTime] = useState<string>('18:00')
  const [commitResult, setCommitResult] = useState<any>(null)

  // Readiness
  const [readiness, setReadiness] = useState<any | null>(null)
  const [hrv, setHrv] = useState<string>('')
  const [rhr, setRhr] = useState<string>('')
  const [sleep, setSleep] = useState<string>('')
  const [energy, setEnergy] = useState<number>(3)
  const [soreness, setSoreness] = useState<number>(3)
  const [stress, setStress] = useState<number>(3)
  const [timeAvail, setTimeAvail] = useState<number>(60)

  // In-workout
  const [workoutId, setWorkoutId] = useState<string>('')
  const [sessionState, setSessionState] = useState<any | null>(null)
  const [nextSet, setNextSet] = useState<any | null>(null)
  const [setWeight, setSetWeight] = useState<string>('')
  const [setReps, setSetReps] = useState<string>('')
  const [setRpe, setSetRpe] = useState<string>('')

  // Auto-scroll handling for chat history
  const historyRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (historyRef.current) {
      historyRef.current.scrollTop = historyRef.current.scrollHeight
    }
  }, [chatSession?.conversation_history?.length, chatSession?.message])

  const handlePropose = async () => {
    const payload = {
      profile: {}, goals: {}, constraints: {},
      equipment: equipment.split(',').map(s => s.trim()).filter(Boolean),
      days_per_week: daysPerWeek,
      session_len_min: sessionLen,
      preferences: { style }
    }
    const resp = await apiClient.fitnessProposePlan(payload)
    setDraft(resp)
  }

  const handleCommit = async () => {
    if (!draft) return
    const edits: any = {}
    if (startDate) {
      edits.schedule = { start_date: startDate, time: startTime }
    }
    const resp = await apiClient.fitnessCommitPlan({ plan_id: draft.plan_id, edits })
    setCommitResult(resp)
  }

  const handleReadiness = async () => {
    const payload = {
      hrv_ms: hrv ? Number(hrv) : undefined,
      rhr: rhr ? Number(rhr) : undefined,
      sleep_hours: sleep ? Number(sleep) : undefined,
      energy, soreness, stress,
      time_available_min: timeAvail
    }
    const resp = await apiClient.fitnessReadiness(payload)
    setReadiness(resp)
  }

  const startWorkout = async () => {
    if (!workoutId) return
    const resp = await apiClient.fitnessStartWorkout(workoutId)
    setSessionState(resp)
    setNextSet(resp.next)
  }

  const logSet = async () => {
    if (!workoutId) return
    const payload = {
      workout_id: workoutId,
      exercise_id: nextSet?.exercises?.[0] || undefined,
      set_index: nextSet?.set_index || 1,
      weight: setWeight ? Number(setWeight) : undefined,
      reps: setReps ? Number(setReps) : undefined,
      rpe: setRpe ? Number(setRpe) : undefined
    }
    const resp = await apiClient.fitnessLogSet(workoutId, payload)
    setNextSet(resp.next_set)
  }

  const rest = async (act: 'start'|'end') => {
    if (!workoutId) return
    const resp = await apiClient.fitnessRest(workoutId, act)
    setSessionState(resp)
  }

  const complete = async () => {
    if (!workoutId) return
    const resp = await apiClient.fitnessComplete(workoutId)
    setSessionState(resp)
  }

  // Chat onboarding handlers
  const startChatOnboarding = async () => {
    setIsLoading(true)
    try {
      const response = await apiClient.fitnessStartChatOnboarding({
        flow_type: 'chat_onboarding'
      })
      setChatSession(response)
    } catch (error) {
      console.error('Failed to start chat onboarding:', error)
      alert('Failed to start onboarding. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const sendMessage = async () => {
    if (!chatSession || !currentMessage.trim() || isLoading) return
    
    setIsLoading(true)
    try {
      const response = await apiClient.fitnessContinueChatOnboarding(chatSession.session_id, {
        message: currentMessage.trim()
      })
      setChatSession(response)
      setCurrentMessage('')
      
      // If onboarding is completed, hide chat interface
      if (response.completed) {
        setShowChatOnboarding(false)
        // Optionally show success message or redirect
        alert('Onboarding completed! Your fitness plan is ready.')
      }
    } catch (error) {
      console.error('Failed to send message:', error)
      alert('Failed to send message. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const goBack = async () => {
    if (!chatSession || isLoading) return
    
    setIsLoading(true)
    try {
      const response = await apiClient.fitnessGoBackChatOnboarding(chatSession.session_id)
      setChatSession(response)
    } catch (error) {
      console.error('Failed to go back:', error)
      alert('Failed to go back. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-10">
      <div>
        <h1 className="text-2xl font-bold text-white mb-2">Fitness</h1>
        <p className="text-gray-400">Chat-based onboarding, readiness, and in-workout flow</p>
      </div>

      {/* Chat Onboarding */}
      {showChatOnboarding && (
        <section className="bg-card border border-card rounded-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-white">Fitness Journey Setup</h2>
            <button
              onClick={() => setShowChatOnboarding(false)}
              className="text-gray-400 hover:text-white px-2 py-1 rounded transition-colors"
            >
              ✕ Switch to Manual
            </button>
          </div>
          
          {!chatSession ? (
            <div className="text-center py-8">
              <p className="text-gray-400 mb-4">
                Let's have a conversation to understand your fitness goals and create a personalized plan.
              </p>
              <button
                onClick={startChatOnboarding}
                disabled={isLoading}
                className="px-6 py-3 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-800 text-white rounded-lg transition-colors"
              >
                {isLoading ? 'Starting...' : 'Start Fitness Chat'}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Progress bar */}
              <div className="w-full bg-gray-800 rounded-full h-2">
                <div 
                  className="bg-teal-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${chatSession.progress}%` }}
                />
              </div>
              <div className="text-sm text-gray-400 text-center">
                {chatSession.stage} - {Math.round(chatSession.progress)}% complete
              </div>
              
              {/* Conversation history */}
              <div ref={historyRef} className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 max-h-96 overflow-y-auto">
                <div className="space-y-3">
                  {chatSession.conversation_history.map((msg, index) => (
                    <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[80%] p-3 rounded-lg ${
                        msg.role === 'user' 
                          ? 'bg-teal-600 text-white ml-12' 
                          : 'bg-gray-700 text-gray-100 mr-12'
                      }`}>
                        <div className="text-sm">{msg.content}</div>
                        {msg.timestamp && (
                          <div className="text-xs opacity-70 mt-1">
                            {new Date(msg.timestamp).toLocaleTimeString()}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  
                  {/* Current assistant message (only if not already in history) */}
                  {(() => {
                    const hist = chatSession.conversation_history
                    const last = hist[hist.length - 1]
                    const shouldShow = chatSession.message && (!last || last.role !== 'assistant' || last.content !== chatSession.message)
                    return shouldShow ? (
                      <div className="flex justify-start">
                        <div className="max-w-[80%] p-3 rounded-lg bg-gray-700 text-gray-100 mr-12">
                          <div className="text-sm">{chatSession.message}</div>
                        </div>
                      </div>
                    ) : null
                  })()}
                </div>
              </div>

              {/* Input area */}
              <div className="flex gap-2">
                <textarea
                  value={currentMessage}
                  onChange={(e) => setCurrentMessage(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Type your response..."
                  className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400 resize-none"
                  rows={2}
                  disabled={isLoading}
                />
                <div className="flex flex-col gap-2">
                  <button
                    onClick={sendMessage}
                    disabled={!currentMessage.trim() || isLoading}
                    className="px-4 py-2 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-800 text-white rounded-lg transition-colors"
                  >
                    {isLoading ? '...' : 'Send'}
                  </button>
                  {chatSession.can_go_back && (
                    <button
                      onClick={goBack}
                      disabled={isLoading}
                      className="px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 text-white rounded-lg transition-colors"
                    >
                      Back
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Manual Onboarding / Plan - Only show if chat onboarding is hidden */}
      {!showChatOnboarding && (
      <section className="bg-card border border-card rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">Manual Plan Setup</h2>
          <button
            onClick={() => {
              setShowChatOnboarding(true)
              setChatSession(null)
            }}
            className="text-gray-400 hover:text-teal-400 px-3 py-1 rounded transition-colors border border-gray-600 hover:border-teal-500"
          >
            💬 Try Chat Setup
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Days / week</label>
            <input type="number" value={daysPerWeek} onChange={e=>setDaysPerWeek(Number(e.target.value))} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Session length (min)</label>
            <input type="number" value={sessionLen} onChange={e=>setSessionLen(Number(e.target.value))} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm text-gray-400 mb-1">Equipment (comma-separated)</label>
            <input type="text" value={equipment} onChange={e=>setEquipment(e.target.value)} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm text-gray-400 mb-1">Style preference</label>
            <input type="text" value={style} onChange={e=>setStyle(e.target.value)} placeholder="e.g., ppl, ul/ul, kb, hybrid" className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" />
          </div>
          <div className="flex items-end gap-2">
            <button onClick={handlePropose} className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded transition-colors">Propose</button>
          </div>
        </div>

        {draft && (
          <div className="mt-4">
            <div className="flex items-center gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Start date</label>
                <input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Time</label>
                <input type="time" value={startTime} onChange={e=>setStartTime(e.target.value)} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" />
              </div>
              <button onClick={handleCommit} className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded transition-colors self-end">Commit & schedule</button>
            </div>
            <div className="mt-4 text-sm text-gray-400">
              <p><strong className="text-white">Phases:</strong> {draft.phases.join(', ')} • <strong className="text-white">Weeks:</strong> {draft.weeks}</p>
              <div className="mt-2 grid gap-3">
                {draft.days.map((d, i) => (
                  <div key={i} className="border border-card rounded p-3 bg-gray-800/50">
                    <div className="font-medium text-white">{d.title} <span className="text-gray-400">(~{d.duration_min || 60} min)</span></div>
                    <ul className="mt-1 text-gray-400 text-sm list-disc pl-5">
                      {d.blocks.map((b, j) => (
                        <li key={j}>{b.exercises.join(' / ')} — {b.sets || '?'}×{b.reps || '?'} @RPE {b.rpe || '-'} (rest {b.rest || 60}s)</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
            {commitResult && (
              <div className="mt-3 p-3 bg-green-900/50 border border-green-700 text-green-300 rounded">
                {commitResult.summary}
              </div>
            )}
          </div>
        )}
      </section>
      )}

      {/* Morning Readiness */}
      <section className="bg-card border border-card rounded-xl p-6 space-y-4">
        <h2 className="text-xl font-semibold text-white">Morning Readiness</h2>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <div>
            <label className="block text-sm text-gray-400 mb-1">HRV (ms)</label>
            <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={hrv} onChange={e=>setHrv(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">RHR</label>
            <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={rhr} onChange={e=>setRhr(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Sleep (h)</label>
            <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={sleep} onChange={e=>setSleep(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Energy (1-5)</label>
            <input type="number" min={1} max={5} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={energy} onChange={e=>setEnergy(Number(e.target.value))} />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Soreness (1-5)</label>
            <input type="number" min={1} max={5} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={soreness} onChange={e=>setSoreness(Number(e.target.value))} />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Stress (1-5)</label>
            <input type="number" min={1} max={5} className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={stress} onChange={e=>setStress(Number(e.target.value))} />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm text-gray-400 mb-1">Time available (min)</label>
            <input type="number" className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={timeAvail} onChange={e=>setTimeAvail(Number(e.target.value))} />
          </div>
          <div className="flex items-end">
            <button onClick={handleReadiness} className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded transition-colors">Compute</button>
          </div>
        </div>
        {readiness && (
          <div className="p-3 bg-teal-900/50 border border-teal-700 text-teal-300 rounded">
            <div><strong>Score:</strong> {readiness.score} • <strong>Recommendation:</strong> {readiness.recommendation}</div>
            <div className="text-sm mt-1">{readiness.message}</div>
          </div>
        )}
      </section>

      {/* In-Workout */}
      <section className="bg-card border border-card rounded-xl p-6 space-y-4">
        <h2 className="text-xl font-semibold text-white">In-Workout</h2>
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-400 mb-1">Workout ID</label>
            <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" value={workoutId} onChange={e=>setWorkoutId(e.target.value)} placeholder="paste a workout id" />
          </div>
          <button onClick={startWorkout} className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded transition-colors">Start</button>
          <button onClick={()=>rest('start')} className="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors">Rest</button>
          <button onClick={()=>rest('end')} className="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors">Resume</button>
          <button onClick={complete} className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded transition-colors">Complete</button>
        </div>
        {nextSet && (
          <div className="p-3 bg-gray-800/50 border border-card rounded">
            <div className="font-medium text-white">Now: {nextSet.exercises?.join(' / ')} — Set {nextSet.set_index}/{nextSet.total_sets}</div>
            <div className="text-sm text-gray-400">Target: {nextSet.prescription?.reps || '?'} reps @RPE {nextSet.prescription?.rpe || '-'} • Rest {nextSet.prescription?.rest || 60}s</div>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" placeholder="weight" value={setWeight} onChange={e=>setSetWeight(e.target.value)} />
          <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" placeholder="reps" value={setReps} onChange={e=>setSetReps(e.target.value)} />
          <input className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400" placeholder="RPE" value={setRpe} onChange={e=>setSetRpe(e.target.value)} />
          <button onClick={logSet} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded transition-colors">Save & Next</button>
        </div>
      </section>

      {/* Privacy/Controls */}
      <section className="bg-card border border-card rounded-xl p-6 space-y-3">
        <h2 className="text-xl font-semibold text-white">Privacy & Controls</h2>
        <div className="flex gap-2">
          <button onClick={async()=>{ const data=await apiClient.fitnessExport('json'); console.log('export', data); alert('Exported to console (JSON).') }} className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors">Export JSON</button>
          <button onClick={async()=>{ await apiClient.fitnessResetOnboarding(); alert('Onboarding reset') }} className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors">Reset Onboarding</button>
          <button onClick={async()=>{ await apiClient.fitnessDisconnectHealth(); alert('Health disconnected') }} className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded transition-colors">Disconnect Health</button>
        </div>
      </section>
    </div>
  )
}
