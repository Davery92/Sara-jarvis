class ApiClient {
  private baseUrl: string = 'https://sara-api.avery.cloud'
  private token: string | null = null

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/$/, '') // Remove trailing slash
  }

  setToken(token: string | null) {
    this.token = token
  }

  async getToken(): Promise<string | null> {
    if (this.token) return this.token
    if (window.electronAPI) {
      this.token = await window.electronAPI.getAuthToken()
    }
    return this.token
  }

  private async getHeaders(): Promise<HeadersInit> {
    const token = await this.getToken()
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    return headers
  }

  // Error callback for auth failures and other errors
  private errorCallback: ((error: string) => void) | null = null

  setErrorCallback(callback: ((error: string) => void) | null) {
    this.errorCallback = callback
  }

  private reportError(message: string) {
    console.error('[API]', message)
    if (this.errorCallback) {
      this.errorCallback(message)
    }
  }

  async login(email: string, password: string): Promise<{ token: string | null; error?: string }> {
    try {
      const response = await fetch(`${this.baseUrl}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',  // Important: receive and store cookies
        body: JSON.stringify({ email, password }),
      })

      if (!response.ok) {
        let errorMessage = 'Login failed'
        try {
          const errorData = await response.json()
          errorMessage = errorData.detail || errorData.message || `Login failed (${response.status})`
        } catch {
          if (response.status === 401) {
            errorMessage = 'Invalid email or password'
          } else if (response.status === 403) {
            errorMessage = 'Access denied'
          } else if (response.status >= 500) {
            errorMessage = 'Server error. Please try again later.'
          }
        }
        this.reportError(errorMessage)
        return { token: null, error: errorMessage }
      }

      const data = await response.json()
      const token = data.access_token || data.token
      if (token) {
        this.token = token
        return { token }
      }
      const error = 'No token received from server'
      this.reportError(error)
      return { token: null, error }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Connection failed. Check your network.'
      this.reportError(message)
      return { token: null, error: message }
    }
  }

  async streamChat(
    message: string,
    onChunk: (chunk: string) => void,
    onComplete: () => void,
    onToolActivity?: (tool: string) => void
  ): Promise<void> {
    const token = await this.getToken()

    const response = await fetch(`${this.baseUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      credentials: 'include',  // Send cookies for auth
      body: JSON.stringify({
        messages: [{ role: 'user', content: message }]
      }),
    })

    if (!response.ok) {
      throw new Error(`Chat request failed: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let sseBuffer = ''
    let fullContent = ''

    try {
      while (true) {
        const { done, value } = await reader.read()

        if (done) {
          // Process any remaining buffer
          if (sseBuffer.trim()) {
            this.processSSEEvent(sseBuffer, onChunk, onComplete, onToolActivity, fullContent)
          }
          onComplete()
          break
        }

        // Append new data to buffer
        sseBuffer += decoder.decode(value, { stream: true })

        // Split on double newline (SSE event separator)
        const parts = sseBuffer.split('\n\n')

        // Keep the last incomplete part in the buffer
        sseBuffer = parts.pop() || ''

        // Process complete events
        for (const part of parts) {
          const result = this.processSSEEvent(part, onChunk, onComplete, onToolActivity, fullContent)
          if (result.done) {
            return
          }
          if (result.content) {
            fullContent = result.content
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  }

  private processSSEEvent(
    eventData: string,
    onChunk: (chunk: string) => void,
    onComplete: () => void,
    onToolActivity?: (tool: string) => void,
    currentContent: string = ''
  ): { done: boolean; content?: string } {
    // Find the data line
    const lines = eventData.split('\n')
    const dataLine = lines.find(line => line.startsWith('data: '))

    if (!dataLine) {
      return { done: false }
    }

    const jsonStr = dataLine.slice(6) // Remove 'data: ' prefix

    if (jsonStr === '[DONE]') {
      onComplete()
      return { done: true }
    }

    try {
      const parsed = JSON.parse(jsonStr)

      // Handle different event types from backend
      switch (parsed.type) {
        case 'text_chunk':
          // Backend sends { type: 'text_chunk', data: { content: '...', full_content: '...' } }
          if (parsed.data?.content) {
            onChunk(parsed.data.content)
          }
          return { done: false, content: parsed.data?.full_content || currentContent + (parsed.data?.content || '') }

        case 'final_response':
          // Complete response with citations
          if (parsed.data?.content && parsed.data.content !== currentContent) {
            // Send any remaining content
            const remaining = parsed.data.content.slice(currentContent.length)
            if (remaining) {
              onChunk(remaining)
            }
          }
          onComplete()
          return { done: true }

        case 'tool_executing':
          // Tool is being executed
          if (onToolActivity && parsed.data?.tool) {
            onToolActivity(parsed.data.tool)
          }
          return { done: false }

        case 'tool_calls_start':
          // Tools are about to be called
          if (onToolActivity && parsed.data?.tools) {
            parsed.data.tools.forEach((tool: string) => onToolActivity(tool))
          }
          return { done: false }

        case 'thinking':
          // Processing status
          return { done: false }

        case 'done':
          onComplete()
          return { done: true }

        case 'error':
          console.error('Chat error:', parsed.data?.message || parsed.message)
          onComplete()
          return { done: true }

        case 'response_ready':
          // Stream complete marker
          onComplete()
          return { done: true }

        default:
          // Fallback for legacy formats
          if (parsed.content) {
            onChunk(parsed.content)
          } else if (parsed.text) {
            onChunk(parsed.text)
          }
          return { done: false }
      }
    } catch (e) {
      // Not valid JSON, might be raw text
      if (jsonStr.trim()) {
        console.warn('Failed to parse SSE event:', jsonStr)
      }
      return { done: false }
    }
  }

  async transcribe(audioBlob: Blob): Promise<string> {
    const token = await this.getToken()

    const formData = new FormData()
    formData.append('audio', audioBlob, 'recording.webm')

    const response = await fetch(`${this.baseUrl}/api/voice-agent/transcribe`, {
      method: 'POST',
      headers: {
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`Transcription failed: ${response.status}`)
    }

    const data = await response.json()
    return data.transcription || data.text || ''
  }

  async speak(text: string): Promise<ArrayBuffer> {
    console.log('[API] speak() called, text length:', text.length)
    const token = await this.getToken()
    console.log('[API] speak() token present:', !!token)

    const url = `${this.baseUrl}/api/voice-agent/speak`
    console.log('[API] speak() URL:', url)

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ text }),
    })

    console.log('[API] speak() response status:', response.status)

    if (!response.ok) {
      const errorText = await response.text()
      console.error('[API] speak() error response:', errorText)
      throw new Error(`TTS failed: ${response.status} - ${errorText}`)
    }

    const buffer = await response.arrayBuffer()
    console.log('[API] speak() got buffer, size:', buffer.byteLength)
    return buffer
  }

  async getNotes(): Promise<Array<{ id: string; title: string; content: string }>> {
    const headers = await this.getHeaders()

    const response = await fetch(`${this.baseUrl}/notes`, {
      headers,
    })

    if (!response.ok) {
      throw new Error(`Failed to fetch notes: ${response.status}`)
    }

    return response.json()
  }

  async getNote(noteId: string): Promise<{ id: string; title: string; content: string } | null> {
    const headers = await this.getHeaders()

    try {
      const response = await fetch(`${this.baseUrl}/notes/${noteId}`, {
        headers,
      })

      if (!response.ok) {
        return null
      }

      return response.json()
    } catch {
      return null
    }
  }

  async searchNotes(query: string): Promise<Array<{ id: string; title: string; content: string }>> {
    const headers = await this.getHeaders()
    console.log('[ApiClient] searchNotes query:', query)
    console.log('[ApiClient] searchNotes baseUrl:', this.baseUrl)

    try {
      // Use /notes endpoint which has proper auth, then filter client-side
      const response = await fetch(`${this.baseUrl}/notes`, {
        headers,
        credentials: 'include',
      })

      console.log('[ApiClient] searchNotes response status:', response.status)

      if (!response.ok) {
        const errorText = await response.text()
        console.log('[ApiClient] searchNotes failed:', response.status, errorText)
        return []
      }

      const allNotes = await response.json() as Array<{ id: string; title: string; content: string }>
      console.log('[ApiClient] searchNotes got', allNotes.length, 'total notes')

      // Filter notes that match the query (case-insensitive)
      const lowerQuery = query.toLowerCase()
      const filtered = allNotes.filter(note =>
        note.title.toLowerCase().includes(lowerQuery) ||
        note.content.toLowerCase().includes(lowerQuery)
      )

      console.log('[ApiClient] searchNotes found:', filtered.length, 'matching notes')
      if (filtered.length > 0) {
        console.log('[ApiClient] First match:', filtered[0].title)
      }
      return filtered
    } catch (e) {
      console.error('[ApiClient] searchNotes error:', e)
      return []
    }
  }

  async getTimers(): Promise<Array<{ id: string; name: string; remaining_seconds: number }>> {
    const headers = await this.getHeaders()

    const response = await fetch(`${this.baseUrl}/timers`, {
      headers,
    })

    if (!response.ok) {
      throw new Error(`Failed to fetch timers: ${response.status}`)
    }

    return response.json()
  }

  async getActiveTimers(): Promise<Array<{ id: string; title: string; remaining_seconds: number }>> {
    const token = await this.getToken()
    console.log('[ApiClient] getActiveTimers called, token:', token ? 'present' : 'MISSING')

    try {
      const response = await fetch(`${this.baseUrl}/api/pi-dashboard/timers`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      })

      console.log('[ApiClient] getActiveTimers response:', response.status)

      if (!response.ok) {
        return []
      }

      const data = await response.json()
      console.log('[ApiClient] getActiveTimers data:', data)
      // The endpoint returns { timers: [...] }
      const timers = data.timers || data || []
      // Return only timers that are still running
      return timers.filter((t: { remaining_seconds: number }) => t.remaining_seconds > 0)
    } catch (e) {
      console.error('[ApiClient] getActiveTimers error:', e)
      return []
    }
  }
}

export const apiClient = new ApiClient()
export default apiClient
