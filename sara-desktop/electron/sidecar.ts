/**
 * Sidecar Process Manager
 *
 * Manages the Python sidecar process that handles:
 * - Wake word detection
 * - Activity monitoring
 * - Screenshot capture
 * - Backend communication
 */
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'
import { app } from 'electron'

export class SidecarManager {
  private process: ChildProcess | null = null
  private restartCount = 0
  private maxRestarts = 5
  private restartDelay = 5000
  private isQuitting = false

  /**
   * Get the path to the sidecar executable.
   * In development, runs Python directly.
   * In production, uses PyInstaller executable.
   */
  private getSidecarPath(): { command: string; args: string[] } {
    const resourcesPath = process.resourcesPath || path.join(__dirname, '..')

    if (app.isPackaged) {
      // Production: use bundled executable
      const exeName = process.platform === 'win32' ? 'sidecar.exe' : 'sidecar'
      const exePath = path.join(resourcesPath, 'sidecar', exeName)

      if (fs.existsSync(exePath)) {
        return { command: exePath, args: [] }
      }

      // Fallback: try running Python script
      console.warn('[Sidecar] Executable not found, trying Python fallback')
    }

    // Development: run Python directly
    const sidecarDir = path.join(__dirname, '..', 'sidecar')
    const mainPy = path.join(sidecarDir, 'main.py')

    // Try to find Python
    const pythonCommands = process.platform === 'win32'
      ? ['python', 'python3', 'py']
      : ['python3', 'python']

    for (const cmd of pythonCommands) {
      try {
        require('child_process').execSync(`${cmd} --version`, { stdio: 'ignore' })
        return { command: cmd, args: [mainPy] }
      } catch {
        // Continue to next command
      }
    }

    console.error('[Sidecar] Python not found')
    return { command: '', args: [] }
  }

  /**
   * Start the sidecar process.
   */
  async start(): Promise<boolean> {
    if (this.process) {
      console.log('[Sidecar] Already running')
      return true
    }

    const { command, args } = this.getSidecarPath()

    if (!command) {
      console.error('[Sidecar] Cannot start: no command found')
      return false
    }

    console.log(`[Sidecar] Starting: ${command} ${args.join(' ')}`)

    try {
      this.process = spawn(command, args, {
        cwd: path.join(__dirname, '..', 'sidecar'),
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
        },
      })

      // Log stdout
      this.process.stdout?.on('data', (data: Buffer) => {
        const lines = data.toString().trim().split('\n')
        for (const line of lines) {
          console.log(`[Sidecar] ${line}`)
        }
      })

      // Log stderr
      this.process.stderr?.on('data', (data: Buffer) => {
        const lines = data.toString().trim().split('\n')
        for (const line of lines) {
          console.error(`[Sidecar] ${line}`)
        }
      })

      // Handle exit
      this.process.on('exit', (code, signal) => {
        console.log(`[Sidecar] Exited with code ${code}, signal ${signal}`)
        this.process = null

        // Auto-restart unless quitting
        if (!this.isQuitting && this.restartCount < this.maxRestarts) {
          this.restartCount++
          console.log(`[Sidecar] Restarting (attempt ${this.restartCount}/${this.maxRestarts})...`)
          setTimeout(() => this.start(), this.restartDelay)
        }
      })

      // Handle error
      this.process.on('error', (err) => {
        console.error('[Sidecar] Error:', err.message)
        this.process = null
      })

      // Reset restart count on successful start
      this.restartCount = 0
      console.log('[Sidecar] Started successfully')
      return true

    } catch (error) {
      console.error('[Sidecar] Failed to start:', error)
      return false
    }
  }

  /**
   * Stop the sidecar process.
   */
  async stop(): Promise<void> {
    this.isQuitting = true

    if (!this.process) {
      return
    }

    console.log('[Sidecar] Stopping...')

    const proc = this.process
    if (!proc) {
      return
    }

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        console.log('[Sidecar] Force killing...')
        proc.kill('SIGKILL')
        this.process = null
        resolve()
      }, 5000)

      proc.once('exit', () => {
        clearTimeout(timeout)
        this.process = null
        console.log('[Sidecar] Stopped')
        resolve()
      })

      // Send SIGTERM for graceful shutdown
      proc.kill('SIGTERM')
    })
  }

  /**
   * Check if sidecar is running.
   */
  isRunning(): boolean {
    return this.process !== null
  }

  /**
   * Restart the sidecar process.
   */
  async restart(): Promise<boolean> {
    await this.stop()
    this.isQuitting = false
    this.restartCount = 0
    return this.start()
  }
}

// Singleton instance
export const sidecarManager = new SidecarManager()
