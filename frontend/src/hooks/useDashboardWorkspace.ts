import { useCallback, useEffect, useRef, useState } from 'react'
import { APP_CONFIG } from '../config'
import { etDateString } from '../components/shell/shellDisplay'
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
  const [brief, setBrief] = useState<any>(null)
  const [briefLoaded, setBriefLoaded] = useState(false)
  const [recovery, setRecovery] = useState<any>(null)
  const [todayTemplate, setTodayTemplate] = useState<any>(null)
  const [activeWorkout, setActiveWorkout] = useState<any>(null)
  const [weightTrend, setWeightTrend] = useState<any[]>([])
  const [briefAudioPlaying, setBriefAudioPlaying] = useState(false)
  const briefAudioRef = useRef<HTMLAudioElement>(null)
  const briefAudioUrlRef = useRef<string | null>(null)

  // Deliberately reads Date.now() at call time rather than closing over the
  // `currentTime` state — that state now ticks every 5s (live "now" marker),
  // and depending on it here destabilized this callback's identity every
  // 5s, which cascaded into loadDashboardData (which lists this in its own
  // deps) re-running its whole 11-fetch batch every 5s instead of every 60s
  // — a request flood that starved the API for every other client,
  // including the iOS app's food-logging calls.
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
        const now = Date.now()

        remindersData.forEach((reminder: any) => {
          const reminderTime = new Date(reminder.reminder_time)
          const timeDiff = Math.abs(reminderTime.getTime() - now)

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
  }, [notifiedReminders, onShowToast])

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

  // Background refreshes (60s poll) shouldn't flash "Loading brief…" over
  // content that's already on screen — only the first load shows it.
  const morningBriefLoadedOnceRef = useRef(false)
  const loadMorningBrief = useCallback(async () => {
    if (!morningBriefLoadedOnceRef.current) setMorningBriefLoading(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/today`, { credentials: 'include' })
      if (res.ok) setMorningBrief(await res.json())
    } catch (e) {
      console.error('Failed to load morning brief:', e)
    } finally {
      setMorningBriefLoading(false)
      morningBriefLoadedOnceRef.current = true
    }
  }, [])

  // Single payload for needs_you, ongoing, journal, digest, and weather —
  // both dashboards render the same /api/sara/brief instead of each
  // assembling their own raw fetches (SARA_MIND_V2 dashboard fix Phase 1).
  const loadBrief = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/sara/brief`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setBrief(data)
        setWeather(data.weather || null)
        setJournalEntries(data.journal || [])
        // Prune (don't wipe) expanded state on each refresh — a live 60s
        // poll shouldn't silently re-collapse an entry David just opened.
        setExpandedJournalEntries((prev) => {
          const validKeys = new Set((data.journal || []).map((e: any, i: number) => String(e.id || i)))
          const next = new Set([...prev].filter((k) => validKeys.has(k)))
          return next.size === prev.size ? prev : next
        })
        setStandingOrders(
          (data.ongoing || [])
            .filter((item: any) => item.kind === 'standing_order')
            .map((item: any) => ({ id: item.id, description: item.title, fires_at: item.fires_at }))
        )
        setAttentionItems(data.needs_you?.items || [])
        setAttentionCounts((prev: any) => ({ ...prev, unread: data.needs_you?.badge || 0 }))
      }
    } catch (e) {
      console.error('Failed to load brief:', e)
    } finally {
      setBriefLoaded(true)
    }
  }, [])

  const loadTodayCalendar = useCallback(async () => {
    try {
      const today = etDateString()
      const tomorrow = etDateString(new Date(Date.now() + 86400000))
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

  // Body & training tiles (dashboard redesign §5) — each tolerates
  // 404/failure by leaving its state null/[]; cards degrade accordingly.
  const loadRecovery = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/recovery/${etDateString()}`, {
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        setRecovery(data || null)
      }
    } catch (e) {
      console.error('Failed to load recovery:', e)
    }
  }, [])

  const loadTodayTemplate = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates/today`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setTodayTemplate(data?.templates?.[0] || null)
      }
    } catch (e) {
      console.error('Failed to load today template:', e)
    }
  }, [])

  const loadActiveWorkout = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workout-session/active`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setActiveWorkout(data?.session || null)
      }
    } catch (e) {
      console.error('Failed to load active workout:', e)
    }
  }, [])

  const loadWeightTrend = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/weight/trend`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setWeightTrend(data?.weights || [])
      }
    } catch (e) {
      console.error('Failed to load weight trend:', e)
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

  const loadMissionControlData = useCallback(async () => {
    try {
      const missionsRes = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions?limit=20`, { credentials: 'include' })
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
      loadBrief(),
      loadTodayCalendar(),
      loadSaraStatus(),
      loadConnectedDevices(),
      loadTimersAndReminders(),
      loadMissionControlData(),
      loadRecovery(),
      loadTodayTemplate(),
      loadActiveWorkout(),
      loadWeightTrend(),
    ])
  }, [
    loadBrief,
    loadConnectedDevices,
    loadMissionControlData,
    loadMorningBrief,
    loadSaraStatus,
    loadTimersAndReminders,
    loadTodayCalendar,
    loadRecovery,
    loadTodayTemplate,
    loadActiveWorkout,
    loadWeightTrend,
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

  const answerVerification = useCallback(async (pkgId: string, confirmed: boolean) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/memory/verification-answer`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pkg_id: pkgId, confirmed }),
      })
    } catch (e) {
      console.error('Failed to record verification answer:', e)
      onShowToast('Unable to record that answer right now.', 'error')
    }
  }, [onShowToast])

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
      // Ticks every 5s so the timeline's "now" marker, isNow highlighting,
      // and relative-time labels actually advance during a session instead
      // of freezing at whatever moment the tab was opened.
      setCurrentTime(now)

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
    // currentTime is intentionally NOT a dependency — the interval reads a
    // fresh `new Date()` itself each tick and only ever writes currentTime,
    // never reads it; depending on it would tear down and recreate this
    // interval every 5s for no reason.
  }, [finishedTimers, isAuthenticated, onShowToast, stopTimer, timers])

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

  // The brief also drives the nav rail's badges (needs-you/inbox counts),
  // which are visible chrome on every view — not just the dashboard — so it
  // polls independently of `view` (same pattern as timers/missions above).
  // The heavier dashboard-only batch below still re-fetches it too while
  // you're actually on the dashboard; the redundancy is cheap and keeps
  // each concern isolated.
  useEffect(() => {
    if (!isAuthenticated) return

    void loadBrief()
    const interval = setInterval(() => {
      void loadBrief()
    }, 60000)
    return () => clearInterval(interval)
  }, [isAuthenticated, loadBrief])

  useEffect(() => {
    if (!isAuthenticated || view !== 'dashboard') return
    loadDashboardData()
    // Everything on the dashboard should refresh live, not just on mount —
    // otherwise badges/cards go stale mid-session (e.g. a notification read
    // elsewhere doesn't clear here until a hard refresh). Timers/reminders
    // and missions already poll on their own 60s intervals above; this
    // covers the rest of the batch (brief, morning brief, calendar, Sara
    // status, connected devices, recovery, template, active workout, weight).
    const interval = setInterval(() => {
      loadDashboardData()
    }, 60000)
    return () => clearInterval(interval)
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
  const inboxUnreadCount = attentionUnreadCount
  const missionAwaitingCount = missions.filter((mission) => mission.state === 'awaiting_confirm').length
  const runningMissionCount = missions.filter((mission) => mission.state === 'running').length
  // needs_you.total (pre-slice count of actionable items) — NOT the same as
  // attentionUnreadCount/badge, which also counts FYI-tier things like
  // unread notifications that never appear in needs_you.items. Both the
  // dashboard's "Need you" tile and the nav's "awaiting decision" badge must
  // agree with what NeedsYouCard actually renders, or "nothing needs you"
  // reads as a lie next to a nonzero badge.
  const needsYouTotal = Number(brief?.needs_you?.total || 0)
  const awaitingDecisionCount = missionAwaitingCount + needsYouTotal

  // Reminders due today, not yet completed — already fetched for the toast
  // notifier but never rendered; the timeline (Card B) is the first consumer.
  const todayReminders = reminders.filter((r: any) => {
    if (r.completed || r.is_completed) return false
    if (!r.reminder_time) return false
    return etDateString(new Date(r.reminder_time)) === etDateString(currentTime)
  })

  return {
    timers,
    reminders,
    todayReminders,
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
    brief,
    briefLoaded,
    briefSections: brief?.brief_sections || [],
    saraStatusLine: brief?.sara_status || null,
    activityState: brief?.activity_state || null,
    interruptibility: brief?.interruptibility ?? null,
    suggestedActions: brief?.suggested_actions || [],
    selfStatus: brief?.self_status || null,
    timePeriod: brief?.time_period || null,
    digest: brief?.digest || null,
    quietLine: brief?.quiet_line || null,
    recovery,
    todayTemplate,
    activeWorkout,
    weightTrend,
    briefAudioPlaying,
    setBriefAudioPlaying,
    briefAudioRef,
    playBriefAudio,
    toggleJournalEntry,
    answerVerification,
    loadTimersAndReminders,
    attentionUnreadCount,
    awaitingDecisionCount,
    inboxUnreadCount,
    needsYouTotal,
    missionAwaitingCount,
    runningMissionCount,
  }
}
