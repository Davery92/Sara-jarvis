import { useState, useEffect, useRef } from 'react'
import { Mail, RefreshCw, Inbox, Star, AlertCircle, Search, ExternalLink, ArrowLeft, Send, Paperclip, MessageSquare } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface EmailAttachment {
  id: string
  filename: string
  content_type: string | null
  size: number
  is_riskninja_relevant: boolean
}

interface Email {
  id: string
  subject: string
  sender_email: string
  sender_name: string | null
  received_at: string
  body_preview: string | null
  body_text?: string | null
  body_html?: string | null
  category: string | null
  importance_score: number | null
  summary?: string | null
  is_read: boolean
  action_required: boolean
  attachments?: EmailAttachment[]
  analyzed_at?: string | null
}

interface EmailStats {
  total_emails: number
  unread_count: number
  important: number
  action_required_count: number
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface EmailWindowData {
  emailId?: string
  initialQuery?: string
}

interface EmailContentProps {
  data: EmailWindowData
  windowId: string
}

export default function EmailContent({ data, windowId }: EmailContentProps) {
  const [emails, setEmails] = useState<Email[]>([])
  const [stats, setStats] = useState<EmailStats | null>(null)
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread' | 'important'>('all')
  const [searchQuery, setSearchQuery] = useState(data.initialQuery || '')
  const [showChat, setShowChat] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const fetchEmails = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email?limit=50`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setEmails(data.emails || [])
      }
    } catch (error) {
      console.error('Failed to fetch emails:', error)
    }
  }

  const fetchStats = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/stats`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setStats(data)
      }
    } catch (error) {
      console.error('Failed to fetch email stats:', error)
    }
  }

  const fetchEmailDetail = async (emailId: string) => {
    try {
      setDetailLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/${emailId}`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setSelectedEmail(data)
        setChatMessages([])
        setShowChat(false)

        // Mark email as read if it wasn't already
        if (!data.is_read) {
          // Update local state immediately for responsive UI
          setEmails(prev => prev.map(e =>
            e.id === emailId ? { ...e, is_read: true } : e
          ))
          setStats(prev => prev ? { ...prev, unread_count: Math.max(0, prev.unread_count - 1) } : prev)

          // Mark as read on server
          fetch(`${APP_CONFIG.apiUrl}/api/email/${emailId}/mark-read`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_read: true })
          }).catch(err => console.error('Failed to mark email as read:', err))
        }
      }
    } catch (error) {
      console.error('Failed to fetch email detail:', error)
    } finally {
      setDetailLoading(false)
    }
  }

  const syncEmails = async () => {
    setSyncing(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/sync`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        setTimeout(() => {
          fetchEmails()
          fetchStats()
          setSyncing(false)
        }, 2000)
      } else {
        setSyncing(false)
      }
    } catch (error) {
      console.error('Failed to sync emails:', error)
      setSyncing(false)
    }
  }

  const sendChatMessage = async () => {
    if (!chatInput.trim() || !selectedEmail) return

    const userMessage = chatInput.trim()
    setChatInput('')
    setChatMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setChatLoading(true)

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/${selectedEmail.id}/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage })
      })

      if (response.ok) {
        const data = await response.json()
        setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }])
      }
    } catch (error) {
      console.error('Failed to send chat:', error)
      setChatMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error.' }])
    } finally {
      setChatLoading(false)
    }
  }

  const downloadAttachment = async (attachmentId: string, filename: string) => {
    if (!selectedEmail) return
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/email/${selectedEmail.id}/attachments/${attachmentId}/download`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('Failed to download attachment:', error)
    }
  }

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      await Promise.all([fetchEmails(), fetchStats()])
      setLoading(false)
    }
    load()
  }, [])

  useEffect(() => {
    if (data.initialQuery) {
      setSearchQuery(data.initialQuery)
    }
  }, [data.initialQuery])

  useEffect(() => {
    if (data.emailId) {
      fetchEmailDetail(data.emailId).catch((err) => {
        console.error('Failed to auto-open email detail:', err)
      })
    }
  }, [data.emailId])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const filteredEmails = emails.filter(email => {
    if (filter === 'unread' && email.is_read) return false
    if (filter === 'important' && (email.importance_score || 0) < 0.7) return false
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        email.subject.toLowerCase().includes(query) ||
        email.sender_email.toLowerCase().includes(query) ||
        (email.sender_name && email.sender_name.toLowerCase().includes(query))
      )
    }
    return true
  })

  const getCategoryColor = (category: string | null) => {
    switch (category) {
      case 'urgent': return 'bg-red-500/20 text-red-400'
      case 'support': return 'bg-orange-500/20 text-orange-400'
      case 'internal': return 'bg-blue-500/20 text-blue-400'
      case 'financial': return 'bg-green-500/20 text-green-400'
      default: return 'bg-gray-500/20 text-gray-400'
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))
    if (days === 0) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (days === 1) return 'Yesterday'
    if (days < 7) return date.toLocaleDateString([], { weekday: 'short' })
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-teal-500"></div>
      </div>
    )
  }

  // Detail view
  if (selectedEmail) {
    return (
      <div className="flex flex-col h-full bg-canvas-base">
        {/* Detail Header */}
        <div className="flex items-center gap-3 p-3 border-b border-canvas-border">
          <button
            onClick={() => setSelectedEmail(null)}
            className="p-1.5 hover:bg-canvas-surface rounded-lg text-canvas-muted hover:text-white"
          >
            <ArrowLeft size={18} />
          </button>
          <div className="flex-1 min-w-0">
            <h2 className="font-medium text-white truncate">{selectedEmail.subject}</h2>
            <p className="text-xs text-canvas-muted truncate">
              {selectedEmail.sender_name || selectedEmail.sender_email}
            </p>
          </div>
          <button
            onClick={() => setShowChat(!showChat)}
            className={`p-2 rounded-lg transition-colors ${showChat ? 'bg-teal-500 text-white' : 'hover:bg-canvas-surface text-canvas-muted hover:text-white'}`}
            title="Chat with Sara about this email"
          >
            <MessageSquare size={18} />
          </button>
        </div>

        {detailLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-teal-500"></div>
          </div>
        ) : (
          <div className="flex-1 flex overflow-hidden">
            {/* Email Content */}
            <div className={`flex-1 flex flex-col overflow-hidden ${showChat ? 'border-r border-canvas-border' : ''}`}>
              {/* Sara's Analysis */}
              {selectedEmail.analyzed_at && (
                <div className="p-3 bg-canvas-elevated border-b border-canvas-border">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-teal-400 text-xs font-medium">Sara's Analysis</span>
                    {selectedEmail.category && (
                      <span className={`px-2 py-0.5 rounded text-xs ${getCategoryColor(selectedEmail.category)}`}>
                        {selectedEmail.category}
                      </span>
                    )}
                    {selectedEmail.importance_score != null && (
                      <span className="text-xs text-canvas-muted">
                        {Math.round(selectedEmail.importance_score * 100)}% importance
                      </span>
                    )}
                  </div>
                  {selectedEmail.summary && (
                    <p className="text-sm text-gray-300">{selectedEmail.summary}</p>
                  )}
                </div>
              )}

              {/* Attachments */}
              {selectedEmail.attachments && selectedEmail.attachments.length > 0 && (
                <div className="p-3 border-b border-canvas-border">
                  <div className="flex items-center gap-2 mb-2 text-xs text-canvas-muted">
                    <Paperclip size={14} />
                    {selectedEmail.attachments.length} attachment{selectedEmail.attachments.length > 1 ? 's' : ''}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedEmail.attachments.map(att => (
                      <button
                        key={att.id}
                        onClick={() => downloadAttachment(att.id, att.filename)}
                        className={`flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                          att.is_riskninja_relevant
                            ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                            : 'bg-canvas-surface text-gray-300 hover:bg-canvas-elevated'
                        }`}
                      >
                        <Paperclip size={12} />
                        <span className="truncate max-w-[150px]">{att.filename}</span>
                        <span className="text-canvas-muted">{formatFileSize(att.size)}</span>
                        {att.is_riskninja_relevant && <span className="text-green-400">RN</span>}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-3">
                {selectedEmail.body_html ? (
                  <div
                    className="prose prose-invert prose-sm max-w-none"
                    dangerouslySetInnerHTML={{ __html: selectedEmail.body_html }}
                  />
                ) : (
                  <pre className="text-sm text-gray-300 whitespace-pre-wrap font-sans">
                    {selectedEmail.body_text || selectedEmail.body_preview}
                  </pre>
                )}
              </div>
            </div>

            {/* Chat Panel */}
            {showChat && (
              <div className="w-64 flex flex-col bg-canvas-elevated">
                <div className="p-2 border-b border-canvas-border">
                  <h3 className="text-sm font-medium text-teal-400">Ask Sara</h3>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                  {chatMessages.length === 0 ? (
                    <div className="text-xs text-canvas-muted space-y-1">
                      <p>Quick actions:</p>
                      {['Summarize this', 'Draft a reply', 'Is this urgent?'].map(q => (
                        <button
                          key={q}
                          onClick={() => setChatInput(q)}
                          className="block w-full text-left px-2 py-1 bg-canvas-surface rounded text-gray-300 hover:bg-canvas-base text-xs"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  ) : (
                    chatMessages.map((msg, i) => (
                      <div
                        key={i}
                        className={`text-xs p-2 rounded ${
                          msg.role === 'user' ? 'bg-teal-500/20 ml-4' : 'bg-canvas-surface mr-4'
                        }`}
                      >
                        <div className="text-[10px] text-canvas-muted mb-0.5">
                          {msg.role === 'user' ? 'You' : 'Sara'}
                        </div>
                        <div className="text-gray-200 whitespace-pre-wrap">{msg.content}</div>
                      </div>
                    ))
                  )}
                  {chatLoading && (
                    <div className="text-xs text-canvas-muted">Sara is thinking...</div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                <div className="p-2 border-t border-canvas-border">
                  <div className="flex gap-1">
                    <input
                      type="text"
                      value={chatInput}
                      onChange={e => setChatInput(e.target.value)}
                      onKeyPress={e => e.key === 'Enter' && sendChatMessage()}
                      placeholder="Ask about this email..."
                      className="flex-1 bg-canvas-surface border border-canvas-border rounded px-2 py-1 text-xs text-white placeholder-canvas-muted focus:outline-none focus:ring-1 focus:ring-teal-500"
                    />
                    <button
                      onClick={sendChatMessage}
                      disabled={!chatInput.trim() || chatLoading}
                      className="p-1.5 bg-teal-600 text-white rounded hover:bg-teal-700 disabled:opacity-50"
                    >
                      <Send size={14} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  // List view
  return (
    <div className="flex flex-col h-full bg-canvas-base">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-canvas-border">
        <div className="flex items-center gap-3">
          <Mail className="text-teal-400" size={20} />
          <h2 className="font-medium text-white">Email</h2>
          {stats && (
            <span className="text-xs text-canvas-muted">
              {stats.unread_count} unread
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={syncEmails}
            disabled={syncing}
            className="p-2 hover:bg-canvas-surface rounded-lg text-canvas-muted hover:text-white transition-colors disabled:opacity-50"
            title="Sync emails"
          >
            <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="flex gap-4 p-3 border-b border-canvas-border text-xs">
          <div className="flex items-center gap-1.5">
            <Inbox size={14} className="text-blue-400" />
            <span className="text-canvas-muted">{stats.total_emails} total</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Mail size={14} className="text-teal-400" />
            <span className="text-canvas-muted">{stats.unread_count} unread</span>
          </div>
          <div className="flex items-center gap-1.5">
            <AlertCircle size={14} className="text-red-400" />
            <span className="text-canvas-muted">{stats.action_required_count} action</span>
          </div>
        </div>
      )}

      {/* Search & Filters */}
      <div className="flex items-center gap-2 p-3 border-b border-canvas-border">
        <div className="flex-1 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-canvas-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search emails..."
            className="w-full bg-canvas-surface border border-canvas-border rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-canvas-muted focus:outline-none focus:ring-1 focus:ring-teal-500"
          />
        </div>
        <div className="flex gap-1">
          {(['all', 'unread', 'important'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${
                filter === f
                  ? 'bg-teal-500 text-white'
                  : 'bg-canvas-surface text-canvas-muted hover:text-white'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Email List */}
      <div className="flex-1 overflow-y-auto">
        {filteredEmails.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-canvas-muted">
            <Mail size={32} className="mb-2 opacity-50" />
            <p className="text-sm">No emails found</p>
            <button
              onClick={syncEmails}
              className="mt-2 text-xs text-teal-400 hover:underline"
            >
              Sync now
            </button>
          </div>
        ) : (
          <div className="divide-y divide-canvas-border">
            {filteredEmails.map((email) => (
              <button
                key={email.id}
                onClick={() => fetchEmailDetail(email.id)}
                className={`w-full text-left p-3 hover:bg-canvas-surface transition-colors ${
                  !email.is_read ? 'bg-canvas-elevated/30' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {!email.is_read && (
                        <div className="w-2 h-2 rounded-full bg-teal-500 flex-shrink-0" />
                      )}
                      <span className={`text-sm truncate ${!email.is_read ? 'font-medium text-white' : 'text-canvas-muted'}`}>
                        {email.sender_name || email.sender_email}
                      </span>
                      {email.category && (
                        <span className={`text-xs px-1.5 py-0.5 rounded ${getCategoryColor(email.category)}`}>
                          {email.category}
                        </span>
                      )}
                      {email.action_required && (
                        <AlertCircle size={12} className="text-red-400 flex-shrink-0" />
                      )}
                    </div>
                    <div className={`text-sm truncate ${!email.is_read ? 'text-white' : 'text-gray-300'}`}>
                      {email.subject}
                    </div>
                    <div className="text-xs text-canvas-muted truncate mt-0.5">
                      {email.summary || email.body_preview}
                    </div>
                  </div>
                  <span className="text-xs text-canvas-muted flex-shrink-0">
                    {formatDate(email.received_at)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
