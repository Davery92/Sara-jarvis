import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Archive, Check, ChevronDown, ChevronRight, AlertTriangle, AlertCircle, Info, Bell, Loader2 } from 'lucide-react'
import { attentionApi } from '../services/api'
import type { AttentionItem } from '../types/sara'

interface AttentionFeedPanelProps {
  isOpen: boolean
  onClose: () => void
}

const PRIORITY_CONFIG: Record<string, { color: string; barColor: string; icon: typeof AlertTriangle }> = {
  critical: { color: 'text-red-400', barColor: 'bg-red-500', icon: AlertTriangle },
  urgent: { color: 'text-orange-400', barColor: 'bg-orange-500', icon: AlertCircle },
  high: { color: 'text-yellow-400', barColor: 'bg-yellow-500', icon: AlertCircle },
  normal: { color: 'text-blue-400', barColor: 'bg-blue-500', icon: Info },
  low: { color: 'text-gray-400', barColor: 'bg-gray-500', icon: Bell },
}

const PRIORITY_ORDER = ['critical', 'urgent', 'high', 'normal', 'low']

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export default function AttentionFeedPanel({ isOpen, onClose }: AttentionFeedPanelProps) {
  const queryClient = useQueryClient()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: items = [], isLoading } = useQuery<AttentionItem[]>({
    queryKey: ['attention-items'],
    queryFn: () => attentionApi.getItems('new,sent'),
    refetchInterval: 30_000,
    enabled: isOpen,
  })

  const markReadMutation = useMutation({
    mutationFn: attentionApi.markRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attention-items'] })
      queryClient.invalidateQueries({ queryKey: ['attention-count'] })
    },
  })

  const archiveMutation = useMutation({
    mutationFn: attentionApi.archive,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attention-items'] })
      queryClient.invalidateQueries({ queryKey: ['attention-count'] })
    },
  })

  const archiveAllMutation = useMutation({
    mutationFn: attentionApi.archiveAll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attention-items'] })
      queryClient.invalidateQueries({ queryKey: ['attention-count'] })
    },
  })

  // Sort by priority then recency
  const sortedItems = [...items].sort((a, b) => {
    const pa = PRIORITY_ORDER.indexOf(a.priority)
    const pb = PRIORITY_ORDER.indexOf(b.priority)
    if (pa !== pb) return pa - pb
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })

  return (
    <div
      className={`fixed top-0 right-0 h-full w-[380px] z-[45] bg-canvas-bg border-l border-canvas-border shadow-2xl transition-transform duration-300 ease-out ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-canvas-border">
        <div className="flex items-center gap-2">
          <Bell size={18} className="text-teal-500" />
          <h2 className="text-white font-semibold">Attention</h2>
          {items.length > 0 && (
            <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 text-xs rounded-full font-medium">
              {items.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {items.length > 0 && (
            <button
              onClick={() => archiveAllMutation.mutate()}
              disabled={archiveAllMutation.isPending}
              className="px-2 py-1 text-xs text-canvas-muted hover:text-white hover:bg-canvas-surface rounded transition-colors"
              title="Archive all"
            >
              {archiveAllMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Archive All'}
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 text-canvas-muted hover:text-white hover:bg-canvas-surface rounded transition-colors"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Items List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar" style={{ height: 'calc(100% - 57px)' }}>
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-canvas-muted">
            <Loader2 size={20} className="animate-spin mr-2" />
            Loading...
          </div>
        ) : sortedItems.length === 0 ? (
          <div className="text-center py-16 text-canvas-muted">
            <Bell size={40} className="mx-auto mb-3 opacity-20" />
            <p className="text-sm">No attention items</p>
            <p className="text-xs mt-1 text-canvas-muted/60">Sara will surface things when they matter</p>
          </div>
        ) : (
          <div className="divide-y divide-canvas-border/50">
            {sortedItems.map((item) => {
              const config = PRIORITY_CONFIG[item.priority] || PRIORITY_CONFIG.normal
              const Icon = config.icon
              const isExpanded = expandedId === item.id
              const isNew = item.status === 'new'

              return (
                <div
                  key={item.id}
                  className={`relative group ${isNew ? 'bg-canvas-surface/30' : ''}`}
                >
                  {/* Priority bar */}
                  <div className={`absolute left-0 top-0 bottom-0 w-1 ${config.barColor}`} />

                  <div className="pl-4 pr-3 py-3">
                    {/* Title row */}
                    <button
                      onClick={() => {
                        setExpandedId(isExpanded ? null : item.id)
                        if (isNew) markReadMutation.mutate(item.id)
                      }}
                      className="flex items-start gap-2 w-full text-left"
                    >
                      <Icon size={14} className={`${config.color} mt-0.5 flex-shrink-0`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-sm ${isNew ? 'text-white font-medium' : 'text-white/80'} line-clamp-2`}>
                            {item.title}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[10px] text-canvas-muted">{timeAgo(item.created_at)}</span>
                          {item.source && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-canvas-surface rounded text-canvas-muted">
                              {item.source}
                            </span>
                          )}
                          {item.category && (
                            <span className="text-[10px] text-canvas-muted/60">{item.category}</span>
                          )}
                        </div>
                      </div>
                      {isExpanded ? (
                        <ChevronDown size={14} className="text-canvas-muted flex-shrink-0 mt-0.5" />
                      ) : (
                        <ChevronRight size={14} className="text-canvas-muted flex-shrink-0 mt-0.5" />
                      )}
                    </button>

                    {/* Expanded body */}
                    {isExpanded && item.body && (
                      <div className="mt-2 ml-6 text-sm text-canvas-muted/90 whitespace-pre-wrap leading-relaxed">
                        {item.body}
                      </div>
                    )}

                    {/* Actions (visible on hover or expanded) */}
                    <div className={`flex items-center gap-1 ml-6 mt-2 ${isExpanded ? '' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
                      {isNew && (
                        <button
                          onClick={() => markReadMutation.mutate(item.id)}
                          className="flex items-center gap-1 px-2 py-1 text-xs text-canvas-muted hover:text-green-400 hover:bg-canvas-surface rounded transition-colors"
                        >
                          <Check size={12} />
                          Read
                        </button>
                      )}
                      <button
                        onClick={() => archiveMutation.mutate(item.id)}
                        className="flex items-center gap-1 px-2 py-1 text-xs text-canvas-muted hover:text-orange-400 hover:bg-canvas-surface rounded transition-colors"
                      >
                        <Archive size={12} />
                        Archive
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
