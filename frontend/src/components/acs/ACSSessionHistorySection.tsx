import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface SessionNote {
  id: string
  title: string
  folder?: string
  created_at: string
}

interface ACSSession {
  id: string
  cognitive_mode: string
  state: string
  started_at: string
  ended_at?: string
  end_reason?: string
  turns_completed: number
  notes_created: number
  duration_minutes?: number
  duration_seconds?: number
  engagement_score?: number
  model_id?: string
  outcome_type?: string
  artifact_summary?: string
  outbound_messages?: number
  suppressed_messages?: number
}

interface AuditDialogueMessage {
  role: 'auditor' | 'sara'
  content: string
  ts?: string
}

interface TranscriptEntry {
  type: 'system_prompt' | 'user_turn' | 'assistant_turn' | 'tool_result' | 'audit_dialogue' | string
  content?: string
  ts?: string
  turn?: number
  tool?: string
  args?: string
  result?: string
  tool_calls?: Array<{ name: string; args: string }>
  // audit_dialogue fields
  audit_id?: string
  trigger_kind?: string
  trigger_reason?: string
  messages?: AuditDialogueMessage[]
  outcome?: string
  resolution?: string
}

interface SessionTranscript {
  session_id: string
  mode?: string
  started_at?: string
  entries: TranscriptEntry[]
  available: boolean
  reason?: string
}

interface SessionDetail {
  id: string
  model_id?: string
  state: string
  started_at: string
  ended_at?: string
  end_reason?: string
  turns_completed: number
  notes_created: number
  curiosities_explored?: number
  token_usage?: number | Record<string, number>
  context_summary?: string
  error_log?: string | null
  cognitive_mode?: string
  engagement_score?: number
  // v2 fields
  interest_nodes_created?: number
  interest_nodes_updated?: number
  interest_edges_created?: number
  notes_written?: number
  self_model_updated?: boolean
  avg_engagement?: number
  early_termination?: boolean
  primary_topic?: string
  primary_objective?: string
  expected_artifact?: string
  outcome_type?: string
  artifact_summary?: string
  outbound_messages?: number
  suppressed_messages?: number
}

const MODE_COLORS: Record<string, string> = {
  exploration: 'bg-indigo-900/30 text-indigo-400',
  consolidation: 'bg-emerald-900/30 text-emerald-400',
  reflection: 'bg-purple-900/30 text-purple-400',
  research: 'bg-blue-900/30 text-blue-400',
  learning: 'bg-amber-900/30 text-amber-400',
}

const STATUS_COLORS: Record<string, string> = {
  completed: 'text-emerald-400',
  ended: 'text-emerald-400',
  running: 'text-blue-400',
  autonomous: 'text-blue-400',
  paused: 'text-amber-400',
  pausing: 'text-amber-400',
  error: 'text-red-400',
}

function formatDuration(startedAt: string, endedAt?: string): string {
  const start = new Date(startedAt)
  const end = endedAt ? new Date(endedAt) : new Date()
  const diffMs = end.getTime() - start.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 60) return `${mins}m`
  return `${Math.floor(mins / 60)}h ${mins % 60}m`
}

function getTokenTotal(tokens: number | Record<string, number>): number {
  if (typeof tokens === 'number') return tokens
  return Object.values(tokens).reduce((sum, v) => sum + (typeof v === 'number' ? v : 0), 0)
}

function formatTokens(tokens: number | Record<string, number>): string {
  const total = getTokenTotal(tokens)
  if (total >= 1000) return `${(total / 1000).toFixed(1)}k`
  return `${total}`
}

