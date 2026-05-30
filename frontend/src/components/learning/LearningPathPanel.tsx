import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'

interface PathStep {
  topic_id: string
  topic_title: string
  priority_score: number
  current_mastery: number
  actions: Array<{
    type: string
    description: string
    suggestion?: string
    focus?: string
  }>
  estimated_time: string
  reason: string
  status?: 'completed' | 'active' | 'pending'
  completed_at?: string | null
}

interface Recommendation {
  type: string
  message: string
  priority: string
  affected_topics?: string[]
}

interface LearningPathData {
  path: PathStep[]
  summary: string
  recommendations: Recommendation[]
  stats: {
    total_topics: number
    avg_mastery: number
    topics_needing_review: number
    topics_with_gaps: number
  }
  persisted?: boolean
  generated_at?: string
  progress?: { completed: number; total: number }
}

interface BlueprintSummary {
  id: string
  status?: string
}

interface BlueprintModule {
  code?: string
  title?: string
  summary?: string | null
}

interface BlueprintPhase {
  index?: number
  title?: string
  duration_label?: string | null
  modules?: BlueprintModule[]
}

interface BlueprintParsedJson {
  phases?: BlueprintPhase[]
}

interface BlueprintDetail {
  id: string
  title: string
  description?: string | null
  status?: string
  materialized_at?: string | null
  updated_at?: string | null
  created_at?: string | null
  parsed_json?: BlueprintParsedJson
}

interface BlueprintProgress {
  completed_modules?: number
  total_modules?: number
}

interface LearningPathPanelProps {
  onSelectTopic: (topicId: string) => void
  isVisible: boolean
  onClose: () => void
  focusTopicId?: string
  focusTopicTitle?: string
}

