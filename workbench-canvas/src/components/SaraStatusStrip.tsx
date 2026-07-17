import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bell, ChevronUp, ChevronDown, Layers } from 'lucide-react'
import { saraApi, attentionApi } from '../services/api'
import type { SaraStatus, SaraBrief } from '../types/sara'

interface SaraStatusStripProps {
  onAttentionClick: () => void
  onScenePickerClick: () => void
  attentionOpen: boolean
}

const MOOD_COLORS: Record<string, string> = {
  happy: '#4ade80',
  content: '#22d3ee',
  curious: '#a78bfa',
  concerned: '#fbbf24',
  focused: '#60a5fa',
  calm: '#34d399',
  thoughtful: '#818cf8',
  excited: '#f472b6',
  neutral: '#94a3b8',
  worried: '#f97316',
  sad: '#6b7280',
}

const ACTIVITY_LABELS: Record<string, string> = {
  SLEEPING: 'Sleeping',
  WAKING: 'Waking',
  MORNING_ROUTINE: 'Morning',
  ACTIVE: 'Active',
  FOCUSED_WORK: 'Focused',
  IN_MEETING: 'In Meeting',
  EXERCISING: 'Exercise',
  COOKING: 'Cooking',
  WINDING_DOWN: 'Winding Down',
  AWAY: 'Away',
  UNKNOWN: '',
}

