import React, { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { APP_CONFIG } from './config'
import MermaidDiagram from './components/MermaidDiagram'
import MemoryGarden from './components/MemoryGarden'
import SimplifiedNotes from './components/SimplifiedNotes'
import KnowledgeGraph from './components/KnowledgeGraph'
import VulnerabilityWatch from './components/VulnerabilityWatch'
import Settings from './pages/Settings'
import HabitToday from './components/HabitToday'
import HabitCreate from './components/HabitCreate'
import HabitInsights from './components/HabitInsights'
import ChatInterface from './components/ChatInterface'
import Sprite, { SpriteHandle } from './components/Sprite'
import InsightInbox from './components/InsightInbox'
import { GTKYTrigger } from './components/onboarding/GTKYTrigger'
import { GTKYInterview } from './components/onboarding/GTKYInterview'
import { GTKYInterviewTest } from './components/onboarding/GTKYInterviewTest'
import { ReflectionTrigger } from './components/reflection/ReflectionTrigger'
import { NightlyReflection } from './components/reflection/NightlyReflection'
import { PrivacyDashboard } from './components/privacy/PrivacyDashboard'
import { useActivityMonitor } from './hooks/useActivityMonitor'

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
  const [view, setView] = useState('login') // login, dashboard, chat, notes, habits, documents, calendar, vulnerability-watch, settings, onboarding, reflection
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isMobileNotesSidebarOpen, setIsMobileNotesSidebarOpen] = useState(false)
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
  const [currentSpriteMode, setCurrentSpriteMode] = useState('companion')
  
  // Ref for auto-scrolling chat messages
  const chatMessagesEndRef = useRef(null)
  
  // Ref to track and cancel ongoing chat requests
  const abortControllerRef = useRef(null)
  
  // Sprite ref for controlling the assistant avatar
  const spriteRef = useRef<SpriteHandle>(null)

  // Activity monitoring for autonomous behaviors
  const { activityState, getIdleMinutes } = useActivityMonitor({
    thresholds: {
      quickSweep: 25 * 60 * 1000,      // 25 minutes - short idle
      standardSweep: 2.5 * 60 * 60 * 1000, // 2.5 hours - medium idle
      digestSweep: 24 * 60 * 60 * 1000     // 24 hours - long idle
    },
    onThresholdReached: async (threshold, duration) => {
      console.log(`🤖 Sara: ${threshold} triggered after ${Math.round(duration / 60000)} minutes idle`)
      
      // Get current mode and trigger autonomous sweep
      const mode = spriteRef.current?.getMode() || 'companion'
      
      try {
        // Call backend autonomous sweep
        const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/sweep/${threshold}?personality_mode=${mode}`, {
          method: 'POST',
          credentials: 'include'
        })
        
        if (response.ok) {
          const result = await response.json()
          console.log(`🤖 Autonomous sweep result:`, result)
          
          // Only notify if meaningful insights were generated
          if (result.insights_stored > 0 && result.new_insights > 0) {
            await fetchAndDisplayLatestInsight(threshold, mode)
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
      spriteRef.current?.setState('idle')
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

  // Load analytics and notes when view changes to dashboard
  useEffect(() => {
    if (isAuthenticated && view === 'dashboard') {
      console.log('Dashboard view activated, loading analytics, notes, timers, and reminders...')
      loadAnalytics()
      loadNotes()
      loadTimersAndReminders()
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
        
        // Welcome notification via sprite
        setTimeout(() => {
          spriteRef.current?.notify(`Welcome back! I'm here to assist you.`, {
            showToast: true,
            keepBadge: false,
            autoHide: 4000,
            onReply: () => setView('chat'),
            onOpen: () => setView('dashboard')
          })
        }, 2000)
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
                    spriteRef.current?.setState('listening')
                    if (isQuickChat) {
                      setQuickChatResponse(toolActivity)
                    }
                    break
                    
                  case 'tool_executing':
                    toolActivity = `🔧 Using ${eventData.data.tool}...`
                    spriteRef.current?.setState('thinking')
                    if (isQuickChat) {
                      setQuickChatResponse(toolActivity)
                    }
                    break
                    
                  case 'thinking':
                    toolActivity = '💭 Processing results...'
                    spriteRef.current?.setState('thinking')
                    if (isQuickChat) {
                      setQuickChatResponse(toolActivity)
                    }
                    break
                    
                  case 'text_chunk':
                    streamingContent = eventData.data.full_content
                    spriteRef.current?.setState('speaking')
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
                    spriteRef.current?.setState('idle')
                    break
                    
                  case 'error':
                    console.error('Streaming error:', eventData.message)
                    setLoading(false)
                    spriteRef.current?.setState('idle')
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
      spriteRef.current?.setState('idle')
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
  
  const showToast = (message, type = 'info', persistent = false, showSprite = false) => {
    const id = Date.now()
    const toast = { id, message, type, persistent }
    setToasts(prev => [...prev, toast])
    
    // Show sprite notification for important messages
    if (showSprite) {
      spriteRef.current?.notify(message, {
        showToast: true,
        keepBadge: true,
        autoHide: persistent ? 0 : 6500,
        onReply: () => {
          // Open chat and pre-fill with a relevant response
          setView('chat')
          setMessage(`About the notification: "${message}"`)
        },
        onOpen: () => {
          // Navigate to most relevant view based on notification type
          if (message.toLowerCase().includes('vuln')) {
            setView('vulnerability-watch')
          } else if (message.toLowerCase().includes('timer')) {
            setView('dashboard')
          } else if (message.toLowerCase().includes('reminder')) {
            setView('dashboard') 
          } else {
            setView('chat')
          }
        }
      })
    }
    
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

  // Autonomous behavior handlers for different idle thresholds
  const handleQuickSweep = useCallback((mode) => {
    console.log(`🔍 Quick Sweep triggered in ${mode} mode`)
    
    const messages = {
      coach: "Ready to tackle something new? 💪",
      analyst: "I've been analyzing your recent patterns...",
      companion: "I'm here if you need to chat about anything",
      guardian: "System status: All secure and running smoothly",
      concierge: "Shall I help organize your day?", 
      librarian: "I noticed some documents that might interest you"
    }

    spriteRef.current?.setState('thinking')
    spriteRef.current?.pulse('subtle')
    
    setTimeout(() => {
      spriteRef.current?.notify(messages[mode] || messages.companion, {
        showToast: true,
        keepBadge: true,
        autoHide: 6000,
        onReply: () => setView('chat'),
        onOpen: () => setView('dashboard')
      })
    }, 2000)
  }, [])

  const handleStandardSweep = useCallback((mode) => {
    console.log(`📊 Standard Sweep triggered in ${mode} mode`)
    
    const messages = {
      coach: "I've spotted some patterns in your habits - want insights?",
      analyst: "Ready for your productivity summary?",
      companion: "How are you feeling about your progress today?",
      guardian: "Time for a security and wellness check-in",
      concierge: "I can help reschedule or prep for upcoming tasks",
      librarian: "I've organized your knowledge graph - take a look?"
    }

    spriteRef.current?.setState('listening')
    spriteRef.current?.pulse('normal')
    
    setTimeout(() => {
      spriteRef.current?.notify(messages[mode] || messages.companion, {
        showToast: true, 
        keepBadge: true,
        autoHide: 8000,
        onReply: () => setView('chat'),
        onOpen: () => {
          // Navigate to relevant view based on mode
          const views = {
            coach: 'habits',
            analyst: 'memory-garden',
            companion: 'chat',
            guardian: 'vulnerability-watch',
            concierge: 'calendar',
            librarian: 'notes'
          }
          setView(views[mode] || 'dashboard')
        }
      })
    }, 1500)
  }, [])

  const handleDigestSweep = useCallback((mode) => {
    console.log(`📝 Digest Sweep triggered in ${mode} mode`)
    
    const messages = {
      coach: "Let's review your wins and plan tomorrow! 🎯",
      analyst: "Your weekly intelligence digest is ready",
      companion: "Shall we reflect on today and set intentions?",
      guardian: "Daily security briefing and system health report",
      concierge: "Tomorrow's schedule optimized with buffer time",
      librarian: "Weekly knowledge summary and reading recommendations"
    }

    spriteRef.current?.setState('notifying')
    spriteRef.current?.pulse('strong')
    
    setTimeout(() => {
      spriteRef.current?.notify(messages[mode] || messages.companion, {
        showToast: true,
        keepBadge: true,
        autoHide: 10000,
        onReply: () => setView('chat'),
        onOpen: () => setView('dashboard')
      })
    }, 1000)
  }, [])

  // Helper function to fetch and display the latest autonomous insight
  const fetchAndDisplayLatestInsight = useCallback(async (threshold: string, mode: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/insights?limit=1&sweep_type=${threshold}`, {
        credentials: 'include'
      })
      
      if (response.ok) {
        const insights = await response.json()
        if (insights.length > 0) {
          const insight = insights[0]
          
          // Set appropriate sprite state based on sweep type
          const spriteState = threshold === 'quickSweep' ? 'thinking' : 
                             threshold === 'standardSweep' ? 'listening' : 'notifying'
          
          spriteRef.current?.setState(spriteState)
          spriteRef.current?.pulse(threshold === 'digestSweep' ? 'strong' : 'normal')
          
          // Display insight via sprite notification
          setTimeout(() => {
            spriteRef.current?.notify(insight.message, {
              showToast: true,
              keepBadge: true,
              autoHide: threshold === 'digestSweep' ? 10000 : threshold === 'standardSweep' ? 8000 : 6000,
              onReply: () => setView('chat'),
              onOpen: () => {
                // Navigate to relevant view based on insight type
                const viewMap: Record<string, string> = {
                  'habit_salvage': 'habits',
                  'content_pattern': 'notes',
                  'knowledge_connection': 'notes',
                  'security_alert': 'vulnerability-watch',
                  'calendar_prep': 'calendar',
                  'weekly_summary': 'dashboard',
                  'gtky_prompt': 'gtky-interview',
                  'reflection_prompt': 'nightly-reflection',
                  'reflection_streak': 'nightly-reflection',
                  'mood_improvement': 'nightly-reflection',
                  'goal_check': 'gtky-interview',
                  'style_adjustment': 'privacy-dashboard'
                }
                setView(viewMap[insight.insight_type] || 'dashboard')
              }
            })
          }, 1500)
        }
      }
    } catch (error) {
      console.warn('Failed to fetch latest insight:', error)
    }
  }, [])

  // Fallback sweep handlers (original client-side behavior)
  const handleFallbackSweep = useCallback((threshold: string, mode: string) => {
    switch (threshold) {
      case 'quickSweep':
        handleQuickSweep(mode)
        break
      case 'standardSweep':
        handleStandardSweep(mode)
        break
      case 'digestSweep':
        handleDigestSweep(mode)
        break
    }
  }, [])

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
    <div className="p-4 md:p-8 pb-20 md:pb-8" style={{backgroundColor: '#0d1117', color: '#c9d1d9', minHeight: '100vh'}}>
      <div className="flex flex-col md:flex-row md:space-x-8">
        
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
            <div className="bg-gray-900 w-64 h-full p-4" onClick={e => e.stopPropagation()}>
              <div className="flex justify-between items-center mb-6">
                <div className="p-3 bg-white text-black rounded-lg font-bold text-xl">S</div>
                <button onClick={() => setIsMobileMenuOpen(false)} className="text-gray-400">✕</button>
              </div>
              <nav className="flex flex-col space-y-4">
                <button
                  onClick={() => { setView('dashboard'); loadNotes(); loadAnalytics(); loadTimersAndReminders(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'dashboard' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">🏠</span>
                  <span>Home</span>
                </button>
                <button
                  onClick={() => { setView('chat'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'chat' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">💬</span>
                  <span>Chat</span>
                </button>
                <button
                  onClick={() => { setView('notes'); loadNotes(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'notes' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">📝</span>
                  <span>Notes</span>
                </button>
                <button
                  onClick={() => { setView('memory-garden'); loadNotes(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'memory-garden' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">🧠</span>
                  <span>Memory Garden</span>
                </button>
                <button
                  onClick={() => { setView('habits'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'habits' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">🎯</span>
                  <span>Habits</span>
                </button>
                <button
                  onClick={() => { setView('documents'); loadDocuments(); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'documents' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">📄</span>
                  <span>Documents</span>
                </button>
                <button
                  onClick={() => { setView('calendar'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'calendar' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">📅</span>
                  <span>Calendar</span>
                </button>
                <button
                  onClick={() => { setView('vulnerability-watch'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'vulnerability-watch' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">🛡️</span>
                  <span>Vulnerability Watch</span>
                </button>
                <button
                  onClick={() => { setView('insights'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'insights' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">🧠</span>
                  <span>Sara's Insights</span>
                </button>
                <button
                  onClick={() => { setView('onboarding'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'onboarding' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">💫</span>
                  <span>Get to Know You</span>
                </button>
                <button
                  onClick={() => { setView('reflection'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'reflection' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">🌙</span>
                  <span>Nightly Reflection</span>
                </button>
                <button
                  onClick={() => { setView('settings'); setIsMobileMenuOpen(false); }}
                  className={`flex items-center space-x-3 p-3 rounded ${view === 'settings' ? 'text-teal-400 bg-teal-400/10' : 'text-gray-400 hover:text-white'}`}
                >
                  <span className="text-xl">⚙️</span>
                  <span>Settings</span>
                </button>
                <button
                  onClick={() => { logout(); setIsMobileMenuOpen(false); }}
                  className="flex items-center space-x-3 p-3 rounded text-gray-400 hover:text-white mt-8 border-t border-gray-700 pt-4"
                >
                  <span className="text-xl">🚪</span>
                  <span>Logout</span>
                </button>
              </nav>
            </div>
          </div>
        )}

        {/* Desktop Sidebar */}
        <aside className="hidden md:flex flex-col items-center space-y-6 bg-card border border-card rounded-xl p-4" style={{height: 'fit-content'}}>
          <div className="p-3 bg-white text-black rounded-lg font-bold text-2xl">S</div>
          <nav className="flex flex-col items-center space-y-6">
            <button
              onClick={() => { setView('dashboard'); loadNotes(); loadAnalytics(); loadTimersAndReminders(); }}
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
              onClick={() => { setView('memory-garden'); loadNotes(); }}
              className={`flex flex-col items-center ${view === 'memory-garden' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">psychology</span>
              <span className="text-xs">Memory</span>
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
              onClick={() => setView('vulnerability-watch')}
              className={`flex flex-col items-center ${view === 'vulnerability-watch' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="material-icons">security</span>
              <span className="text-xs">Vulns</span>
            </button>
            <button
              onClick={() => setView('onboarding')}
              className={`flex flex-col items-center ${view === 'onboarding' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="text-xl">💫</span>
              <span className="text-xs">GTKY</span>
            </button>
            <button
              onClick={() => setView('reflection')}
              className={`flex flex-col items-center ${view === 'reflection' ? 'text-teal-400' : 'text-gray-400 hover:text-white'}`}
            >
              <span className="text-xl">🌙</span>
              <span className="text-xs">Reflect</span>
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
        <main className="flex-1 min-w-0">
          <header className="hidden md:flex justify-between items-center mb-8">
            <h1 className="text-4xl font-bold">{APP_CONFIG.assistantName}</h1>
            <div className="flex items-center space-x-4">
              <span className="text-gray-400 text-sm">Hello, {user?.email}</span>
            </div>
          </header>

          {view === 'dashboard' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-8">
              <div className="lg:col-span-2 space-y-4 md:space-y-8">
                {/* System Monitoring & Analytics */}
                <div className="bg-card border border-card rounded-xl p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold">SYSTEM MONITORING & ANALYTICS</h2>
                    <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                      analytics?.system_health?.status === 'healthy' 
                        ? 'bg-green-500/20 text-green-400 border border-green-500/30' 
                        : 'bg-red-500/20 text-red-400 border border-red-500/30'
                    }`}>
                      {analytics?.system_health?.status?.toUpperCase() || 'LOADING...'}
                    </div>
                  </div>
                  
                  {analytics ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <h3 className="font-semibold text-gray-300">Memory System</h3>
                        <div className="space-y-2 text-sm text-gray-400">
                          <div className="flex justify-between">
                            <span>Total Messages:</span>
                            <span className="text-white font-medium">{analytics.memory.total_messages.toLocaleString()}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Conversations:</span>
                            <span className="text-white font-medium">{analytics.memory.total_conversations}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Archived:</span>
                            <span className="text-white font-medium">{analytics.memory.archived_count} ({analytics.memory.archival_percentage}%)</span>
                          </div>
                        </div>
                      </div>
                      
                      <div className="space-y-4">
                        <h3 className="font-semibold text-gray-300">AI System Performance</h3>
                        <div className="space-y-2 text-sm text-gray-400">
                          <div className="flex justify-between">
                            <span>Responses (7d):</span>
                            <span className="text-white font-medium">{analytics.ai_system.successful_responses_7d}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Tool Calls (7d):</span>
                            <span className="text-white font-medium">{analytics.ai_system.tool_calls_successful_7d}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Embedding Service:</span>
                            <span className={`font-medium ${analytics.ai_system.embedding_service_health ? 'text-green-400' : 'text-red-400'}`}>
                              {analytics.ai_system.embedding_service_health ? 'HEALTHY' : 'DOWN'}
                            </span>
                          </div>
                        </div>
                      </div>
                      
                      <div className="space-y-4">
                        <h3 className="font-semibold text-gray-300">Database Health</h3>
                        <div className="space-y-2 text-sm text-gray-400">
                          <div className="flex justify-between">
                            <span>Size:</span>
                            <span className="text-white font-medium">{analytics.database.size}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Connections:</span>
                            <span className="text-white font-medium">{analytics.database.connections}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Status:</span>
                            <span className={`font-medium ${analytics.database.health ? 'text-green-400' : 'text-red-400'}`}>
                              {analytics.database.health ? 'HEALTHY' : 'ERROR'}
                            </span>
                          </div>
                        </div>
                      </div>
                      
                      <div className="space-y-4">
                        <h3 className="font-semibold text-gray-300">User Activity</h3>
                        <div className="space-y-2 text-sm text-gray-400">
                          <div className="flex justify-between">
                            <span>Active Timers:</span>
                            <span className="text-white font-medium">{analytics.user_data.active_timers}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Pending Reminders:</span>
                            <span className="text-white font-medium">{analytics.user_data.active_reminders}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Last Activity:</span>
                            <span className="text-white font-medium">
                              {analytics.ai_system.last_activity 
                                ? new Date(analytics.ai_system.last_activity).toLocaleDateString()
                                : 'Never'}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center text-gray-400 py-8">
                      <div className="animate-spin inline-block w-6 h-6 border-2 border-gray-400 border-t-transparent rounded-full mb-2"></div>
                      <p>Loading analytics...</p>
                    </div>
                  )}
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-8">
                  <div className="bg-card border border-card rounded-xl p-6 text-center">
                    <h3 className="text-gray-400 font-medium">NOTES</h3>
                    <p className="text-5xl font-bold my-2">{notes.length}</p>
                    <p className="text-sm text-gray-500">notes</p>
                  </div>
                  <div className="bg-card border border-card rounded-xl p-6 text-center">
                    <h3 className="text-gray-400 font-medium">REMINDERS</h3>
                    <p className="text-5xl font-bold my-2">{reminders.length}</p>
                    <p className="text-sm text-gray-500">reminders</p>
                  </div>
                  <div className="bg-card border border-card rounded-xl p-6">
                    <h3 className="text-gray-400 font-medium mb-2">CALENDAR</h3>
                    <p className="text-white font-semibold">{currentTime.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}</p>
                    <div className="text-xs text-gray-500 mt-2">
                      <div className="text-2xl font-bold text-white">
                        {currentTime.getDate()}
                      </div>
                      <div className="text-gray-400">
                        {currentTime.toLocaleDateString('en-US', { weekday: 'long' })}
                      </div>
                    </div>
                  </div>
                  <div className="bg-card border border-card rounded-xl p-6 text-center">
                    <h3 className="text-gray-400 font-medium">TIMER</h3>
                    {timers.length > 0 ? (
                      <div>
                        <p className="text-3xl font-mono my-2 text-teal-400">
                          <LiveTimer endTime={timers[0].end_time} />
                        </p>
                        <p className="text-sm text-gray-500">{timers[0].title}</p>
                        <button
                          onClick={() => stopTimer(timers[0].id)}
                          className="mt-2 text-xs bg-red-600/20 hover:bg-red-600/30 text-red-400 px-2 py-1 rounded"
                        >
                          Stop
                        </button>
                      </div>
                    ) : (
                      <div>
                        <p className="text-3xl font-mono my-2 text-gray-500">--:--:--</p>
                        <p className="text-sm text-gray-500">no timer</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Quick Chat */}
                <div className="bg-card border border-card rounded-xl p-6">
                  <h2 className="text-lg font-semibold mb-4">QUICK CHAT</h2>
                  <form onSubmit={(e) => sendMessage(e, true)}>
                    <div className="flex">
                      <input
                        type="text"
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        placeholder="How can I assist you today?"
                        className="flex-grow bg-gray-800 border border-gray-700 rounded-l-lg p-3 focus:outline-none focus:ring-2 focus:ring-teal-500 text-white"
                        disabled={loading}
                      />
                      <button
                        type="submit"
                        disabled={loading}
                        className="bg-gray-700 text-white font-semibold px-6 rounded-r-lg hover:bg-gray-600"
                      >
                        SEND
                      </button>
                    </div>
                  </form>
                  
                  {showQuickResponse && (
                    <div className="mt-4 p-4 bg-gray-800 rounded-lg border border-gray-700">
                      <div className="flex justify-between items-start mb-2">
                        <div className="flex items-center">
                          <div className="w-6 h-6 bg-teal-600 rounded-full flex items-center justify-center text-white text-xs font-medium mr-2">
                            S
                          </div>
                          <span className="text-sm text-gray-400">Sara</span>
                        </div>
                        <button
                          onClick={() => setShowQuickResponse(false)}
                          className="text-gray-400 hover:text-white"
                        >
                          <span className="material-icons text-sm">close</span>
                        </button>
                      </div>
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        skipHtml={false}
                        components={{
                          code({node, inline, className, children, ...props}) {
                            const match = /language-(\w+)/.exec(className || '')
                            const language = match ? match[1] : ''
                            const codeContent = String(children).replace(/\n$/, '')
                            
                            // Handle Mermaid diagrams - temporarily disabled
                            if (!inline && language === 'mermaid') {
                              return (
                                <div className="my-2 p-3 bg-blue-900/20 border border-blue-500 rounded">
                                  <p className="text-blue-300 text-xs mb-1">🎨 Mermaid Diagram</p>
                                  <code className="bg-gray-600 px-1 py-0.5 rounded text-xs">{codeContent}</code>
                                </div>
                              )
                            }
                            
                            return (
                              <code className="bg-gray-600 px-1 py-0.5 rounded text-xs" {...props}>
                                {children}
                              </code>
                            )
                          },
                          p: ({children}) => <p className="text-gray-100 text-sm">{children}</p>,
                          ul: ({children}) => <ul className="list-disc list-inside text-gray-100 text-sm">{children}</ul>,
                          ol: ({children}) => <ol className="list-decimal list-inside text-gray-100 text-sm">{children}</ol>,
                          table: ({children}) => (
                            <div className="overflow-x-auto my-4">
                              <table className="w-full border-collapse border border-gray-600 bg-gray-800/50 rounded-lg">
                                {children}
                              </table>
                            </div>
                          ),
                          thead: ({children}) => <thead className="bg-gray-700/50">{children}</thead>,
                          tbody: ({children}) => <tbody>{children}</tbody>,
                          tr: ({children}) => <tr className="border-b border-gray-600 hover:bg-gray-700/30">{children}</tr>,
                          th: ({children}) => (
                            <th className="border border-gray-600 px-3 py-2 text-left font-semibold text-teal-300">
                              {children}
                            </th>
                          ),
                          td: ({children}) => (
                            <td className="border border-gray-600 px-3 py-2 text-gray-300">
                              {children}
                            </td>
                          ),
                        }}
                      >
                        {quickChatResponse}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Sidebar */}
              <div className="lg:col-span-1 space-y-4 md:space-y-8">
                {/* Active Items */}
                <div className="bg-card border border-card rounded-xl p-6">
                  <h2 className="text-lg font-semibold mb-4">ACTIVE TIMERS</h2>
                  {timers.length > 0 ? (
                    <div className="space-y-3">
                      {timers.map((timer) => (
                        <div key={timer.id} className="bg-gray-800 p-3 rounded-lg">
                          <div className="flex justify-between items-center">
                            <span className="font-medium">{timer.title}</span>
                            <LiveTimer 
                              endTime={timer.end_time} 
                              className="text-teal-400 font-mono text-sm"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-400 text-center py-4">No active timers</p>
                  )}
                </div>

                {/* Recent Reminders */}
                <div className="bg-card border border-card rounded-xl p-6">
                  <h2 className="text-lg font-semibold mb-4">REMINDERS</h2>
                  {reminders.length > 0 ? (
                    <div className="space-y-3">
                      {reminders.slice(0, 3).map((reminder) => (
                        <div key={reminder.id} className="bg-gray-800 p-3 rounded-lg">
                          <div className="flex justify-between items-start">
                            <div className="flex-1">
                              <div className="font-medium">{reminder.title}</div>
                              <div className="text-xs text-gray-400 mt-1">
                                {new Date(reminder.reminder_time).toLocaleDateString()}
                              </div>
                            </div>
                            <button
                              onClick={() => completeReminder(reminder.id)}
                              className="text-xs bg-green-600/20 hover:bg-green-600/30 text-green-400 px-2 py-1 rounded"
                            >
                              ✓
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-400 text-center py-4">No reminders</p>
                  )}
                </div>

                {/* Recent Notes */}
                <div className="bg-card border border-card rounded-xl p-6">
                  <h2 className="text-lg font-semibold mb-4">RECENT NOTES</h2>
                  {notes.slice(0, 3).length > 0 ? (
                    <div className="space-y-3">
                      {notes.slice(0, 3).map((note) => (
                        <div key={note.id} className="bg-gray-800 p-3 rounded-lg">
                          <p className="text-sm text-gray-300 font-medium">
                            {note.title || 'Untitled Note'}
                          </p>
                          <div className="text-xs text-gray-500 mt-1">
                            {new Date(note.created_at).toLocaleDateString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-400 text-center py-4">No notes yet</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {view === 'chat' && (
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
          )}

          {view === 'notes' && (
            <SimplifiedNotes
              notes={notes}
              setNotes={setNotes}
              editingNote={editingNote}
              setEditingNote={setEditingNote}
              editNoteContent={editNoteContent}
              setEditNoteContent={setEditNoteContent}
              editNoteTitle={editNoteTitle}
              setEditNoteTitle={setEditNoteTitle}
            />
          )}

          {view === 'memory-garden' && (
            <MemoryGarden
              notes={notes}
              setNotes={setNotes}
              editingNote={editingNote}
              setEditingNote={setEditingNote}
            />
          )}

          {view === 'graph' && (
            <div className="bg-card border border-card rounded-xl p-6 h-[calc(100vh-8rem)] md:h-[calc(100vh-12rem)]">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold">KNOWLEDGE GRAPH</h2>
                <p className="text-sm text-gray-400">Interactive visualization of your knowledge network</p>
              </div>
              <div className="h-[calc(100%-3rem)]">
                <KnowledgeGraph
                  notes={notes}
                  selectedNoteId={editingNote}
                  useApiData={true}
                  onNodeClick={handleGraphNodeClick}
                />
              </div>
            </div>
          )}

          {view === 'documents' && (
            <div className="space-y-6">
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
            <div className="bg-card border border-card rounded-xl p-6">
              <h2 className="text-lg font-semibold mb-4">CALENDAR</h2>
              <p className="text-gray-400 text-center py-8">Calendar view coming soon...</p>
            </div>
          )}

          {view === 'habits' && (
            <div className="space-y-6">
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

          {view === 'vulnerability-watch' && (
            <VulnerabilityWatch onToast={showToast} />
          )}

          {view === 'insights' && (
            <InsightInbox onToast={showToast} onNavigate={setView} />
          )}

          {view === 'onboarding' && (
            <div className="max-w-4xl mx-auto">
              <GTKYTrigger
                onComplete={() => {
                  showToast('Welcome! Your profile has been created successfully.', 'success')
                  setView('dashboard')
                }}
                onSpriteStateChange={(state) => {
                  if (spriteRef.current) {
                    spriteRef.current.setState(state)
                  }
                }}
                personalityMode={spriteRef.current?.getMode() || 'companion'}
              />
            </div>
          )}

          {view === 'reflection' && (
            <div className="max-w-4xl mx-auto">
              <ReflectionTrigger
                onComplete={() => {
                  showToast('Thank you for reflecting! Your insights have been saved.', 'success')
                  setView('dashboard')
                }}
                onSpriteStateChange={(state) => {
                  if (spriteRef.current) {
                    spriteRef.current.setState(state)
                  }
                }}
              />
            </div>
          )}

          {view === 'gtky-interview' && (
            <div className="max-w-4xl mx-auto bg-gray-900 text-white p-8 rounded-lg">
              <div className="text-center mb-4">
                <h2 className="text-2xl font-bold text-white">GTKY Interview Debug</h2>
                <p className="text-gray-400">Testing if this renders...</p>
              </div>
              <GTKYInterviewTest
                onComplete={() => {
                  showToast('Welcome! Your profile has been created successfully.', 'success')
                  setView('dashboard')
                }}
                onSpriteStateChange={(state) => {
                  if (spriteRef.current) {
                    spriteRef.current.setState(state)
                  }
                }}
              />
            </div>
          )}

          {view === 'nightly-reflection' && (
            <div className="max-w-4xl mx-auto">
              <NightlyReflection
                onComplete={(insights) => {
                  showToast('Thank you for reflecting! Your insights have been saved.', 'success')
                  setView('dashboard')
                }}
                onSpriteStateChange={(state) => {
                  if (spriteRef.current) {
                    spriteRef.current.setState(state)
                  }
                }}
              />
            </div>
          )}

          {view === 'privacy-dashboard' && (
            <div className="max-w-4xl mx-auto">
              <PrivacyDashboard
                onToast={(message, type) => {
                  showToast(message, type || 'info')
                }}
              />
            </div>
          )}

          {view === 'settings' && (
            <div className="space-y-6">
              <Settings />
              
              {/* Sprite Mode Testing */}
              <div className="bg-card border border-card rounded-xl p-6">
                <h2 className="text-lg font-semibold mb-4">SPRITE PERSONALITY MODES</h2>
                <p className="text-gray-400 text-sm mb-4">Test different personality modes for Sara's sprite. Each mode has unique colors, breathing rhythms, and energy levels.</p>
                
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {[
                    { mode: 'coach', label: 'Coach', desc: 'Bright & Energetic' },
                    { mode: 'analyst', label: 'Analyst', desc: 'Focused & Sharp' },
                    { mode: 'companion', label: 'Companion', desc: 'Warm & Gentle' },
                    { mode: 'guardian', label: 'Guardian', desc: 'Calm & Steady' },
                    { mode: 'concierge', label: 'Concierge', desc: 'Practical & Efficient' },
                    { mode: 'librarian', label: 'Librarian', desc: 'Quiet & Thoughtful' }
                  ].map(({ mode, label, desc }) => (
                    <button
                      key={mode}
                      onClick={async () => {
                        try {
                          // Update backend
                          const response = await fetch(`${APP_CONFIG.apiUrl}/user/personality-mode`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'include',
                            body: JSON.stringify({ mode })
                          })
                          
                          if (response.ok) {
                            // Update frontend
                            spriteRef.current?.setMode(mode as any)
                            setCurrentSpriteMode(mode)
                            showToast(`Switched to ${label} mode`, 'success', false, true)
                            
                            // Also notify the sprite for tooltip support
                            setTimeout(() => {
                              spriteRef.current?.notify(`Now in ${label} mode: ${desc}`, {
                                showToast: false,
                                keepBadge: true,
                                importance: 'medium'
                              })
                            }, 500)
                          } else {
                            showToast('Failed to update personality mode', 'error')
                          }
                        } catch (error) {
                          console.error('Error updating personality mode:', error)
                          showToast('Failed to update personality mode', 'error')
                        }
                      }}
                      className={`p-3 rounded-lg border transition-colors text-left ${
                        currentSpriteMode === mode
                          ? 'border-teal-500 bg-teal-500/10 text-teal-300'
                          : 'border-gray-700 bg-gray-800 text-gray-300 hover:border-gray-600 hover:bg-gray-700'
                      }`}
                    >
                      <div className="font-medium">{label}</div>
                      <div className="text-xs text-gray-400 mt-1">{desc}</div>
                    </button>
                  ))}
                </div>
                
                <div className="mt-4 flex gap-2">
                  <button
                    onClick={() => spriteRef.current?.pulse('subtle')}
                    className="px-4 py-2 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30 text-sm"
                  >
                    Subtle Pulse
                  </button>
                  <button
                    onClick={() => spriteRef.current?.pulse('normal')}
                    className="px-4 py-2 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30 text-sm"
                  >
                    Normal Pulse
                  </button>
                  <button
                    onClick={() => spriteRef.current?.pulse('strong')}
                    className="px-4 py-2 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30 text-sm"
                  >
                    Strong Pulse
                  </button>
                </div>
              </div>

              {/* Activity Monitor Status */}
              <div className="bg-card border border-card rounded-xl p-6">
                <h2 className="text-lg font-semibold mb-4">ACTIVITY MONITORING</h2>
                <p className="text-gray-400 text-sm mb-4">Sara monitors your activity to provide timely autonomous assistance.</p>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="bg-gray-800 p-4 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-gray-300 font-medium">Status</span>
                      <span className={`px-2 py-1 rounded text-xs font-medium ${
                        activityState.isIdle 
                          ? 'bg-yellow-900 text-yellow-300' 
                          : 'bg-green-900 text-green-300'
                      }`}>
                        {activityState.isIdle ? 'Idle' : 'Active'}
                      </span>
                    </div>
                    <div className="text-sm text-gray-400">
                      {activityState.isIdle 
                        ? `Idle for ${getIdleMinutes()} minutes`
                        : 'Currently active'
                      }
                    </div>
                  </div>

                  <div className="bg-gray-800 p-4 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-gray-300 font-medium">Threshold</span>
                      <span className="text-xs text-gray-500 capitalize">
                        {activityState.currentThreshold.replace('Sweep', ' Sweep')}
                      </span>
                    </div>
                    <div className="text-sm text-gray-400">
                      Next: {
                        activityState.currentThreshold === 'active' ? 'Quick Sweep (30s)' :
                        activityState.currentThreshold === 'quickSweep' ? 'Standard Sweep (2min)' :
                        activityState.currentThreshold === 'standardSweep' ? 'Digest Sweep (5min)' :
                        'All triggered'
                      }
                    </div>
                  </div>

                  <div className="bg-gray-800 p-4 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-gray-300 font-medium">Last Activity</span>
                    </div>
                    <div className="text-sm text-gray-400">
                      {activityState.lastActivity.toLocaleTimeString()}
                    </div>
                  </div>

                  <div className="bg-gray-800 p-4 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-gray-300 font-medium">Mode</span>
                      <span className="text-xs text-teal-400 capitalize">
                        {currentSpriteMode}
                      </span>
                    </div>
                    <div className="text-sm text-gray-400">
                      Autonomous behavior style
                    </div>
                  </div>
                </div>

                <div className="mt-4 text-xs text-gray-500">
                  <strong>Testing Thresholds:</strong> Quick (30s), Standard (2min), Digest (5min)
                  <br />
                  <strong>Tip:</strong> Stop interacting to see autonomous notifications appear!
                </div>
              </div>

              {/* Manual Sweep Testing */}
              <div className="bg-card border border-card rounded-xl p-6">
                <h2 className="text-lg font-semibold mb-4">AUTONOMOUS SWEEP TESTING</h2>
                <p className="text-gray-400 text-sm mb-4">Manually trigger Sara's background analysis to test autonomous insights generation.</p>
                
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <button
                    onClick={async () => {
                      const mode = spriteRef.current?.getMode() || 'companion'
                      try {
                        const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/sweep/quick_sweep?personality_mode=${mode}`, {
                          method: 'POST',
                          credentials: 'include'
                        })
                        if (response.ok) {
                          const result = await response.json()
                          showToast(`Quick sweep completed: ${result.insights_stored} insights generated`, 'success')
                          if (result.insights_stored > 0) {
                            fetchAndDisplayLatestInsight('quick_sweep', mode)
                          }
                        }
                      } catch (error) {
                        showToast('Sweep failed', 'error')
                      }
                    }}
                    className="p-3 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30 transition-colors"
                  >
                    <div className="font-medium">Quick Sweep</div>
                    <div className="text-xs text-gray-400 mt-1">Fast checks & alerts</div>
                  </button>

                  <button
                    onClick={async () => {
                      const mode = spriteRef.current?.getMode() || 'companion'
                      try {
                        const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/sweep/standard_sweep?personality_mode=${mode}`, {
                          method: 'POST',
                          credentials: 'include'
                        })
                        if (response.ok) {
                          const result = await response.json()
                          showToast(`Standard sweep completed: ${result.insights_stored} insights generated`, 'success')
                          if (result.insights_stored > 0) {
                            fetchAndDisplayLatestInsight('standard_sweep', mode)
                          }
                        }
                      } catch (error) {
                        showToast('Sweep failed', 'error')
                      }
                    }}
                    className="p-3 bg-purple-600/20 text-purple-400 rounded-lg hover:bg-purple-600/30 transition-colors"
                  >
                    <div className="font-medium">Standard Sweep</div>
                    <div className="text-xs text-gray-400 mt-1">Pattern analysis</div>
                  </button>

                  <button
                    onClick={async () => {
                      const mode = spriteRef.current?.getMode() || 'companion'
                      try {
                        const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/sweep/digest_sweep?personality_mode=${mode}`, {
                          method: 'POST',
                          credentials: 'include'
                        })
                        if (response.ok) {
                          const result = await response.json()
                          showToast(`Digest sweep completed: ${result.insights_stored} insights generated`, 'success')
                          if (result.insights_stored > 0) {
                            fetchAndDisplayLatestInsight('digest_sweep', mode)
                          }
                        }
                      } catch (error) {
                        showToast('Sweep failed', 'error')
                      }
                    }}
                    className="p-3 bg-green-600/20 text-green-400 rounded-lg hover:bg-green-600/30 transition-colors"
                  >
                    <div className="font-medium">Digest Sweep</div>
                    <div className="text-xs text-gray-400 mt-1">Deep insights</div>
                  </button>
                </div>

                <div className="mt-4 text-xs text-gray-500">
                  <strong>Note:</strong> Sweeps analyze your notes, conversations, habits, and patterns to generate contextual insights. Results depend on available data.
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
      
      {/* Mobile Bottom Navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-700 z-40">
        <div className="flex justify-around py-2">
          <button
            onClick={() => { setView('dashboard'); loadNotes(); loadAnalytics(); loadTimersAndReminders(); }}
            className={`flex flex-col items-center p-2 ${view === 'dashboard' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">home</span>
            <span className="text-xs">Home</span>
          </button>
          <button
            onClick={() => setView('chat')}
            className={`flex flex-col items-center p-2 ${view === 'chat' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">chat</span>
            <span className="text-xs">Chat</span>
          </button>
          <button
            onClick={() => { setView('notes'); loadNotes(); }}
            className={`flex flex-col items-center p-2 ${view === 'notes' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">notes</span>
            <span className="text-xs">Notes</span>
          </button>
          <button
            onClick={() => { setView('memory-garden'); loadNotes(); }}
            className={`flex flex-col items-center p-2 ${view === 'memory-garden' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">psychology</span>
            <span className="text-xs">Memory</span>
          </button>
          <button
            onClick={() => setView('habits')}
            className={`flex flex-col items-center p-2 ${view === 'habits' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">track_changes</span>
            <span className="text-xs">Habits</span>
          </button>
          <button
            onClick={() => { setView('documents'); loadDocuments(); }}
            className={`flex flex-col items-center p-2 ${view === 'documents' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">description</span>
            <span className="text-xs">Docs</span>
          </button>
          <button
            onClick={() => setView('calendar')}
            className={`flex flex-col items-center p-2 ${view === 'calendar' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">calendar_today</span>
            <span className="text-xs">Calendar</span>
          </button>
          <button
            onClick={() => setView('vulnerability-watch')}
            className={`flex flex-col items-center p-2 ${view === 'vulnerability-watch' ? 'text-teal-400' : 'text-gray-400'}`}
          >
            <span className="material-icons text-lg">security</span>
            <span className="text-xs">Vulns</span>
          </button>
        </div>
      </nav>

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
      
      {/* Sara Sprite Assistant */}
      <Sprite 
        ref={spriteRef}
        onNavigate={setView}
      />
    </div>
  )
}

export default App
