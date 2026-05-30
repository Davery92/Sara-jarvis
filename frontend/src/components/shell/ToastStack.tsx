import React from 'react'

interface Toast {
  id: string | number
  message: string
  type?: 'success' | 'error' | 'info'
  persistent?: boolean
}

interface ToastStackProps {
  toasts: Toast[]
  onRemoveToast: (id: string | number) => void
}

const ToastStack: React.FC<ToastStackProps> = ({ toasts, onRemoveToast }) => {
  const toastToneMap = {
    success: {
      border: 'border-emerald-400/20',
      surface: 'bg-emerald-400/10',
      icon: 'check_circle',
      iconClass: 'text-emerald-300',
      meta: 'Action completed',
    },
    error: {
      border: 'border-rose-400/20',
      surface: 'bg-rose-400/10',
      icon: 'error',
      iconClass: 'text-rose-300',
      meta: 'Needs attention',
    },
    info: {
      border: 'border-sky-400/20',
      surface: 'bg-sky-400/10',
      icon: 'info',
      iconClass: 'text-sky-300',
      meta: 'Assistant update',
    },
  } as const

  return (
    <div className="fixed right-4 top-4 z-50 space-y-3">
      {toasts.map((toast) => {
        const tone = toastToneMap[toast.type || 'info']

        return (
        <div
          key={toast.id}
          className={`assistant-panel max-w-sm w-full rounded-md p-4 transition-all duration-300 ${tone.border} ${toast.persistent ? 'ring-1 ring-amber-300/50' : ''}`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <span className={`mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-md border border-white/8 ${tone.surface}`}>
                <span className={`material-icons text-[18px] ${tone.iconClass}`}>{tone.icon}</span>
              </span>
              <div className="min-w-0">
                <div className="assistant-kicker mb-2">{tone.meta}</div>
                <p className="text-sm font-medium leading-relaxed text-white">{toast.message}</p>
                {toast.persistent && (
                  <div className="mt-2 text-xs text-amber-300">
                    Click acknowledge to clear this notice.
                  </div>
                )}
              </div>
            </div>
            <button
              onClick={() => onRemoveToast(toast.id)}
              className="rounded-md border border-white/8 bg-white/[0.03] p-2 text-slate-400 transition hover:bg-white/[0.06] hover:text-white"
              title={toast.persistent ? 'Acknowledge' : 'Close'}
            >
              <span className="material-icons text-sm">
                {toast.persistent ? 'check' : 'close'}
              </span>
            </button>
          </div>
        </div>
        )
      })}
    </div>
  )
}

export default ToastStack