export default function SaraStatusStrip({ onAttentionClick, onScenePickerClick, attentionOpen }: SaraStatusStripProps) {
  const [isCollapsed, setIsCollapsed] = useState(() => localStorage.getItem('sara-strip-collapsed') === 'true')
  const [thoughtIndex, setThoughtIndex] = useState(0)

  // Persist collapse state
  useEffect(() => {
    localStorage.setItem('sara-strip-collapsed', String(isCollapsed))
  }, [isCollapsed])

  // Sara status polling
  const { data: status } = useQuery<SaraStatus>({
    queryKey: ['sara-status'],
    queryFn: saraApi.getStatus,
    refetchInterval: 45_000,
    retry: 1,
  })

  // Sara brief polling
  const { data: brief } = useQuery<SaraBrief>({
    queryKey: ['sara-brief'],
    queryFn: saraApi.getBrief,
    refetchInterval: 120_000,
    retry: 1,
  })

  // Attention count polling
  const { data: attentionCount } = useQuery({
    queryKey: ['attention-count'],
    queryFn: attentionApi.getCount,
    refetchInterval: 30_000,
    retry: 1,
  })

  const count = attentionCount?.count || 0
  const moodColor = MOOD_COLORS[status?.emotional_state || 'neutral'] || MOOD_COLORS.neutral
  const rawActivity = brief?.activity_state || 'unknown'
  const activityState = rawActivity.toUpperCase()
  const activityLabel = ACTIVITY_LABELS[activityState] || ''
  const interruptibility = brief?.interruptibility ?? 0.5

  const normalizeText = (value: unknown): string | null => {
    if (typeof value === 'string') {
      const v = value.trim()
      return v || null
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value)
    }
    if (value && typeof value === 'object') {
      const obj = value as Record<string, unknown>
      const message = obj.message
      const text = obj.text
      const label = obj.label
      if (typeof message === 'string' && message.trim()) return message.trim()
      if (typeof text === 'string' && text.trim()) return text.trim()
      if (typeof label === 'string' && label.trim()) return label.trim()
    }
    return null
  }

  // Rotate through watching_for items
  const watchingForRaw = status?.watching_for
  const watchingFor = Array.isArray(watchingForRaw)
    ? watchingForRaw
    : normalizeText(watchingForRaw)
      ? [normalizeText(watchingForRaw) as string]
      : []
  const latestThought = normalizeText(status?.latest_thought)
  const displayTexts = [latestThought, ...watchingFor].map(normalizeText).filter(Boolean) as string[]

  useEffect(() => {
    if (displayTexts.length <= 1) return
    const interval = setInterval(() => {
      setThoughtIndex(prev => (prev + 1) % displayTexts.length)
    }, 8000)
    return () => clearInterval(interval)
  }, [displayTexts.length])

  const currentText = displayTexts[thoughtIndex % displayTexts.length] || ''

  // Collapsed: minimal strip
  if (isCollapsed) {
    return (
      <div className="fixed top-0 left-0 right-0 z-40 pointer-events-none">
        <div className="flex items-center justify-between px-3 py-1 pointer-events-auto">
          {/* Left: mood dot */}
          <div className="flex items-center gap-2">
            <div
              className="w-2.5 h-2.5 rounded-full shadow-lg"
              style={{ backgroundColor: moodColor, boxShadow: `0 0 6px ${moodColor}` }}
              title={`Mood: ${status?.emotional_state || 'unknown'}`}
            />
          </div>

          {/* Right: attention badge + expand */}
          <div className="flex items-center gap-2">
            {count > 0 && (
              <button
                onClick={onAttentionClick}
                className="relative p-1"
              >
                <Bell size={14} className="text-canvas-muted" />
                <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-red-500 rounded-full text-[9px] text-white flex items-center justify-center font-bold animate-pulse">
                  {count > 9 ? '9+' : count}
                </span>
              </button>
            )}
            <button onClick={() => setIsCollapsed(false)} className="p-1 text-canvas-muted hover:text-white">
              <ChevronDown size={14} />
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Expanded strip
  return (
    <div className="fixed top-0 left-0 right-0 z-40 pointer-events-none">
      <div className="mx-auto max-w-5xl px-4 pt-2 pointer-events-auto">
        <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-canvas-surface/80 backdrop-blur-md border border-canvas-border/50 shadow-lg">
          {/* Left: mood + activity */}
          <div className="flex items-center gap-2.5 flex-shrink-0">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: moodColor, boxShadow: `0 0 8px ${moodColor}40` }}
              title={`Mood: ${status?.emotional_state || 'unknown'}`}
            />
            {activityLabel && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-canvas-bg/60 text-canvas-muted border border-canvas-border/30">
                {activityLabel}
              </span>
            )}
          </div>

          {/* Center: rotating thought */}
          <div className="flex-1 min-w-0 text-center">
            <span
              className="text-xs text-canvas-muted/80 italic truncate block transition-opacity duration-500"
              key={thoughtIndex}
            >
              {currentText}
            </span>
          </div>

          {/* Right: interruptibility + attention + scene + collapse */}
          <div className="flex items-center gap-2.5 flex-shrink-0">
            {/* Interruptibility bar */}
            <div className="w-16 h-1.5 bg-canvas-bg/60 rounded-full overflow-hidden" title={`Interruptibility: ${Math.round(interruptibility * 100)}%`}>
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${interruptibility * 100}%`,
                  backgroundColor: interruptibility > 0.6 ? '#4ade80' : interruptibility > 0.3 ? '#fbbf24' : '#ef4444',
                }}
              />
            </div>

            {/* Attention badge */}
            <button
              onClick={onAttentionClick}
              className={`relative p-1.5 rounded-lg transition-colors ${attentionOpen ? 'bg-canvas-bg text-white' : 'text-canvas-muted hover:text-white hover:bg-canvas-bg/60'}`}
              title={`${count} attention items`}
            >
              <Bell size={16} />
              {count > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 rounded-full text-[10px] text-white flex items-center justify-center font-bold animate-pulse">
                  {count > 9 ? '9+' : count}
                </span>
              )}
            </button>

            {/* Scene picker */}
            <button
              onClick={onScenePickerClick}
              className="p-1.5 rounded-lg text-canvas-muted hover:text-white hover:bg-canvas-bg/60 transition-colors"
              title="Workspace scenes"
            >
              <Layers size={16} />
            </button>

            {/* Collapse */}
            <button
              onClick={() => setIsCollapsed(true)}
              className="p-1 text-canvas-muted hover:text-white"
            >
              <ChevronUp size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
