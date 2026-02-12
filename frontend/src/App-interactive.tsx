import React, { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { APP_CONFIG } from './config'
import Notes from './components/Notes'
import CalendarView from './components/CalendarView'
import Settings from './pages/Settings'
import HabitToday from './components/HabitToday'
import HabitCreate from './components/HabitCreate'
import HabitInsights from './components/HabitInsights'
import ChatInterface from './components/ChatInterface'
import FitnessSection from './components/fitness/FitnessSection'
import RecipesSection from './components/fitness/RecipesSection'
import LearningSection from './components/learning/LearningSection'
import ProjectSection from './components/projects/ProjectSection'
// Moved GTKY into Settings; reflection features removed from UI
import { PrivacyDashboard } from './components/privacy/PrivacyDashboard'
import { useActivityMonitor } from './hooks/useActivityMonitor'
import { getCalmMode } from './utils/prefs'
import { CommandPalette } from './components/CommandPalette'
import MorningBrief from './components/MorningBrief'
import OrchestratorLab from './components/OrchestratorLab'
import NotificationBanner from './components/NotificationBanner'
import BackgroundTasksIndicator from './components/BackgroundTasksIndicator'
import AutomationTasksIndicator from './components/AutomationTasksIndicator'
import MiniChatOverlay from './components/MiniChatOverlay'
import HealthAlertChat from './components/HealthAlertChat'
import SensoryMonitor from './components/SensoryMonitor'
import EmailPage from './components/EmailPage'
import ContentInbox from './components/ContentInbox'

// LiveTimer component that updates every second without causing parent re-renders
function LiveTimer({ endTime, className = "" }) {
  const [timeLeft, setTimeLeft] = useState("")
  
  useEffect(() => {
    const updateTimer = () => {
      const now = new Date()
      const end = new Date(endTime)
      const diff = end - now
      
      if (diff <= 0) {
        setTimeLeft('FINISHED')
        return
      }
      
      const hours = Math.floor(diff / (1000 * 60 * 60))
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
      const seconds = Math.floor((diff % (1000 * 60)) / 1000)
      
      if (hours > 0) {
        setTimeLeft(`${hours}h ${minutes}m ${seconds}s`)
      } else if (minutes > 0) {
        setTimeLeft(`${minutes}m ${seconds}s`)
      } else {
        setTimeLeft(`${seconds}s`)
      }
    }
    
    // Update immediately
    updateTimer()
    
    // Then update every second
    const interval = setInterval(updateTimer, 1000)
    
    return () => clearInterval(interval)
  }, [endTime])
  
  return <span className={className}>{timeLeft}</span>
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [user, setUser] = useState(null)
  const [view, setView] = useState('login') // login, dashboard, chat, notes, habits, documents, calendar, fitness, recipes, settings, briefings, context-mode, smart-insights, orchestrator-lab
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLogin, setIsLogin] = useState(true)
  const [message, setMessage] = useState('')
  const [chatMessages, setChatMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [notes, setNotes] = useState([])
  const [newNote, setNewNote] = useState('')
  const [editingNote, setEditingNote] = useState(null)
  const [editNoteContent, setEditNoteContent] = useState('')
  const [editNoteTitle, setEditNoteTitle] = useState('')
  const [timers, setTimers] = useState([])
  const [reminders, setReminders] = useState([])
  const [currentTime, setCurrentTime] = useState(new Date())
  const [quickChatResponse, setQuickChatResponse] = useState('')
  const [showQuickResponse, setShowQuickResponse] = useState(false)
  const [toasts, setToasts] = useState([])
  const [finishedTimers, setFinishedTimers] = useState(new Set())
  const [notifiedReminders, setNotifiedReminders] = useState(new Set())
  const [timerTick, setTimerTick] = useState(0) // Force re-render for timer displays
  const [documents, setDocuments] = useState([])
  
  // Habit-related state
  const [habitView, setHabitView] = useState('today') // today, insights, create
  const [showHabitCreate, setShowHabitCreate] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [analytics, setAnalytics] = useState(null)
  const [editingDocumentId, setEditingDocumentId] = useState(null)
  const [editingDocumentTitle, setEditingDocumentTitle] = useState('')

  // Dashboard state
  const [morningBrief, setMorningBrief] = useState<any>(null)
  const [morningBriefLoading, setMorningBriefLoading] = useState(false)
  const [weather, setWeather] = useState<any>(null)
  const [calendarEvents, setCalendarEvents] = useState<any[]>([])
  const [saraStatus, setSaraStatus] = useState<any>(null)
  const [connectedDevices, setConnectedDevices] = useState<any[]>([])
  const [standingOrders, setStandingOrders] = useState<any[]>([])
  const [journalEntries, setJournalEntries] = useState<any[]>([])
  const [briefAudioPlaying, setBriefAudioPlaying] = useState(false)
  const briefAudioRef = useRef<HTMLAudioElement>(null)

  // Health alert chat state
  const [activeHealthAlert, setActiveHealthAlert] = useState<{
    severity: string
    title: string
    body: string
    insightId?: string
  } | null>(null)
  const [dismissedHealthAlertIds, setDismissedHealthAlertIds] = useState<Set<string>>(() => {
    // Load dismissed IDs from localStorage on mount
    try {
      const stored = localStorage.getItem('dismissedHealthAlertIds')
      if (stored) {
        const parsed = JSON.parse(stored)
        // Only keep IDs from last 24 hours (they're timestamped as id:timestamp)
        const now = Date.now()
        const valid = parsed.filter((entry: string) => {
          const [, timestamp] = entry.split(':')
          return timestamp && (now - parseInt(timestamp)) < 24 * 60 * 60 * 1000
        })
        return new Set(valid.map((entry: string) => entry.split(':')[0]))
      }
    } catch {}
    return new Set()
  })

  // Ref for scrolling main content to top on view change
  const mainContentRef = useRef<HTMLDivElement>(null)

  // Ref for auto-scrolling chat messages
  const chatMessagesEndRef = useRef(null)

  // Ref to track and cancel ongoing chat requests
  const abortControllerRef = useRef(null)

  // Scroll main content to top on view change
  useEffect(() => {
    const scrollable = mainContentRef.current?.querySelector('.overflow-y-auto')
    scrollable?.scrollTo(0, 0)
  }, [view])

  // Activity monitoring for autonomous behaviors
  const { activityState, getIdleMinutes } = useActivityMonitor({
    thresholds: {
      quickSweep: 25 * 60 * 1000,      // 25 minutes - short idle
      standardSweep: 2.5 * 60 * 60 * 1000, // 2.5 hours - medium idle
      digestSweep: 24 * 60 * 60 * 1000     // 24 hours - long idle
    },
    onThresholdReached: async (threshold, duration) => {
      console.log(`🤖 Sara: ${threshold} triggered after ${Math.round(duration / 60000)} minutes idle`)
      
      try {
        // Call backend autonomous sweep
        const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/sweep/${threshold}`, {
          method: 'POST',
          credentials: 'include'
        })

        if (response.ok) {
          const result = await response.json()
          console.log(`🤖 Autonomous sweep result:`, result)

          // Only notify if meaningful insights were generated
          if (result.insights_stored > 0 && result.new_insights > 0) {
            await fetchAndDisplayLatestInsight(threshold, 'companion')
          } else {
            console.log(`🤖 Sara: No new insights to share (${result.insights_stored} stored, ${result.new_insights || 0} new)`)
            // Don't show notifications or fallback behaviors when there's nothing new
          }
        } else {
          console.log(`🤖 Sara: Sweep completed but no actionable insights found`)
          // Don't notify on failed sweeps - just log quietly
        }
      } catch (error) {
        console.log(`🤖 Sara: Unable to generate insights at this time`)
        // Don't notify on errors - just log quietly
      }
    },
    onActivityResume: () => {
      console.log('🤖 Sara: Activity resumed, returning to idle')
    },
    enableLogging: true
  })


  // Check authentication on load
  useEffect(() => {
    checkAuth()
  }, [])

  // Update current time only when day changes, but check timers every second
  useEffect(() => {
    const interval = setInterval(() => {
      const now = new Date()
      
      // Only update currentTime state if the day changed (to prevent constant re-renders)
      if (now.getDate() !== currentTime.getDate() || 
          now.getMonth() !== currentTime.getMonth() || 
          now.getFullYear() !== currentTime.getFullYear()) {
        setCurrentTime(now)
      }
      
      // Increment timer tick to force re-render of timer displays (disabled to prevent constant re-renders)
      // setTimerTick(prev => prev + 1)
      
      // Check for timer completions globally (to avoid duplicates)
      timers.forEach(timer => {
        const endTime = new Date(timer.end_time)
        if (endTime <= now && timer.is_active && !finishedTimers.has(timer.id)) {
          setFinishedTimers(prev => new Set([...prev, timer.id]))
          showToast(`🔔 Timer finished: ${timer.title}`, 'success', true, true)
          // Automatically stop the timer on the backend
          stopTimer(timer.id)
        }
      })
    }, 5000) // Reduced from 1s to 5s to prevent constant re-renders
    return () => clearInterval(interval)
  }, [timers, finishedTimers, currentTime])

  // Load timers and reminders periodically when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      loadTimersAndReminders()
      const interval = setInterval(loadTimersAndReminders, 60000) // Reduced from 30s to 60s
      return () => clearInterval(interval)
    }
  }, [isAuthenticated])

  // Poll for health alerts that need attention
  useEffect(() => {
    if (!isAuthenticated) return

    const checkHealthAlerts = async () => {
      try {
        const res = await fetch(`${APP_CONFIG.apiUrl}/api/health/insights?limit=1&severity=warning`, {
          credentials: 'include'
        })
        if (!res.ok) return

        const data = await res.json()
        if (data.insights && data.insights.length > 0) {
          const insight = data.insights[0]
          // Only show if not dismissed and not already showing
          if (!dismissedHealthAlertIds.has(insight.id) && !activeHealthAlert) {
            setActiveHealthAlert({
              severity: insight.severity,
              title: insight.title,
              body: insight.content,
              insightId: insight.id
            })
          }
        }
      } catch (error) {
        // Log error but don't block - health alerts are optional
        console.warn('Health alerts check failed:', error instanceof Error ? error.message : error)
      }
    }

    checkHealthAlerts()
    const interval = setInterval(checkHealthAlerts, 60000) // Check every minute
    return () => clearInterval(interval)
  }, [isAuthenticated, dismissedHealthAlertIds, activeHealthAlert])

  // Load dashboard data when view changes to dashboard
  useEffect(() => {
    if (isAuthenticated && view === 'dashboard') {
      loadDashboardData()
    }
  }, [isAuthenticated, view])

  // Auto-scroll chat to bottom when messages change
  useEffect(() => {
    if (view === 'chat' && chatMessagesEndRef.current) {
      setTimeout(() => {
        chatMessagesEndRef.current?.scrollIntoView({ 
          behavior: 'smooth',
          block: 'end',
          inline: 'nearest'
        })
      }, 100)
    }
  }, [chatMessages, view, loading])

  // Cleanup: cancel any ongoing chat requests when component unmounts
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [])

  // Command Palette keyboard shortcut (Cmd+K / Ctrl+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        e.stopPropagation()
        setCommandPaletteOpen(prev => !prev)
      }
    }

    // Use capture phase to intercept before browser handles it
    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [])

  // Custom navigation event listener (used by Settings page for Orchestrator Lab)
  useEffect(() => {
    const handleNavigate = (e: CustomEvent<{ view: string }>) => {
      if (e.detail?.view) {
        setView(e.detail.view)
      }
    }

    window.addEventListener('navigate', handleNavigate as EventListener)
    return () => window.removeEventListener('navigate', handleNavigate as EventListener)
  }, [])

  const loadTimersAndReminders = async () => {
    try {
      // Load timers
      const timersResponse = await fetch(`${APP_CONFIG.apiUrl}/timers`, {
        credentials: 'include'
      })
      if (timersResponse.ok) {
        const timersData = await timersResponse.json()
        setTimers(timersData)
      }

      // Load reminders
      const remindersResponse = await fetch(`${APP_CONFIG.apiUrl}/reminders`, {
        credentials: 'include'
      })
      if (remindersResponse.ok) {
        const remindersData = await remindersResponse.json()
        
        // Check for due reminders
        remindersData.forEach(reminder => {
          const reminderTime = new Date(reminder.reminder_time)
          const now = currentTime
          const timeDiff = Math.abs(reminderTime - now)
          
          // If reminder is due (within 30 seconds) and we haven't notified yet
          if (timeDiff < 30000 && !notifiedReminders.has(reminder.id)) {
            setNotifiedReminders(prev => new Set([...prev, reminder.id]))
            showToast(`🔔 Reminder: ${reminder.title}`, 'info', true, true)
          }
        })
        
        setReminders(remindersData)
      }
    } catch (error) {
      console.error('Failed to load timers/reminders:', error)
    }
  }

  const formatTimeLeft = (endTime) => {
    const now = new Date() // Use current time instead of state
    const end = new Date(endTime)
    const diff = end - now
    
    if (diff <= 0) {
      return 'FINISHED'
    }
    
    const hours = Math.floor(diff / (1000 * 60 * 60))
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
    const seconds = Math.floor((diff % (1000 * 60)) / 1000)
    
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
  }

  const stopTimer = async (timerId) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/timers/${timerId}/stop`, {
        method: 'PATCH',
        credentials: 'include'
      })
      if (response.ok) {
        await loadTimersAndReminders()
      }
    } catch (error) {
      console.error('Failed to stop timer:', error)
    }
  }

  const completeReminder = async (reminderId) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/reminders/${reminderId}/complete`, {
        method: 'PATCH',
        credentials: 'include'
      })
      if (response.ok) {
        await loadTimersAndReminders()
      }
    } catch (error) {
      console.error('Failed to complete reminder:', error)
    }
  }

  const createQuickTimer = async (minutes, title) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/timers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: title,
          duration_minutes: minutes
        })
      })
      if (response.ok) {
        await loadTimersAndReminders()
      }
    } catch (error) {
      console.error('Failed to create timer:', error)
    }
  }

  const checkAuth = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/auth/me`, {
        credentials: 'include'
      })
      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
        setIsAuthenticated(true)
        setView('dashboard')
      }
    } catch (error) {
      console.log('Not authenticated')
    }
  }

  const handleAuth = async (e) => {
    e.preventDefault()
    setLoading(true)
    
    try {
      const endpoint = isLogin ? '/auth/login' : '/auth/signup'
      const response = await fetch(`${APP_CONFIG.apiUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password })
      })

      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
        setIsAuthenticated(true)
        setView('dashboard')
        setChatMessages([{
          role: 'assistant',
          content: `Hello! I'm ${APP_CONFIG.assistantName}, your personal AI assistant. How can I help you today?`,
          timestamp: new Date()
        }])
      } else {
        const error = await response.json()
        setMessage(error.detail || 'Authentication failed')
      }
    } catch (error) {
      setMessage('Connection error. Please try again.')
    }
    setLoading(false)
  }

  const sendMessage = async (e, isQuickChat = false) => {
    e.preventDefault()
    if (!message.trim() || loading) return // Prevent multiple concurrent requests

    // Cancel any existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    
    // Create new abort controller for this request
    abortControllerRef.current = new AbortController()

    const userMessage = { role: 'user', content: message, timestamp: new Date() }
    if (!isQuickChat) {
      setChatMessages(prev => [...prev, userMessage])
    }
    setMessage('')
    setLoading(true)
    
    if (isQuickChat) {
      setShowQuickResponse(true)
      setQuickChatResponse('Sara is typing...')
    }

    // State for streaming
    let streamingContent = ''
    let isFirstStreamChunk = true
    let isUsingTools = false
    let toolActivity = ''

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          messages: [...chatMessages, userMessage].map(m => ({ role: m.role, content: m.content }))
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body reader available')
      }

      const decoder = new TextDecoder()
      
      try {
        while (true) {
          const { done, value } = await reader.read()
          
          if (done) break
          
          const chunk = decoder.decode(value)
          const lines = chunk.split('\n')
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const eventData = JSON.parse(line.slice(6))
                console.log('Received SSE event:', eventData)
                
                // Debug tool events specifically
                if (eventData.type?.includes('tool')) {
                  console.log('🔧 TOOL EVENT RECEIVED:', eventData)
                }
                
                switch (eventData.type) {
                  case 'tool_calls_start':
                    isUsingTools = true
                    toolActivity = `🔧 Using Tools (Round ${eventData.data.round})`
                    if (isQuickChat) {
                      setQuickChatResponse(toolActivity)
                    }
                    break
                    
                  case 'tool_executing':
                    toolActivity = `🔧 Using ${eventData.data.tool}...`
                    if (isQuickChat) {
                      setQuickChatResponse(toolActivity)
                    }
                    break
                    
                  case 'thinking':
                    toolActivity = '💭 Processing results...'
                    if (isQuickChat) {
                      setQuickChatResponse(toolActivity)
                    }
                    break
                    
                  case 'text_chunk':
                    streamingContent = eventData.data.full_content
                    if (isFirstStreamChunk) {
                      // Brief "breath to talk" surge on first streamed token
                      isFirstStreamChunk = false
                    }
                    if (isQuickChat) {
                      setQuickChatResponse(streamingContent)
                    } else {
                      // Update the last message with streaming content
                      setChatMessages(prev => {
                        const newMessages = [...prev]
                        if (newMessages[newMessages.length - 1]?.role === 'assistant') {
                          newMessages[newMessages.length - 1].content = streamingContent
                        } else {
                          newMessages.push({
                            role: 'assistant',
                            content: streamingContent,
                            timestamp: new Date()
                          })
                        }
                        return newMessages
                      })
                    }
                    break
                    
                  case 'final_response':
                    const finalContent = eventData.data.content
                    const finalCitations = eventData.data.citations || []
                    if (isQuickChat) {
                      setQuickChatResponse(finalContent)
                    } else {
                      setChatMessages(prev => {
                        const newMessages = [...prev]
                        if (newMessages[newMessages.length - 1]?.role === 'assistant') {
                          newMessages[newMessages.length - 1].content = finalContent
                          newMessages[newMessages.length - 1].citations = finalCitations
                        } else {
                          newMessages.push({
                            role: 'assistant',
                            content: finalContent,
                            citations: finalCitations,
                            timestamp: new Date()
                          })
                        }
                        return newMessages
                      })
                    }
                    break
                    
                  case 'response_ready':
                    setLoading(false)
                    isUsingTools = false
                    break
                    
                  case 'error':
                    console.error('Streaming error:', eventData.message)
                    setLoading(false)
                    break
                }
              } catch (e) {
                console.warn('Failed to parse SSE data:', line)
              }
            }
          }
        }
      } finally {
        reader.releaseLock()
      }
      
      // Refresh timers/reminders after chat in case something was created
      await loadTimersAndReminders()
    } catch (error) {
      // Don't show error if request was aborted (user sent another message)
      if (error.name === 'AbortError') {
        console.log('Chat request was cancelled')
        return
      }
      
      const errorMsg = 'Connection error. Please check your network and try again.'
      if (isQuickChat) {
        setQuickChatResponse(errorMsg)
      } else {
        setChatMessages(prev => [...prev, {
          role: 'assistant',
          content: errorMsg,
          timestamp: new Date()
        }])
      }
    } finally {
      setLoading(false)
      // Clear the abort controller when done
      if (abortControllerRef.current) {
        abortControllerRef.current = null
      }
    }
  }

  const createNote = async (e) => {
    e.preventDefault()
    if (!newNote.trim()) return

    setLoading(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ content: newNote })
      })

      if (response.ok) {
        const note = await response.json()
        setNotes(prev => [note, ...prev])
        setNewNote('')
      }
    } catch (error) {
      console.error('Failed to create note:', error)
    }
    setLoading(false)
  }

  const updateNote = async (noteId) => {
    if (!editNoteContent.trim()) return

    setLoading(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ 
          title: editNoteTitle, 
          content: editNoteContent 
        })
      })

      if (response.ok) {
        const updatedNote = await response.json()
        setNotes(prev => prev.map(note => 
          note.id === noteId ? updatedNote : note
        ))
        setEditingNote(null)
        setEditNoteContent('')
        setEditNoteTitle('')
      }
    } catch (error) {
      console.error('Failed to update note:', error)
    }
    setLoading(false)
  }

  const deleteNote = async (noteId) => {
    if (!confirm('Are you sure you want to delete this note?')) return

    setLoading(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        setNotes(prev => prev.filter(note => note.id !== noteId))
      }
    } catch (error) {
      console.error('Failed to delete note:', error)
    }
    setLoading(false)
  }

  const startEditNote = (note) => {
    setEditingNote(note.id)
    setEditNoteTitle(note.title || '')
    setEditNoteContent(note.content)
  }

  const cancelEditNote = () => {
    setEditingNote(null)
    setEditNoteContent('')
    setEditNoteTitle('')
  }

  const loadNotes = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
        credentials: 'include'
      })
      if (response.ok) {
        const notesData = await response.json()
        setNotes(notesData)
      }
    } catch (error) {
      console.error('Failed to load notes:', error)
    }
  }

  const loadDocuments = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents`, {
        credentials: 'include'
      })
      if (response.ok) {
        const documentsData = await response.json()
        setDocuments(documentsData)
      }
    } catch (error) {
      console.error('Failed to load documents:', error)
    }
  }

  const loadAnalytics = async () => {
    try {
      console.log('Loading analytics...')
      const response = await fetch(`${APP_CONFIG.apiUrl}/analytics/dashboard`, {
        credentials: 'include'
      })
      console.log('Analytics response status:', response.status)
      if (response.ok) {
        const analyticsData = await response.json()
        console.log('Analytics data loaded:', analyticsData)
        setAnalytics(analyticsData)
      } else {
        console.error('Analytics response error:', response.status, response.statusText)
        const errorText = await response.text()
        console.error('Error details:', errorText)
      }
    } catch (error) {
      console.error('Failed to load analytics:', error)
    }
  }

  // Dashboard data loading
  const getGreeting = () => {
    const h = new Date().getHours()
    if (h < 12) return 'Good morning'
    if (h < 17) return 'Good afternoon'
    return 'Good evening'
  }

  const formatRelativeTime = (ts: string) => {
    const diff = Date.now() - new Date(ts).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  }

  const WEATHER_EMOJI: Record<string, string> = {
    'clear-day': '\u2600\ufe0f', 'clear-night': '\ud83c\udf19', 'cloudy': '\u2601\ufe0f',
    'partly-cloudy-day': '\u26c5', 'partly-cloudy-night': '\ud83c\udf24\ufe0f',
    'rain': '\ud83c\udf27\ufe0f', 'snow': '\u2744\ufe0f', 'wind': '\ud83c\udf2c\ufe0f',
    'fog': '\ud83c\udf2b\ufe0f', 'thunderstorm': '\u26c8\ufe0f',
  }

  const EMOTION_EMOJI: Record<string, string> = {
    'neutral': '\ud83d\ude10', 'curious': '\ud83e\uddd0', 'concerned': '\ud83d\ude1f',
    'pleased': '\ud83d\ude0a', 'alert': '\u26a0\ufe0f', 'reflective': '\ud83d\udcad',
    'focused': '\ud83c\udfaf', 'calm': '\ud83e\uddd8', 'energetic': '\u26a1',
  }

  const loadMorningBrief = async () => {
    setMorningBriefLoading(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/today`, { credentials: 'include' })
      if (res.ok) setMorningBrief(await res.json())
    } catch (e) { console.error('Failed to load morning brief:', e) }
    finally { setMorningBriefLoading(false) }
  }

  const loadWeather = async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/weather`, { credentials: 'include' })
      if (res.ok) setWeather(await res.json())
    } catch (e) { console.error('Failed to load weather:', e) }
  }

  const loadTodayCalendar = async () => {
    try {
      const today = new Date().toISOString().split('T')[0]
      const tomorrow = new Date(Date.now() + 86400000).toISOString().split('T')[0]
      const res = await fetch(`${APP_CONFIG.apiUrl}/calendar/events?start_date=${today}&end_date=${tomorrow}`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setCalendarEvents(Array.isArray(data) ? data : data.events || [])
      }
    } catch (e) { console.error('Failed to load calendar:', e) }
  }

  const loadSaraStatus = async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/sara/status`, { credentials: 'include' })
      if (res.ok) setSaraStatus(await res.json())
    } catch (e) { console.error('Failed to load Sara status:', e) }
  }

  const loadConnectedDevices = async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/devices/connected`, { credentials: 'include' })
      if (res.ok) setConnectedDevices(await res.json())
    } catch (e) { setConnectedDevices([]) }
  }

  const loadStandingOrders = async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/standing-orders?status=active`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setStandingOrders(data.orders || [])
      }
    } catch (e) { setStandingOrders([]) }
  }

  const loadJournalEntries = async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/sara/activity?hours=24&limit=20&activity_type=journal`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setJournalEntries(Array.isArray(data) ? data : data.activities || [])
      }
    } catch (e) { setJournalEntries([]) }
  }

  const loadDashboardData = () => {
    Promise.allSettled([
      loadMorningBrief(),
      loadWeather(),
      loadTodayCalendar(),
      loadSaraStatus(),
      loadConnectedDevices(),
      loadStandingOrders(),
      loadJournalEntries(),
      loadTimersAndReminders(),
    ])
  }

  const playBriefAudio = () => {
    const el = briefAudioRef.current
    if (!el) return
    if (briefAudioPlaying) { el.pause(); setBriefAudioPlaying(false) }
    else { el.play(); setBriefAudioPlaying(true) }
  }

  const uploadDocument = async (file) => {
    if (!file) return
    
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents`, {
        method: 'POST',
        body: formData,
        credentials: 'include'
      })
      
      if (response.ok) {
        const newDocument = await response.json()
        setDocuments(prev => [newDocument, ...prev])
        setSelectedFile(null)
        showToast('Document uploaded successfully!', 'success')
      } else {
        const error = await response.json()
        showToast(error.detail || 'Failed to upload document', 'error')
      }
    } catch (error) {
      console.error('Upload error:', error)
      showToast('Failed to upload document', 'error')
    } finally {
      setUploading(false)
    }
  }

  const downloadDocument = async (documentId, filename) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents/${documentId}/file`, {
        credentials: 'include'
      })
      
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.style.display = 'none'
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      } else {
        showToast('Failed to download document', 'error')
      }
    } catch (error) {
      console.error('Download error:', error)
      showToast('Failed to download document', 'error')
    }
  }

  const deleteDocument = async (documentId) => {
    if (!confirm('Are you sure you want to delete this document?')) return
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents/${documentId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      
      if (response.ok) {
        setDocuments(prev => prev.filter(doc => doc.id !== documentId))
        showToast('Document deleted successfully', 'success')
      } else {
        showToast('Failed to delete document', 'error')
      }
    } catch (error) {
      console.error('Delete error:', error)
      showToast('Failed to delete document', 'error')
    }
  }

  const updateDocumentTitle = async (documentId, newTitle) => {
    if (!newTitle.trim()) return
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents/${documentId}?title=${encodeURIComponent(newTitle)}`, {
        method: 'PUT',
        credentials: 'include'
      })
      
      if (response.ok) {
        const updatedDocument = await response.json()
        setDocuments(prev => prev.map(doc => 
          doc.id === documentId ? updatedDocument : doc
        ))
        setEditingDocumentId(null)
        setEditingDocumentTitle('')
        showToast('Document title updated successfully', 'success')
      } else {
        showToast('Failed to update document title', 'error')
      }
    } catch (error) {
      console.error('Update error:', error)
      showToast('Failed to update document title', 'error')
    }
  }

  const startEditDocumentTitle = (doc) => {
    setEditingDocumentId(doc.id)
    setEditingDocumentTitle(doc.title || doc.original_filename)
  }

  const cancelEditDocumentTitle = () => {
    setEditingDocumentId(null)
    setEditingDocumentTitle('')
  }

  // Memoize the onNodeClick function to prevent unnecessary re-renders of the knowledge graph
  const handleGraphNodeClick = useCallback((nodeId, nodeType) => {
    if (nodeType === 'note') {
      const noteIdString = nodeId.replace('note-', '')
      const noteId = parseInt(noteIdString)
      const note = notes.find(n => n.id === noteId)
      if (note) {
        setEditingNote(noteId)
        setEditNoteTitle(note.title || '')
        setEditNoteContent(note.content || '')
        setView('notes') // Switch to notes view when clicking a note node
      }
    } else if (nodeType === 'episode') {
      console.log('Episode clicked:', nodeId)
      // Could implement episode details view
    } else if (nodeType === 'document') {
      console.log('Document clicked:', nodeId)
      // Could navigate to document view
      setView('documents')
    }
  }, [notes, setEditingNote, setEditNoteTitle, setEditNoteContent, setView])

  const clearChat = () => {
    setChatMessages([{
      role: 'assistant',
      content: `Hello! I'm ${APP_CONFIG.assistantName}, your personal AI assistant. How can I help you today?`,
      timestamp: new Date()
    }])
  }

  const showToast = (message, type = 'info', persistent = false) => {
    const id = Date.now()
    const toast = { id, message, type, persistent }
    setToasts(prev => [...prev, toast])

    // Auto-remove toast after 5 seconds (unless persistent)
    if (!persistent) {
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id))
      }, 5000)
    }
  }
  
  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  const logout = async () => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/auth/logout`, {
        method: 'POST',
        credentials: 'include'
      })
    } catch (error) {
      console.error('Logout error:', error)
    }
    setIsAuthenticated(false)
    setUser(null)
    setView('login')
    setChatMessages([])
    setNotes([])
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8" style={{backgroundColor: '#0d1117', color: '#c9d1d9'}}>
        <div className="max-w-md w-full bg-card border border-card rounded-xl p-8">
          <div className="text-center mb-8">
            <div className="w-16 h-16 bg-white text-black rounded-lg mx-auto mb-4 flex items-center justify-center text-2xl font-bold">
              S
            </div>
            <h1 className="text-2xl font-bold text-white">Welcome to {APP_CONFIG.assistantName}</h1>
            <p className="text-gray-400 mt-2">{APP_CONFIG.ui.subtitle}</p>
          </div>

          <form onSubmit={handleAuth}>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500 text-white"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500 text-white"
                  required
                />
              </div>
            </div>

            {message && (
              <div className="mt-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
                {message}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-teal-600 hover:bg-teal-700 text-white font-medium py-2 px-4 rounded-lg transition-colors mt-6"
            >
              {loading ? 'Please wait...' : (isLogin ? 'Sign In' : 'Sign Up')}
            </button>

            <div className="mt-4 text-center">
              <button
                type="button"
                onClick={() => setIsLogin(!isLogin)}
                className="text-teal-400 hover:text-teal-300 text-sm"
              >
                {isLogin ? "Don't have an account? Sign up" : "Already have an account? Sign in"}
              </button>
            </div>
          </form>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 pb-20 md:pb-4 h-screen overflow-hidden flex flex-col" style={{backgroundColor: '#0d1117', color: '#c9d1d9'}}>
      {/* Command Palette */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={(v) => { setView(v); if (v === 'notes') loadNotes(); }}
        currentView={view}
      />

      <div className="flex flex-col md:flex-row md:space-x-6 flex-1 min-h-0">
        
        {/* Mobile Header */}
        <div className="md:hidden flex justify-between items-center mb-4">
          <h1 className="text-2xl font-bold">{APP_CONFIG.assistantName}</h1>
          <button 
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            className="p-2 text-gray-400 hover:text-white"
          >
            <span className="text-2xl">{isMobileMenuOpen ? '✕' : '☰'}</span>
          </button>
        </div>

        {/* Mobile Navigation Overlay */}
        {isMobileMenuOpen && (
          <div className="md:hidden fixed inset-0 bg-black bg-opacity-50 z-50" onClick={() => setIsMobileMenuOpen(false)}>
            <div className="bg-gray-900 w-full max-w-sm h-full flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
              <div className="flex justify-between items-center p-4 border-b border-gray-700 flex-shrink-0">
                <div className="p-3 bg-white text-black rounded-lg font-bold text-xl">S</div>
                <button onClick={() => setIsMobileMenuOpen(false)} className="text-gray-400 text-2xl tap-target">✕</button>
              </div>
              <nav className="flex-1 overflow-y-auto p-4 space-y-2">
                <button
                  onClick={() => { setView('dashboard'); loadDashboardData(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'dashboard' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">home</span>
                  <span>Home</span>
                </button>
                <button
                  onClick={() => { setView('chat'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'chat' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">chat</span>
                  <span>Chat</span>
                </button>
                <button
                  onClick={() => { setView('notes'); loadNotes(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'notes' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">notes</span>
                  <span>Notes</span>
                </button>
                <button
                  onClick={() => { setView('habits'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'habits' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">track_changes</span>
                  <span>Habits</span>
                </button>
                <button
                  onClick={() => { setView('documents'); loadDocuments(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'documents' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">description</span>
                  <span>Documents</span>
                </button>
                <button
                  onClick={() => { setView('calendar'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'calendar' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">calendar_today</span>
                  <span>Calendar</span>
                </button>
                <button
                  onClick={() => { setView('email'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'email' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">email</span>
                  <span>Email</span>
                </button>
                <button
                  onClick={() => { setView('fitness'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'fitness' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">💪</span>
                  <span>Fitness</span>
                </button>
                <button
                  onClick={() => { setView('learn'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'learn' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">school</span>
                  <span>Learn</span>
                </button>
                <button
                  onClick={() => { setView('projects'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'projects' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">work</span>
                  <span>Projects</span>
                </button>
                <button
                  onClick={() => { setView('recipes'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'recipes' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">👨‍🍳</span>
                  <span>Recipes</span>
                </button>
                <button
                  onClick={() => { setView('briefings'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'briefings' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">wb_sunny</span>
                  <span>Morning Brief</span>
                </button>
                <button
                  onClick={() => { setView('sensory-monitor'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'sensory-monitor' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">sensors</span>
                  <span>Sensory</span>
                </button>
                <button
                  onClick={() => { setView('inbox'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'inbox' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">inbox</span>
                  <span>Inbox</span>
                </button>
                <button
                  onClick={() => { setView('settings'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded w-full tap-target ${view === 'settings' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="material-icons">settings</span>
                  <span>Settings</span>
                </button>
                <button
                  onClick={() => { logout(); setIsMobileMenuOpen(false); }}
                  className="flex items-center space-x-3 p-3 rounded w-full text-gray-400 hover:text-white mt-6 border-t border-gray-700 pt-6 tap-target"
                >
                  <span className="material-icons">logout</span>
                  <span>Logout</span>
                </button>
              </nav>
            </div>
          </div>
        )}

        {/* Desktop Sidebar */}
        <aside className="hidden md:flex flex-col items-center bg-card border border-card rounded-xl p-4 max-h-full overflow-y-auto scrollbar-hidden flex-shrink-0">
          <div className="p-3 bg-white text-black rounded-lg font-bold text-2xl flex-shrink-0">S</div>
          <nav className="flex flex-col items-center space-y-4 mt-4">
            <button
              onClick={() => { setView('dashboard'); loadDashboardData(); }}
              className={`flex flex-col items-center ${view === 'dashboard' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">home</span>
              <span className="text-xs">Home</span>
            </button>
            <button
              onClick={() => setView('chat')}
              className={`flex flex-col items-center ${view === 'chat' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">chat</span>
              <span className="text-xs">Chat</span>
            </button>
            <button
              onClick={() => { setView('notes'); loadNotes(); }}
              className={`flex flex-col items-center ${view === 'notes' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">notes</span>
              <span className="text-xs">Notes</span>
            </button>
            <button
              onClick={() => setView('habits')}
              className={`flex flex-col items-center ${view === 'habits' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">track_changes</span>
              <span className="text-xs">Habits</span>
            </button>
            <button
              onClick={() => { setView('documents'); loadDocuments(); }}
              className={`flex flex-col items-center ${view === 'documents' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">description</span>
              <span className="text-xs">Documents</span>
            </button>
            <button
              onClick={() => setView('calendar')}
              className={`flex flex-col items-center ${view === 'calendar' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">calendar_today</span>
              <span className="text-xs">Calendar</span>
            </button>
            <button
              onClick={() => setView('email')}
              className={`flex flex-col items-center ${view === 'email' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">email</span>
              <span className="text-xs">Email</span>
            </button>
            <button
              onClick={() => setView('fitness')}
              className={`flex flex-col items-center ${view === 'fitness' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="text-xl">💪</span>
              <span className="text-xs">Fitness</span>
            </button>
            <button
              onClick={() => setView('learn')}
              className={`flex flex-col items-center ${view === 'learn' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">school</span>
              <span className="text-xs">Learn</span>
            </button>
            <button
              onClick={() => setView('projects')}
              className={`flex flex-col items-center ${view === 'projects' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">work</span>
              <span className="text-xs">Projects</span>
            </button>
            <button
              onClick={() => setView('recipes')}
              className={`flex flex-col items-center ${view === 'recipes' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="text-xl">👨‍🍳</span>
              <span className="text-xs">Recipes</span>
            </button>
            <button
              onClick={() => setView('briefings')}
              className={`flex flex-col items-center ${view === 'briefings' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">wb_sunny</span>
              <span className="text-xs">Brief</span>
            </button>
            <button
              onClick={() => setView('sensory-monitor')}
              className={`flex flex-col items-center ${view === 'sensory-monitor' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">sensors</span>
              <span className="text-xs">Sensory</span>
            </button>
            <button
              onClick={() => setView('inbox')}
              className={`flex flex-col items-center ${view === 'inbox' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">inbox</span>
              <span className="text-xs">Inbox</span>
            </button>
            <button
              onClick={() => setView('settings')}
              className={`flex flex-col items-center ${view === 'settings' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">settings</span>
              <span className="text-xs">Settings</span>
            </button>
          </nav>
          <div className="mt-auto">
            <button
              onClick={logout}
              className="flex flex-col items-center text-gray-400 hover:text-white"
            >
              <span className="material-icons">logout</span>
            </button>
          </div>
        </aside>

        {/* Main Content */}
        <main ref={mainContentRef} className="flex-1 min-w-0 flex flex-col min-h-0 overflow-hidden">
          <header className="hidden md:flex justify-between items-center mb-4 flex-shrink-0">
            <h1 className="text-4xl font-bold">{APP_CONFIG.assistantName}</h1>
            <div className="flex items-center space-x-4">
              <AutomationTasksIndicator
                onOpenAutomations={() => setView('orchestrator')}
              />
              <BackgroundTasksIndicator
                onNavigateToWorkspace={(noteId) => {
                  setView('notes')
                  console.log('Navigate to workspace note:', noteId)
                }}
              />
              <span className="text-gray-400 text-sm">Hello, {user?.email}</span>
            </div>
          </header>

          {view === 'dashboard' && (
            <div className="flex-1 overflow-y-auto min-h-0 grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">
              {/* ===== LEFT COLUMN (2/3) ===== */}
              <div className="lg:col-span-2 space-y-4 md:space-y-6">

                {/* Morning Brief Hero Card */}
                <div className="bg-gradient-to-br from-[#161b22] to-[#1a2332] border border-gray-700/50 rounded-xl p-6 md:p-8">
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h1 className="text-2xl md:text-3xl font-bold text-white">
                        {getGreeting()}, David
                      </h1>
                      {weather && (
                        <p className="text-gray-400 mt-1 text-sm md:text-base">
                          {WEATHER_EMOJI[weather.icon] || WEATHER_EMOJI['clear-day']}{' '}
                          {Math.round(weather.temperature || weather.temp || 0)}&deg;F &mdash; {weather.description || weather.summary || 'Clear'}
                        </p>
                      )}
                    </div>
                    {morningBrief && (
                      <button
                        onClick={playBriefAudio}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 border border-teal-500/30 transition-colors"
                      >
                        <span className="material-icons text-sm">{briefAudioPlaying ? 'pause' : 'play_arrow'}</span>
                        <span className="text-sm font-medium">{briefAudioPlaying ? 'Pause' : 'Listen'}</span>
                      </button>
                    )}
                  </div>

                  {morningBrief && (
                    <audio
                      ref={briefAudioRef}
                      src={`${APP_CONFIG.apiUrl}/api/morning-brief/${morningBrief.brief_date}/audio`}
                      onEnded={() => setBriefAudioPlaying(false)}
                      style={{ display: 'none' }}
                    />
                  )}

                  {morningBriefLoading ? (
                    <div className="flex items-center gap-2 text-gray-500 py-4">
                      <div className="animate-spin w-4 h-4 border-2 border-gray-500 border-t-transparent rounded-full"></div>
                      <span className="text-sm">Loading brief...</span>
                    </div>
                  ) : morningBrief ? (
                    <div>
                      <div className="text-gray-300 text-sm md:text-base leading-relaxed prose prose-invert prose-sm max-w-none
                        prose-headings:text-gray-200 prose-headings:text-base prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1
                        prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-strong:text-gray-200">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {(morningBrief.full_text || morningBrief.summary || '').slice(0, 800)}
                        </ReactMarkdown>
                      </div>
                      {(morningBrief.full_text || '').length > 800 && (
                        <button
                          onClick={() => setView('briefings')}
                          className="text-teal-400 hover:text-teal-300 text-sm mt-3 inline-flex items-center gap-1"
                        >
                          Read full brief <span className="material-icons text-sm">arrow_forward</span>
                        </button>
                      )}
                    </div>
                  ) : (
                    <p className="text-gray-500 text-sm py-2">No brief available yet today.</p>
                  )}
                </div>

                {/* Today's Calendar */}
                <div className="bg-card border border-card rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                      {currentTime.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
                    </h2>
                    <button onClick={() => setView('calendar')} className="text-gray-500 hover:text-teal-400 transition-colors">
                      <span className="material-icons text-sm">open_in_new</span>
                    </button>
                  </div>
                  {calendarEvents.length > 0 ? (
                    <div className="space-y-2">
                      {calendarEvents.map((evt: any, i: number) => {
                        const start = new Date(evt.start_time || evt.start || evt.dtstart)
                        const end = new Date(evt.end_time || evt.end || evt.dtend)
                        const now = new Date()
                        const isNow = now >= start && now <= end
                        return (
                          <div key={evt.id || i} className="flex items-stretch gap-3">
                            <div className={`w-1 rounded-full flex-shrink-0 ${isNow ? 'bg-teal-400' : 'bg-gray-600'}`}></div>
                            <div className="flex-1 py-1">
                              <div className="flex items-baseline justify-between">
                                <span className={`font-medium text-sm ${isNow ? 'text-teal-400' : 'text-gray-200'}`}>
                                  {evt.title || evt.summary}
                                </span>
                                <span className="text-xs text-gray-500 ml-2 flex-shrink-0">
                                  {start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                                  {' - '}
                                  {end.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                                </span>
                              </div>
                              {evt.location && (
                                <span className="text-xs text-gray-500">{evt.location}</span>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-gray-500 text-sm text-center py-3">No events today</p>
                  )}
                </div>

                {/* Sara's Journal */}
                <div className="bg-card border border-card rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Sara's Journal</h2>
                  </div>
                  {journalEntries.length > 0 ? (
                    <div className="space-y-3">
                      {journalEntries.slice(0, 5).map((entry: any, i: number) => (
                        <div key={entry.id || i} className="flex gap-3">
                          <span className="text-xs text-gray-500 flex-shrink-0 w-14 pt-0.5 text-right">
                            {entry.timestamp || entry.created_at
                              ? new Date(entry.timestamp || entry.created_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
                              : ''}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-gray-300 leading-relaxed">
                              {entry.summary || entry.content || entry.text || ''}
                            </p>
                            {entry.emotional_state && (
                              <span className="text-xs text-gray-500 mt-0.5 inline-block">
                                {EMOTION_EMOJI[entry.emotional_state] || ''} {entry.emotional_state}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-500 text-sm text-center py-3">No journal entries in the last 24 hours</p>
                  )}
                </div>
              </div>

              {/* ===== RIGHT COLUMN (1/3) ===== */}
              <div className="lg:col-span-1 space-y-4 md:space-y-6">

                {/* Activity & Devices */}
                <div className="bg-card border border-card rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Activity & Devices</h2>
                  {saraStatus && (
                    <div className="mb-4">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-lg">{EMOTION_EMOJI[saraStatus.emotional_state] || EMOTION_EMOJI['neutral']}</span>
                        <span className="text-sm text-gray-300 capitalize">{saraStatus.emotional_state || 'neutral'}</span>
                      </div>
                      {saraStatus.latest_thought && (
                        <p className="text-xs text-gray-500 italic leading-relaxed">
                          "{(saraStatus.latest_thought || '').slice(0, 120)}{(saraStatus.latest_thought || '').length > 120 ? '...' : ''}"
                        </p>
                      )}
                    </div>
                  )}
                  <div className="space-y-2">
                    {connectedDevices.length > 0 ? connectedDevices.map((dev: any, i: number) => (
                      <div key={dev.device_id || i} className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          dev.is_connected ? 'bg-green-400' :
                          dev.is_online ? 'bg-yellow-400' : 'bg-gray-600'
                        }`}></div>
                        <span className="text-sm text-gray-300">{dev.friendly_name || dev.hostname || 'Unknown'}</span>
                        <span className="text-xs text-gray-500 ml-auto">{dev.platform || ''}</span>
                      </div>
                    )) : (
                      <p className="text-gray-500 text-xs">No devices connected</p>
                    )}
                  </div>
                </div>

                {/* Standing Orders */}
                <div className="bg-card border border-card rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Standing Orders</h2>
                  {standingOrders.length > 0 ? (
                    <div className="space-y-2">
                      {standingOrders.slice(0, 5).map((order: any) => (
                        <div key={order.id} className="flex items-start gap-2">
                          <span className="material-icons text-sm text-gray-500 mt-0.5" style={{fontSize: '16px'}}>
                            {order.trigger_type === 'timer' ? 'timer' :
                             order.trigger_type === 'time' ? 'schedule' :
                             order.trigger_type === 'climate' ? 'thermostat' :
                             order.trigger_type === 'presence' ? 'sensors' : 'auto_awesome'}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-gray-300 leading-tight">{order.description}</p>
                            <div className="flex items-center gap-2 mt-0.5">
                              {order.fires_at && (
                                <span className="text-xs text-amber-400">
                                  {new Date(order.fires_at).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})}
                                </span>
                              )}
                              {order.scheduled_time && (
                                <span className="text-xs text-blue-400">
                                  {order.scheduled_time}{order.scheduled_days ? ` (${order.scheduled_days.join(', ')})` : ' daily'}
                                </span>
                              )}
                              {!order.fires_at && !order.scheduled_time && (
                                <span className="text-xs text-gray-500">{order.execution_count || 0} runs</span>
                              )}
                              {order.last_executed_at && (
                                <span className="text-xs text-gray-600">&middot; {formatRelativeTime(order.last_executed_at)}</span>
                              )}
                              {order.trigger_config?.one_shot && (
                                <span className="text-xs text-gray-600">&middot; one-time</span>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-500 text-xs text-center py-2">No active standing orders</p>
                  )}
                </div>

                {/* Quick Actions */}
                <div className="bg-card border border-card rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Quick Actions</h2>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { icon: 'chat', label: 'Chat', view: 'chat', color: 'text-teal-400' },
                      { icon: 'edit_note', label: 'Notes', view: 'notes', color: 'text-blue-400' },
                      { icon: 'calendar_month', label: 'Calendar', view: 'calendar', color: 'text-purple-400' },
                      { icon: 'summarize', label: 'Briefs', view: 'briefings', color: 'text-amber-400' },
                    ].map(action => (
                      <button
                        key={action.view}
                        onClick={() => setView(action.view)}
                        className="flex flex-col items-center gap-1 py-3 rounded-lg bg-gray-800/50 hover:bg-gray-700/50 transition-colors"
                      >
                        <span className={`material-icons ${action.color}`}>{action.icon}</span>
                        <span className="text-xs text-gray-400">{action.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Active Timers (conditional) */}
                {timers.length > 0 && (
                  <div className="bg-card border border-card rounded-xl p-5">
                    <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Active Timers</h2>
                    <div className="space-y-2">
                      {timers.map((timer: any) => (
                        <div key={timer.id} className="flex items-center justify-between bg-gray-800/50 p-2 rounded-lg">
                          <span className="text-sm text-gray-300 truncate mr-2">{timer.title}</span>
                          <LiveTimer
                            endTime={timer.end_time}
                            className="text-teal-400 font-mono text-sm flex-shrink-0"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {view === 'chat' && (
            <div className="flex-1 min-h-0">
            <ChatInterface
              messages={chatMessages}
              setMessages={setChatMessages}
              loading={loading}
              onSendMessage={null} // Let ChatInterface handle its own message sending
              onClearChat={clearChat}
              message={message}
              setMessage={setMessage}
              abortControllerRef={abortControllerRef}
            />
            </div>
          )}

          {view === 'notes' && (
            <div className="flex-1 min-h-0">
            <Notes
              notes={notes}
              setNotes={setNotes}
              editingNote={editingNote}
              setEditingNote={setEditingNote}
              editNoteContent={editNoteContent}
              setEditNoteContent={setEditNoteContent}
              editNoteTitle={editNoteTitle}
              setEditNoteTitle={setEditNoteTitle}
            />
            </div>
          )}

          {view === 'documents' && (
            <div className="flex-1 overflow-y-auto min-h-0 space-y-6">
              {/* Document Upload Section */}
              <div className="bg-card border border-card rounded-xl p-6">
                <h2 className="text-lg font-semibold mb-4">UPLOAD DOCUMENT</h2>
                <div className="space-y-4">
                  <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center">
                    <input
                      type="file"
                      id="document-upload"
                      className="hidden"
                      accept=".pdf,.doc,.docx,.txt,.md"
                      onChange={(e) => setSelectedFile(e.target.files[0])}
                    />
                    <label htmlFor="document-upload" className="cursor-pointer">
                      <div className="space-y-2">
                        <span className="material-icons text-4xl text-gray-400">cloud_upload</span>
                        <p className="text-gray-400">Click to select a document or drag and drop</p>
                        <p className="text-sm text-gray-500">Supports PDF, DOC, DOCX, TXT, MD files</p>
                      </div>
                    </label>
                  </div>
                  
                  {selectedFile && (
                    <div className="bg-gray-800 p-4 rounded-lg">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-3">
                          <span className="material-icons text-teal-400">description</span>
                          <div>
                            <p className="text-white font-medium">{selectedFile.name}</p>
                            <p className="text-sm text-gray-400">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                          </div>
                        </div>
                        <div className="space-x-2">
                          <button
                            onClick={() => uploadDocument(selectedFile)}
                            disabled={uploading}
                            className="bg-teal-600 hover:bg-teal-700 text-white px-4 py-2 rounded-lg disabled:opacity-50"
                          >
                            {uploading ? 'Uploading...' : 'Upload'}
                          </button>
                          <button
                            onClick={() => setSelectedFile(null)}
                            className="bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded-lg"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Documents List */}
              <div className="bg-card border border-card rounded-xl p-6">
                <h2 className="text-lg font-semibold mb-4">YOUR DOCUMENTS</h2>
                {documents.length === 0 ? (
                  <p className="text-gray-400 text-center py-8">No documents uploaded yet</p>
                ) : (
                  <div className="space-y-3">
                    {documents.map((doc) => (
                      <div key={doc.id} className="bg-gray-800 p-4 rounded-lg">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center space-x-3 flex-1">
                            <span className="material-icons text-teal-400">
                              {doc.mime_type?.includes('pdf') ? 'picture_as_pdf' : 
                               doc.mime_type?.includes('word') ? 'article' : 
                               'description'}
                            </span>
                            <div className="flex-1">
                              {editingDocumentId === doc.id ? (
                                <div className="flex items-center space-x-2">
                                  <input
                                    type="text"
                                    value={editingDocumentTitle}
                                    onChange={(e) => setEditingDocumentTitle(e.target.value)}
                                    className="flex-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-sm"
                                    onKeyPress={(e) => {
                                      if (e.key === 'Enter') {
                                        updateDocumentTitle(doc.id, editingDocumentTitle)
                                      }
                                      if (e.key === 'Escape') {
                                        cancelEditDocumentTitle()
                                      }
                                    }}
                                    autoFocus
                                  />
                                  <button
                                    onClick={() => updateDocumentTitle(doc.id, editingDocumentTitle)}
                                    className="text-green-400 hover:text-green-300 p-1"
                                    title="Save"
                                  >
                                    <span className="material-icons text-sm">check</span>
                                  </button>
                                  <button
                                    onClick={cancelEditDocumentTitle}
                                    className="text-gray-400 hover:text-gray-300 p-1"
                                    title="Cancel"
                                  >
                                    <span className="material-icons text-sm">close</span>
                                  </button>
                                </div>
                              ) : (
                                <div className="flex items-center space-x-2">
                                  <p className="text-white font-medium flex-1">{doc.title || doc.original_filename}</p>
                                  <button
                                    onClick={() => startEditDocumentTitle(doc)}
                                    className="text-gray-400 hover:text-gray-300 p-1"
                                    title="Edit title"
                                  >
                                    <span className="material-icons text-sm">edit</span>
                                  </button>
                                </div>
                              )}
                              <div className="flex items-center space-x-4 text-sm text-gray-400 mt-1">
                                <span>{(doc.file_size / 1024 / 1024).toFixed(2)} MB</span>
                                <span>•</span>
                                <span>Uploaded {new Date(doc.created_at).toLocaleDateString()}</span>
                                <span>•</span>
                                <span className={`px-2 py-1 rounded text-xs ${
                                  doc.is_processed === 'true' ? 'bg-green-900 text-green-300' :
                                  doc.is_processed === 'error' ? 'bg-red-900 text-red-300' :
                                  'bg-yellow-900 text-yellow-300'
                                }`}>
                                  {doc.is_processed === 'true' ? 'Processed' :
                                   doc.is_processed === 'error' ? 'Error' :
                                   'Processing...'}
                                </span>
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center space-x-2">
                            <button
                              onClick={() => downloadDocument(doc.id, doc.original_filename)}
                              className="text-teal-400 hover:text-teal-300 p-2"
                              title="Download"
                            >
                              <span className="material-icons">download</span>
                            </button>
                            <button
                              onClick={() => deleteDocument(doc.id)}
                              className="text-red-400 hover:text-red-300 p-2"
                              title="Delete"
                            >
                              <span className="material-icons">delete</span>
                            </button>
                          </div>
                        </div>
                        
                        {doc.content_text && doc.is_processed === 'true' && (
                          <div className="mt-3 pt-3 border-t border-gray-700">
                            <p className="text-sm text-gray-400 mb-2">Document Preview:</p>
                            <p className="text-xs text-gray-500 line-clamp-3">
                              {doc.content_text.substring(0, 200)}...
                            </p>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {view === 'calendar' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <CalendarView />
            </div>
          )}

          {view === 'habits' && (
            <div className="flex-1 overflow-y-auto min-h-0 space-y-6">
              {/* Habit Sub-Navigation */}
              <div className="bg-card border border-card rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div className="flex space-x-4">
                    <button
                      onClick={() => setHabitView('today')}
                      className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                        habitView === 'today'
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                      }`}
                    >
                      Today
                    </button>
                    <button
                      onClick={() => setHabitView('insights')}
                      className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                        habitView === 'insights'
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                      }`}
                    >
                      Insights
                    </button>
                  </div>
                  
                  <button
                    onClick={() => setShowHabitCreate(true)}
                    className="flex items-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                  >
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    Create Habit
                  </button>
                </div>
              </div>

              {/* Habit Content */}
              {habitView === 'today' && (
                <HabitToday />
              )}
              
              {habitView === 'insights' && (
                <HabitInsights />
              )}

              {/* Create Habit Modal */}
              <HabitCreate
                isOpen={showHabitCreate}
                onClose={() => setShowHabitCreate(false)}
                onCreated={() => {
                  setShowHabitCreate(false);
                  showToast('Habit created successfully!', 'success');
                  // Refresh today view if that's active
                  if (habitView === 'today') {
                    // HabitToday component will automatically refresh
                  }
                }}
              />
            </div>
          )}

          {view === 'fitness' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <FitnessSection />
            </div>
          )}

          {view === 'learn' && (
            <div className="flex-1 min-h-0">
            <LearningSection />
            </div>
          )}

          {view === 'projects' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <ProjectSection />
            </div>
          )}

          {view === 'recipes' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <RecipesSection />
            </div>
          )}

          {/* GTKY now managed within Settings; reflection views removed */}

          {view === 'privacy-dashboard' && (
            <div className="flex-1 overflow-y-auto min-h-0 max-w-4xl mx-auto">
              <PrivacyDashboard
                onToast={(message, type) => {
                  showToast(message, type || 'info')
                }}
              />
            </div>
          )}

          {view === 'settings' && (
            <div className="flex-1 overflow-y-auto min-h-0 space-y-6">
              <Settings />

            </div>
          )}

          {view === 'orchestrator-lab' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <OrchestratorLab onBack={() => setView('settings')} />
            </div>
          )}

          {view === 'briefings' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <MorningBrief />
            </div>
          )}

          {view === 'sensory-monitor' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <SensoryMonitor />
            </div>
          )}

          {view === 'email' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <EmailPage />
            </div>
          )}

          {view === 'inbox' && (
            <div className="flex-1 overflow-y-auto min-h-0">
            <ContentInbox
              onNavigateToChat={(inboxItemId, title) => {
                // Navigate to chat with inbox item context
                setMessage(`Let's talk about this: ${title}`);
                setChatMessages([]);
                setView('chat');
                // Store inbox_item_id for next chat request
                (window as any).__inboxItemId = inboxItemId;
              }}
            />
            </div>
          )}
        </main>
      </div>
      
      {/* Mobile Bottom Navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-700 z-40 overflow-x-auto scrollbar-hidden">
        <div className="flex py-2 px-2 gap-1" style={{minWidth: 'fit-content'}}>
          <button
            onClick={() => { setView('dashboard'); loadDashboardData(); }}
            className={`flex flex-col items-center px-3 py-2 rounded flex-shrink-0 tap-target ${view === 'dashboard' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">home</span>
            <span className="text-xs whitespace-nowrap">Home</span>
          </button>
          <button
            onClick={() => setView('chat')}
            className={`flex flex-col items-center px-3 py-2 rounded flex-shrink-0 tap-target ${view === 'chat' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">chat</span>
            <span className="text-xs whitespace-nowrap">Chat</span>
          </button>
          <button
            onClick={() => { setView('notes'); loadNotes(); }}
            className={`flex flex-col items-center px-3 py-2 rounded flex-shrink-0 tap-target ${view === 'notes' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">notes</span>
            <span className="text-xs whitespace-nowrap">Notes</span>
          </button>
          <button
            onClick={() => setView('calendar')}
            className={`flex flex-col items-center px-3 py-2 rounded flex-shrink-0 tap-target ${view === 'calendar' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">calendar_today</span>
            <span className="text-xs whitespace-nowrap">Calendar</span>
          </button>
          <button
            onClick={() => setView('email')}
            className={`flex flex-col items-center px-3 py-2 rounded flex-shrink-0 tap-target ${view === 'email' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">email</span>
            <span className="text-xs whitespace-nowrap">Email</span>
          </button>
          <button
            onClick={() => setView('fitness')}
            className={`flex flex-col items-center px-3 py-2 rounded flex-shrink-0 tap-target ${view === 'fitness' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400'}`}
          >
            <span className="text-xl">💪</span>
            <span className="text-xs whitespace-nowrap">Fitness</span>
          </button>
          <button
            onClick={() => setIsMobileMenuOpen(true)}
            className="flex flex-col items-center px-3 py-2 rounded flex-shrink-0 text-gray-400 tap-target"
          >
            <span className="material-icons text-lg">more_horiz</span>
            <span className="text-xs whitespace-nowrap">More</span>
          </button>
        </div>
      </nav>


      {/* Background Task Notifications */}
      <NotificationBanner
        onNavigateToWorkspace={(noteId) => {
          // Navigate to notes view and select the result note
          setView('notes')
          // You can pass the noteId to Notes component to auto-select it
          console.log('Navigate to workspace note:', noteId)
        }}
        onShowToast={(message, type) => {
          const newToast = { id: Date.now().toString(), message, type }
          setToasts(prev => [...prev, newToast])
          setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== newToast.id))
          }, 5000)
        }}
      />

      {/* Mini Chat Overlay for Agent Clarifications */}
      <MiniChatOverlay />

      {/* Health Alert Chat Overlay */}
      {activeHealthAlert && (
        <HealthAlertChat
          alert={activeHealthAlert}
          onClose={() => {
            // Mark as dismissed so it doesn't reappear (persisted to localStorage)
            if (activeHealthAlert.insightId) {
              const newDismissed = new Set([...dismissedHealthAlertIds, activeHealthAlert.insightId!])
              setDismissedHealthAlertIds(newDismissed)
              // Save to localStorage with timestamp for 24-hour expiry
              try {
                const entries = Array.from(newDismissed).map(id => `${id}:${Date.now()}`)
                localStorage.setItem('dismissedHealthAlertIds', JSON.stringify(entries))
              } catch {}
            }
            setActiveHealthAlert(null)
          }}
        />
      )}

      {/* Toast Notifications */}
      <div className="fixed top-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`max-w-sm w-full border-2 rounded-lg shadow-lg p-4 transform transition-all duration-300 ${
              toast.type === 'success' ? 'border-green-500 bg-green-900' : 
              toast.type === 'error' ? 'border-red-500 bg-red-900' : 
              'border-blue-500 bg-blue-900'
            } ${toast.persistent ? 'ring-2 ring-yellow-400 ring-opacity-50' : ''}`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center flex-1">
                <span className={`material-icons text-sm mr-2 ${
                  toast.type === 'success' ? 'text-green-400' : 
                  toast.type === 'error' ? 'text-red-400' : 
                  'text-blue-400'
                }`}>
                  {toast.type === 'success' ? 'check_circle' : 
                   toast.type === 'error' ? 'error' : 
                   'info'}
                </span>
                <p className="text-white text-sm font-medium">{toast.message}</p>
              </div>
              <button
                onClick={() => removeToast(toast.id)}
                className={`text-gray-400 hover:text-white ml-2 ${
                  toast.persistent ? 'bg-gray-700 hover:bg-gray-600 rounded p-1' : ''
                }`}
                title={toast.persistent ? 'Click to acknowledge' : 'Close'}
              >
                <span className="material-icons text-sm">
                  {toast.persistent ? 'check' : 'close'}
                </span>
              </button>
            </div>
            {toast.persistent && (
              <div className="mt-2 text-xs text-yellow-400">
                Click ✓ to acknowledge
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
