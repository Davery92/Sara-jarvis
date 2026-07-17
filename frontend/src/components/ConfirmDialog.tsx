import React from 'react'

interface ConfirmDialogProps {
  isOpen: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'danger' | 'neutral'
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!isOpen) return null

  const confirmClass =
    tone === 'danger'
      ? 'border-rose-400/20 bg-rose-400/12 text-rose-100 hover:bg-rose-400/18'
      : 'border-teal-300/20 bg-teal-300/12 text-teal-100 hover:bg-teal-300/18'

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/78 p-4 backdrop-blur-md">
      <div
        className="assistant-panel w-full max-w-md rounded-md p-6 shadow-[0_30px_90px_rgba(2,8,23,0.48)]"
        role="dialog"
        aria-modal="true"
      >
        <div className="assistant-kicker mb-3">{tone === 'danger' ? 'Confirm Destructive Action' : 'Confirm Action'}</div>
        <h3 className="font-display text-2xl font-semibold text-white">{title}</h3>
        <p className="mt-3 text-sm leading-relaxed text-slate-300">{message}</p>

        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="rounded-md border border-white/8 bg-white/[0.03] px-4 py-2.5 text-slate-300 transition hover:bg-white/[0.06] hover:text-white disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className={`rounded-md border px-4 py-2.5 transition disabled:opacity-50 ${confirmClass}`}
          >
            {busy ? 'Working...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
