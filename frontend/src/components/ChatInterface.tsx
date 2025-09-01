import React, { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { APP_CONFIG } from '../config'
import { spriteBus } from '../state/spriteBus'
import { apiClient } from '../api/client'
import type { Document } from '../api/client'
import MermaidDiagram from './MermaidDiagram'

interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  user_id: string
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  citations?: any[]
  attachedDocuments?: Document[]
}

interface ChatInterfaceProps {
  messages: ChatMessage[]
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  loading: boolean
  onSendMessage: ((e: React.FormEvent, isQuickChat?: boolean) => Promise<void>) | null
  onClearChat: () => void
  message: string
  setMessage: React.Dispatch<React.SetStateAction<string>>
  abortControllerRef: React.MutableRefObject<AbortController | null>
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({
  messages,
  setMessages,
  loading,
  onSendMessage,
  onClearChat,
  message,
  setMessage,
  abortControllerRef
}) => {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [loadingConversations, setLoadingConversations] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [toolActivity, setToolActivity] = useState('')
  const [isUsingTools, setIsUsingTools] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [uploadedDocuments, setUploadedDocuments] = useState<Document[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatMessagesEndRef = useRef<HTMLDivElement>(null)

  // Check if mobile on mount and window resize
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768)
      // Auto-collapse sidebar on mobile
      if (window.innerWidth < 768) {
        setSidebarCollapsed(true)
      }
    }
    
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  // Load conversations on component mount
  useEffect(() => {
    loadConversations()
  }, [])

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (chatMessagesEndRef.current) {
      setTimeout(() => {
        chatMessagesEndRef.current?.scrollIntoView({ 
          behavior: 'smooth',
          block: 'end',
          inline: 'nearest'
        })
      }, 100)
    }
  }, [messages, loading])

  // Handle document upload for chat context
  const handleDocumentUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const file = files[0]
    setIsUploading(true)

    try {
      // Upload document with chat_context=true
      const uploadedDoc = await apiClient.uploadDocument(file, true)
      
      // Add to uploaded documents list
      setUploadedDocuments(prev => [...prev, uploadedDoc])
      
      console.log('Document uploaded for chat:', uploadedDoc)
    } catch (error) {
      console.error('Error uploading document:', error)
      // Could add toast notification here
    } finally {
      setIsUploading(false)
      // Reset the input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // Remove uploaded document
  const removeUploadedDocument = (docId: string) => {
    setUploadedDocuments(prev => prev.filter(doc => doc.id !== docId))
  }

  // Enhanced send message with tool activity tracking
  const handleSendMessage = async (e: React.FormEvent, isQuickChat = false) => {
    e.preventDefault()
    if ((!message.trim() && uploadedDocuments.length === 0) || loading) return
    
    // If parent provided onSendMessage, use it
    if (onSendMessage) {
      return await onSendMessage(e, isQuickChat)
    }
    
    // Otherwise, handle message sending internally with proper conversation management
    // Cancel any existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    
    // Create new abort controller for this request
    abortControllerRef.current = new AbortController()

    // Create user message with attached documents
    const userMessage = { 
      role: 'user' as const, 
      content: message, 
      timestamp: new Date(),
      attachedDocuments: uploadedDocuments.length > 0 ? [...uploadedDocuments] : undefined
    }
    setMessages(prev => [...prev, userMessage])
    setMessage('')
    
    // Clear uploaded documents after sending
    setUploadedDocuments([])
    setIsLoading(true)
    // Sprite: indicate listening state when sending
    spriteBus.setBase('listening', 'chatInterface:send')
    spriteBus.setTone('focused', 'chatInterface:send')
    setIsUsingTools(false)
    setToolActivity('')
    
    // State for streaming
    let streamingContent = ''
    let firstStreamChunk = true
    
    try {
      const saveTrace = async (content: string, role: 'user' | 'assistant') => {
        try {
          if (!content || content.trim().length === 0) return
          await fetch(`${APP_CONFIG.apiUrl}/memory/trace`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ content, role, heads: ['semantic'] })
          })
        } catch (err) {
          // Non-fatal: memory trace save is best-effort
          console.warn('Failed to save memory trace:', err)
        }
      }

      // Best-effort save of user's message to memory
      saveTrace(userMessage.content, 'user')
      const response = await fetch(`${APP_CONFIG.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          messages: [...messages, userMessage].map(m => {
            let messageContent = m.content
            
            // If this message has attached documents, prepend their content
            if (m.attachedDocuments && m.attachedDocuments.length > 0) {
              const documentContext = m.attachedDocuments
                .map(doc => `[Document: ${doc.title || doc.original_filename}]\n${doc.content_text || 'Content could not be extracted'}\n[End of ${doc.title || doc.original_filename}]`)
                .join('\n\n')
              messageContent = `${documentContext}\n\n${m.content}`
            }
            
            return { role: m.role, content: messageContent }
          }),
          conversation_id: currentConversationId
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
                
                switch (eventData.type) {
                  case 'tool_calls_start':
                    console.log('🔧 TOOL_CALLS_START event received:', eventData)
                    setIsUsingTools(true)
                    setToolActivity(`🔧 Using Tools (Round ${eventData.data.round})`)
                    spriteBus.setBase('listening', 'chatInterface:tools_start')
                    spriteBus.setTone('focused', 'chatInterface:tools_start')
                    break
                    
                  case 'tool_executing':
                    console.log('🔧 TOOL_EXECUTING event received:', eventData)
                    setToolActivity(`🔧 Using ${eventData.data.tool}...`)
                    spriteBus.setBase('thinking', 'chatInterface:tool_executing')
                    spriteBus.setTone('focused', 'chatInterface:tool_executing')
                    spriteBus.setVisuals({ energyScale: 1.02 }, 'chatInterface:tool_executing')
                    break
                    
                  case 'thinking':
                    console.log('💭 THINKING event received:', eventData)
                    setIsUsingTools(true)
                    setToolActivity('💭 Processing results...')
                    spriteBus.setBase('thinking', 'chatInterface:thinking')
                    spriteBus.setTone('focused', 'chatInterface:thinking')
                    spriteBus.setVisuals({ energyScale: 1.015 }, 'chatInterface:thinking')
                    break
                    
                  case 'text_chunk':
                    streamingContent = eventData.data.full_content
                    setIsUsingTools(false)
                    setToolActivity('')
                    if (firstStreamChunk) {
                      spriteBus.setVisuals({ energyScale: 1.04, tempoBreatheSec: 3.2 }, 'chatInterface:first_chunk')
                      firstStreamChunk = false
                    }
                    spriteBus.setOverlay('speaking', { source: 'chatInterface:text_chunk', autoClearMs: 900 })
                    spriteBus.setTone('playful', 'chatInterface:text_chunk')
                    // Update the last message with streaming content
                    setMessages(prev => {
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
                    break
                    
                  case 'final_response':
                    const finalContent = eventData.data.content
                    const finalCitations = eventData.data.citations || []
                    const responseConversationId = eventData.data.conversation_id
                    
                    // Update conversation ID if we got one back
                    if (responseConversationId && responseConversationId !== currentConversationId) {
                      setCurrentConversationId(responseConversationId)
                    }
                    
                    setIsUsingTools(false)
                    setToolActivity('')
                    setMessages(prev => {
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
                    // Best-effort save of assistant response to memory
                    saveTrace(finalContent, 'assistant')
                    break
                    
                  case 'response_ready':
                    setIsUsingTools(false)
                    setToolActivity('')
                    setIsLoading(false)
                    spriteBus.setBase('idle', 'chatInterface:response_ready')
                    spriteBus.setTone(undefined, 'chatInterface:response_ready')
                    spriteBus.setVisuals({ energyScale: 1.0, tempoBreatheSec: 3.6 }, 'chatInterface:response_ready')
                    break
                    
                  case 'error':
                    console.error('Streaming error:', eventData.message)
                    setIsUsingTools(false)
                    setToolActivity('')
                    setIsLoading(false)
                    spriteBus.setBase('idle', 'chatInterface:error')
                    spriteBus.setTone(undefined, 'chatInterface:error')
                    spriteBus.setVisuals({ energyScale: 1.0, tempoBreatheSec: 3.6 }, 'chatInterface:error')
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
      
    } catch (error) {
      // Don't show error if request was aborted (user sent another message)
      if (error.name === 'AbortError') {
        console.log('Chat request was cancelled')
        return
      }
      
      const errorMsg = 'Connection error. Please check your network and try again.'
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: errorMsg,
        timestamp: new Date()
      }])
    } finally {
      setIsUsingTools(false)
      setToolActivity('')
      setIsLoading(false)
      // Clear the abort controller when done
      if (abortControllerRef.current) {
        abortControllerRef.current = null
      }
    }
    
    // Refresh conversations after sending a message (in case a new conversation was created)
    setTimeout(() => {
      loadConversations()
    }, 1000)
  }

  const loadConversations = async () => {
    setLoadingConversations(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/conversations`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setConversations(data)
      }
    } catch (error) {
      console.error('Failed to load conversations:', error)
    }
    setLoadingConversations(false)
  }

  const loadConversation = async (conversationId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/conversations/${conversationId}/turns`, {
        credentials: 'include'
      })
      if (response.ok) {
        const turns = await response.json()
        const chatMessages = turns.map((turn: any) => ({
          role: turn.role,
          content: turn.content,
          timestamp: new Date(turn.created_at)
        }))
        setMessages(chatMessages)
        setCurrentConversationId(conversationId)
        
        // Auto-collapse sidebar on mobile after selecting a conversation
        if (isMobile) {
          setSidebarCollapsed(true)
        }
      }
    } catch (error) {
      console.error('Failed to load conversation:', error)
    }
  }

  const startNewConversation = () => {
    setMessages([{
      role: 'assistant',
      content: `Hello! I'm ${APP_CONFIG.assistantName}, your personal AI assistant. How can I help you today?`,
      timestamp: new Date()
    }])
    setCurrentConversationId(null)
    
    // Auto-collapse sidebar on mobile after starting new conversation
    if (isMobile) {
      setSidebarCollapsed(true)
    }
  }

  const deleteConversation = async (conversationId: string, event: React.MouseEvent) => {
    event.stopPropagation() // Prevent triggering the conversation click
    
    if (!confirm('Are you sure you want to delete this conversation? This action cannot be undone.')) {
      return
    }

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/conversations/${conversationId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        // If we're deleting the current conversation, clear the chat
        if (currentConversationId === conversationId) {
          setCurrentConversationId(null)
          messages.splice(0, messages.length) // Clear current messages
        }
        
        // Reload conversations list
        loadConversations()
        console.log('✅ Conversation deleted successfully')
      } else {
        console.error('Failed to delete conversation')
        alert('Failed to delete conversation. Please try again.')
      }
    } catch (error) {
      console.error('Error deleting conversation:', error)
      alert('Error deleting conversation. Please try again.')
    }
  }

  const formatConversationTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60)
    
    if (diffInHours < 1) {
      return 'Just now'
    } else if (diffInHours < 24) {
      return `${Math.floor(diffInHours)}h ago`
    } else if (diffInHours < 24 * 7) {
      return `${Math.floor(diffInHours / 24)}d ago`
    } else {
      return date.toLocaleDateString()
    }
  }

  return (
    <div className="relative flex h-[calc(100vh-8rem)] md:h-[calc(100vh-12rem)] bg-card border border-card rounded-xl overflow-hidden">
      {/* Mobile Sidebar Overlay */}
      {isMobile && !sidebarCollapsed && (
        <div 
          className="absolute inset-0 bg-black bg-opacity-50 z-40"
          onClick={() => setSidebarCollapsed(true)}
        />
      )}
      
      {/* Sidebar */}
      <div className={`${
        sidebarCollapsed ? 'w-0' : isMobile ? 'absolute left-0 top-0 h-full w-80 z-50' : 'w-80'
      } transition-all duration-300 bg-gray-800 border-r border-gray-700 flex flex-col overflow-hidden`}>
        {!sidebarCollapsed && (
          <>
            {/* Sidebar Header */}
            <div className="p-4 border-b border-gray-700">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">Chat History</h3>
                {isMobile && (
                  <button
                    onClick={() => setSidebarCollapsed(true)}
                    className="text-gray-400 hover:text-white p-1"
                  >
                    <span className="material-icons">close</span>
                  </button>
                )}
              </div>
              <button
                onClick={startNewConversation}
                className="w-full bg-teal-600 hover:bg-teal-700 text-white font-medium py-2 px-4 rounded-lg transition-colors flex items-center justify-center space-x-2"
              >
                <span className="material-icons text-sm">add</span>
                <span>New Chat</span>
              </button>
            </div>

            {/* Conversations List */}
            <div className="flex-1 overflow-y-auto">
              <div className="p-2">
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2 px-2">Recent Conversations</h3>
                {loadingConversations ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="animate-spin w-5 h-5 border-2 border-gray-400 border-t-transparent rounded-full"></div>
                  </div>
                ) : conversations.length === 0 ? (
                  <p className="text-gray-500 text-sm px-2 py-4">No conversations yet</p>
                ) : (
                  <div className="space-y-1">
                    {conversations.map((conv) => (
                      <button
                        key={conv.id}
                        onClick={() => loadConversation(conv.id)}
                        className={`w-full text-left p-3 rounded-lg transition-colors hover:bg-gray-700 ${
                          currentConversationId === conv.id ? 'bg-gray-700 border border-teal-500/50' : 'border border-transparent'
                        }`}
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-200 truncate">
                              {conv.title || 'New Conversation'}
                            </p>
                            <p className="text-xs text-gray-400 mt-1">
                              {formatConversationTime(conv.updated_at)}
                            </p>
                          </div>
                          <div className="flex items-center gap-1 ml-2">
                            <span className="material-icons text-xs text-gray-500">
                              chat_bubble_outline
                            </span>
                            <button
                              onClick={(e) => deleteConversation(conv.id, e)}
                              className="p-1 rounded hover:bg-gray-600 text-gray-400 hover:text-red-400 transition-colors"
                              title="Delete conversation"
                            >
                              <span className="material-icons text-sm">delete</span>
                            </button>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-center justify-between bg-gray-800">
          <div className="flex items-center space-x-3">
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="text-gray-400 hover:text-white transition-colors p-1"
            >
              <span className="material-icons text-lg">
                {sidebarCollapsed ? 'menu' : 'menu_open'}
              </span>
            </button>
            <h2 className="text-lg font-semibold">
              {currentConversationId ? 
                conversations.find(c => c.id === currentConversationId)?.title || 'Chat' :
                'New Chat'
              }
            </h2>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => loadConversations()}
              className="text-gray-400 hover:text-white transition-colors p-2"
              title="Refresh conversations"
            >
              <span className="material-icons text-sm">refresh</span>
            </button>
            <button
              onClick={onClearChat}
              className="text-gray-400 hover:text-white transition-colors p-2"
              title="Clear current chat"
            >
              <span className="material-icons text-sm">clear</span>
            </button>
          </div>
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((msg, index) => (
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
                      skipHtml={false}
                      components={{
                        code({node, inline, className, children, ...props}) {
                          const match = /language-(\w+)/.exec(className || '')
                          const language = match ? match[1] : ''
                          const codeContent = String(children).replace(/\n$/, '')
                          
                          // Handle Mermaid diagrams
                          if (!inline && language === 'mermaid') {
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
                        hr: () => <hr className="border-gray-600 my-4" />,
                        a: ({href, children}) => {
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
                      {msg.content}
                    </ReactMarkdown>
                  ) : (
                    <p>{msg.content}</p>
                  )}
                  
                  {/* Display attached documents for user messages */}
                  {msg.role === 'user' && msg.attachedDocuments && msg.attachedDocuments.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {msg.attachedDocuments.map((doc) => (
                        <div key={doc.id} className="flex items-center bg-teal-900/20 border border-teal-700/30 rounded-lg px-3 py-2 text-sm">
                          <span className="material-icons text-teal-400 mr-2 text-sm">description</span>
                          <span className="text-teal-200">
                            {doc.title || doc.original_filename}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  
                  {msg.role === 'assistant' && Array.isArray((msg as any).citations) && (msg as any).citations.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="text-[11px] text-gray-300">Sources</div>
                      <ul className="space-y-1">
                        {(msg as any).citations.slice(0,5).map((c: any, i: number) => (
                          <li key={i} className="text-[11px] text-gray-400 truncate">
                            <a href={typeof c === 'string' ? c : c.url} target="_blank" rel="noreferrer" className="hover:text-gray-200">
                              {typeof c === 'string' ? c : (c.title || c.url)}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
                
                <div className={`text-xs text-gray-500 mt-1 ${
                  msg.role === 'user' ? 'text-right' : 'text-left'
                }`}>
                  {msg.timestamp.toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))}
          
          {(isLoading || isUsingTools) && (
            <div className="flex justify-start">
              <div className="max-w-[80%]">
                <div className="flex items-center mb-2">
                  <div className="w-8 h-8 bg-teal-600 rounded-full flex items-center justify-center text-white text-sm font-medium mr-2">
                    S
                  </div>
                  <span className="text-sm text-gray-400">Sara</span>
                </div>
                <div className="bg-gray-700 rounded-lg px-4 py-3">
                  {isUsingTools && toolActivity ? (
                    <div className="text-gray-100 text-sm">
                      {toolActivity}
                    </div>
                  ) : (
                    <div className="flex space-x-1">
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.1s'}}></div>
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.2s'}}></div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
          
          <div ref={chatMessagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-700 bg-gray-800">
          {/* Uploaded Documents Preview */}
          {uploadedDocuments.length > 0 && (
            <div className="p-4 border-b border-gray-700">
              <div className="text-xs text-gray-400 mb-2">Attached Documents:</div>
              <div className="flex flex-wrap gap-2">
                {uploadedDocuments.map((doc) => (
                  <div key={doc.id} className="flex items-center bg-gray-600 rounded-lg px-3 py-1.5 text-sm">
                    <span className="material-icons text-teal-400 mr-2 text-sm">description</span>
                    <span className="text-gray-200 truncate max-w-48">
                      {doc.title || doc.original_filename}
                    </span>
                    <button
                      onClick={() => removeUploadedDocument(doc.id)}
                      className="ml-2 text-gray-400 hover:text-red-400 transition-colors"
                      type="button"
                    >
                      <span className="material-icons text-xs">close</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          <form onSubmit={handleSendMessage} className="p-4">
            <div className="flex space-x-4">
              <input
                type="text"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={APP_CONFIG.ui.chatPlaceholder}
                className="flex-1 bg-gray-700 border border-gray-600 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-teal-500 text-white placeholder-gray-400"
                disabled={isLoading}
              />
              
              {/* Hidden file input */}
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleDocumentUpload}
                accept=".pdf,.doc,.docx,.txt,.md"
                className="hidden"
              />
              
              {/* File upload button */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 text-white font-medium px-4 rounded-lg transition-colors flex items-center"
                title="Upload document"
              >
                {isUploading ? (
                  <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
                ) : (
                  <span className="material-icons">attach_file</span>
                )}
              </button>
              
              <button 
                type="submit" 
                disabled={isLoading || (!message.trim() && uploadedDocuments.length === 0)}
                className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium px-6 rounded-lg transition-colors flex items-center"
              >
                <span className="material-icons">send</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

export default ChatInterface