export default function LearningPathPanel({ onSelectTopic, isVisible, onClose, focusTopicId, focusTopicTitle }: LearningPathPanelProps) {
  const [pathData, setPathData] = useState<LearningPathData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [gatheringSources, setGatheringSources] = useState<Record<number, boolean>>({})
  const [gatheredSources, setGatheredSources] = useState<Record<number, { count: number; message: string }>>({})
  const [completingStep, setCompletingStep] = useState<number | null>(null)
  const [loadedForTopicId, setLoadedForTopicId] = useState<string | undefined>(undefined)
  const [isBlueprintPath, setIsBlueprintPath] = useState(false)

  useEffect(() => {
    if (isVisible) {
      // Cache only topic-specific paths; global path should refresh so newly imported plans appear.
      if (focusTopicId && pathData && !error && loadedForTopicId === focusTopicId) return
      loadLearningPath()
    }
  }, [isVisible, focusTopicId])

  const handleGatherSources = async (stepIndex: number, concept: string) => {
    if (!focusTopicId || gatheringSources[stepIndex]) return
    setGatheringSources(prev => ({ ...prev, [stepIndex]: true }))
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/learn/topics/${focusTopicId}/find-more-sources`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ focus: concept, count: 3, fetch_inline: true })
        }
      )
      if (response.ok) {
        const data = await response.json()
        setGatheredSources(prev => ({
          ...prev,
          [stepIndex]: { count: data.sources_added, message: data.message }
        }))
      }
    } catch (err) {
      /* ignore */
    } finally {
      setGatheringSources(prev => ({ ...prev, [stepIndex]: false }))
    }
  }

  const handleCompleteStep = async (stepIndex: number) => {
    if (!focusTopicId || completingStep !== null) return
    setCompletingStep(stepIndex)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/learn/curriculum/${focusTopicId}/steps/${stepIndex}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ status: 'completed' })
        }
      )
      if (response.ok) {
        const curriculum = await response.json()
        // Update local state from the returned curriculum
        updatePathFromCurriculum(curriculum)
      }
    } catch (err) {
      /* ignore */
    } finally {
      setCompletingStep(null)
    }
  }

  const updatePathFromCurriculum = (curriculum: any) => {
    if (!pathData || !curriculum?.steps) return
    const steps = curriculum.steps
    const completed = steps.filter((s: any) => s.status === 'completed').length
    const total = steps.length

    const newPath = steps.map((step: any) => ({
      topic_id: focusTopicId!,
      topic_title: step.concept,
      priority_score: 100 - step.index * 5,
      current_mastery: 0,
      actions: [{ type: step.action_type, description: step.description }],
      estimated_time: step.estimated_time,
      reason: step.reason,
      status: step.status,
      completed_at: step.completed_at,
    }))

    setPathData({
      ...pathData,
      path: newPath,
      persisted: true,
      progress: { completed, total }
    })
    setIsBlueprintPath(false)
  }

  const buildPathFromBlueprint = (blueprint: BlueprintDetail, progress: BlueprintProgress | null): LearningPathData | null => {
    const phases = Array.isArray(blueprint?.parsed_json?.phases) ? blueprint.parsed_json?.phases || [] : []
    const orderedSteps = phases.flatMap((phase, phaseIndex) => {
      const modules = Array.isArray(phase.modules) ? phase.modules : []
      return modules.map((module, moduleIndex) => ({
        module,
        phase,
        phaseIndex,
        moduleIndex
      }))
    })

    if (orderedSteps.length === 0) return null

    const completedCount = Math.max(
      0,
      Math.min(progress?.completed_modules || 0, orderedSteps.length)
    )

    const path = orderedSteps.map(({ module, phase, phaseIndex, moduleIndex }, index) => {
      const status: PathStep['status'] =
        index < completedCount ? 'completed' : (index === completedCount ? 'active' : 'pending')
      return {
        topic_id: '',
        topic_title: module.title || module.code || `Module ${index + 1}`,
        priority_score: Math.max(10, 100 - index * 3),
        current_mastery: 0,
        actions: [{
          type: 'study',
          description: (module.summary || `Study ${module.title || module.code || 'this module'}`).slice(0, 180)
        }],
        estimated_time: phase.duration_label || '60-90 min',
        reason: `Phase ${phase.index || phaseIndex + 1}${phase.title ? `: ${phase.title}` : ''}${module.code ? ` • ${module.code}` : ''}`,
        status
      }
    })

    const total = progress?.total_modules || orderedSteps.length
    const completed = Math.min(completedCount, total)

    return {
      path,
      summary: blueprint.description || `Showing your imported learning plan: ${blueprint.title}`,
      recommendations: [],
      stats: {
        total_topics: orderedSteps.length,
        avg_mastery: total > 0 ? completed / total : 0,
        topics_needing_review: 0,
        topics_with_gaps: 0
      },
      persisted: true,
      generated_at: blueprint.materialized_at || blueprint.updated_at || blueprint.created_at,
      progress: { completed, total }
    }
  }

  const loadLatestBlueprintPath = async (): Promise<boolean> => {
    try {
      const listRes = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints`, {
        credentials: 'include'
      })
      if (!listRes.ok) return false

      const listData = await listRes.json()
      const rows = Array.isArray(listData?.blueprints) ? (listData.blueprints as BlueprintSummary[]) : []
      if (rows.length === 0) return false

      const target = rows.find((row) => row.status === 'materialized') || rows[0]
      if (!target?.id) return false

      const detailRes = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${target.id}`, {
        credentials: 'include'
      })
      if (!detailRes.ok) return false
      const detail = (await detailRes.json()) as BlueprintDetail

      let progress: BlueprintProgress | null = null
      if (target.status === 'materialized') {
        const progressRes = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${target.id}/progress`, {
          credentials: 'include'
        })
        if (progressRes.ok) {
          progress = (await progressRes.json()) as BlueprintProgress
        }
      }

      const mapped = buildPathFromBlueprint(detail, progress)
      if (!mapped) return false

      setPathData(mapped)
      setLoadedForTopicId(undefined)
      setIsBlueprintPath(true)
      return true
    } catch {
      return false
    }
  }

  const loadLearningPath = async () => {
    setLoading(true)
    setError(null)
    setGatheredSources({})
    setGatheringSources({})

    // For topic-focused views, try persisted curriculum first
    if (focusTopicId) {
      try {
        const currRes = await fetch(
          `${APP_CONFIG.apiUrl}/api/learn/curriculum/${focusTopicId}`,
          { credentials: 'include' }
        )
        if (currRes.ok) {
          const curriculum = await currRes.json()
          const steps = curriculum.steps || []
          const completed = steps.filter((s: any) => s.status === 'completed').length

          setPathData({
            path: steps.map((step: any) => ({
              topic_id: focusTopicId,
              topic_title: step.concept,
              priority_score: 100 - step.index * 5,
              current_mastery: 0,
              actions: [{ type: step.action_type, description: step.description }],
              estimated_time: step.estimated_time,
              reason: step.reason,
              status: step.status,
              completed_at: step.completed_at,
            })),
            summary: curriculum.summary,
            recommendations: [],
            stats: { total_topics: 1, avg_mastery: 0, topics_needing_review: 0, topics_with_gaps: 0 },
            persisted: true,
            generated_at: curriculum.generated_at,
            progress: { completed, total: steps.length }
          })
          setLoadedForTopicId(focusTopicId)
          setIsBlueprintPath(false)
          setLoading(false)
          return
        }
        // 404 = no persisted curriculum, fall through to generate
      } catch {
        // fall through
      }
    }

    // For global path view, prefer the latest imported blueprint plan.
    if (!focusTopicId) {
      const loadedBlueprint = await loadLatestBlueprintPath()
      if (loadedBlueprint) {
        setLoading(false)
        return
      }
    }

    // Generate via /path (will auto-persist for topic-focused paths)
    try {
      const params = new URLSearchParams({ max_steps: '10' })
      if (focusTopicId) {
        params.set('focus_topic_id', focusTopicId)
      }
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/path?${params}`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setPathData(data)
        setLoadedForTopicId(focusTopicId)
        setIsBlueprintPath(false)
      } else {
        setError('Failed to load learning path')
      }
    } catch (err) {
      setError('Could not connect to server')
    } finally {
      setLoading(false)
    }
  }

  const handleRegenerate = async () => {
    if (!focusTopicId) {
      setLoadedForTopicId(undefined)
      loadLearningPath()
      return
    }
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/learn/curriculum/${focusTopicId}/regenerate`,
        { method: 'POST', credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setPathData(data)
        setLoadedForTopicId(focusTopicId)
      } else {
        setError('Failed to regenerate curriculum')
      }
    } catch {
      setError('Could not connect to server')
    } finally {
      setLoading(false)
    }
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'text-red-400 bg-red-500/10'
      case 'medium': return 'text-yellow-400 bg-yellow-500/10'
      case 'low': return 'text-green-400 bg-green-500/10'
      default: return 'text-gray-400 bg-gray-500/10'
    }
  }

  const getActionIcon = (type: string) => {
    switch (type) {
      case 'add_sources': return 'search'
      case 'fetch_sources': return 'download'
      case 'study': return 'menu_book'
      case 'practice': return 'edit_note'
      case 'review': return 'refresh'
      case 'quick_review': return 'timer'
      case 'connect': return 'hub'
      case 'teach': return 'school'
      case 'take_notes': return 'note_add'
      default: return 'play_arrow'
    }
  }

  const getMasteryColor = (mastery: number) => {
    if (mastery >= 0.85) return 'text-green-400'
    if (mastery >= 0.6) return 'text-teal-400'
    if (mastery >= 0.3) return 'text-yellow-400'
    return 'text-orange-400'
  }

  if (!isVisible) return null

  const progress = pathData?.progress

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-md border border-gray-700 w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="material-icons text-teal-400 text-2xl">route</span>
            <div>
              <h2 className="text-lg font-semibold text-white">
                {focusTopicTitle ? `Path: ${focusTopicTitle}` : 'Your Learning Path'}
              </h2>
              <p className="text-sm text-gray-400">
                {focusTopicTitle
                  ? 'How to approach this topic'
                  : (isBlueprintPath ? 'Loaded from your imported plan' : 'Personalized study recommendations')}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <span className="material-icons">close</span>
          </button>
        </div>

        {/* Progress bar */}
        {progress && progress.total > 0 && (
          <div className="px-6 py-2 border-b border-gray-700/50 bg-gray-800/30">
            <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
              <span>{progress.completed}/{progress.total} steps complete</span>
              <span>{Math.round((progress.completed / progress.total) * 100)}%</span>
            </div>
            <div className="w-full bg-gray-700 rounded-full h-1.5">
              <div
                className="bg-teal-500 h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${(progress.completed / progress.total) * 100}%` }}
              />
            </div>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-teal-500 border-t-transparent"></div>
            </div>
          ) : error ? (
            <div className="text-center py-12 text-gray-400">
              <span className="material-icons text-4xl mb-2">error_outline</span>
              <p>{error}</p>
              <button onClick={loadLearningPath} className="mt-4 text-teal-400 hover:text-teal-300">
                Try again
              </button>
            </div>
          ) : pathData ? (
            <div className="space-y-6">
              {/* Summary */}
              <div className="bg-gray-800/50 rounded-lg p-4">
                <p className="text-gray-300">{pathData.summary}</p>
                {!focusTopicId && pathData.stats && (
                  <div className="flex flex-wrap gap-4 mt-3 text-sm">
                    <span className="text-gray-500">
                      <span className="text-white font-medium">{pathData.stats.total_topics}</span> topics
                    </span>
                    <span className="text-gray-500">
                      <span className={getMasteryColor(pathData.stats.avg_mastery)}>
                        {Math.round(pathData.stats.avg_mastery * 100)}%
                      </span> avg mastery
                    </span>
                    {pathData.stats.topics_needing_review > 0 && (
                      <span className="text-yellow-400">
                        {pathData.stats.topics_needing_review} need review
                      </span>
                    )}
                    {pathData.stats.topics_with_gaps > 0 && (
                      <span className="text-orange-400">
                        {pathData.stats.topics_with_gaps} with gaps
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Path Steps */}
              {pathData.path.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
                    {focusTopicId ? 'Curriculum' : (isBlueprintPath ? 'Plan Modules' : 'Recommended Path')}
                  </h3>
                  <div className="space-y-3">
                    {pathData.path.map((step, index) => {
                      const stepStatus = step.status || 'pending'
                      const isCompleted = stepStatus === 'completed'
                      const isActive = stepStatus === 'active'
                      const canSelectTopic = !focusTopicId && !isBlueprintPath && !!step.topic_id

                      return (
                        <div
                          key={`${step.topic_id}-${index}`}
                          className={`bg-gray-800 rounded-lg p-4 border transition-colors ${
                            isActive
                              ? 'border-teal-500/70 ring-1 ring-teal-500/30'
                              : isCompleted
                                ? 'border-green-500/30 opacity-75'
                                : 'border-gray-700 hover:border-teal-500/50'
                          } ${canSelectTopic ? 'cursor-pointer' : ''}`}
                          onClick={() => {
                            if (canSelectTopic) {
                              onSelectTopic(step.topic_id)
                              onClose()
                            }
                          }}
                        >
                          <div className="flex items-start gap-3">
                            {/* Step number / completion toggle */}
                            {focusTopicId ? (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (!isCompleted) handleCompleteStep(index)
                                }}
                                disabled={isCompleted || completingStep !== null}
                                className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-all ${
                                  isCompleted
                                    ? 'bg-green-500/20 text-green-400'
                                    : isActive
                                      ? 'bg-teal-500/20 text-teal-400 ring-2 ring-teal-500/50 hover:bg-teal-500/30'
                                      : 'bg-gray-700 text-gray-500'
                                } ${!isCompleted && completingStep === null ? 'cursor-pointer' : ''}`}
                                title={isCompleted ? 'Completed' : isActive ? 'Mark as complete' : 'Pending'}
                              >
                                {completingStep === index ? (
                                  <div className="animate-spin rounded-full h-4 w-4 border border-teal-400 border-t-transparent" />
                                ) : isCompleted ? (
                                  <span className="material-icons text-sm">check</span>
                                ) : (
                                  <span className="text-sm font-medium">{index + 1}</span>
                                )}
                              </button>
                            ) : (
                              <div className="w-8 h-8 rounded-full bg-teal-500/20 flex items-center justify-center text-teal-400 font-medium flex-shrink-0">
                                {index + 1}
                              </div>
                            )}

                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <h4 className={`font-medium truncate ${isCompleted ? 'text-gray-400 line-through' : 'text-white'}`}>
                                  {step.topic_title}
                                </h4>
                                {!focusTopicId && (
                                  <span className={`text-xs ${getMasteryColor(step.current_mastery)}`}>
                                    {Math.round(step.current_mastery * 100)}%
                                  </span>
                                )}
                                {isActive && (
                                  <span className="text-xs px-1.5 py-0.5 rounded bg-teal-500/15 text-teal-400">current</span>
                                )}
                              </div>
                              <p className={`text-sm mb-2 ${isCompleted ? 'text-gray-500' : 'text-gray-400'}`}>{step.reason}</p>
                              <div className="flex flex-wrap gap-2">
                                {step.actions.map((action, actionIndex) => (
                                  <span
                                    key={actionIndex}
                                    className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-700 text-gray-300"
                                  >
                                    <span className="material-icons text-xs">{getActionIcon(action.type)}</span>
                                    {action.description.slice(0, 50)}{action.description.length > 50 ? '...' : ''}
                                  </span>
                                ))}
                              </div>
                              <div className="flex items-center gap-3 mt-2">
                                <div className="text-xs text-gray-500">
                                  <span className="material-icons text-xs align-middle mr-1">schedule</span>
                                  {step.estimated_time}
                                </div>
                                {focusTopicId && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      handleGatherSources(index, step.topic_title)
                                    }}
                                    disabled={gatheringSources[index]}
                                    className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-teal-500/10 text-teal-400 hover:bg-teal-500/20 transition-colors disabled:opacity-50"
                                  >
                                    {gatheringSources[index] ? (
                                      <>
                                        <div className="animate-spin rounded-full h-3 w-3 border border-teal-400 border-t-transparent" />
                                        Searching...
                                      </>
                                    ) : gatheredSources[index] ? (
                                      <>
                                        <span className="material-icons text-xs">check_circle</span>
                                        {gatheredSources[index].count} sources added
                                      </>
                                    ) : (
                                      <>
                                        <span className="material-icons text-xs">search</span>
                                        Gather Sources
                                      </>
                                    )}
                                  </button>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Recommendations */}
              {pathData.recommendations.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
                    Recommendations
                  </h3>
                  <div className="space-y-2">
                    {pathData.recommendations.map((rec, index) => (
                      <div
                        key={index}
                        className={`rounded-lg p-3 ${getPriorityColor(rec.priority)}`}
                      >
                        <p className="text-sm">{rec.message}</p>
                        {rec.affected_topics && rec.affected_topics.length > 0 && (
                          <div className="mt-1 text-xs opacity-75">
                            Topics: {rec.affected_topics.join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Empty state */}
              {pathData.path.length === 0 && pathData.recommendations.length === 0 && (
                <div className="text-center py-8 text-gray-400">
                  <span className="material-icons text-4xl mb-2">emoji_events</span>
                  <p>You're all caught up! Create new topics to expand your learning.</p>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-700 bg-gray-800/50 flex justify-between items-center">
          <button
            onClick={handleRegenerate}
            disabled={loading}
            className="text-sm text-gray-400 hover:text-white flex items-center gap-1"
          >
            <span className="material-icons text-sm">autorenew</span>
            {focusTopicId ? 'Regenerate' : 'Refresh'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white text-sm rounded-lg transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}