function buildTranscriptText(
  session: ACSSession,
  detail: SessionDetail | undefined,
  transcript: SessionTranscript | undefined,
  sessionNotes: SessionNote[] | undefined,
): string {
  const lines: string[] = []
  lines.push(`# ACS Session Transcript`)
  lines.push(`Session ID: ${session.id}`)
  if (session.cognitive_mode) lines.push(`Mode: ${session.cognitive_mode}`)
  if (detail?.model_id) lines.push(`Model: ${detail.model_id}`)
  lines.push(`State: ${session.state}`)
  lines.push(`Started: ${new Date(session.started_at).toLocaleString()}`)
  if (session.ended_at) lines.push(`Ended: ${new Date(session.ended_at).toLocaleString()}`)
  lines.push(`Duration: ${formatDuration(session.started_at, session.ended_at)}`)
  lines.push(`Turns: ${session.turns_completed}`)
  lines.push(`Notes Created: ${session.notes_created}`)
  if (session.end_reason) lines.push(`End reason: ${session.end_reason}`)
  if (detail?.token_usage != null) {
    lines.push(`Tokens: ${formatTokens(detail.token_usage)}`)
  }
  if (detail?.engagement_score != null) {
    lines.push(`Engagement: ${(detail.engagement_score * 100).toFixed(0)}%`)
  }
  lines.push('')

  if (detail?.context_summary) {
    lines.push(`## Session Summary`)
    lines.push(detail.context_summary)
    lines.push('')
  }

  if (detail?.outcome_type || detail?.artifact_summary) {
    lines.push(`## Outcome`)
    if (detail.outcome_type) lines.push(`Type: ${detail.outcome_type}`)
    if (detail.artifact_summary) lines.push(detail.artifact_summary)
    lines.push('')
  }

  if (detail?.error_log) {
    lines.push(`## Error Log`)
    lines.push(detail.error_log)
    lines.push('')
  }

  if (sessionNotes && sessionNotes.length > 0) {
    lines.push(`## Notes Created (${sessionNotes.length})`)
    for (const n of sessionNotes) {
      lines.push(`- ${n.title}${n.folder ? ` [${n.folder}]` : ''}`)
    }
    lines.push('')
  }

  lines.push(`## Full Transcript`)
  if (!transcript || !transcript.available || !transcript.entries || transcript.entries.length === 0) {
    lines.push(transcript?.reason || 'Transcript unavailable.')
    return lines.join('\n')
  }

  for (const e of transcript.entries) {
    const ts = e.ts ? new Date(e.ts).toLocaleTimeString() : ''
    if (e.type === 'system_prompt') {
      lines.push(`### System Prompt${ts ? `  [${ts}]` : ''}`)
      if (e.content) lines.push(e.content)
      lines.push('')
    } else if (e.type === 'user_turn') {
      lines.push(`### Turn ${e.turn ?? '?'} — Prompt${ts ? `  [${ts}]` : ''}`)
      if (e.content) lines.push(e.content)
      lines.push('')
    } else if (e.type === 'assistant_turn') {
      lines.push(`### Turn ${e.turn ?? '?'} — Sara${ts ? `  [${ts}]` : ''}`)
      if (e.content) lines.push(e.content)
      if (e.tool_calls && e.tool_calls.length > 0) {
        for (const tc of e.tool_calls) {
          lines.push(`  → tool call: ${tc.name}(${tc.args})`)
        }
      }
      lines.push('')
    } else if (e.type === 'tool_result') {
      lines.push(`  ← ${e.tool} result${ts ? `  [${ts}]` : ''}`)
      if (e.result) lines.push(`    ${e.result}`)
      lines.push('')
    } else if (e.type === 'audit_dialogue') {
      lines.push(`### 🛑 AUDITOR INTERVENTION (${e.outcome || 'unresolved'})${ts ? `  [${ts}]` : ''}`)
      if (e.trigger_reason) lines.push(`Trigger: ${e.trigger_kind} — ${e.trigger_reason}`)
      lines.push('')
      for (const m of (e.messages || [])) {
        const role = m.role === 'auditor' ? 'AUDITOR' : 'SARA'
        lines.push(`${role}:`)
        lines.push(m.content)
        lines.push('')
      }
      if (e.resolution) {
        lines.push(`Resolution: ${e.resolution}`)
      }
      lines.push('')
    } else {
      lines.push(`### ${e.type}${ts ? `  [${ts}]` : ''}`)
      if (e.content) lines.push(e.content)
      lines.push('')
    }
  }

  return lines.join('\n')
}

