import React, { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { APP_CONFIG } from './config'
import MermaidDiagram from './components/MermaidDiagram'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [user, setUser] = useState(null)
  const [view, setView] = useState('login') // login, dashboard, chat, notes, documents, calendar, settings
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
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploading, setUploading] = useState(false)

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
      
      // Increment timer tick to force re-render of timer displays
      setTimerTick(prev => prev + 1)
      
      // Check for timer completions globally (to avoid duplicates)
      timers.forEach(timer => {
        const endTime = new Date(timer.end_time)
        if (endTime <= now && timer.is_active && !finishedTimers.has(timer.id)) {
          setFinishedTimers(prev => new Set([...prev, timer.id]))
          showToast(`🔔 Timer finished: ${timer.title}`, 'success', true)
          // Automatically stop the timer on the backend
          stopTimer(timer.id)
        }
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [timers, finishedTimers, currentTime])

  // Load timers and reminders periodically when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      loadTimersAndReminders()
      const interval = setInterval(loadTimersAndReminders, 30000)
      return () => clearInterval(interval)
    }
  }, [isAuthenticated])

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
            showToast(`🔔 Reminder: ${reminder.title}`, 'info')
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
    if (!message.trim()) return

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

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          messages: [...chatMessages, userMessage].map(m => ({ role: m.role, content: m.content }))
        })
      })

      if (response.ok) {
        const data = await response.json()
        console.log('🔍 Frontend received response:', data)
        console.log('🔍 Message content:', data.message?.content)
        console.log('🔍 Message content length:', data.message?.content?.length)
        
        // DEBUGGING: Alert to see what we got
        if (data.message?.content) {
          console.log('✅ RESPONSE RECEIVED:', data.message.content)
        } else {
          console.log('❌ NO CONTENT IN RESPONSE:', data)
          alert('NO CONTENT: ' + JSON.stringify(data))
        }
        
        if (isQuickChat) {
          setQuickChatResponse(data.message.content)
        } else {
          setChatMessages(prev => [...prev, {
            role: 'assistant',
            content: data.message.content,
            timestamp: new Date()
          }])
        }
        // Refresh timers/reminders after chat in case something was created
        await loadTimersAndReminders()
      } else {
        const errorMsg = 'Sorry, I encountered an error. Please try again.'
        if (isQuickChat) {
          setQuickChatResponse(errorMsg)
        } else {
          setChatMessages(prev => [...prev, {
            role: 'assistant',
            content: errorMsg,
            timestamp: new Date()
          }])
        }
      }
    } catch (error) {
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
    }
    setLoading(false)
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
                  onClick={() => { setView('dashboard'); loadNotes(); setIsMobileMenuOpen(false); }}
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
              onClick={() => { setView('dashboard'); loadNotes(); }}
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
                {/* Project Charter */}
                <div className="bg-card border border-card rounded-xl p-6">
                  <h2 className="text-lg font-semibold mb-4">PERSONAL AI HUB</h2>
                  <h3 className="font-semibold mb-2">Capabilities:</h3>
                  <p className="text-gray-400 mb-4">Your intelligent personal assistant that can:</p>
                  <ul className="space-y-2 text-gray-400 list-disc list-inside">
                    <li>capture & browse notes with AI-powered search</li>
                    <li>create reminders, timers, and calendar events</li>
                    <li>chat with AI that remembers your preferences</li>
                    <li>upload and search through documents</li>
                    <li>learn from every conversation to assist you better</li>
                    <li>provide contextual help based on your data</li>
                  </ul>
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
                          {formatTimeLeft(timers[0].end_time)}
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
                            <span className="text-teal-400 font-mono text-sm">
                              {formatTimeLeft(timer.end_time)}
                            </span>
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
            <div className="flex flex-col h-[calc(100vh-8rem)] md:h-[calc(100vh-12rem)]">
              <div className="bg-card border border-card rounded-t-xl p-4 md:p-6 border-b-0">
                <div className="flex justify-between items-center">
                  <h2 className="text-lg font-semibold">CHAT WITH SARA</h2>
                  <button
                    onClick={clearChat}
                    className="text-gray-400 hover:text-white flex items-center space-x-2"
                  >
                    <span className="material-icons text-sm">refresh</span>
                    <span className="text-sm">Clear Chat</span>
                  </button>
                </div>
              </div>
              
              <div className="flex-1 bg-card border border-card border-t-0 border-b-0 overflow-hidden">
                <div className="h-full p-4 md:p-6 overflow-y-auto space-y-4">
                  {chatMessages.map((msg, index) => {
                    console.log(`🔍 Rendering message ${index}:`, msg.role, msg.content?.length || 0, 'chars')
                    return (
                      <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[85%] md:max-w-[80%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                        {msg.role === 'assistant' && (
                          <div className="flex items-center mb-2">
                            <div className="w-8 h-8 bg-teal-600 rounded-full flex items-center justify-center text-white text-sm font-medium mr-2">
                              S
                            </div>
                            <span className="text-sm text-gray-400">Sara</span>
                          </div>
                        )}
                        
                        <div className={`rounded-lg px-4 py-3 ${
                          msg.role === 'user' 
                            ? 'bg-teal-600 text-white ml-auto' 
                            : 'bg-gray-700 text-gray-100'
                        }`}>
                          {msg.role === 'assistant' ? (
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                code({node, inline, className, children, ...props}) {
                                  const match = /language-(\w+)/.exec(className || '')
                                  const language = match ? match[1] : ''
                                  const codeContent = String(children).replace(/\n$/, '')
                                  
                                  console.log('🔍 CODE BLOCK DETECTED:', { inline, className, language, contentPreview: codeContent.substring(0, 50) + '...' })
                                  
                                  // Handle Mermaid diagrams
                                  if (!inline && language === 'mermaid') {
                                    console.log('🎯 MERMAID DETECTED! Language:', language, 'Content:', codeContent.substring(0, 100) + '...')
                                    return (
                                      <MermaidDiagram 
                                        chart={codeContent} 
                                        id={`mermaid-${Date.now()}-${Math.random()}`} 
                                      />
                                    )
                                  }
                                  
                                  // Handle regular code blocks
                                  return !inline && match ? (
                                    <SyntaxHighlighter
                                      style={oneDark}
                                      language={language}
                                      PreTag="div"
                                      className="rounded-md mt-2"
                                      {...props}
                                    >
                                      {codeContent}
                                    </SyntaxHighlighter>
                                  ) : (
                                    <code className="bg-gray-600 px-1 py-0.5 rounded text-sm" {...props}>
                                      {children}
                                    </code>
                                  )
                                },
                                p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
                                ul: ({children}) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                                ol: ({children}) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                                blockquote: ({children}) => (
                                  <blockquote className="border-l-4 border-gray-500 pl-4 italic my-2">
                                    {children}
                                  </blockquote>
                                ),
                                h1: ({children}) => <h1 className="text-xl font-bold mb-2">{children}</h1>,
                                h2: ({children}) => <h2 className="text-lg font-bold mb-2">{children}</h2>,
                                h3: ({children}) => <h3 className="text-md font-bold mb-2">{children}</h3>,
                                // Style citations and references
                                hr: () => <hr className="border-gray-600 my-4" />,
                                a: ({href, children}) => {
                                  // Style citation links differently
                                  if (href && href.startsWith('#')) {
                                    return (
                                      <span className="inline-block px-1.5 py-0.5 text-xs bg-teal-600/20 border border-teal-500/30 rounded text-teal-400 hover:bg-teal-600/30 cursor-pointer transition-colors">
                                        {children}
                                      </span>
                                    )
                                  }
                                  return (
                                    <a href={href} className="text-teal-400 hover:text-teal-300 underline" target="_blank" rel="noopener noreferrer">
                                      {children}
                                    </a>
                                  )
                                },
                              }}
                            >
                              {msg.content}
                            </ReactMarkdown>
                          ) : (
                            <p>{msg.content}</p>
                          )}
                        </div>
                        
                        <div className={`text-xs text-gray-500 mt-1 ${
                          msg.role === 'user' ? 'text-right' : 'text-left'
                        }`}>
                          {msg.timestamp.toLocaleTimeString()}
                        </div>
                        </div>
                      </div>
                    )
                  })}
                  {loading && (
                    <div className="flex justify-start">
                      <div className="max-w-[80%]">
                        <div className="flex items-center mb-2">
                          <div className="w-8 h-8 bg-teal-600 rounded-full flex items-center justify-center text-white text-sm font-medium mr-2">
                            S
                          </div>
                          <span className="text-sm text-gray-400">Sara</span>
                        </div>
                        <div className="bg-gray-700 rounded-lg px-4 py-3">
                          <div className="flex space-x-1">
                            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.1s'}}></div>
                            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.2s'}}></div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              
              <div className="bg-card border border-card rounded-b-xl border-t-0">
                <form onSubmit={sendMessage} className="p-4 md:p-6">
                  <div className="flex space-x-2 md:space-x-4">
                    <input
                      type="text"
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      placeholder={APP_CONFIG.ui.chatPlaceholder}
                      className="flex-1 bg-gray-800 border border-gray-600 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-teal-500 text-white"
                      disabled={loading}
                    />
                    <button 
                      type="submit" 
                      disabled={loading || !message.trim()}
                      className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium px-6 rounded-lg transition-colors"
                    >
                      <span className="material-icons">send</span>
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {view === 'notes' && (
            <div className="h-[calc(100vh-12rem)] md:h-[calc(100vh-12rem)] bg-gray-900 text-white rounded-xl overflow-hidden relative">
              
              {/* Mobile Notes Header */}
              <div className="md:hidden bg-gray-800 p-4 border-b border-gray-700 flex justify-between items-center">
                <h2 className="text-lg font-semibold">📝 Notes</h2>
                <button 
                  onClick={() => setIsMobileNotesSidebarOpen(!isMobileNotesSidebarOpen)}
                  className="p-2 text-gray-400 hover:text-white"
                >
                  <span className="text-xl">{isMobileNotesSidebarOpen ? '✕' : '☰'}</span>
                </button>
              </div>

              <div className="flex h-full md:h-auto">
                {/* Desktop Sidebar - always visible */}
                <div className="hidden md:flex w-80 bg-gray-800 border-r border-gray-700 flex-col">
                {/* Header */}
                <div className="p-4 border-b border-gray-700">
                  <h2 className="text-lg font-semibold mb-3">📝 Notes - Obsidian Style</h2>
                  
                  {/* Search */}
                  <div className="relative mb-3">
                    <span className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400">🔍</span>
                    <input
                      type="text"
                      placeholder="Search notes..."
                      className="w-full pl-10 pr-4 py-2 bg-gray-700 border border-gray-600 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  {/* Action buttons */}
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        const name = prompt('Folder name:')
                        if (name) console.log('Create folder:', name)
                      }}
                      className="flex items-center px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm"
                    >
                      📁 Folder
                    </button>
                    <button
                      onClick={async () => {
                        const title = prompt('Note title:')
                        if (title) {
                          try {
                            const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              credentials: 'include',
                              body: JSON.stringify({ title: title, content: '' })
                            })
                            if (response.ok) {
                              const note = await response.json()
                              setNotes(prev => [note, ...prev])
                              setEditingNote(note.id)
                              setEditNoteTitle(note.title || '')
                              setEditNoteContent(note.content || '')
                            }
                          } catch (error) {
                            console.error('Failed to create note:', error)
                          }
                        }
                      }}
                      className="flex items-center px-3 py-1.5 bg-green-600 hover:bg-green-700 rounded text-sm"
                    >
                      ➕ Note
                    </button>
                  </div>
                </div>

                  {/* Tree */}
                  <div className="flex-1 overflow-y-auto p-2">
                    {notes.length === 0 ? (
                      <div className="text-center text-gray-400 mt-8">
                        <div className="text-4xl mb-2 opacity-50">📝</div>
                        <p>No notes yet</p>
                        <p className="text-xs">Create your first note or folder</p>
                      </div>
                    ) : (
                      <div className="space-y-1">
                        {notes.map(note => (
                          <div 
                            key={note.id}
                            className="flex items-center py-1 px-2 hover:bg-gray-700 cursor-pointer rounded"
                            onClick={() => {
                              setEditingNote(note.id)
                              setEditNoteTitle(note.title || '')
                              setEditNoteContent(note.content)
                            }}
                          >
                            <div className="w-4 h-4 mr-1" />
                            <span className="text-green-400 mr-2">📄</span>
                            <span className="text-sm text-gray-200 truncate">
                              {note.title || note.content.substring(0, 30) + '...' || 'Untitled'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Mobile Sidebar - overlay */}
                {isMobileNotesSidebarOpen && (
                  <div className="md:hidden absolute inset-0 bg-black bg-opacity-50 z-10" onClick={() => setIsMobileNotesSidebarOpen(false)}>
                    <div className="bg-gray-800 w-64 h-full border-r border-gray-700 flex flex-col" onClick={e => e.stopPropagation()}>
                      {/* Header */}
                      <div className="p-4 border-b border-gray-700">
                        <div className="flex justify-between items-center mb-3">
                          <h2 className="text-lg font-semibold">📝 Notes</h2>
                          <button onClick={() => setIsMobileNotesSidebarOpen(false)} className="text-gray-400">✕</button>
                        </div>
                        
                        {/* Search */}
                        <div className="relative mb-3">
                          <span className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400">🔍</span>
                          <input
                            type="text"
                            placeholder="Search notes..."
                            className="w-full pl-10 pr-4 py-2 bg-gray-700 border border-gray-600 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        {/* Action buttons */}
                        <div className="flex gap-2">
                          <button
                            onClick={() => {
                              const name = prompt('Folder name:')
                              if (name) console.log('Create folder:', name)
                            }}
                            className="flex items-center px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm"
                          >
                            📁 Folder
                          </button>
                          <button
                            onClick={async () => {
                              const title = prompt('Note title:')
                              if (title) {
                                try {
                                  const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    credentials: 'include',
                                    body: JSON.stringify({ title: title, content: '' })
                                  })
                                  if (response.ok) {
                                    const note = await response.json()
                                    setNotes(prev => [note, ...prev])
                                    setEditingNote(note.id)
                                    setEditNoteTitle(note.title || '')
                                    setEditNoteContent(note.content || '')
                                    setIsMobileNotesSidebarOpen(false)
                                  }
                                } catch (error) {
                                  console.error('Failed to create note:', error)
                                }
                              }
                            }}
                            className="flex items-center px-3 py-1.5 bg-green-600 hover:bg-green-700 rounded text-sm"
                          >
                            ➕ Note
                          </button>
                        </div>
                      </div>

                      {/* Tree */}
                      <div className="flex-1 overflow-y-auto p-2">
                        {notes.length === 0 ? (
                          <div className="text-center text-gray-400 mt-8">
                            <div className="text-4xl mb-2 opacity-50">📝</div>
                            <p>No notes yet</p>
                            <p className="text-xs">Create your first note or folder</p>
                          </div>
                        ) : (
                          <div className="space-y-1">
                            {notes.map(note => (
                              <div 
                                key={note.id}
                                className="flex items-center py-1 px-2 hover:bg-gray-700 cursor-pointer rounded"
                                onClick={() => {
                                  setEditingNote(note.id)
                                  setEditNoteTitle(note.title || '')
                                  setEditNoteContent(note.content)
                                  setIsMobileNotesSidebarOpen(false)
                                }}
                              >
                                <div className="w-4 h-4 mr-1" />
                                <span className="text-green-400 mr-2">📄</span>
                                <span className="text-sm text-gray-200 truncate">
                                  {note.title || note.content.substring(0, 30) + '...' || 'Untitled'}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

              {/* Main content */}
              <div className="flex-1 flex flex-col">
                {editingNote ? (
                  <>
                    {/* Note header */}
                    <div className="p-4 border-b border-gray-700 bg-gray-800">
                      <input
                        type="text"
                        value={editNoteTitle}
                        onChange={(e) => setEditNoteTitle(e.target.value)}
                        placeholder="Note title..."
                        className="text-xl font-semibold bg-transparent border-none focus:outline-none text-white placeholder-gray-400 w-full"
                      />
                      <div className="flex space-x-2 mt-2">
                        <button
                          onClick={() => {
                            const note = notes.find(n => n.id === editingNote)
                            if (note) updateNote(note.id)
                          }}
                          disabled={loading}
                          className="bg-teal-600 hover:bg-teal-700 text-white text-sm px-3 py-1 rounded transition-colors"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => {
                            const note = notes.find(n => n.id === editingNote)
                            if (note && confirm('Delete this note?')) deleteNote(note.id)
                          }}
                          className="bg-red-600 hover:bg-red-700 text-white text-sm px-3 py-1 rounded transition-colors"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setEditingNote(null)}
                          className="bg-gray-600 hover:bg-gray-700 text-white text-sm px-3 py-1 rounded transition-colors"
                        >
                          Close
                        </button>
                      </div>
                    </div>

                    {/* Note content */}
                    <div className="flex-1 p-4">
                      <textarea
                        value={editNoteContent}
                        onChange={(e) => setEditNoteContent(e.target.value)}
                        className="w-full h-full bg-gray-800 border border-gray-600 rounded-lg p-4 text-gray-200 resize-none focus:outline-none focus:ring-2 focus:ring-teal-500"
                        placeholder="Start writing your note..."
                      />
                    </div>
                  </>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-gray-400">
                    <div className="text-center">
                      <div className="text-6xl mb-4 opacity-50">📄</div>
                      <h3 className="text-lg font-medium mb-2">Select a note to view</h3>
                      <p className="text-sm">Choose a note from the sidebar or create a new one</p>
                    </div>
                  </div>
                )}
              </div>
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
                              <p className="text-white font-medium">{doc.original_filename}</p>
                              <div className="flex items-center space-x-4 text-sm text-gray-400">
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

          {view === 'settings' && (
            <div className="bg-card border border-card rounded-xl p-6">
              <h2 className="text-lg font-semibold mb-4">SETTINGS</h2>
              <p className="text-gray-400 text-center py-8">Settings panel coming soon...</p>
            </div>
          )}
        </main>
      </div>
      
      {/* Mobile Bottom Navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-700 z-40">
        <div className="flex justify-around py-2">
          <button
            onClick={() => { setView('dashboard'); loadNotes(); }}
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
    </div>
  )
}

export default App