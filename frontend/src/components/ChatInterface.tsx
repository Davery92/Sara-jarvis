import React, { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'
import { apiClient } from '../api/client'
import type { Document, ChatModel, ChatModelsResponse } from '../api/client'
import MermaidDiagram from './MermaidDiagram'
import StarRating from './StarRating'
import { CanvasPanel } from './canvas/CanvasPanel'
import { useArtifacts } from './canvas/hooks/useArtifacts'
import { NoteSelectorModal } from './canvas/NoteSelectorModal'
import { Code, FileText, GitBranch, Maximize2, StickyNote, Ghost, ChevronDown } from 'lucide-react'
import { ArtifactType, NoteContent, CanvasCommand } from './canvas/types'

interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  user_id: string
}

interface AttachedImage {
  data: string      // Base64 encoded image data
  type: string      // MIME type (e.g., "image/jpeg")
  preview: string   // Data URL for preview display
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string | Array<{type: string, text?: string, data?: string, media_type?: string}>
  timestamp: Date
  citations?: any[]
  attachedDocuments?: Document[]
  attachedImages?: AttachedImage[]
  episode_id?: string
  artifacts?: ParsedArtifact[]
}

// Parsed artifact from message content
interface ParsedArtifact {
  id: string
  type: 'code' | 'diagram' | 'document'
  title: string
  content: string
  language?: string
}

function getMessageText(content: ChatMessage['content']): string {
  if (typeof content === 'string') {
    return content
  }

  return content
    .map(part => {
      if (part.type === 'text') {
        return part.text || ''
      }
      if (part.type.includes('image')) {
        return '[Image attachment]'
      }
      return part.text || ''
    })
    .filter(Boolean)
    .join('\n')
}

// Extract artifacts from message content
function parseArtifacts(content: string): { cleanContent: string; artifacts: ParsedArtifact[] } {
  const artifacts: ParsedArtifact[] = []

  // Match ```artifact:type blocks
  const artifactRegex = /```artifact:(code|diagram|document)(?:\s+title="([^"]*)")?(?:\s+language="([^"]*)")?\n([\s\S]*?)```/g

  let cleanContent = content
  let match

  while ((match = artifactRegex.exec(content)) !== null) {
    const [fullMatch, type, title, language, artifactContent] = match

    artifacts.push({
      id: `artifact-${Date.now()}-${artifacts.length}`,
      type: type as 'code' | 'diagram' | 'document',
      title: title || `${type.charAt(0).toUpperCase() + type.slice(1)} Artifact`,
      content: artifactContent.trim(),
      language: language || (type === 'code' ? 'javascript' : undefined)
    })

    // Replace the artifact block with a placeholder
    cleanContent = cleanContent.replace(fullMatch, `[Artifact: ${title || type}]`)
  }

  return { cleanContent, artifacts }
}

