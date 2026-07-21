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
import { Code, FileText, GitBranch, Maximize2, StickyNote, Ghost, ChevronDown, History, Plus } from 'lucide-react'
import ConversationHistoryDrawer from './ConversationHistoryDrawer'
import { Artifact, ArtifactType, NoteContent, CanvasCommand } from './canvas/types'
import { SurfaceModel, SurfaceCommand } from './surfaces/types'
import { SurfacePanel } from './surfaces/SurfacePanel'

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
  // Defensive: content can be undefined/null (e.g. an event with no text payload).
  // Never let this throw — it renders during React's render pass and would crash the page.
  if (!Array.isArray(content)) {
    return content == null ? '' : String(content)
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
      className="mt-3 cursor-pointer overflow-hidden rounded-xl border border-white/10 bg-white/[0.03] transition-colors hover:border-teal-300/30"
      onClick={onExpand}
    >
      <div className="flex items-center justify-between border-b border-white/8 px-3 py-2">
        <div className="flex items-center gap-2 text-slate-400">
          {getIcon()}
          <span className="text-sm font-medium text-slate-200">{artifact.title}</span>
          {artifact.language && (
            <span className="text-xs text-slate-500">{artifact.language}</span>
          )}
        </div>
        <button
          className="rounded-lg p-1 text-slate-500 transition-colors hover:text-teal-300"
          title="Open in Canvas"
        >
          <Maximize2 size={14} />
        </button>
      </div>
      <pre className="max-h-20 overflow-hidden p-3 font-mono text-xs text-slate-500">
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
  autoSendToken?: number
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
  autoSendToken,
}) => {
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
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
  // Full artifact opened via SSE canvas_open — carries the persisted artifact_id
  // so the panel can render immediately and "Open in Studio" can deep-link.
  const [canvasDirectArtifact, setCanvasDirectArtifact] = useState<Artifact | null>(null)
  // Active interactive surface (checklist / cook-mode / form), driven by SSE.
  const [activeSurface, setActiveSurface] = useState<SurfaceModel | null>(null)
  const [canvasWidth, setCanvasWidth] = useState(50) // percentage
  const [isResizing, setIsResizing] = useState(false)
  const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([])
  const [showImageMenu, setShowImageMenu] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:20b')
  const [isEphemeral, setIsEphemeral] = useState(false)
  const [showModelDropdown, setShowModelDropdown] = useState(false)
  const [availableModels, setAvailableModels] = useState<ChatModelsResponse | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)
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

  // True once the user sends a message this mount — the history restore below
  // must not clobber an in-flight exchange (e.g. dashboard ask-dock auto-send
  // lands while the history fetch is still pending).
  const sentSinceMountRef = useRef(false)

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
          if (sentSinceMountRef.current) {
            // A message went out while this fetch was pending — the fetched
            // history is stale (it predates the send) and replacing messages
            // would erase the user's bubble. The stream sets conversation_id.
            console.log('Skipping history restore: message sent while loading')
            return
          }

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

  // Re-show an active surface (checklist / cook-mode) for this conversation on
  // load, so a page reload or returning to chat doesn't lose it. Surfaces are
  // persistent DB rows; the live SSE panel is only in-memory otherwise.
  useEffect(() => {
    if (!currentConversationId || activeSurface) return
    let cancelled = false
    const loadActiveSurface = async () => {
      try {
        const res = await fetch(
          `${APP_CONFIG.apiUrl}/api/surfaces?status=active&conversation_id=${currentConversationId}`,
          { credentials: 'include' },
        )
        if (!res.ok) return
        const surfaces = (await res.json()) as SurfaceModel[]
        if (!cancelled && surfaces.length > 0) {
          setActiveSurface(surfaces[0]) // most recent (list is updated_at desc)
        }
      } catch {
        // non-critical
      }
    }
    loadActiveSurface()
    return () => {
      cancelled = true
    }
  }, [currentConversationId, activeSurface])

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
    sentSinceMountRef.current = true

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
          ephemeral: isEphemeral,
          // SARA_UNLEASHED Phase T.4: one-shot — a reply from the attention
          // inbox carries the original item's id so the conversation
          // continues instead of restarting cold. Cleared immediately so it
          // only applies to this one outgoing turn.
          ...((window as any).__attentionItemId
            ? { attention_item_id: (window as any).__attentionItemId }
            : {}),
          // P3: the inbox button sets this one-shot so THIS turn's context gets
          // the full unified inbox injected server-side (deterministic, not a
          // question Sara answers from a partial slice). Cleared right after.
          ...((window as any).__includeInbox ? { include_inbox: true } : {}),
        })
      })
      ;(window as any).__attentionItemId = undefined
      ;(window as any).__includeInbox = undefined

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
                    // Normal LLM streaming sends `full_content` (accumulated); chess/code
                    // mode send `content`. Fall back so neither yields undefined.
                    streamingContent = eventData.data.full_content ?? eventData.data.content ?? streamingContent ?? ''
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

                  case 'ui_command':
                    // Jarvis-style overlay request ("bring up my morning brief").
                    // SaraOverlayHost (mounted in the app shell) listens for this.
                    console.log('🪟 UI_COMMAND event received:', eventData.data)
                    window.dispatchEvent(new CustomEvent('sara:ui-command', { detail: eventData.data }))
                    break

                  case 'canvas_command':
                    console.log('📐 CANVAS_COMMAND event received:', eventData.data)
                    const canvasData = eventData.data as CanvasCommand
                    if (canvasData.canvas_command === 'open') {
                      if (canvasData.artifact_type === 'note' && canvasData.content) {
                        // Opening a note - use the note content directly
                        setCanvasNoteContent(canvasData.content as NoteContent)
                        setCanvasDirectArtifact(null)
                        setSelectedArtifactId(null)
                        setPendingArtifact(null)
                        setCanvasPanelOpen(true)
                      } else if (canvasData.artifact_type && canvasData.content) {
                        // Opening other content types. The backend now persists the
                        // artifact row and returns artifact_id — render it directly
                        // and keep the real id so it lives in the Studio library.
                        const nowIso = new Date().toISOString()
                        const direct: Artifact = {
                          id: canvasData.artifact_id || `pending-${Date.now()}`,
                          user_id: '',
                          artifact_type: canvasData.artifact_type,
                          title: canvasData.title || 'Canvas',
                          content: canvasData.content,
                          metadata: null,
                          conversation_id: null,
                          episode_id: null,
                          is_pinned: false,
                          created_at: nowIso,
                          updated_at: nowIso,
                        }
                        setCanvasDirectArtifact(direct)
                        setPendingArtifact(null)
                        setCanvasNoteContent(null)
                        setCanvasPanelOpen(true)
                      }
                    } else if (canvasData.canvas_command === 'update') {
                      // Update current canvas content
                      if (canvasNoteContent && canvasData.content) {
                        setCanvasNoteContent(prev => prev ? { ...prev, ...canvasData.content as NoteContent } : null)
                      } else {
                        setCanvasDirectArtifact(prev =>
                          prev
                            ? {
                                ...prev,
                                content: canvasData.content ?? prev.content,
                                title: canvasData.title ?? prev.title,
                                updated_at: new Date().toISOString(),
                              }
                            : prev
                        )
                      }
                    } else if (canvasData.canvas_command === 'close') {
                      setCanvasPanelOpen(false)
                      setSelectedArtifactId(null)
                      setPendingArtifact(null)
                      setCanvasNoteContent(null)
                      setCanvasDirectArtifact(null)
                    }
                    break

                  case 'surface_command': {
                    console.log('🧩 SURFACE_COMMAND event received:', eventData.data)
                    const surfaceData = eventData.data as SurfaceCommand
                    if (
                      (surfaceData.surface_command === 'open' ||
                        surfaceData.surface_command === 'update') &&
                      surfaceData.surface
                    ) {
                      setActiveSurface(surfaceData.surface)
                    } else if (surfaceData.surface_command === 'close') {
                      setActiveSurface((prev) =>
                        prev && prev.id === surfaceData.surface_id ? null : prev,
                      )
                    }
                    break
                  }
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

  // Auto-send for handoffs like the dashboard ask dock: the caller sets the
  // message and bumps the token, and we fire the send once the prefilled
  // message has landed — no second Enter required.
  const lastAutoSendRef = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!autoSendToken || autoSendToken === lastAutoSendRef.current) return
    if (!message.trim() || loading) return
    lastAutoSendRef.current = autoSendToken
    handleSendMessage({ preventDefault: () => {} } as React.FormEvent)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSendToken, message, loading])

  // Phase 12K item 4 — the inbox button. A pill appears when there are pending
  // notifications / Needs-You items (server-computed badge); pressing it pulls
  // them into the conversation so David can address any subset in one reply, and
  // the ack tool (called by that reply) clears them. Manual twin of the automatic
  // return-recap. iOS gets the same via its own ChatScreen chip.
  const [inboxCount, setInboxCount] = useState(0)
  const [inboxSendToken, setInboxSendToken] = useState(0)
  const loadInboxCount = useCallback(async () => {
    try {
      const r = await fetch(`${APP_CONFIG.apiUrl}/api/assistant-inbox/badge`, { credentials: 'include' })
      if (r.ok) setInboxCount((await r.json()).badge || 0)
    } catch { /* noop */ }
  }, [])
  useEffect(() => {
    loadInboxCount()
    const id = setInterval(loadInboxCount, 30000)
    return () => clearInterval(id)
  }, [loadInboxCount])
  // Refetch right after a response completes (an ack in that turn drops the count).
  useEffect(() => { if (!loading) loadInboxCount() }, [loading, loadInboxCount])
  const lastInboxSendRef = useRef(0)
  useEffect(() => {
    if (!inboxSendToken || inboxSendToken === lastInboxSendRef.current) return
    if (!message.trim() || loading) return
    lastInboxSendRef.current = inboxSendToken
    handleSendMessage({ preventDefault: () => {} } as React.FormEvent)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inboxSendToken, message, loading])
  const openInbox = () => {
    if (loading) return
    // The server injects the full inbox on this turn (include_inbox). The typed
    // text is just David's cue to Sara; the authoritative item list is the digest.
    ;(window as any).__includeInbox = true
    setMessage("Walk me through my inbox — everything waiting for me right now.")
    setInboxSendToken((t) => t + 1)
  }

  // Handle text-to-speech for messages via the shared voice-agent endpoint
  // (same Kokoro backend the iOS app uses — see /api/voice-agent/speak).
  const handleSpeak = async (text: string, messageIndex: number) => {
    // Toggle off if this message is already speaking
    if (speakingMessageIndex === messageIndex) {
      currentAudioRef.current?.pause()
      currentAudioRef.current = null
      setSpeakingMessageIndex(null)
      return
    }
    // Switching messages mid-speech: stop the previous one first
    currentAudioRef.current?.pause()
    currentAudioRef.current = null

    setVoiceError(null)
    setSpeakingMessageIndex(messageIndex)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/voice-agent/speak`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, response_format: 'mp3' }),
      })
      if (!res.ok) throw new Error(`TTS service unavailable (${res.status})`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      currentAudioRef.current = audio
      audio.onended = () => {
        setSpeakingMessageIndex((cur) => (cur === messageIndex ? null : cur))
        URL.revokeObjectURL(url)
      }
      audio.onerror = () => {
        setVoiceError("Couldn't play that back")
        setSpeakingMessageIndex((cur) => (cur === messageIndex ? null : cur))
        URL.revokeObjectURL(url)
      }
      await audio.play()
    } catch (error) {
      console.error('[TTS] Error:', error)
      setVoiceError("Couldn't hear that — voice service unavailable")
      setSpeakingMessageIndex((cur) => (cur === messageIndex ? null : cur))
    }
  }

  // Mic recording -> transcribe -> populate the input (does not auto-send, so
  // the user can review/edit exactly like a typed message).
  const startRecording = async () => {
    setVoiceError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : MediaRecorder.isTypeSupported('audio/mp4')
          ? 'audio/mp4'
          : ''
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream)
      audioChunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data)
      }
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        void transcribeRecording()
      }
      mediaRecorderRef.current = recorder
      recorder.start()
      setIsRecording(true)
    } catch (error) {
      console.error('[Voice] Mic access failed:', error)
      setVoiceError("Couldn't access the microphone")
      setIsRecording(false)
    }
  }

  const stopRecording = () => {
    mediaRecorderRef.current?.stop()
    setIsRecording(false)
  }

  const transcribeRecording = async () => {
    if (audioChunksRef.current.length === 0) return
    setIsTranscribing(true)
    setVoiceError(null)
    try {
      const blob = new Blob(audioChunksRef.current, {
        type: mediaRecorderRef.current?.mimeType || 'audio/webm',
      })
      const formData = new FormData()
      formData.append('audio', blob, 'recording.webm')
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/voice-agent/transcribe`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (!res.ok) throw new Error(`Transcription service unavailable (${res.status})`)
      const data = await res.json()
      const transcription = (data.transcription || '').trim()
      if (!transcription) {
        setVoiceError("Couldn't hear that — try again")
        return
      }
      setMessage((prev) => (prev.trim() ? `${prev.trim()} ${transcription}` : transcription))
    } catch (error) {
      console.error('[Voice] Transcription error:', error)
      setVoiceError("Couldn't hear that — voice service unavailable")
    } finally {
      setIsTranscribing(false)
    }
  }

  // Load a past conversation into the chat (from the history drawer).
  // The save-active effect persists the selection once currentConversationId changes.
  const loadConversation = useCallback(async (conversationId: string) => {
    if (!conversationId || conversationId === currentConversationId) return
    try {
      setIsLoadingHistory(true)
      const res = await fetch(
        `${APP_CONFIG.apiUrl}/api/conversations/${conversationId}/messages?limit=100`,
        { credentials: 'include' }
      )
      if (!res.ok) {
        console.error('Failed to load conversation', conversationId)
        return
      }
      const data = await res.json()
      const loaded: ChatMessage[] = (data || []).map((ep: any) => ({
        role: ep.role,
        content: ep.content,
        timestamp: new Date(ep.created_at),
      }))
      setMessages(loaded)
      setCurrentConversationId(conversationId)
    } catch (error) {
      console.error('Error loading conversation:', error)
    } finally {
      setIsLoadingHistory(false)
    }
  }, [currentConversationId, setMessages])

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
      className={`relative flex h-full overflow-hidden ${isResizing ? 'select-none' : ''}`}
    >
      <ConversationHistoryDrawer
        open={showHistory}
        onClose={() => setShowHistory(false)}
        currentConversationId={currentConversationId}
        onSelect={loadConversation}
        onNewChat={handleNewChat}
      />

      {/* Main Chat Area - shrinks when canvas is open */}
      <div
        className={`flex flex-col min-w-0 ${!isResizing ? 'transition-all duration-300' : ''}`}
        style={{ width: canvasPanelOpen ? `${100 - canvasWidth}%` : '100%' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-2.5">
          <div className="flex min-w-0 items-baseline gap-3">
            <h2 className="font-display text-xl font-semibold text-white">Chat with Sara</h2>

            {/* Model Selector Dropdown */}
            <div className="relative" ref={modelDropdownRef}>
              <button
                onClick={() => setShowModelDropdown(!showModelDropdown)}
                className="flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-300"
              >
                <span className="max-w-[140px] truncate">
                  {availableModels?.models?.find(m => m.id === selectedModel)?.name || selectedModel}
                </span>
                <ChevronDown size={12} className={`transition-transform ${showModelDropdown ? 'rotate-180' : ''}`} />
              </button>

              {showModelDropdown && availableModels?.models && (
                <div className="absolute top-full left-0 z-50 mt-1.5 max-h-64 w-52 overflow-y-auto rounded-xl border border-white/10 bg-[#0c1626] py-1 shadow-[0_8px_40px_rgba(2,8,23,0.6)]">
                  {/* Group models by provider */}
                  {Object.entries(
                    availableModels.models.reduce((acc, model) => {
                      if (!acc[model.provider]) acc[model.provider] = []
                      acc[model.provider].push(model)
                      return acc
                    }, {} as Record<string, ChatModel[]>)
                  ).map(([provider, models]) => (
                    <div key={provider}>
                      <div className="px-3 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
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
                          className={`w-full px-3 py-1.5 text-left text-sm transition-colors hover:bg-white/[0.06] ${
                            model.id === selectedModel ? 'text-teal-300' : 'text-slate-300'
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

            {isEphemeral && (
              <span className="text-xs text-purple-300/80">ephemeral — not saved</span>
            )}
          </div>

          <div className="flex items-center gap-1">
            {/* Conversation history */}
            <button
              onClick={() => setShowHistory(true)}
              className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-teal-300"
              title="Conversation history"
            >
              <History size={18} />
            </button>

            {/* Ghost/Ephemeral Toggle */}
            <button
              onClick={() => setIsEphemeral(!isEphemeral)}
              className={`rounded-lg p-2 transition-colors ${
                isEphemeral
                  ? 'bg-purple-400/10 text-purple-300 hover:bg-purple-400/20'
                  : 'text-slate-500 hover:bg-white/[0.06] hover:text-purple-300'
              }`}
              title={isEphemeral ? "Ephemeral mode ON - chat won't be saved" : "Ephemeral mode OFF - chat will be saved"}
            >
              <Ghost size={18} />
            </button>

            <button
              onClick={handleNewChat}
              className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-teal-300"
              title="Start a new conversation"
            >
              <Plus size={18} />
            </button>
          </div>
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto w-full max-w-[75ch] space-y-6">
          {!hasUserMessages && (
            <div>
              <p className="text-sm text-slate-500">New conversation.</p>
              <div className="mt-4 space-y-1">
                <button
                  onClick={() => handleQuickAction('inbox_attention')}
                  className="flex w-full items-baseline justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/[0.04]"
                >
                  <span className="text-[15px] text-slate-200">Review attention inbox</span>
                  <span className="flex-shrink-0 text-xs text-slate-500">
                    {quickActionContext?.attentionUnreadCount || 0} unread
                  </span>
                </button>
                <button
                  onClick={() => handleQuickAction('missions')}
                  className="flex w-full items-baseline justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/[0.04]"
                >
                  <span className="text-[15px] text-slate-200">Open missions</span>
                  <span className="flex-shrink-0 text-xs text-slate-500">
                    {quickActionContext?.missionAwaitingCount || 0} awaiting · {quickActionContext?.runningMissionCount || 0} running
                  </span>
                </button>
                <button
                  onClick={() => handleQuickAction('standing_orders')}
                  className="flex w-full items-baseline justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/[0.04]"
                >
                  <span className="text-[15px] text-slate-200">Summarize standing orders</span>
                  <span className="flex-shrink-0 text-xs text-slate-500">
                    {quickActionContext?.standingOrdersCount || 0} active
                  </span>
                </button>
              </div>
            </div>
          )}

          {messages.map((msg, index) => {
            const messageText = getMessageText(msg.content)

            return (
            <div key={index} className={`group flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={msg.role === 'user' ? 'max-w-[85%] md:max-w-[75%]' : 'min-w-0 w-full'}>
                <div className={
                  msg.role === 'user'
                    ? 'rounded-2xl bg-teal-400/10 px-4 py-2.5 text-[15px] leading-relaxed text-slate-100'
                    : 'text-[15px] leading-relaxed text-slate-300'
                }>
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
                                <pre className="mt-2 mb-3 overflow-x-auto rounded-xl border border-white/10 bg-[#0a1322] p-4">
                                  <code className={`${className} text-[13px] text-slate-200`} {...rest}>
                                    {codeContent}
                                  </code>
                                </pre>
                              ) : (
                                <code className="rounded bg-white/[0.08] px-1.5 py-0.5 text-[13px] text-slate-200" {...rest}>
                                  {children}
                                </code>
                              )
                            },
                            p: ({children}) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
                            ul: ({children}) => <ul className="my-2 list-disc space-y-1 pl-5 marker:text-slate-600">{children}</ul>,
                            ol: ({children}) => <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-slate-600">{children}</ol>,
                            li: ({children}) => <li className="my-1 leading-relaxed">{children}</li>,
                            strong: ({children}) => <strong className="font-medium text-slate-100">{children}</strong>,
                            blockquote: ({children}) => (
                              <blockquote className="my-2 border-l-2 border-white/15 pl-4 text-slate-400">
                                {children}
                              </blockquote>
                            ),
                            h1: ({children}) => <h1 className="mb-1.5 mt-4 text-base font-semibold text-slate-100 first:mt-0">{children}</h1>,
                            h2: ({children}) => <h2 className="mb-1.5 mt-4 text-[15px] font-semibold text-slate-100 first:mt-0">{children}</h2>,
                            h3: ({children}) => <h3 className="mb-1 mt-3 text-[13px] font-semibold uppercase tracking-wide text-slate-400 first:mt-0">{children}</h3>,
                            hr: () => <hr className="my-4 border-white/8" />,
                            a: ({href, children}) => {
                              if (href && href.startsWith('#')) {
                                return (
                                  <span className="cursor-pointer text-xs text-teal-300 transition-colors hover:text-teal-200">
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
                                    className="inline-flex max-w-full cursor-pointer items-center gap-1 text-teal-300 no-underline transition-colors hover:text-teal-200"
                                    title="Click to download"
                                  >
                                    <span className="material-icons flex-shrink-0 text-xs" style={{fontSize: '14px'}}>attach_file</span>
                                    <span className="truncate">{children}</span>
                                  </a>
                                )
                              }
                              return (
                                <a
                                  href={href}
                                  className="inline-block max-w-full truncate align-bottom text-teal-300 underline decoration-teal-300/30 transition-colors hover:text-teal-200"
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  {children}
                                </a>
                              )
                            },
                            table: ({children}) => (
                              <div className="my-4 overflow-x-auto">
                                <table className="w-full border-collapse text-sm">
                                  {children}
                                </table>
                              </div>
                            ),
                            thead: ({children}) => <thead>{children}</thead>,
                            tbody: ({children}) => <tbody>{children}</tbody>,
                            tr: ({children}) => <tr className="border-b border-white/8 transition-colors hover:bg-white/[0.03]">{children}</tr>,
                            th: ({children}) => (
                              <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                                {children}
                              </th>
                            ),
                            td: ({children}) => (
                              <td className="px-3 py-2 text-slate-300">
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
                    <p className="whitespace-pre-wrap break-words">{messageText}</p>
                  )}

                  {/* Display attached documents for user messages */}
                  {msg.role === 'user' && msg.attachedDocuments && msg.attachedDocuments.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {msg.attachedDocuments.map((doc) => (
                        <div key={doc.id} className="flex items-center gap-1.5 text-xs text-teal-200/80">
                          <span className="material-icons text-sm">description</span>
                          <span className="truncate">
                            {doc.title || doc.original_filename}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {msg.role === 'assistant' && Array.isArray((msg as any).citations) && (msg as any).citations.length > 0 && (
                    <div className="mt-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Sources</div>
                      <ul className="mt-1 space-y-0.5">
                        {(msg as any).citations.slice(0,5).map((c: any, i: number) => (
                          <li key={i} className="truncate text-xs text-slate-500">
                            <a href={typeof c === 'string' ? c : c.url} target="_blank" rel="noreferrer" className="transition-colors hover:text-teal-300">
                              {typeof c === 'string' ? c : (c.title || c.url)}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <div className={`mt-1.5 flex items-center gap-2 text-xs text-slate-600 ${
                  msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'
                }`}>
                  <span>{msg.timestamp.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>

                  <div className="flex items-center gap-1">
                    {/* TTS button for assistant messages */}
                    {msg.role === 'assistant' && (
                      <button
                        onClick={() => handleSpeak(messageText, index)}
                        className={`rounded-md p-1 transition-colors ${
                          speakingMessageIndex === index
                            ? 'text-teal-300'
                            : 'text-slate-600 hover:text-slate-300'
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
              {isUsingTools && toolActivity ? (
                <span className="text-sm text-slate-500">{toolActivity}</span>
              ) : (
                <div className="flex items-center gap-1 py-1">
                  <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500"></div>
                  <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500" style={{animationDelay: '0.1s'}}></div>
                  <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500" style={{animationDelay: '0.2s'}}></div>
                </div>
              )}
            </div>
          )}

          <div ref={chatMessagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="border-t border-white/8 px-4">
          <div className="mx-auto w-full max-w-[75ch]">
            {/* Uploaded Documents Preview */}
            {uploadedDocuments.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-3">
                {uploadedDocuments.map((doc) => (
                  <div key={doc.id} className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs text-slate-300">
                    <span className="material-icons text-sm text-teal-300/80">description</span>
                    <span className="max-w-48 truncate">
                      {doc.title || doc.original_filename}
                    </span>
                    <button
                      onClick={() => removeUploadedDocument(doc.id)}
                      className="text-slate-500 transition-colors hover:text-rose-300"
                      type="button"
                    >
                      <span className="material-icons text-xs">close</span>
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Attached Images Preview */}
            {attachedImages.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-3">
                {attachedImages.map((img, idx) => (
                  <div key={idx} className="relative group">
                    <img
                      src={img.preview}
                      alt={`Attached ${idx + 1}`}
                      className="h-16 w-16 rounded-lg border border-white/10 object-cover"
                    />
                    <button
                      onClick={() => removeAttachedImage(idx)}
                      className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-white/10 bg-[#0c1626] text-xs text-slate-300 transition-colors hover:text-rose-300"
                      type="button"
                    >
                      <span className="material-icons text-xs">close</span>
                    </button>
                  </div>
                ))}
              </div>
            )}

            {inboxCount > 0 && !loading && (
              <button
                type="button"
                onClick={openInbox}
                className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-teal-300/30 bg-teal-500/10 px-3 py-1 text-xs font-medium text-teal-200 hover:bg-teal-500/20 transition-colors"
                title="Pull your pending notifications and inbox items into the chat"
              >
                📥 {inboxCount} waiting — address here
              </button>
            )}

            <form onSubmit={handleSendMessage} className="py-3">
              <div className="flex items-center gap-1 rounded-2xl border border-white/10 bg-white/[0.04] px-2 transition-colors focus-within:border-teal-300/30">
                <input
                  type="text"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder={APP_CONFIG.ui.chatPlaceholder}
                  className="min-w-0 flex-1 bg-transparent px-2 py-2.5 text-[15px] text-slate-100 placeholder-slate-500 outline-none"
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
                    className="flex items-center rounded-lg p-2 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200 disabled:opacity-40 tap-target"
                    title="Add image"
                  >
                    <span className="material-icons text-lg">add_photo_alternate</span>
                  </button>
                  {showImageMenu && (
                    <div className="absolute bottom-full left-0 z-50 mb-2 overflow-hidden rounded-xl border border-white/10 bg-[#0c1626] py-1 shadow-[0_8px_40px_rgba(2,8,23,0.6)]">
                      <button
                        type="button"
                        onClick={() => {
                          imageInputRef.current?.click()
                          setShowImageMenu(false)
                        }}
                        className="flex w-full items-center gap-2 whitespace-nowrap px-4 py-2 text-left text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
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
                        className="flex w-full items-center gap-2 whitespace-nowrap px-4 py-2 text-left text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
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
                  className="flex items-center rounded-lg p-2 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200 disabled:opacity-40 tap-target"
                  title="Upload document"
                >
                  {isUploading ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-transparent"></div>
                  ) : (
                    <span className="material-icons text-lg">attach_file</span>
                  )}
                </button>

                {/* Open Note in Canvas button */}
                <button
                  type="button"
                  onClick={() => setShowNoteSelector(true)}
                  disabled={isLoading}
                  className="flex items-center rounded-lg p-2 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200 disabled:opacity-40 tap-target"
                  title="Open note in canvas"
                >
                  <StickyNote size={18} />
                </button>

                {/* Mic button — record, transcribe via /api/voice-agent/transcribe,
                    populate the input for review before sending. */}
                <button
                  type="button"
                  onClick={isRecording ? stopRecording : startRecording}
                  disabled={isLoading || isTranscribing}
                  className={`flex items-center rounded-lg p-2 transition-colors disabled:opacity-40 tap-target ${
                    isRecording
                      ? 'animate-pulse text-rose-400 hover:text-rose-300'
                      : 'text-slate-500 hover:bg-white/[0.06] hover:text-slate-200'
                  }`}
                  title={isRecording ? 'Stop recording' : 'Speak your message'}
                >
                  {isTranscribing ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-transparent"></div>
                  ) : (
                    <span className="material-icons text-lg">{isRecording ? 'stop_circle' : 'mic'}</span>
                  )}
                </button>

                <button
                  type="submit"
                  disabled={isLoading || (!message.trim() && uploadedDocuments.length === 0 && attachedImages.length === 0)}
                  className="my-1 ml-1 flex items-center rounded-xl bg-teal-400/90 p-2 text-slate-950 transition-colors hover:bg-teal-300 disabled:cursor-not-allowed disabled:bg-white/[0.06] disabled:text-slate-600 tap-target"
                  aria-label="Send"
                >
                  <span className="material-icons text-lg">arrow_upward</span>
                </button>
              </div>
              {voiceError && (
                <div className="mt-1.5 px-2 text-xs text-rose-300">{voiceError}</div>
              )}
            </form>
          </div>
        </div>
      </div>

      {/* Resizable Divider */}
      {canvasPanelOpen && (
        <div
          className="group relative w-1 flex-shrink-0 cursor-col-resize bg-white/10 transition-colors hover:bg-teal-400/60"
          onMouseDown={handleResizeStart}
        >
          <div className="absolute inset-y-0 -left-1 -right-1 group-hover:bg-teal-400/20" />
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
          setCanvasDirectArtifact(null)
        }}
        artifactId={selectedArtifactId}
        conversationId={currentConversationId || undefined}
        width={canvasWidth}
        isResizing={isResizing}
        onOpenInStudio={(artifactId) => {
          window.dispatchEvent(new CustomEvent('navigate', {
            detail: { view: 'artifacts', params: artifactId ? { id: artifactId } : undefined }
          }))
        }}
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
        } : canvasDirectArtifact}
      />

      {/* Interactive Surface overlay */}
      <SurfacePanel surface={activeSurface} onClose={() => setActiveSurface(null)} />

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
