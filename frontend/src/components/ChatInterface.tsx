import React, { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { APP_CONFIG } from '../config'
import { apiClient } from '../api/client'
import type { Document } from '../api/client'
import MermaidDiagram from './MermaidDiagram'
import { ttsService } from '../services/tts'
import StarRating from './StarRating'

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
  episode_id?: string
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
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [isMobile, setIsMobile] = useState(false)
  const [toolActivity, setToolActivity] = useState('')
  const [isUsingTools, setIsUsingTools] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [uploadedDocuments, setUploadedDocuments] = useState<Document[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [speakingMessageIndex, setSpeakingMessageIndex] = useState<number | null>(null)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatMessagesEndRef = useRef<HTMLDivElement>(null)
  const hasLoadedHistory = useRef(false)

  // Load conversation history on mount
  useEffect(() => {
    const loadConversationHistory = async () => {
      if (hasLoadedHistory.current) return
      hasLoadedHistory.current = true

      try {
        setIsLoadingHistory(true)

        // Get active conversation from backend
        const activeResponse = await fetch(`${APP_CONFIG.apiUrl}/api/conversations/active`, {
          credentials: 'include'
        })

        if (!activeResponse.ok) {
          console.log('No active conversation found')
          return
        }

        const activeData = await activeResponse.json()
        const savedConversationId = activeData.conversation_id

        if (!savedConversationId) {
          console.log('No active conversation ID')
          return
        }

        console.log('Loading conversation history for:', savedConversationId)

        // Load conversation messages
        const messagesResponse = await fetch(
          `${APP_CONFIG.apiUrl}/api/conversations/${savedConversationId}/messages?limit=100`,
          { credentials: 'include' }
        )

        if (!messagesResponse.ok) {
          console.error('Failed to load conversation messages')
          return
        }

        const messagesData = await messagesResponse.json()

        if (messagesData && messagesData.length > 0) {
          // Convert Episode format to ChatMessage format
          const loadedMessages: ChatMessage[] = messagesData.map((ep: any) => ({
            role: ep.role,
            content: ep.content,
            timestamp: new Date(ep.created_at)
          }))

          setMessages(loadedMessages)
          setCurrentConversationId(savedConversationId)
          console.log(`Loaded ${loadedMessages.length} messages from conversation ${savedConversationId}`)
        }
      } catch (error) {
        console.error('Error loading conversation history:', error)
      } finally {
        setIsLoadingHistory(false)
      }
    }

    loadConversationHistory()
  }, [setMessages])

  // Save active conversation when conversation_id changes
  useEffect(() => {
    const saveActiveConversation = async () => {
      if (!currentConversationId) return

      try {
        await fetch(`${APP_CONFIG.apiUrl}/api/conversations/active`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ conversation_id: currentConversationId })
        })
        console.log('Saved active conversation:', currentConversationId)
      } catch (error) {
        console.error('Error saving active conversation:', error)
      }
    }

    saveActiveConversation()
  }, [currentConversationId])

  // Check if mobile on mount and window resize
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768)
    }

    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
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

  // Fetch episode IDs for messages (for rating functionality)
  useEffect(() => {
    const fetchEpisodeIds = async () => {
      if (!currentConversationId || messages.length === 0) return

      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/episodes/find-by-content`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            conversation_id: currentConversationId,
            messages: messages.map(m => ({ role: m.role, content: m.content }))
          })
        })

        if (response.ok) {
          const data = await response.json()
          if (data.episodes && data.episodes.length > 0) {
            // Update messages with episode IDs
            setMessages(prev => prev.map((msg, index) => ({
              ...msg,
              episode_id: data.episodes[index]?.episode_id || msg.episode_id
            })))
          }
        }
      } catch (error) {
        console.error('Error fetching episode IDs:', error)
      }
    }

    // Debounce to avoid excessive API calls
    const timeoutId = setTimeout(fetchEpisodeIds, 1000)
    return () => clearTimeout(timeoutId)
  }, [currentConversationId, messages.length])

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

      console.log('📤 Sending request with conversation_id:', currentConversationId)

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body reader available')
      }

      const decoder = new TextDecoder()
      let sseBuffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          // Append chunk to buffer and process full SSE events separated by blank lines
          sseBuffer += decoder.decode(value, { stream: true })
          const parts = sseBuffer.split('\n\n')
          // Keep the last (possibly incomplete) part in the buffer
          sseBuffer = parts.pop() || ''

          for (const part of parts) {
            // Find the first data: line; backend sends one JSON payload per event
            const dataLine = part.split('\n').find(l => l.startsWith('data: '))
            if (dataLine) {
              try {
                const eventData = JSON.parse(dataLine.slice(6))
                
                switch (eventData.type) {
                  case 'tool_calls_start':
                    console.log('🔧 TOOL_CALLS_START event received:', eventData)
                    setIsUsingTools(true)
                    setToolActivity(`🔧 Using Tools (Round ${eventData.data.round})`)
                    break
                    
                  case 'tool_executing':
                    console.log('🔧 TOOL_EXECUTING event received:', eventData)
                    setToolActivity(`🔧 Using ${eventData.data.tool}...`)
                    break
                    
                  case 'thinking':
                    console.log('💭 THINKING event received:', eventData)
                    setIsUsingTools(true)
                    setToolActivity('💭 Processing results...')
                    break
                    
                  case 'text_chunk':
                    streamingContent = eventData.data.full_content
                    setIsUsingTools(false)
                    setToolActivity('')
                    if (firstStreamChunk) {
                      firstStreamChunk = false
                    }
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

                    console.log('📨 Received final_response with conversation_id:', responseConversationId)
                    console.log('📊 Current conversation_id:', currentConversationId)

                    // Update conversation ID if we got one back
                    if (responseConversationId) {
                      if (responseConversationId !== currentConversationId) {
                        console.log('🔄 Updating conversation_id from', currentConversationId, 'to', responseConversationId)
                        setCurrentConversationId(responseConversationId)
                      } else {
                        console.log('✅ conversation_id already matches:', responseConversationId)
                      }
                    } else {
                      console.warn('⚠️ No conversation_id in final_response!')
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
                    break
                    
                  case 'error':
                    console.error('Streaming error:', eventData.message)
                    setIsUsingTools(false)
                    setToolActivity('')
                    setIsLoading(false)
                    break
                }
              } catch (e) {
                console.warn('Failed to parse SSE data:', dataLine)
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
  }

  // Handle text-to-speech for messages
  const handleSpeak = async (text: string, messageIndex: number) => {
    try {
      // If already speaking this message, stop it
      if (speakingMessageIndex === messageIndex) {
        ttsService.stop()
        setSpeakingMessageIndex(null)
        return
      }

      // Stop any currently playing audio
      ttsService.stop()

      // Start speaking
      setSpeakingMessageIndex(messageIndex)
      await ttsService.speak(text)
      setSpeakingMessageIndex(null)
    } catch (error) {
      console.error('[TTS] Error:', error)
      setSpeakingMessageIndex(null)
    }
  }

  // Handle new chat - clear conversation and start fresh
  const handleNewChat = async () => {
    onClearChat()
    setCurrentConversationId(null)

    // Clear active conversation on backend
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/conversations/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ conversation_id: null })
      })
      console.log('Started new conversation')
    } catch (error) {
      console.error('Error clearing active conversation:', error)
    }
  }

  return (
    <div className="relative flex h-[calc(100dvh-8rem)] md:h-[calc(100vh-12rem)] bg-card border border-card rounded-xl overflow-hidden">
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-center justify-between bg-gray-800">
          <h2 className="text-lg font-semibold">Chat with Sara</h2>
          <div className="flex items-center space-x-2">
            <button
              onClick={handleNewChat}
              className="text-gray-400 hover:text-white transition-colors px-3 py-1 rounded-md bg-gray-700 hover:bg-gray-600 text-sm"
              title="Start a new conversation"
            >
              + New Chat
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

                <div className={`flex items-center justify-between text-xs text-gray-500 mt-1 ${
                  msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'
                }`}>
                  <span>{msg.timestamp.toLocaleTimeString()}</span>

                  <div className="flex items-center gap-2">
                    {/* TTS button for assistant messages */}
                    {msg.role === 'assistant' && (
                      <button
                        onClick={() => handleSpeak(msg.content, index)}
                        className={`p-1 rounded-md transition-colors ${
                          speakingMessageIndex === index
                            ? 'bg-teal-600 text-white'
                            : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                        }`}
                        title={speakingMessageIndex === index ? 'Stop speaking' : 'Read aloud'}
                      >
                        {speakingMessageIndex === index ? (
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.707.707L4.586 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.586l3.707-3.707a1 1 0 011.09-.217zM14.657 2.929a1 1 0 011.414 0A9.972 9.972 0 0119 10a9.972 9.972 0 01-2.929 7.071 1 1 0 01-1.414-1.414A7.971 7.971 0 0017 10c0-2.21-.894-4.208-2.343-5.657a1 1 0 010-1.414zm-2.829 2.828a1 1 0 011.415 0A5.983 5.983 0 0115 10a5.984 5.984 0 01-1.757 4.243 1 1 0 01-1.415-1.415A3.984 3.984 0 0013 10a3.983 3.983 0 00-1.172-2.828 1 1 0 010-1.415z" clipRule="evenodd" />
                          </svg>
                        )}
                      </button>
                    )}

                    {/* Star rating for assistant messages with episode_id and length > 50 */}
                    {msg.role === 'assistant' && msg.episode_id && msg.content.length > 50 && (
                      <StarRating
                        episodeId={msg.episode_id}
                        size="sm"
                      />
                    )}
                  </div>
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
          
          <form onSubmit={handleSendMessage} className="p-3 md:p-4">
            <div className="flex space-x-2 md:space-x-4">
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
                className="bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 text-white font-medium px-3 md:px-4 rounded-lg transition-colors flex items-center tap-target"
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
                className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium px-4 md:px-6 rounded-lg transition-colors flex items-center tap-target"
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