// Artifact preview card component
const ArtifactCard: React.FC<{
  artifact: ParsedArtifact
  onExpand: () => void
}> = ({ artifact, onExpand }) => {
  const getIcon = () => {
    switch (artifact.type) {
      case 'code': return <Code size={18} />
      case 'diagram': return <GitBranch size={18} />
      case 'document': return <FileText size={18} />
    }
  }

  const getPreview = () => {
    const lines = artifact.content.split('\n').slice(0, 3)
    return lines.join('\n') + (artifact.content.split('\n').length > 3 ? '\n...' : '')
  }

  return (
    <div
      className="mt-3 bg-gray-800 border border-gray-600 rounded-lg overflow-hidden cursor-pointer hover:border-teal-500 transition-colors"
      onClick={onExpand}
    >
      <div className="flex items-center justify-between px-3 py-2 bg-gray-700 border-b border-gray-600">
        <div className="flex items-center gap-2 text-gray-300">
          {getIcon()}
          <span className="text-sm font-medium">{artifact.title}</span>
          {artifact.language && (
            <span className="text-xs px-1.5 py-0.5 bg-gray-600 rounded text-gray-400">
              {artifact.language}
            </span>
          )}
        </div>
        <button
          className="p-1 hover:bg-gray-600 rounded text-gray-400 hover:text-white"
          title="Open in Canvas"
        >
          <Maximize2 size={14} />
        </button>
      </div>
      <pre className="p-3 text-xs text-gray-400 font-mono overflow-hidden max-h-20">
        {getPreview()}
      </pre>
    </div>
  )
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
  quickActionContext?: {
    inboxUnreadCount: number
    attentionUnreadCount: number
    missionAwaitingCount: number
    runningMissionCount: number
    standingOrdersCount: number
  }
  onQuickAction?: (actionId: 'inbox_attention' | 'missions' | 'standing_orders') => void
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({
  messages,
  setMessages,
  loading,
  onSendMessage,
  onClearChat,
  message,
  setMessage,
  abortControllerRef,
  quickActionContext,
  onQuickAction,
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
  const [canvasPanelOpen, setCanvasPanelOpen] = useState(false)
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null)
  const [pendingArtifact, setPendingArtifact] = useState<ParsedArtifact | null>(null)
  const [showNoteSelector, setShowNoteSelector] = useState(false)
  const [canvasNoteContent, setCanvasNoteContent] = useState<NoteContent | null>(null)
  const [canvasWidth, setCanvasWidth] = useState(50) // percentage
  const [isResizing, setIsResizing] = useState(false)
  const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([])
  const [showImageMenu, setShowImageMenu] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:20b')
  const [isEphemeral, setIsEphemeral] = useState(false)
  const [showModelDropdown, setShowModelDropdown] = useState(false)
  const [availableModels, setAvailableModels] = useState<ChatModelsResponse | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const modelDropdownRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)
  const imageMenuRef = useRef<HTMLDivElement>(null)
  const chatMessagesEndRef = useRef<HTMLDivElement>(null)
  const hasLoadedHistory = useRef(false)
  const hasUserMessages = messages.some((msg) => msg.role === 'user')

  // Artifacts hook for creating/managing artifacts
  const { createArtifact, artifacts } = useArtifacts({ conversationId: currentConversationId || undefined })

  // Handle opening an artifact in the canvas panel
  const handleOpenArtifact = useCallback(async (artifact: ParsedArtifact) => {
    // Create the artifact in the backend
    const artifactType = artifact.type

    let content: any
    if (artifact.type === 'code') {
      content = { code: artifact.content, language: artifact.language || 'javascript' }
    } else if (artifact.type === 'diagram') {
      content = { source: artifact.content, diagram_type: 'mermaid' }
    } else {
      content = { content: artifact.content, format: 'markdown' }
    }

    try {
      const newArtifact = await createArtifact(
        artifactType,
        artifact.title,
        content
      )

      if (newArtifact) {
        setSelectedArtifactId(newArtifact.id)
        setCanvasPanelOpen(true)
      } else {
        // Still show panel with pending artifact for preview
        setPendingArtifact(artifact)
        setCanvasPanelOpen(true)
      }
    } catch (error) {
      console.error('Failed to create artifact:', error)
      // Still show panel with pending artifact for preview
      setPendingArtifact(artifact)
      setCanvasPanelOpen(true)
    }
  }, [createArtifact])

  // Load conversation history on mount
  useEffect(() => {
    const loadConversationHistory = async () => {
      if (hasLoadedHistory.current) return
      hasLoadedHistory.current = true

      try {
        setIsLoadingHistory(true)

        let savedConversationId: string | null = null

        // First, check for a cross-device active session (e.g. started on iOS)
        try {
          const sessionResponse = await fetch(`${APP_CONFIG.apiUrl}/api/session/active`, {
            credentials: 'include'
          })
          if (sessionResponse.ok) {
            const sessionData = await sessionResponse.json()
            if (sessionData.active && sessionData.session?.conversation_id) {
              savedConversationId = sessionData.session.conversation_id
              console.log('Resuming cross-device session:', savedConversationId, 'from', sessionData.session.last_device)
            }
          }
        } catch {
          // Non-critical — fall through to conversations/active
        }

        // Fall back to the per-device active conversation
        if (!savedConversationId) {
          const activeResponse = await fetch(`${APP_CONFIG.apiUrl}/api/conversations/active`, {
            credentials: 'include'
          })

          if (!activeResponse.ok) {
            console.log('No active conversation found')
            return
          }

          const activeData = await activeResponse.json()
          savedConversationId = activeData.conversation_id
        }

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

  // Fetch available chat models on mount
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const models = await apiClient.getChatModels()
        setAvailableModels(models)
        if (models.default && selectedModel === 'gpt-oss:20b') {
          setSelectedModel(models.default)
        }
      } catch (error) {
        console.error('Failed to fetch chat models:', error)
      }
    }
    fetchModels()
  }, [])

  // Close model dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(event.target as Node)) {
        setShowModelDropdown(false)
      }
    }
    if (showModelDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showModelDropdown])

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
    // Skip if loading/streaming to avoid aborted requests
    if (loading || !currentConversationId || messages.length === 0) return

    const controller = new AbortController()

    const fetchEpisodeIds = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/episodes/find-by-content`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          signal: controller.signal,
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
        // Ignore abort errors - they're expected when component updates
        if (error instanceof Error && error.name === 'AbortError') return
        console.error('Error fetching episode IDs:', error)
      }
    }

    // Debounce to avoid excessive API calls
    const timeoutId = setTimeout(fetchEpisodeIds, 1500)
    return () => {
      clearTimeout(timeoutId)
      controller.abort()
    }
  }, [currentConversationId, messages.length, loading])

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

  // Handle image selection from gallery
  const handleImageSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const file = files[0]
    if (!file.type.startsWith('image/')) {
      console.error('Selected file is not an image')
      return
    }

    // Convert to base64
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      const base64 = result.split(',')[1]
      setAttachedImages(prev => [...prev, {
        data: base64,
        type: file.type,
        preview: result
      }])
    }
    reader.readAsDataURL(file)

    // Reset input
    if (imageInputRef.current) {
      imageInputRef.current.value = ''
    }
  }

  // Handle camera capture (same logic, just different input)
  const handleCameraCapture = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const file = files[0]
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      const base64 = result.split(',')[1]
      setAttachedImages(prev => [...prev, {
        data: base64,
        type: file.type,
        preview: result
      }])
    }
    reader.readAsDataURL(file)

    if (cameraInputRef.current) {
      cameraInputRef.current.value = ''
    }
  }

  // Remove attached image
  const removeAttachedImage = (index: number) => {
    setAttachedImages(prev => prev.filter((_, i) => i !== index))
  }

  const handleQuickAction = (actionId: 'inbox_attention' | 'missions' | 'standing_orders') => {
    if (actionId === 'standing_orders') {
      setMessage('Review my active standing orders and tell me what is scheduled next.')
    }
    onQuickAction?.(actionId)
  }

  // Close image menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (imageMenuRef.current && !imageMenuRef.current.contains(event.target as Node)) {
        setShowImageMenu(false)
      }
    }
    if (showImageMenu) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showImageMenu])

  // Enhanced send message with tool activity tracking
  const handleSendMessage = async (e: React.FormEvent, isQuickChat = false) => {
    e.preventDefault()
    if ((!message.trim() && uploadedDocuments.length === 0 && attachedImages.length === 0) || loading) return
    
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

    // Create user message with attached documents and images
    const userMessage: ChatMessage = {
      role: 'user' as const,
      content: message,
      timestamp: new Date(),
      attachedDocuments: uploadedDocuments.length > 0 ? [...uploadedDocuments] : undefined,
      attachedImages: attachedImages.length > 0 ? [...attachedImages] : undefined
    }
    setMessages(prev => [...prev, userMessage])
    setMessage('')

    // Clear uploaded documents and images after sending
    setUploadedDocuments([])
    setAttachedImages([])
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

      // Best-effort save of user's message to memory (text only)
      const textContent = typeof userMessage.content === 'string'
        ? userMessage.content
        : (userMessage.content as any[]).find(c => c.type === 'text')?.text || ''
      saveTrace(textContent, 'user')

      const response = await fetch(`${APP_CONFIG.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          messages: [...messages, userMessage].map(m => {
            // Get text content
            let textContent = typeof m.content === 'string' ? m.content : ''
            if (Array.isArray(m.content)) {
              textContent = m.content.find((c: any) => c.type === 'text')?.text || ''
            }

            // If this message has attached documents, prepend their content
            if (m.attachedDocuments && m.attachedDocuments.length > 0) {
              const documentContext = m.attachedDocuments
                .map(doc => `[Document: ${doc.title || doc.original_filename}]\n${doc.content_text || 'Content could not be extracted'}\n[End of ${doc.title || doc.original_filename}]`)
                .join('\n\n')
              textContent = `${documentContext}\n\n${textContent}`
            }

            // If this message has attached images, use multimodal format
            if (m.attachedImages && m.attachedImages.length > 0) {
              const multimodalContent: Array<{type: string, text?: string, data?: string, media_type?: string}> = [
                // Add images first
                ...m.attachedImages.map(img => ({
                  type: 'image',
                  data: img.data,
                  media_type: img.type
                })),
                // Then add text
                { type: 'text', text: textContent }
              ]
              return { role: m.role, content: multimodalContent }
            }

            return { role: m.role, content: textContent }
          }),
          conversation_id: currentConversationId,
          model: selectedModel,
          ephemeral: isEphemeral
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

                  case 'canvas_command':
                    console.log('📐 CANVAS_COMMAND event received:', eventData.data)
                    const canvasData = eventData.data as CanvasCommand
                    if (canvasData.canvas_command === 'open') {
                      if (canvasData.artifact_type === 'note' && canvasData.content) {
                        // Opening a note - use the note content directly
                        setCanvasNoteContent(canvasData.content as NoteContent)
                        setSelectedArtifactId(null)
                        setPendingArtifact(null)
                        setCanvasPanelOpen(true)
                      } else if (canvasData.artifact_type && canvasData.content) {
                        // Opening other content types - create as pending artifact
                        const artifactContent = {
                          type: canvasData.artifact_type,
                          title: canvasData.title || 'Canvas',
                          content: canvasData.content
                        }
                        setPendingArtifact(artifactContent as any)
                        setCanvasNoteContent(null)
                        setCanvasPanelOpen(true)
                      }
                    } else if (canvasData.canvas_command === 'update') {
                      // Update current canvas content
                      if (canvasNoteContent && canvasData.content) {
                        setCanvasNoteContent(prev => prev ? { ...prev, ...canvasData.content as NoteContent } : null)
                      }
                    } else if (canvasData.canvas_command === 'close') {
                      setCanvasPanelOpen(false)
                      setSelectedArtifactId(null)
                      setPendingArtifact(null)
                      setCanvasNoteContent(null)
                    }
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

  // Handle text-to-speech for messages (disabled - use iOS app for voice)
  const handleSpeak = async (text: string, messageIndex: number) => {
    // TTS disabled on web - use iOS app for voice features
    console.log('[TTS] Web TTS disabled - use iOS app for voice')
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

  // Handle resize of chat/canvas panels
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const containerRect = containerRef.current.getBoundingClientRect()
      const newChatWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100
      // Clamp between 25% and 75%
      const clampedWidth = Math.max(25, Math.min(75, newChatWidth))
      setCanvasWidth(100 - clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  return (
    <div
      ref={containerRef}
      className={`relative flex h-full bg-card border border-card rounded-md overflow-hidden ${isResizing ? 'select-none' : ''}`}
    >
      {/* Main Chat Area - shrinks when canvas is open */}
      <div
        className={`flex flex-col min-w-0 ${!isResizing ? 'transition-all duration-300' : ''}`}
        style={{ width: canvasPanelOpen ? `${100 - canvasWidth}%` : '100%' }}
      >
        {/* Header */}
        <div className={`px-3 py-2 border-b border-gray-700 flex items-center justify-between ${isEphemeral ? 'bg-purple-900/20' : 'bg-gray-800'}`}>
          <div className="flex items-center gap-2.5">
            <h2 className="text-sm font-semibold">Chat with Sara</h2>

            {/* Model Selector Dropdown */}
            <div className="relative" ref={modelDropdownRef}>
              <button
                onClick={() => setShowModelDropdown(!showModelDropdown)}
                className="flex items-center gap-1.5 px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm text-white transition-colors"
              >
                <span className="max-w-[120px] truncate">
                  {availableModels?.models?.find(m => m.id === selectedModel)?.name || selectedModel}
                </span>
                <ChevronDown size={14} className={`text-gray-400 transition-transform ${showModelDropdown ? 'rotate-180' : ''}`} />
              </button>

              {showModelDropdown && availableModels?.models && (
                <div className="absolute top-full left-0 mt-1 w-48 bg-gray-700 border border-gray-600 rounded-lg shadow-xl z-50 py-1 max-h-64 overflow-y-auto">
                  {/* Group models by provider */}
                  {Object.entries(
                    availableModels.models.reduce((acc, model) => {
                      if (!acc[model.provider]) acc[model.provider] = []
                      acc[model.provider].push(model)
                      return acc
                    }, {} as Record<string, ChatModel[]>)
                  ).map(([provider, models]) => (
                    <div key={provider}>
                      <div className="px-3 py-1 text-xs text-gray-400 uppercase tracking-wider">
                        {provider === 'anthropic'
                          ? 'Claude'
                          : provider === 'google'
                          ? 'Gemini'
                          : provider === 'codex'
                          ? 'ChatGPT Codex'
                          : provider === 'openai'
                          ? 'OpenAI'
                          : 'Local'}
                      </div>
                      {models.map((model) => (
                        <button
                          key={model.id}
                          onClick={() => {
                            setSelectedModel(model.id)
                            setShowModelDropdown(false)
                          }}
                          className={`w-full px-3 py-1.5 text-left text-sm hover:bg-gray-600 transition-colors ${
                            model.id === selectedModel ? 'text-teal-400 bg-gray-600' : 'text-white'
                          }`}
                        >
                          {model.name}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Ghost/Ephemeral Toggle */}
            <button
              onClick={() => setIsEphemeral(!isEphemeral)}
              className={`p-1.5 rounded transition-colors ${
                isEphemeral
                  ? 'text-purple-400 bg-purple-500/20 hover:bg-purple-500/30'
                  : 'text-gray-400 hover:text-purple-400 hover:bg-gray-700'
              }`}
              title={isEphemeral ? "Ephemeral mode ON - chat won't be saved" : "Ephemeral mode OFF - chat will be saved"}
            >
              <Ghost size={18} />
            </button>

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
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {!hasUserMessages && (
            <div className="bg-gray-800/60 border border-gray-700 rounded-md p-3">
              <div className="mb-2">
                <h3 className="text-xs font-semibold text-gray-200 uppercase tracking-wider">Quick Actions</h3>
                <p className="text-[11px] text-gray-500 mt-0.5">Context-aware shortcuts based on your current queue.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <button
                  onClick={() => handleQuickAction('inbox_attention')}
                  className="text-left rounded-lg border border-gray-700 bg-gray-900/70 hover:border-teal-500/50 px-3 py-2"
                >
                  <p className="text-sm text-white">Review Attention Inbox</p>
                  <p className="text-xs text-gray-400 mt-1">
                    {quickActionContext?.attentionUnreadCount || 0} unread attention item(s)
                  </p>
                </button>
                <button
                  onClick={() => handleQuickAction('missions')}
                  className="text-left rounded-lg border border-gray-700 bg-gray-900/70 hover:border-teal-500/50 px-3 py-2"
                >
                  <p className="text-sm text-white">Open Missions</p>
                  <p className="text-xs text-gray-400 mt-1">
                    {quickActionContext?.missionAwaitingCount || 0} awaiting decisions, {quickActionContext?.runningMissionCount || 0} running
                  </p>
                </button>
                <button
                  onClick={() => handleQuickAction('standing_orders')}
                  className="text-left rounded-lg border border-gray-700 bg-gray-900/70 hover:border-teal-500/50 px-3 py-2"
                >
                  <p className="text-sm text-white">Summarize Standing Orders</p>
                  <p className="text-xs text-gray-400 mt-1">
                    {quickActionContext?.standingOrdersCount || 0} active standing order(s)
                  </p>
                </button>
              </div>
            </div>
          )}

          {messages.map((msg, index) => {
            const messageText = getMessageText(msg.content)

            return (
            <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] md:max-w-[80%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                {msg.role === 'assistant' && (
                  <div className="flex items-center mb-1.5">
                    <div className="w-6 h-6 bg-teal-600 rounded-full flex items-center justify-center text-white text-[11px] font-medium mr-2">
                      S
                    </div>
                    <span className="text-xs text-gray-400">Sara</span>
                  </div>
                )}

                <div className={`rounded-lg px-3 py-2 ${
                  msg.role === 'user' 
                    ? 'bg-teal-600 text-white ml-auto' 
                    : 'bg-gray-700 text-gray-100'
                }`}>
                  {msg.role === 'assistant' ? (() => {
                    // Parse artifacts from content
                    const { cleanContent, artifacts: parsedArtifacts } = parseArtifacts(messageText)

                    return (
                      <>
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          skipHtml={false}
                          components={{
                            code(props: any) {
                              const { inline, className, children, ...rest } = props
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
                                <pre className="rounded-md mt-2 bg-gray-900 border border-gray-600 p-4 overflow-x-auto">
                                  <code className={`${className} text-gray-100 text-sm`} {...rest}>
                                    {codeContent}
                                  </code>
                                </pre>
                              ) : (
                                <code className="bg-gray-600 px-1 py-0.5 rounded text-sm" {...rest}>
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
                              // Internal API links (e.g. /email/.../download) — fetch with auth cookie
                              if (href && (href.startsWith('/email/') || href.startsWith('/api/'))) {
                                const handleApiDownload = async (e: React.MouseEvent) => {
                                  e.preventDefault()
                                  try {
                                    const apiBase = APP_CONFIG.apiUrl
                                    const res = await fetch(`${apiBase}${href}`, { credentials: 'include' })
                                    if (!res.ok) throw new Error(`Download failed: ${res.status}`)
                                    const blob = await res.blob()
                                    const url = URL.createObjectURL(blob)
                                    const a = document.createElement('a')
                                    a.href = url
                                    // Extract filename from Content-Disposition or href
                                    const disposition = res.headers.get('Content-Disposition')
                                    const filenameMatch = disposition?.match(/filename="?([^"]+)"?/)
                                    a.download = filenameMatch?.[1] || href.split('/').pop() || 'download'
                                    document.body.appendChild(a)
                                    a.click()
                                    document.body.removeChild(a)
                                    URL.revokeObjectURL(url)
                                  } catch (err) {
                                    console.error('Download failed:', err)
                                  }
                                }
                                return (
                                  <a
                                    href={href}
                                    onClick={handleApiDownload}
                                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-blue-600/20 border border-blue-500/30 rounded text-blue-400 hover:bg-blue-600/30 cursor-pointer transition-colors no-underline"
                                    title="Click to download"
                                  >
                                    <span className="material-icons text-xs" style={{fontSize: '14px'}}>attach_file</span>
                                    {children}
                                  </a>
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
                          {cleanContent}
                        </ReactMarkdown>

                        {/* Render artifact cards */}
                        {parsedArtifacts.length > 0 && (
                          <div className="mt-3 space-y-2">
                            {parsedArtifacts.map((artifact) => (
                              <ArtifactCard
                                key={artifact.id}
                                artifact={artifact}
                                onExpand={() => handleOpenArtifact(artifact)}
                              />
                            ))}
                          </div>
                        )}
                      </>
                    )
                  })() : (
                    <p>{messageText}</p>
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
                        onClick={() => handleSpeak(messageText, index)}
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
                    {msg.role === 'assistant' && msg.episode_id && messageText.length > 50 && (
                      <StarRating
                        episodeId={msg.episode_id}
                        size="sm"
                      />
                    )}
                  </div>
                </div>
              </div>
            </div>
            )
          })}
          
          {(isLoading || isUsingTools) && (
            <div className="flex justify-start">
              <div className="max-w-[80%]">
                <div className="flex items-center mb-1.5">
                  <div className="w-6 h-6 bg-teal-600 rounded-full flex items-center justify-center text-white text-[11px] font-medium mr-2">
                    S
                  </div>
                  <span className="text-xs text-gray-400">Sara</span>
                </div>
                <div className="bg-gray-700 rounded-lg px-3 py-2">
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
            <div className="px-3 py-2 border-b border-gray-700">
              <div className="text-[11px] text-gray-400 mb-1.5">Attached Documents</div>
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

          {/* Attached Images Preview */}
          {attachedImages.length > 0 && (
            <div className="px-3 py-2 border-b border-gray-700">
              <div className="text-[11px] text-gray-400 mb-1.5">Attached Images</div>
              <div className="flex flex-wrap gap-2">
                {attachedImages.map((img, idx) => (
                  <div key={idx} className="relative group">
                    <img
                      src={img.preview}
                      alt={`Attached ${idx + 1}`}
                      className="h-16 w-16 object-cover rounded-lg border border-gray-600"
                    />
                    <button
                      onClick={() => removeAttachedImage(idx)}
                      className="absolute -top-1 -right-1 bg-red-500 hover:bg-red-600 rounded-full w-5 h-5 flex items-center justify-center text-white text-xs transition-colors"
                      type="button"
                    >
                      <span className="material-icons text-xs">close</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <form onSubmit={handleSendMessage} className="p-3">
            <div className="flex space-x-2">
              <input
                type="text"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={APP_CONFIG.ui.chatPlaceholder}
                className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-500 text-white placeholder-gray-400"
                disabled={isLoading}
              />
              
              {/* Hidden file inputs */}
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleDocumentUpload}
                accept=".pdf,.doc,.docx,.txt,.md"
                className="hidden"
              />
              <input
                ref={imageInputRef}
                type="file"
                onChange={handleImageSelect}
                accept="image/*"
                className="hidden"
              />
              <input
                ref={cameraInputRef}
                type="file"
                onChange={handleCameraCapture}
                accept="image/*"
                capture="environment"
                className="hidden"
              />

              {/* Image menu button */}
              <div className="relative" ref={imageMenuRef}>
                <button
                  type="button"
                  onClick={() => setShowImageMenu(!showImageMenu)}
                  disabled={isLoading}
                  className="bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 text-white px-2.5 rounded-lg transition-colors flex items-center tap-target"
                  title="Add image"
                >
                  <span className="material-icons text-lg">add_photo_alternate</span>
                </button>
                {showImageMenu && (
                  <div className="absolute bottom-full left-0 mb-2 bg-gray-700 rounded-lg shadow-lg border border-gray-600 overflow-hidden z-50">
                    <button
                      type="button"
                      onClick={() => {
                        imageInputRef.current?.click()
                        setShowImageMenu(false)
                      }}
                      className="w-full px-4 py-2 text-left text-white hover:bg-gray-600 flex items-center gap-2 whitespace-nowrap"
                    >
                      <span className="material-icons text-sm">photo_library</span>
                      Choose from gallery
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        cameraInputRef.current?.click()
                        setShowImageMenu(false)
                      }}
                      className="w-full px-4 py-2 text-left text-white hover:bg-gray-600 flex items-center gap-2 whitespace-nowrap"
                    >
                      <span className="material-icons text-sm">photo_camera</span>
                      Take a photo
                    </button>
                  </div>
                )}
              </div>

              {/* Document upload button */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 text-white px-2.5 rounded-lg transition-colors flex items-center tap-target"
                title="Upload document"
              >
                {isUploading ? (
                  <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
                ) : (
                  <span className="material-icons text-lg">attach_file</span>
                )}
              </button>

              {/* Open Note in Canvas button */}
              <button
                type="button"
                onClick={() => setShowNoteSelector(true)}
                disabled={isLoading}
                className="bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 text-white px-2.5 rounded-lg transition-colors flex items-center tap-target"
                title="Open note in canvas"
              >
                <StickyNote size={18} />
              </button>

              <button
                type="submit"
                disabled={isLoading || (!message.trim() && uploadedDocuments.length === 0 && attachedImages.length === 0)}
                className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-3 md:px-4 rounded-lg transition-colors flex items-center tap-target"
              >
                <span className="material-icons text-lg">send</span>
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Resizable Divider */}
      {canvasPanelOpen && (
        <div
          className="w-1 bg-gray-700 hover:bg-teal-500 cursor-col-resize flex-shrink-0 transition-colors group relative"
          onMouseDown={handleResizeStart}
        >
          <div className="absolute inset-y-0 -left-1 -right-1 group-hover:bg-teal-500/20" />
        </div>
      )}

      {/* Canvas Panel for Artifacts */}
      <CanvasPanel
        isOpen={canvasPanelOpen}
        onClose={() => {
          setCanvasPanelOpen(false)
          setSelectedArtifactId(null)
          setPendingArtifact(null)
          setCanvasNoteContent(null)
        }}
        artifactId={selectedArtifactId}
        conversationId={currentConversationId || undefined}
        width={canvasWidth}
        isResizing={isResizing}
        directArtifact={canvasNoteContent ? {
          id: `note-${canvasNoteContent.note_id}`,
          user_id: '',
          artifact_type: 'note',
          title: canvasNoteContent.title || 'Untitled',
          content: canvasNoteContent,
          metadata: null,
          conversation_id: null,
          episode_id: null,
          is_pinned: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        } : null}
      />

      {/* Note Selector Modal */}
      <NoteSelectorModal
        isOpen={showNoteSelector}
        onClose={() => setShowNoteSelector(false)}
        onSelectNote={(note) => {
          setCanvasNoteContent({
            note_id: note.id,
            title: note.title,
            content: note.content,
            folder_id: note.folder_id
          })
          setSelectedArtifactId(null)
          setPendingArtifact(null)
          setCanvasPanelOpen(true)
        }}
      />
    </div>
  )
}

export default ChatInterface
