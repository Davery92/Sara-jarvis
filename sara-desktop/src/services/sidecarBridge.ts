/**
 * Sidecar Bridge
 *
 * WebSocket client that connects to the Python sidecar's local server.
 * Receives wake word events, commands, and activity updates.
 */

type MessageHandler = (message: SidecarMessage) => void

export interface SidecarMessage {
  type: string
  [key: string]: unknown
}

export class SidecarBridge {
  private ws: WebSocket | null = null
  private url: string
  private handlers: Map<string, MessageHandler[]> = new Map()
  private reconnectTimeout: number | null = null
  private reconnectDelay = 250
  private maxReconnectDelay = 5000
  private isConnecting = false

  constructor(port: number = 9876) {
    this.url = `ws://127.0.0.1:${port}`
  }

  /**
   * Connect to the sidecar WebSocket server.
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return
    }

    this.isConnecting = true
    console.log('[SidecarBridge] Connecting to', this.url)

    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        console.log('[SidecarBridge] Connected')
        this.isConnecting = false
        this.reconnectDelay = 1000 // Reset delay on successful connect

        // Send auth token if available
        this.sendAuthToken()
      }

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as SidecarMessage
          this.handleMessage(message)
        } catch (error) {
          console.error('[SidecarBridge] Failed to parse message:', error)
        }
      }

      this.ws.onclose = () => {
        console.log('[SidecarBridge] Disconnected')
        this.ws = null
        this.isConnecting = false
        this.scheduleReconnect()
      }

      this.ws.onerror = (error) => {
        console.error('[SidecarBridge] Error:', error)
        this.isConnecting = false
      }

    } catch (error) {
      console.error('[SidecarBridge] Failed to connect:', error)
      this.isConnecting = false
      this.scheduleReconnect()
    }
  }

  /**
   * Disconnect from the sidecar.
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  /**
   * Schedule a reconnection attempt.
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return
    }

    console.log(`[SidecarBridge] Reconnecting in ${this.reconnectDelay}ms...`)

    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null
      this.connect()

      // Exponential backoff
      this.reconnectDelay = Math.min(
        this.reconnectDelay * 2,
        this.maxReconnectDelay
      )
    }, this.reconnectDelay)
  }

  /**
   * Send a message to the sidecar.
   */
  send(message: SidecarMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[SidecarBridge] Cannot send: not connected')
      return false
    }

    try {
      this.ws.send(JSON.stringify(message))
      return true
    } catch (error) {
      console.error('[SidecarBridge] Send error:', error)
      return false
    }
  }

  /**
   * Send auth token to sidecar.
   */
  private async sendAuthToken(): Promise<void> {
    if (typeof window !== 'undefined' && window.electronAPI) {
      const token = await window.electronAPI.getAuthToken()
      if (token) {
        this.send({ type: 'auth_token', token })
      }
    }
  }

  /**
   * Handle incoming message from sidecar.
   */
  private handleMessage(message: SidecarMessage): void {
    const handlers = this.handlers.get(message.type) || []
    const allHandlers = this.handlers.get('*') || []

    for (const handler of [...handlers, ...allHandlers]) {
      try {
        handler(message)
      } catch (error) {
        console.error('[SidecarBridge] Handler error:', error)
      }
    }
  }

  /**
   * Register a handler for a message type.
   * Use '*' to handle all messages.
   */
  on(type: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, [])
    }
    this.handlers.get(type)!.push(handler)

    // Return unsubscribe function
    return () => {
      const handlers = this.handlers.get(type)
      if (handlers) {
        const index = handlers.indexOf(handler)
        if (index >= 0) {
          handlers.splice(index, 1)
        }
      }
    }
  }

  /**
   * Check if connected.
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  // Convenience methods for common operations

  /**
   * Request a screenshot from the sidecar.
   */
  takeScreenshot(analyze: boolean = false, prompt?: string): boolean {
    return this.send({
      type: 'take_screenshot',
      analyze,
      analyze_prompt: prompt
    })
  }

  /**
   * Notify sidecar of configuration change.
   */
  updateConfig(config: Record<string, unknown>): boolean {
    return this.send({
      type: 'config_update',
      ...config
    })
  }

  /**
   * Send ping to check connection.
   */
  ping(): boolean {
    return this.send({ type: 'ping' })
  }
}

// Singleton instance
export const sidecarBridge = new SidecarBridge()

// Auto-connect when in Electron environment - connect immediately
if (typeof window !== 'undefined') {
  sidecarBridge.connect()
}
