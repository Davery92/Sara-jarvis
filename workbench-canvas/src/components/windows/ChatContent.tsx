import { useState, useRef, useEffect } from 'react'
import { MessageSquare, Send, Loader2, StopCircle, Wrench, Trash2, Ghost, ChevronDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { chatApi, workspaceApi, type ChatMessage, type StreamEvent, type ChatModel } from '../../services/api'
import { useCanvasStore } from '../../store/canvasStore'
import type { ChatWindowData, WindowType } from '../../types'

interface ChatContentProps {
  data: ChatWindowData
  windowId: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolActivity?: { tool: string; status: 'running' | 'done'; result?: string }[]
}

export default function ChatContent({ data }: ChatContentProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentToolActivity, setCurrentToolActivity] = useState<{ tool: string; status: 'running' | 'done' }[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:120b')
  const [isEphemeral, setIsEphemeral] = useState(false)
  const [showModelDropdown, setShowModelDropdown] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Fetch available models
  const { data: modelsData } = useQuery({
    queryKey: ['chat-models'],
    queryFn: chatApi.getModels,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  })

  // Set default model when loaded
  useEffect(() => {
    if (modelsData?.default && selectedModel === 'gpt-oss:120b') {
      setSelectedModel(modelsData.default)
    }
  }, [modelsData])

  // Group models by provider
  const groupedModels = modelsData?.models?.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = []
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ChatModel[]>) || {}

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    // Use scrollIntoView with block: 'nearest' to only scroll the immediate container
    // and prevent scrolling parent containers (which could affect the canvas)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, currentToolActivity])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Handle workspace commands from Sara's tools
  const handleWorkspaceCommand = (data: any) => {
    if (!data) return
    const { openWindow, closeWindow, bringToFront, windows, transform } = useCanvasStore.getState()
    const command = data.workspace_command

    console.log('[ChatContent] Workspace command:', command, data)

    switch (command) {
      case 'open_window': {
        // Special handling for note_editor - open specific note in its own window
        if (data.window_type === 'note_editor' && data.data?.note_id) {
          const { openNoteWindow } = useCanvasStore.getState()
          openNoteWindow(data.data.note_id, data.data.title || data.title || 'Note', data.data.content || '')
          break
        }

        // Map window_type to our WindowType
        const typeMap: Record<string, WindowType> = {
          notes: 'note',
          chat: 'chat',
          fitness: 'fitness',
          calendar: 'note', // Use note window for now
          tasks: 'note', // Use note window for now
          intelligence: 'note', // Use note window for now
          settings: 'settings',
        }
        const windowType = typeMap[data.window_type] || 'note'
        openWindow(windowType, data.data || {}, { title: data.title })
        break
      }

      case 'close_window': {
        // Find window by ID or title
        if (data.window_id) {
          closeWindow(data.window_id)
        } else if (data.window_title) {
          const targetWindow = windows.find(w =>
            w.title.toLowerCase().includes(data.window_title.toLowerCase())
          )
          if (targetWindow) {
            closeWindow(targetWindow.id)
          }
        }
        break
      }

      case 'focus_window': {
        // Find window by ID or title
        if (data.window_id) {
          bringToFront(data.window_id)
        } else if (data.window_title) {
          const targetWindow = windows.find(w =>
            w.title.toLowerCase().includes(data.window_title.toLowerCase())
          )
          if (targetWindow) {
            bringToFront(targetWindow.id)
          }
        }
        break
      }

      case 'save_state': {
        // Save current workspace state to server
        const stateData = {
          transform,
          windows: windows.map(w => ({
            id: w.id,
            type: w.type,
            title: w.title,
            position: w.position,
            size: w.size,
            zIndex: w.zIndex,
            data: w.data,
          })),
        }
        workspaceApi.saveState(stateData).then(() => {
          console.log('[ChatContent] Workspace state saved')
        }).catch(err => {
          console.error('[ChatContent] Failed to save workspace state:', err)
        })
        break
      }

      case 'arrange_windows': {
        // Window arrangement (tile, cascade, stack, center)
        // TODO: Implement arrangement logic in canvasStore
        console.log('[ChatContent] Arrange windows:', data.arrangement)
        break
      }

      case 'show_map': {
        // Show a map on the canvas
        const { addMap, updateMap, maps } = useCanvasStore.getState()
        const mapData = data.map
        if (!mapData) {
          console.warn('[ChatContent] show_map: No map data provided')
          break
        }

        // Check if map already exists on canvas
        const existingMap = maps.find(m => m.id === mapData.id)
        if (existingMap) {
          // Update existing map and uncollapse it
          updateMap(mapData.id, {
            mapData: mapData.map_data,
            collapsed: false,
          })
        } else {
          // Add new map to canvas
          const newMap = {
            id: mapData.id,
            name: mapData.name,
            description: mapData.description,
            mapData: mapData.map_data,
            isReadonly: mapData.is_readonly || false,
            canvasPosition: data.position || { x: 200, y: 200 },
            collapsed: data.collapsed || false,
          }
          addMap(newMap)
        }
        console.log('[ChatContent] Map shown:', mapData.name)
        break
      }

      case 'update_map': {
        // Update an existing map on the canvas
        const { updateMap: updateMapStore, maps: currentMaps, addMap: addMapStore } = useCanvasStore.getState()
        const updatedMapData = data.map
        console.log('[ChatContent] update_map received:', {
          mapId: updatedMapData?.id,
          mapName: updatedMapData?.name,
          hasMapData: !!updatedMapData?.map_data,
          currentMapsCount: currentMaps.length,
          currentMapIds: currentMaps.map(m => m.id)
        })

        if (!updatedMapData) {
          console.warn('[ChatContent] update_map: No map data provided')
          break
        }

        const mapToUpdate = currentMaps.find(m => m.id === updatedMapData.id)
        if (mapToUpdate) {
          updateMapStore(updatedMapData.id, {
            mapData: updatedMapData.map_data,
          })
          console.log('[ChatContent] Map updated successfully:', updatedMapData.name)
        } else {
          // Map not on canvas - add it
          console.log('[ChatContent] Map not on canvas, adding it:', updatedMapData.id)
          const newMap = {
            id: updatedMapData.id,
            name: updatedMapData.name,
            description: updatedMapData.description,
            mapData: updatedMapData.map_data,
            isReadonly: updatedMapData.is_readonly || false,
            canvasPosition: { x: 200, y: 200 },
            collapsed: false,
          }
          addMapStore(newMap)
          console.log('[ChatContent] Map added to canvas:', updatedMapData.name)
        }
        break
      }

      case 'hide_map':
      case 'collapse_map': {
        // Hide or collapse a map
        const { removeMap, collapseMap } = useCanvasStore.getState()
        if (command === 'hide_map') {
          removeMap(data.map_id)
        } else {
          collapseMap(data.map_id, true)
        }
        break
      }

      default:
        console.warn('[ChatContent] Unknown workspace command:', command)
    }
  }

  // Poll for pending workspace commands from voice/non-SSE sources
  useEffect(() => {
    const pollPendingCommands = async () => {
      try {
        const result = await workspaceApi.getPendingCommands()
        if (result.commands && result.commands.length > 0) {
          console.log('[ChatContent] Received pending workspace commands:', result.commands)
          for (const cmd of result.commands) {
            handleWorkspaceCommand(cmd)
          }
        }
      } catch (error) {
        // Silently ignore errors - this is just polling
      }
    }

    // Poll every 2 seconds
    const interval = setInterval(pollPendingCommands, 2000)

    // Initial poll
    pollPendingCommands()

    return () => clearInterval(interval)
  }, [])

  const handleSend = async () => {
    console.log('[ChatContent] handleSend called, input:', input, 'isStreaming:', isStreaming)
    if (!input.trim() || isStreaming) return

    console.log('[ChatContent] Sending message with model:', selectedModel, 'ephemeral:', isEphemeral)
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsStreaming(true)
    setCurrentToolActivity([])

    // Prepare messages for API
    const apiMessages: ChatMessage[] = [
      ...messages.map((m) => ({ role: m.role, content: m.content })),
      { role: 'user', content: userMessage.content },
    ]

    // Create abort controller
    abortControllerRef.current = new AbortController()

    // Create assistant message placeholder
    const assistantId = (Date.now() + 1).toString()
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: 'assistant', content: '' },
    ])

    try {
      console.log('[ChatContent] Calling chatApi.sendMessage with', apiMessages.length, 'messages')
      await chatApi.sendMessage(
        apiMessages,
        (event: StreamEvent) => {
          console.log('[ChatContent] Received event:', event.type)
          switch (event.type) {
            case 'content':
            case 'text_chunk':
              // Handle both 'content' and 'text_chunk' event types
              const textContent = event.content || event.data?.content || ''
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + textContent }
                    : m
                )
              )
              break

            case 'tool_start':
              setCurrentToolActivity((prev) => [
                ...prev,
                { tool: event.tool || 'unknown', status: 'running' },
              ])
              break

            case 'tool_end':
              setCurrentToolActivity((prev) =>
                prev.map((t) =>
                  t.tool === event.tool ? { ...t, status: 'done' } : t
                )
              )
              break

            case 'done':
            case 'final_response':
              // Attach tool activity to the message
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, toolActivity: currentToolActivity }
                    : m
                )
              )
              break

            case 'error':
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + `\n\nError: ${event.error}` }
                    : m
                )
              )
              break

            case 'workspace_command':
              // Handle workspace commands from Sara's tools
              handleWorkspaceCommand(event.data)
              break
          }
        },
        abortControllerRef.current.signal,
        { model: selectedModel, ephemeral: isEphemeral }
      )
    } catch (err: any) {
      console.error('[ChatContent] Error in sendMessage:', err)
      if (err.name !== 'AbortError') {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: m.content || 'Failed to get response. Please try again.' }
              : m
          )
        )
      }
    } finally {
      console.log('[ChatContent] sendMessage complete')
      setIsStreaming(false)
      setCurrentToolActivity([])
      abortControllerRef.current = null
    }
  }

  const handleStop = () => {
    abortControllerRef.current?.abort()
  }

  const handleClear = () => {
    setMessages([])
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Stop all keyboard events from bubbling to canvas/global handlers
    e.stopPropagation()

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Get display name for selected model
  const selectedModelName = modelsData?.models?.find(m => m.id === selectedModel)?.name || selectedModel

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Header */}
      <div className={`flex items-center justify-between px-4 py-2 border-b border-canvas-border ${isEphemeral ? 'bg-purple-500/10' : ''}`}>
        <div className="flex items-center gap-3">
          <MessageSquare size={18} className="text-teal-500" />

          {/* Model Selector Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowModelDropdown(!showModelDropdown)}
              className="flex items-center gap-1.5 px-2 py-1 bg-canvas-surface hover:bg-canvas-elevated rounded text-sm text-white transition-colors"
            >
              <span className="max-w-[120px] truncate">{selectedModelName}</span>
              <ChevronDown size={14} className={`text-canvas-muted transition-transform ${showModelDropdown ? 'rotate-180' : ''}`} />
            </button>

            {showModelDropdown && (
              <div className="absolute top-full left-0 mt-1 w-48 bg-canvas-surface border border-canvas-border rounded-lg shadow-xl z-50 py-1 max-h-64 overflow-y-auto custom-scrollbar">
                {Object.entries(groupedModels).map(([provider, models]) => (
                  <div key={provider}>
                    <div className="px-3 py-1 text-xs text-canvas-muted uppercase tracking-wider">
                      {provider === 'anthropic' ? 'Claude' : provider === 'google' ? 'Gemini' : 'Local'}
                    </div>
                    {models.map((model) => (
                      <button
                        key={model.id}
                        onClick={() => {
                          setSelectedModel(model.id)
                          setShowModelDropdown(false)
                        }}
                        className={`w-full px-3 py-1.5 text-left text-sm hover:bg-canvas-elevated transition-colors ${
                          model.id === selectedModel ? 'text-teal-400 bg-canvas-elevated' : 'text-white'
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

        <div className="flex items-center gap-1">
          {/* Ghost/Ephemeral Toggle */}
          <button
            onClick={() => setIsEphemeral(!isEphemeral)}
            className={`p-1.5 rounded transition-colors ${
              isEphemeral
                ? 'text-purple-400 bg-purple-500/20 hover:bg-purple-500/30'
                : 'text-canvas-muted hover:text-purple-400 hover:bg-canvas-surface'
            }`}
            title={isEphemeral ? 'Ephemeral mode ON - chat won\'t be saved' : 'Ephemeral mode OFF - chat will be saved'}
          >
            <Ghost size={16} />
          </button>

          {/* Clear Chat */}
          {messages.length > 0 && (
            <button
              onClick={handleClear}
              className="p-1.5 text-canvas-muted hover:text-red-400 hover:bg-canvas-surface rounded transition-colors"
              title="Clear chat"
            >
              <Trash2 size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4" data-scrollable="true">
        {messages.length === 0 && (
          <div className="text-center text-canvas-muted py-12">
            <MessageSquare size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg">Start a conversation</p>
            <p className="text-sm mt-1">Ask Sara anything</p>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {/* Tool activity during streaming */}
        {isStreaming && currentToolActivity.length > 0 && (
          <div className="flex flex-wrap gap-2 px-2">
            {currentToolActivity.map((activity, i) => (
              <div
                key={i}
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                  activity.status === 'running'
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : 'bg-green-500/20 text-green-400'
                }`}
              >
                <Wrench size={12} />
                {activity.tool}
                {activity.status === 'running' && (
                  <Loader2 size={10} className="animate-spin" />
                )}
              </div>
            ))}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-canvas-border">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Sara..."
            rows={1}
            className="flex-1 px-4 py-2.5 bg-canvas-surface rounded-lg border border-canvas-border text-white placeholder-canvas-muted resize-none focus:outline-none focus:border-teal-500"
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              onClick={handleStop}
              className="px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg transition-colors"
              title="Stop"
            >
              <StopCircle size={20} className="text-white" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="px-4 py-2 bg-teal-500 hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
              title="Send"
            >
              <Send size={20} className="text-white" />
            </button>
          )}
        </div>
        <div className="mt-2 text-xs text-canvas-muted text-center">
          Press Enter to send, Shift+Enter for new line
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-teal-600 text-white rounded-br-md'
            : 'bg-canvas-surface text-white rounded-bl-md'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="markdown-content prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content || '...'}
            </ReactMarkdown>
          </div>
        )}

        {/* Tool activity badges */}
        {message.toolActivity && message.toolActivity.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-white/10">
            {message.toolActivity.map((activity, i) => (
              <div
                key={i}
                className="flex items-center gap-1 px-1.5 py-0.5 bg-white/10 rounded text-xs text-white/70"
              >
                <Wrench size={10} />
                {activity.tool}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
