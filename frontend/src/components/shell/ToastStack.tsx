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
  onClearAll?: () => void
}

const VISIBLE_LIMIT = 3

const ToastStack: React.FC<ToastStackProps> = ({ toasts, onRemoveToast, onClearAll }) => {
  const toastToneMap = {
    success: { border: 'border-l-emerald-400/80', icon: 'check', iconClass: 'text-emerald-300' },
    error: { border: 'border-l-rose-400/80', icon: 'priority_high', iconClass: 'text-rose-300' },
    info: { border: 'border-l-sky-400/80', icon: 'info', iconClass: 'text-sky-300' },
  } as const

  const visible = toasts.slice(-VISIBLE_LIMIT)
  const hiddenCount = toasts.length - visible.length

  if (toasts.length === 0) return null

  return (
    <div className="fixed right-4 top-14 z-50 w-[340px] space-y-2">
      {hiddenCount > 0 && (
        <div className="flex items-center justify-between rounded-xl border border-white/8 bg-[#0c1626]/95 px-3 py-1.5 text-xs text-slate-400 shadow-lg backdrop-blur-xl">
          <span>{hiddenCount} earlier {hiddenCount === 1 ? 'notice' : 'notices'}</span>
          {onClearAll && (
            <button onClick={onClearAll} className="font-medium text-slate-300 transition hover:text-white">
              Clear all
            </button>
          )}
        </div>
      )}
      {visible.map((toast) => {
        const tone = toastToneMap[toast.type || 'info']

        return (
          <div
            key={toast.id}
            className={`flex items-start gap-2.5 rounded-xl border border-white/8 border-l-2 bg-[#0c1626]/95 py-2.5 pl-3 pr-2 shadow-[0_8px_30px_rgba(2,8,23,0.5)] backdrop-blur-xl transition-all duration-300 ${tone.border}`}
          >
            <span className={`material-icons mt-0.5 text-[16px] ${tone.iconClass}`}>{tone.icon}</span>
            <p className="min-w-0 flex-1 text-[13px] leading-snug text-slate-200">{toast.message}</p>
            <button
              onClick={() => onRemoveToast(toast.id)}
              className="rounded-md p-1 text-slate-500 transition hover:bg-white/[0.06] hover:text-white"
              title="Dismiss"
            >
              <span className="material-icons text-[14px]">close</span>
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default ToastStack