function downloadTextFile(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function ACSSessionHistorySection() {
  const [sessions, setSessions] = useState<ACSSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, SessionNote[]>>({})
  const [details, setDetails] = useState<Record<string, SessionDetail>>({})
  const [transcripts, setTranscripts] = useState<Record<string, SessionTranscript>>({})
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({})
  const limit = 20

  const fetchSessions = useCallback(async (newOffset: number) => {
    try {
      const res = await fetch(
        `${APP_CONFIG.apiUrl}/api/acs/sessions?limit=${limit}&offset=${newOffset}`,
        { credentials: 'include' }
      )
      if (res.ok) {
        const data = await res.json()
        const items: ACSSession[] = Array.isArray(data) ? data : data.sessions || []
        if (newOffset === 0) {
          setSessions(items)
        } else {
          setSessions(prev => [...prev, ...items])
        }
        setHasMore(items.length === limit)
        setError(null)
      } else {
        setError('Failed to load sessions')
      }
    } catch {
      setError('Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSessions(0) }, [fetchSessions])

  const loadMore = () => {
    const newOffset = offset + limit
    setOffset(newOffset)
    fetchSessions(newOffset)
  }

  const toggleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null)
      return
    }
    setExpandedId(id)

    // Fetch detail, notes, and transcript in parallel if not already cached
    const needsDetail = !details[id]
    const needsNotes = !notes[id]
    const needsTranscript = !transcripts[id]

    if (needsDetail || needsNotes || needsTranscript) {
      setDetailLoading(prev => ({ ...prev, [id]: true }))

      const fetches: Promise<void>[] = []

      if (needsDetail) {
        fetches.push(
          fetch(`${APP_CONFIG.apiUrl}/api/acs/sessions/${id}`, { credentials: 'include' })
            .then(res => res.ok ? res.json() : null)
            .then(data => {
              if (data) setDetails(prev => ({ ...prev, [id]: data }))
            })
            .catch(() => {})
        )
      }

      if (needsNotes) {
        fetches.push(
          fetch(`${APP_CONFIG.apiUrl}/api/acs/sessions/${id}/notes`, { credentials: 'include' })
            .then(res => res.ok ? res.json() : null)
            .then(data => {
              if (data) {
                const notesList: SessionNote[] = Array.isArray(data) ? data : data.notes || []
                setNotes(prev => ({ ...prev, [id]: notesList }))
              }
            })
            .catch(() => {})
        )
      }

      if (needsTranscript) {
        fetches.push(
          fetch(`${APP_CONFIG.apiUrl}/api/acs/sessions/${id}/transcript`, { credentials: 'include' })
            .then(res => res.ok ? res.json() : null)
            .then(data => {
              if (data) setTranscripts(prev => ({ ...prev, [id]: data }))
            })
            .catch(() => {})
        )
      }

      await Promise.all(fetches)
      setDetailLoading(prev => ({ ...prev, [id]: false }))
    }
  }

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>

  if (sessions.length === 0) {
    return (
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-8 text-center">
        <p className="text-gray-400">No sessions recorded yet.</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {sessions.map(session => (
        <div key={session.id} className="bg-gray-800/50 rounded-lg border border-gray-700">
          <button
            onClick={() => toggleExpand(session.id)}
            className="w-full p-4 text-left"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-0.5 rounded ${MODE_COLORS[session.cognitive_mode] || 'bg-gray-700 text-gray-400'}`}>
                  {session.cognitive_mode || 'unknown'}
                </span>
                <span className={`text-sm ${STATUS_COLORS[session.state] || 'text-gray-400'}`}>
                  {session.state}
                </span>
              </div>
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span>{session.turns_completed} turns</span>
                <span>{session.notes_created} notes</span>
                {transcripts[session.id]?.entries && (() => {
                  const auditCount = transcripts[session.id].entries.filter(e => e.type === 'audit_dialogue').length
                  return auditCount > 0 ? (
                    <span className="text-red-400 font-medium">🛑 audited {auditCount}x</span>
                  ) : null
                })()}
                <span>{formatDuration(session.started_at, session.ended_at)}</span>
                <span>{new Date(session.started_at).toLocaleString()}</span>
              </div>
            </div>
            {session.end_reason && (
              <p className="text-xs text-gray-500 mt-1">{session.end_reason}</p>
            )}
          </button>

          {expandedId === session.id && (
            <div className="px-4 pb-4 border-t border-gray-700/50">
              {detailLoading[session.id] ? (
                <div className="text-gray-500 text-sm py-3">Loading session details...</div>
              ) : (
                <>
                  {/* Export action */}
                  <div className="flex justify-end mt-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        const text = buildTranscriptText(
                          session,
                          details[session.id],
                          transcripts[session.id],
                          notes[session.id],
                        )
                        const ts = new Date(session.started_at)
                          .toISOString()
                          .replace(/[:.]/g, '-')
                          .slice(0, 19)
                        const mode = session.cognitive_mode || 'session'
                        const filename = `acs-${mode}-${ts}-${session.id.slice(0, 8)}.txt`
                        downloadTextFile(filename, text)
                      }}
                      className="text-xs px-2.5 py-1 rounded border border-gray-700 text-gray-300 hover:text-white hover:border-indigo-500/60 hover:bg-indigo-900/20 transition-colors"
                      title="Download this session as a .txt file"
                    >
                      Export .txt
                    </button>
                  </div>

                  {/* Context Summary */}
                  {details[session.id]?.context_summary && (
                    <div className="mt-3">
                      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Session Summary</h4>
                      <p className="text-sm text-gray-300 leading-relaxed bg-gray-900/40 rounded-md p-3">
                        {details[session.id].context_summary}
                      </p>
                    </div>
                  )}

                  {/* Stats Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3 text-sm">
                    <div>
                      <span className="text-gray-500">Duration:</span>{' '}
                      <span className="text-gray-300">{session.duration_minutes ? `${session.duration_minutes}m` : formatDuration(session.started_at, session.ended_at)}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Started:</span>{' '}
                      <span className="text-gray-300">{new Date(session.started_at).toLocaleString()}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Ended:</span>{' '}
                      <span className="text-gray-300">{session.ended_at ? new Date(session.ended_at).toLocaleString() : 'Running'}</span>
                    </div>
                    {details[session.id]?.model_id && (
                      <div>
                        <span className="text-gray-500">Model:</span>{' '}
                        <span className="text-gray-300 font-mono text-xs">{details[session.id].model_id}</span>
                      </div>
                    )}
                    {details[session.id]?.token_usage != null && getTokenTotal(details[session.id].token_usage!) > 0 && (
                      <div>
                        <span className="text-gray-500">Tokens:</span>{' '}
                        <span className="text-gray-300">{formatTokens(details[session.id].token_usage!)}</span>
                      </div>
                    )}
                    {(details[session.id]?.engagement_score ?? session.engagement_score) != null && (
                      <div>
                        <span className="text-gray-500">Engagement:</span>{' '}
                        <span className="text-gray-300">
                          {((details[session.id]?.engagement_score ?? session.engagement_score)! * 100).toFixed(0)}%
                        </span>
                      </div>
                    )}
                    {details[session.id]?.avg_engagement != null && details[session.id]?.avg_engagement !== details[session.id]?.engagement_score && (
                      <div>
                        <span className="text-gray-500">Avg Engagement:</span>{' '}
                        <span className="text-gray-300">{(details[session.id].avg_engagement! * 100).toFixed(0)}%</span>
                      </div>
                    )}
                    {details[session.id]?.curiosities_explored != null && details[session.id]!.curiosities_explored! > 0 && (
                      <div>
                        <span className="text-gray-500">Curiosities:</span>{' '}
                        <span className="text-gray-300">{details[session.id].curiosities_explored}</span>
                      </div>
                    )}
                  </div>

                  {/* Interest Graph Activity */}
                  {details[session.id] && (
                    (details[session.id].interest_nodes_created || details[session.id].interest_nodes_updated || details[session.id].interest_edges_created) ? (
                      <div className="mt-3">
                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Interest Graph Activity</h4>
                        <div className="flex flex-wrap gap-3 text-sm">
                          {details[session.id].interest_nodes_created != null && details[session.id].interest_nodes_created! > 0 && (
                            <span className="bg-indigo-900/20 text-indigo-400 px-2 py-0.5 rounded text-xs">
                              +{details[session.id].interest_nodes_created} nodes created
                            </span>
                          )}
                          {details[session.id].interest_nodes_updated != null && details[session.id].interest_nodes_updated! > 0 && (
                            <span className="bg-cyan-900/20 text-cyan-400 px-2 py-0.5 rounded text-xs">
                              {details[session.id].interest_nodes_updated} nodes updated
                            </span>
                          )}
                          {details[session.id].interest_edges_created != null && details[session.id].interest_edges_created! > 0 && (
                            <span className="bg-purple-900/20 text-purple-400 px-2 py-0.5 rounded text-xs">
                              +{details[session.id].interest_edges_created} edges created
                            </span>
                          )}
                          {details[session.id].self_model_updated && (
                            <span className="bg-amber-900/20 text-amber-400 px-2 py-0.5 rounded text-xs">
                              self-model updated
                            </span>
                          )}
                          {details[session.id].early_termination && (
                            <span className="bg-red-900/20 text-red-400 px-2 py-0.5 rounded text-xs">
                              early termination
                            </span>
                          )}
                        </div>
                      </div>
                    ) : null
                  )}

                  {/* Error Log */}
                  {details[session.id]?.error_log && (
                    <div className="mt-3">
                      <h4 className="text-xs font-semibold text-red-500 uppercase tracking-wider mb-1.5">Error Log</h4>
                      <pre className="text-xs text-red-300 bg-red-900/20 border border-red-800/40 rounded-md p-3 overflow-x-auto whitespace-pre-wrap">
                        {details[session.id].error_log}
                      </pre>
                    </div>
                  )}

                  {/* Notes */}
                  {notes[session.id] && notes[session.id].length > 0 && (
                    <div className="mt-3">
                      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Notes Created</h4>
                      <div className="space-y-1">
                        {notes[session.id].map(note => (
                          <div key={note.id} className="text-sm text-gray-300 flex items-center gap-2">
                            <span>{note.title}</span>
                            {note.folder && <span className="text-xs text-gray-600">{note.folder}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {notes[session.id] && notes[session.id].length === 0 && (
                    <p className="text-xs text-gray-600 mt-3">No notes created in this session.</p>
                  )}

                  {/* Full Transcript */}
                  {transcripts[session.id] && (
                    <div className="mt-4">
                      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                        Full Transcript
                        {transcripts[session.id].available && transcripts[session.id].entries.length > 0 && (
                          <span className="ml-2 text-gray-600 normal-case font-normal">
                            ({transcripts[session.id].entries.length} entries)
                          </span>
                        )}
                      </h4>
                      {!transcripts[session.id].available ? (
                        <p className="text-xs text-gray-600 italic bg-gray-900/40 rounded-md p-3">
                          {transcripts[session.id].reason || 'Transcript unavailable.'}
                        </p>
                      ) : transcripts[session.id].entries.length === 0 ? (
                        <p className="text-xs text-gray-600 italic">Transcript is empty.</p>
                      ) : (
                        <div className="bg-gray-900/40 rounded-md border border-gray-800 max-h-96 overflow-y-auto p-3 space-y-3 font-mono text-xs">
                          {transcripts[session.id].entries.map((entry, idx) => {
                            const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString() : ''
                            if (entry.type === 'system_prompt') {
                              return (
                                <div key={idx} className="border-l-2 border-gray-600 pl-2">
                                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
                                    System Prompt {ts && <span className="text-gray-600">· {ts}</span>}
                                  </div>
                                  <div className="text-gray-400 whitespace-pre-wrap break-words">{entry.content}</div>
                                </div>
                              )
                            }
                            if (entry.type === 'user_turn') {
                              return (
                                <div key={idx} className="border-l-2 border-indigo-600 pl-2">
                                  <div className="text-[10px] uppercase tracking-wider text-indigo-400 mb-1">
                                    Turn {entry.turn} · Prompt {ts && <span className="text-gray-600">· {ts}</span>}
                                  </div>
                                  <div className="text-gray-200 whitespace-pre-wrap break-words">{entry.content}</div>
                                </div>
                              )
                            }
                            if (entry.type === 'assistant_turn') {
                              return (
                                <div key={idx} className="border-l-2 border-emerald-600 pl-2">
                                  <div className="text-[10px] uppercase tracking-wider text-emerald-400 mb-1">
                                    Turn {entry.turn} · Sara {ts && <span className="text-gray-600">· {ts}</span>}
                                  </div>
                                  <div className="text-gray-200 whitespace-pre-wrap break-words">{entry.content}</div>
                                  {entry.tool_calls && entry.tool_calls.length > 0 && (
                                    <div className="mt-1 space-y-0.5">
                                      {entry.tool_calls.map((tc, tcIdx) => (
                                        <div key={tcIdx} className="text-amber-400">
                                          → {tc.name}({tc.args})
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )
                            }
                            if (entry.type === 'tool_result') {
                              return (
                                <div key={idx} className="border-l-2 border-amber-700 pl-2">
                                  <div className="text-[10px] uppercase tracking-wider text-amber-500 mb-1">
                                    ← {entry.tool} result {ts && <span className="text-gray-600">· {ts}</span>}
                                  </div>
                                  <div className="text-gray-400 whitespace-pre-wrap break-words">{entry.result}</div>
                                </div>
                              )
                            }
                            if (entry.type === 'audit_dialogue') {
                              const outcomeColor =
                                entry.outcome === 'stopped' ? 'text-red-400 border-red-600' :
                                entry.outcome === 'redirected' ? 'text-amber-400 border-amber-600' :
                                entry.outcome === 'timeout' ? 'text-gray-400 border-gray-600' :
                                'text-indigo-400 border-indigo-600'
                              return (
                                <div key={idx} className={`border-2 ${outcomeColor} rounded-md p-3 bg-red-950/20`}>
                                  <div className="text-[10px] uppercase tracking-wider text-red-400 font-bold mb-1">
                                    🛑 AUDITOR INTERVENTION ({entry.outcome || 'unresolved'})
                                    {ts && <span className="text-gray-600 font-normal"> · {ts}</span>}
                                  </div>
                                  {entry.trigger_reason && (
                                    <div className="text-[10px] text-gray-500 italic mb-2">
                                      Trigger: {entry.trigger_kind} — {entry.trigger_reason}
                                    </div>
                                  )}
                                  <div className="space-y-2 mt-2">
                                    {(entry.messages || []).map((m, mi) => (
                                      <div key={mi} className={`pl-2 border-l-2 ${
                                        m.role === 'auditor' ? 'border-red-500' : 'border-emerald-500'
                                      }`}>
                                        <div className={`text-[10px] uppercase tracking-wider mb-0.5 ${
                                          m.role === 'auditor' ? 'text-red-400' : 'text-emerald-400'
                                        }`}>
                                          {m.role === 'auditor' ? 'AUDITOR' : 'SARA'}
                                        </div>
                                        <div className="text-gray-200 whitespace-pre-wrap break-words">
                                          {m.content}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                  {entry.resolution && (
                                    <div className="mt-3 pt-2 border-t border-gray-700">
                                      <div className="text-[10px] uppercase tracking-wider text-amber-400 mb-0.5">
                                        Resolution
                                      </div>
                                      <div className="text-gray-200 whitespace-pre-wrap break-words">
                                        → {entry.resolution}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )
                            }
                            return (
                              <div key={idx} className="text-gray-500">
                                <span className="text-[10px] uppercase tracking-wider">{entry.type}</span>
                                {entry.content && <div className="whitespace-pre-wrap break-words">{entry.content}</div>}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      ))}

      {hasMore && (
        <button onClick={loadMore}
          className="w-full py-2 text-sm text-indigo-400 hover:text-indigo-300 transition-colors">
          Load more sessions
        </button>
      )}
    </div>
  )
}
