import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, ExternalLink, X, Zap } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import type { IntelligenceWindowData } from '../../types'

interface IntelligenceContentProps {
  data: IntelligenceWindowData
  windowId: string
}

interface IntelligenceItem {
  id: string
  source: string
  source_category: string
  title: string
  summary: string | null
  url: string | null
  novelty_score: number
  relevance_score: number
  discovered_at: string | null
  dismissed: boolean
}

type CategoryFilter = 'all' | 'ai_research' | 'local_ai' | 'broader_tech'

const SOURCE_LABELS: Record<string, string> = {
  arxiv_cs_ai: 'arXiv AI', arxiv_cs_cl: 'arXiv CL', arxiv_cs_lg: 'arXiv ML',
  openai_blog: 'OpenAI', anthropic_blog: 'Anthropic', google_ai_blog: 'Google AI',
  meta_ai_blog: 'Meta AI', huggingface_papers: 'HF Papers',
  r_locallama: 'r/LocalLLaMA', r_machinelearning: 'r/ML', r_programming: 'r/prog',
  ollama_releases: 'Ollama', llamacpp_releases: 'llama.cpp',
  exllamav2_releases: 'ExLlamaV2', vllm_releases: 'vLLM',
  hackernews: 'HN', ars_technica: 'Ars', techcrunch: 'TC',
  krebs_on_security: 'Krebs', the_record: 'Record',
}

function scoreColor(score: number): string {
  if (score >= 0.8) return 'text-emerald-400'
  if (score >= 0.6) return 'text-teal-400'
  if (score >= 0.4) return 'text-yellow-400'
  return 'text-gray-500'
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const diffMs = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

export default function IntelligenceContent({ data }: IntelligenceContentProps) {
  const [items, setItems] = useState<IntelligenceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [category, setCategory] = useState<CategoryFilter>(
    (data.sourceCategory as CategoryFilter) || 'all'
  )

  const loadFeed = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: '30', offset: '0' })
      if (category !== 'all') params.set('source_category', category)

      const res = await fetch(
        `${APP_CONFIG.apiUrl}/api/intelligence/feed?${params}`,
        { credentials: 'include' }
      )
      if (res.ok) {
        const data = await res.json()
        setItems(data.items || [])
      }
    } catch (err) {
      console.error('Intelligence feed error:', err)
    } finally {
      setLoading(false)
    }
  }, [category])

  useEffect(() => { loadFeed() }, [loadFeed])

  const handleDismiss = async (id: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/intelligence/${id}/dismiss`, {
        method: 'POST', credentials: 'include',
      })
      setItems(prev => prev.filter(i => i.id !== id))
    } catch {}
  }

  const handleDigDeeper = async (id: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/intelligence/${id}/dig-deeper`, {
        method: 'POST', credentials: 'include',
      })
    } catch {}
  }

  const categories: { key: CategoryFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'ai_research', label: 'AI' },
    { key: 'local_ai', label: 'Local' },
    { key: 'broader_tech', label: 'Tech' },
  ]

  return (
    <div className="flex flex-col h-full text-canvas-text">
      {/* Toolbar */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-canvas-border">
        {categories.map(cat => (
          <button
            key={cat.key}
            onClick={() => setCategory(cat.key)}
            className={`px-2 py-0.5 rounded text-xs transition-colors ${
              category === cat.key
                ? 'bg-teal-500/20 text-teal-400'
                : 'text-canvas-muted hover:text-canvas-text'
            }`}
          >
            {cat.label}
          </button>
        ))}
        <div className="flex-1" />
        <button
          onClick={loadFeed}
          className="p-1 rounded hover:bg-canvas-hover text-canvas-muted"
          title="Refresh"
        >
          <RefreshCw size={12} />
        </button>
      </div>

      {/* Feed */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-canvas-muted text-xs">No items</div>
        ) : (
          <div className="divide-y divide-canvas-border">
            {items.map(item => (
              <div key={item.id} className="px-3 py-2 hover:bg-canvas-hover group">
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-[9px] text-canvas-muted bg-canvas-bg px-1 rounded">
                        {SOURCE_LABELS[item.source] || item.source}
                      </span>
                      <span className={`text-[9px] font-mono ${scoreColor(item.novelty_score)}`}>
                        N{(item.novelty_score * 100).toFixed(0)}
                      </span>
                      <span className={`text-[9px] font-mono ${scoreColor(item.relevance_score)}`}>
                        R{(item.relevance_score * 100).toFixed(0)}
                      </span>
                      <span className="text-[9px] text-canvas-muted">
                        {timeAgo(item.discovered_at)}
                      </span>
                    </div>
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-canvas-text hover:text-teal-400 line-clamp-2 leading-tight"
                      >
                        {item.title}
                      </a>
                    ) : (
                      <p className="text-xs text-canvas-text line-clamp-2 leading-tight">
                        {item.title}
                      </p>
                    )}
                  </div>
                  <div className="flex-shrink-0 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleDigDeeper(item.id)}
                      className="p-0.5 rounded hover:bg-indigo-900/40 text-indigo-400"
                      title="Dig deeper"
                    >
                      <Zap size={10} />
                    </button>
                    <button
                      onClick={() => handleDismiss(item.id)}
                      className="p-0.5 rounded hover:bg-red-900/30 text-canvas-muted"
                      title="Dismiss"
                    >
                      <X size={10} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
