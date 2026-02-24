import React from 'react'

interface AppErrorBoundaryState {
  hasError: boolean
  errorMessage: string
}

export default class AppErrorBoundary extends React.Component<React.PropsWithChildren, AppErrorBoundaryState> {
  constructor(props: React.PropsWithChildren) {
    super(props)
    this.state = { hasError: false, errorMessage: '' }
  }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error?.message || 'Unknown runtime error',
    }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('[Workbench] App crashed:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full bg-canvas-bg text-white flex items-center justify-center p-6">
          <div className="max-w-2xl w-full bg-canvas-surface border border-canvas-border rounded-xl p-5">
            <h1 className="text-xl font-semibold">Workspace encountered an error</h1>
            <p className="mt-2 text-canvas-muted text-sm">
              The app hit a runtime issue instead of loading the canvas.
            </p>
            <pre className="mt-4 p-3 rounded bg-canvas-bg text-red-300 text-xs overflow-auto whitespace-pre-wrap">
              {this.state.errorMessage}
            </pre>
            <div className="mt-4 flex gap-2">
              <button
                onClick={() => window.location.reload()}
                className="px-3 py-2 rounded bg-teal-600 hover:bg-teal-500 text-white text-sm"
              >
                Reload Workspace
              </button>
              <button
                onClick={() => this.setState({ hasError: false, errorMessage: '' })}
                className="px-3 py-2 rounded bg-canvas-elevated hover:bg-canvas-surface text-canvas-muted text-sm"
              >
                Try Continue
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
