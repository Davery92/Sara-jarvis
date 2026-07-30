import { useCallback, useEffect, useRef, useState } from 'react'
import { APP_CONFIG } from '../config'
import type { AppView } from '../navigation/views'

interface UseDashboardWorkspaceOptions {
  isAuthenticated: boolean
  view: AppView
  onShowToast: (message: string, type?: string, persistent?: boolean, highlight?: boolean) => void
}

export function useDashboardWorkspace({
  isAuthenticated,
  view,
  onShowToast,
}: UseDashboardWorkspaceOptions) {
  const [timers, setTimers] = useState<any[]>([])
  const [reminders, setReminders] = useState<any[]>([])
  const [currentTime, setCurrentTime] = useState(new Date())
  const [finishedTimers, setFinishedTimers] = useState<Set<string | number>>(new Set())
  const [notifiedReminders, setNotifiedReminders] = useState<Set<string | number>>(new Set())
  const [morningBrief, setMorningBrief] = useState<any>(null)
  const [morningBriefLoading, setMorningBriefLoading] = useState(false)
  const [weather, setWeather] = useState<any>(null)
  const [calendarEvents, setCalendarEvents] = useState<any[]>([])
  const [saraStatus, setSaraStatus] = useState<any>(null)
  const [connectedDevices, setConnectedDevices] = useState<any[]>([])
  const [standingOrders, setStandingOrders] = useState<any[]>([])
  const [journalEntries, setJournalEntries] = useState<any[]>([])
  const [expandedJournalEntries, setExpandedJournalEntries] = useState<Set<string>>(new Set())
  const [attentionCounts, setAttentionCounts] = useState<any>({ new: 0, sent: 0, read: 0, archived: 0, unread: 0 })
  const [attentionItems, setAttentionItems] = useState<any[]>([])
  const [missions, setMissions] = useState<any[]>([])
  const [briefAudioPlaying, setBriefAudioPlaying] = useState(false)
  const briefAudioRef = useRef<HTMLAudioElement>(null)
  const briefAudioUrlRef = useRef<string | null>(null)

  const loadTimersAndReminders = useCallback(async () => {
    try {
      const timersResponse = await fetch(`${APP_CONFIG.apiUrl}/timers`, {
        credentials: 'include',
      })
      if (timersResponse.ok) {
        const timersData = await timersResponse.json()
        setTimers(timersData)
      }

      const remindersResponse = await fetch(`${APP_CONFIG.apiUrl}/reminders`, {
        credentials: 'include',
      })
      if (remindersResponse.ok) {
        const remindersData = await remindersResponse.json()

        remindersData.forEach((reminder: any) => {
          const reminderTime = new Date(reminder.reminder_time)
          const timeDiff = Math.abs(reminderTime.getTime() - currentTime.getTime())

          if (timeDiff < 30000 && !notifiedReminders.has(reminder.id)) {
            setNotifiedReminders((prev) => new Set([...prev, reminder.id]))
            onShowToast(`🔔 Reminder: ${reminder.title}`, 'info', true, true)
          }
        })

        setReminders(remindersData)
      }
    } catch (error) {
      console.error('Failed to load timers/reminders:', error)
    }
  }, [currentTime, notifiedReminders, onShowToast])

  const stopTimer = useCallback(async (timerId: string | number) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/timers/${timerId}/stop`, {
        method: 'PATCH',
        credentials: 'include',
      })
      if (response.ok) {
        await loadTimersAndReminders()
      }
    } catch (error) {
      console.error('Failed to stop timer:', error)
    }
  }, [loadTimersAndReminders])

  const loadMorningBrief = useCallback(async () => {
    setMorningBriefLoading(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/today`, { credentials: 'include' })
      if (res.ok) setMorningBrief(await res.json())
    } catch (e) {
      console.error('Failed to load morning brief:', e)
    } finally {
      setMorningBriefLoading(false)
    }
  }, [])

  const loadWeather = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/weather`, { credentials: 'include' })
      if (res.ok) setWeather(await res.json())
    } catch (e) {
      console.error('Failed to load weather:', e)
    }
  }, [])

  const loadTodayCalendar = useCallback(async () => {
    try {
      const today = new Date().toISOString().split('T')[0]
      const tomorrow = new Date(Date.now() + 86400000).toISOString().split('T')[0]
      const res = await fetch(`${APP_CONFIG.apiUrl}/calendar/events?start_date=${today}&end_date=${tomorrow}`, {
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        setCalendarEvents(Array.isArray(data) ? data : data.events || [])
      }
    } catch (e) {
      console.error('Failed to load calendar:', e)
    }
  }, [])

  const loadSaraStatus = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/sara/status`, { credentials: 'include' })
      if (res.ok) setSaraStatus(await res.json())
    } catch (e) {
      console.error('Failed to load Sara status:', e)
    }
  }, [])

  const loadConnectedDevices = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/devices/connected`, { credentials: 'include' })
      if (res.ok) setConnectedDevices(await res.json())
    } catch {
      setConnectedDevices([])
    }
  }, [])

  const loadStandingOrders = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/standing-orders?status=active`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setStandingOrders(data.orders || [])
      }
    } catch {
      setStandingOrders([])
    }
  }, [])

  const loadJournalEntries = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/sara/activity?hours=24&limit=20&activity_type=journal`, {
        credentials: 'include',
      })
      if (!res.ok) return

      const data = await res.json()
      const entries = Array.isArray(data) ? data : data.activities || []
      const normalized = entries.map((entry: any) => ({
        ...entry,
        content: entry?.details?.full_content || entry?.content || entry?.summary || entry?.text || '',
        emotional_state: entry?.emotional_state || entry?.details?.emotional_state || null,
      }))
      const dedupeWindowMs = 8 * 60 * 1000
      const semanticWindowMs = 12 * 60 * 60 * 1000
      const normalize = (value: string) => (value || '')
        .toLowerCase()
        .replace(/https?:\/\/\S+/g, '')
        .replace(/[^a-z0-9\s]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
      const similarity = (a: string, b: string) => {
        const aw = new Set(normalize(a).split(' ').filter(Boolean))
        const bw = new Set(normalize(b).split(' ').filter(Boolean))
        if (aw.size === 0 || bw.size === 0) return 0
        let overlap = 0
        aw.forEach((w) => { if (bw.has(w)) overlap += 1 })
        return overlap / Math.max(aw.size, bw.size)
      }
      const deduped: any[] = []
      let lastUnifiedTimestampMs: number | null = null
      let lastSemantic: { content: string; ts: number } | null = null

      for (const entry of normalized) {
        const entryType = entry?.details?.entry_type || entry?.entry_type || ''
        const timestampRaw = entry?.timestamp || entry?.created_at
        const timestampMs = timestampRaw ? new Date(timestampRaw).getTime() : NaN

        if (entryType === 'unified' && Number.isFinite(timestampMs)) {
          if (
            lastUnifiedTimestampMs !== null &&
            (lastUnifiedTimestampMs - timestampMs) < dedupeWindowMs
          ) {
            continue
          }
          lastUnifiedTimestampMs = timestampMs
        }

        const fullContent = entry.content || ''
        if (
          lastSemantic &&
          Number.isFinite(timestampMs) &&
          Math.abs(lastSemantic.ts - timestampMs) <= semanticWindowMs &&
          similarity(fullContent, lastSemantic.content) >= 0.9
        ) {
          continue
        }

        deduped.push(entry)
        if (fullContent && Number.isFinite(timestampMs)) {
          lastSemantic = { content: fullContent, ts: timestampMs }
        }
      }

      setJournalEntries(deduped)
      setExpandedJournalEntries(new Set())
    } catch {
      setJournalEntries([])
    }
  }, [])

  const loadMissionControlData = useCallback(async () => {
    try {
      const [attentionCountRes, attentionItemsRes, missionsRes] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/autonomy/attention/count`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/autonomy/attention?limit=20`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/autonomy/missions?limit=20`, { credentials: 'include' }),
      ])

      if (attentionCountRes.ok) {
        const attentionCountData = await attentionCountRes.json()
        setAttentionCounts({
          ...(attentionCountData.counts || {}),
          unread: attentionCountData.unread || 0,
        })
      }

      if (attentionItemsRes.ok) {
        const attentionItemsData = await attentionItemsRes.json()
        setAttentionItems(attentionItemsData.items || [])
      }

      if (missionsRes.ok) {
        const missionsData = await missionsRes.json()
        setMissions(missionsData.missions || [])
      }
    } catch (e) {
      console.warn('Mission control data load failed:', e)
    }
  }, [])

  const loadDashboardData = useCallback(() => {
    Promise.allSettled([
      loadMorningBrief(),
      loadWeather(),
      loadTodayCalendar(),
      loadSaraStatus(),
      loadConnectedDevices(),
      loadStandingOrders(),
      loadJournalEntries(),
      loadTimersAndReminders(),
      loadMissionControlData(),
    ])
  }, [
    loadConnectedDevices,
    loadJournalEntries,
    loadMissionControlData,
    loadMorningBrief,
    loadSaraStatus,
    loadStandingOrders,
    loadTimersAndReminders,
    loadTodayCalendar,
    loadWeather,
  ])

  const playBriefAudio = useCallback(async () => {
    const el = briefAudioRef.current
    if (!el || !morningBrief?.brief_date) return

    if (briefAudioPlaying) {
      el.pause()
      setBriefAudioPlaying(false)
      return
    }

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/morning-brief/${morningBrief.brief_date}/audio`,
        { credentials: 'include' },
      )
      if (!response.ok) {
        throw new Error(`Audio request failed (${response.status})`)
      }

      const blob = await response.blob()

      if (briefAudioUrlRef.current) {
        URL.revokeObjectURL(briefAudioUrlRef.current)
      }
      briefAudioUrlRef.current = URL.createObjectURL(blob)

      el.src = briefAudioUrlRef.current
      await el.play()
      setBriefAudioPlaying(true)
    } catch (error) {
      console.error('Failed to play brief audio:', error)
      onShowToast('Unable to play brief audio right now.', 'error')
      setBriefAudioPlaying(false)
    }
  }, [briefAudioPlaying, morningBrief?.brief_date, onShowToast])

  const toggleJournalEntry = useCallback((entryKey: string) => {
    setExpandedJournalEntries((prev) => {
      const next = new Set(prev)
      if (next.has(entryKey)) next.delete(entryKey)
      else next.add(entryKey)
      return next
    })
  }, [])

  useEffect(() => {
    if (!isAuthenticated) return

    const interval = setInterval(() => {
      const now = new Date()

      if (
        now.getDate() !== currentTime.getDate() ||
        now.getMonth() !== currentTime.getMonth() ||
        now.getFullYear() !== currentTime.getFullYear()
      ) {
        setCurrentTime(now)
      }

      timers.forEach((timer) => {
        const endTime = new Date(timer.end_time)
        if (endTime <= now && timer.is_active && !finishedTimers.has(timer.id)) {
          setFinishedTimers((prev) => new Set([...prev, timer.id]))
          onShowToast(`🔔 Timer finished: ${timer.title}`, 'success', true, true)
          void stopTimer(timer.id)
        }
      })
    }, 5000)

    return () => clearInterval(interval)
  }, [currentTime, finishedTimers, isAuthenticated, onShowToast, stopTimer, timers])

  useEffect(() => {
    if (!isAuthenticated) return

    void loadTimersAndReminders()
    const interval = setInterval(() => {
      void loadTimersAndReminders()
    }, 60000)
    return () => clearInterval(interval)
  }, [isAuthenticated, loadTimersAndReminders])

  useEffect(() => {
    if (!isAuthenticated) return

    void loadMissionControlData()
    const interval = setInterval(() => {
      void loadMissionControlData()
    }, 60000)
    return () => clearInterval(interval)
  }, [isAuthenticated, loadMissionControlData])

  useEffect(() => {
    if (!isAuthenticated || view !== 'dashboard') return
    loadDashboardData()
  }, [isAuthenticated, loadDashboardData, view])

  useEffect(() => {
    return () => {
      if (briefAudioUrlRef.current) {
        URL.revokeObjectURL(briefAudioUrlRef.current)
        briefAudioUrlRef.current = null
      }
    }
  }, [])

  const attentionUnreadCount = Number(attentionCounts?.unread || 0)
  const awaitingDecisionCount = missions.filter((mission) => mission.state === 'awaiting_confirm').length + attentionUnreadCount
  const inboxUnreadCount = attentionUnreadCount
  const missionAwaitingCount = missions.filter((mission) => mission.state === 'awaiting_confirm').length
  const runningMissionCount = missions.filter((mission) => mission.state === 'running').length

  return {
    timers,
    reminders,
    currentTime,
    morningBrief,
    morningBriefLoading,
    weather,
    calendarEvents,
    saraStatus,
    connectedDevices,
    standingOrders,
    journalEntries,
    expandedJournalEntries,
    attentionCounts,
    attentionItems,
    missions,
    briefAudioPlaying,
    setBriefAudioPlaying,
    briefAudioRef,
    playBriefAudio,
    toggleJournalEntry,
    loadTimersAndReminders,
    attentionUnreadCount,
    awaitingDecisionCount,
    inboxUnreadCount,
    missionAwaitingCount,
    runningMissionCount,
  }
}
