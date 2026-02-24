import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'
import ReactMarkdown from 'react-markdown'

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
  included_in_digest_at: string | null
  notified_at: string | null
  dismissed: boolean
  created_at: string | null
}

type CategoryFilter = 'all' | 'ai_research' | 'local_ai' | 'broader_tech'
type ViewMode = 'feed' | 'digest'

const CATEGORY_LABELS: Record<string, string> = {
  ai_research: 'AI Research',
  local_ai: 'Local AI',
  broader_tech: 'Broader Tech',
}

const SOURCE_LABELS: Record<string, string> = {
  arxiv_cs_ai: 'arXiv AI',
  arxiv_cs_cl: 'arXiv CL',
  arxiv_cs_lg: 'arXiv ML',
  openai_blog: 'OpenAI',
  anthropic_blog: 'Anthropic',
  google_ai_blog: 'Google AI',
  meta_ai_blog: 'Meta AI',
  huggingface_papers: 'HF Papers',
  r_locallama: 'r/LocalLLaMA',
  r_machinelearning: 'r/ML',
  r_programming: 'r/programming',
  ollama_releases: 'Ollama',
  llamacpp_releases: 'llama.cpp',
  exllamav2_releases: 'ExLlamaV2',
  vllm_releases: 'vLLM',
  hackernews: 'Hacker News',
  ars_technica: 'Ars Technica',
  techcrunch: 'TechCrunch',
  krebs_on_security: 'Krebs',
  the_record: 'The Record',
}

function ScoreBadge({ score, label }: { score: number; label: string }) {
  let color = 'bg-gray-700 text-gray-300'
  if (score >= 0.8) color = 'bg-emerald-900/60 text-emerald-300'
  else if (score >= 0.6) color = 'bg-teal-900/50 text-teal-300'
  else if (score >= 0.4) color = 'bg-yellow-900/40 text-yellow-300'
  else color = 'bg-gray-800 text-gray-400'

  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${color}`}>
      {label} {(score * 100).toFixed(0)}
    </span>
  )
}

function SourceTag({ source }: { source: string }) {
  const label = SOURCE_LABELS[source] || source
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-800 text-gray-400 border border-gray-700">
      {label}
    </span>
  )
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

export default function IntelligenceFeed() {
  const [items, setItems] = useState<IntelligenceItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [category, setCategory] = useState<CategoryFilter>('all')
  const [viewMode, setViewMode] = useState<ViewMode>('feed')
  const [digest, setDigest] = useState<string | null>(null)
  const [digestLoading, setDigestLoading] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [offset, setOffset] = useState(0)
  const limit = 50

  const loadFeed = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      })
      if (category !== 'all') {
        params.set('source_category', category)
      }

      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/intelligence/feed?${params}`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setItems(data.items || [])
        setTotal(data.total || 0)
      }
    } catch (err) {
      console.error('Failed to load intelligence feed:', err)
    } finally {
      setLoading(false)
    }
  }, [category, offset])

  const loadDigest = useCallback(async () => {
    setDigestLoading(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/intelligence/digest`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setDigest(data.digest)
      }
    } catch (err) {
      console.error('Failed to load digest:', err)
    } finally {
      setDigestLoading(false)
    }
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/intelligence/stats`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setStats(data)
      }
    } catch (err) {
      // Non-critical
    }
  }, [])

  useEffect(() => {
    loadFeed()
    loadStats()
  }, [loadFeed, loadStats])

  useEffect(() => {
    if (viewMode === 'digest') {
      loadDigest()
    }
  }, [viewMode, loadDigest])

  const handleScanNow = async () => {
    setScanning(true)
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/intelligence/scan-now`, {
        method: 'POST',
        credentials: 'include',
      })
      // Poll for a bit, then reload
      setTimeout(() => {
        loadFeed()
        loadStats()
        setScanning(false)
      }, 3000)
    } catch (err) {
      setScanning(false)
    }
  }

  const handleDismiss = async (itemId: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/intelligence/${itemId}/dismiss`, {
        method: 'POST',
        credentials: 'include',
      })
      setItems(prev => prev.filter(i => i.id !== itemId))
    } catch (err) {
      console.error('Failed to dismiss:', err)
    }
  }

  const handleDigDeeper = async (itemId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/intelligence/${itemId}/dig-deeper`, {
        method: 'POST',
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        // Mark it visually
        setItems(prev => prev.map(i =>
          i.id === itemId ? { ...i, _researching: true } as any : i
        ))
        alert(`Research dispatched. Job ID: ${data.research_job_id || 'pending'}`)
      }
    } catch (err) {
      console.error('Failed to dispatch research:', err)
    }
  }

  const categories: { key: CategoryFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'ai_research', label: 'AI Research' },
    { key: 'local_ai', label: 'Local AI' },
    { key: 'broader_tech', label: 'Broader Tech' },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 bg-card border border-card rounded-xl p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold text-white">Intelligence Feed</h2>
            {stats && (
              <p className="text-xs text-gray-400 mt-0.5">
                {stats.last_24h} items in last 24h | {stats.total} total
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* View mode toggle */}
            <div className="flex bg-gray-800 rounded-lg p-0.5">
              <button
                onClick={() => setViewMode('feed')}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                  viewMode === 'feed'
                    ? 'bg-teal-500/20 text-teal-400'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                Feed
              </button>
              <button
                onClick={() => setViewMode('digest')}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                  viewMode === 'digest'
                    ? 'bg-teal-500/20 text-teal-400'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                Digest
              </button>
            </div>

            <button
              onClick={handleScanNow}
              disabled={scanning}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-50 transition-colors"
            >
              {scanning ? 'Scanning...' : 'Scan Now'}
            </button>
          </div>
        </div>

        {/* Category tabs */}
        {viewMode === 'feed' && (
          <div className="flex gap-2">
            {categories.map(cat => (
              <button
                key={cat.key}
                onClick={() => { setCategory(cat.key); setOffset(0) }}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  category === cat.key
                    ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800 border border-transparent'
                }`}
              >
                {cat.label}
                {stats?.by_category && cat.key !== 'all' && (
                  <span className="ml-1 text-[10px] opacity-60">
                    ({stats.by_category[cat.key] || 0})
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {viewMode === 'feed' ? (
          <>
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <div className="w-6 h-6 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
                <span className="ml-3 text-gray-400 text-sm">Loading feed...</span>
              </div>
            ) : items.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <p className="text-lg mb-2">No intelligence items yet</p>
                <p className="text-sm">Click "Scan Now" to start discovering.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {items.map(item => (
                  <div
                    key={item.id}
                    className="bg-card border border-card rounded-lg p-3 hover:border-gray-600 transition-colors group"
                  >
                    <div className="flex items-start gap-3">
                      {/* Main content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <SourceTag source={item.source} />
                          <ScoreBadge score={item.novelty_score} label="N" />
                          <ScoreBadge score={item.relevance_score} label="R" />
                          <span className="text-[10px] text-gray-500">
                            {timeAgo(item.discovered_at)}
                          </span>
                        </div>

                        {item.url ? (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm font-medium text-gray-200 hover:text-teal-400 transition-colors line-clamp-2"
                          >
                            {item.title}
                          </a>
                        ) : (
                          <p className="text-sm font-medium text-gray-200 line-clamp-2">
                            {item.title}
                          </p>
                        )}

                        {item.summary && (
                          <p className="text-xs text-gray-400 mt-1 line-clamp-2">
                            {item.summary}
                          </p>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex-shrink-0 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => handleDigDeeper(item.id)}
                          className="px-2 py-1 rounded text-[10px] font-medium bg-indigo-900/40 text-indigo-300 hover:bg-indigo-800/60 transition-colors"
                          title="Dig deeper - dispatch research agent"
                        >
                          Dig Deeper
                        </button>
                        <button
                          onClick={() => handleDismiss(item.id)}
                          className="px-2 py-1 rounded text-[10px] font-medium bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300 transition-colors"
                          title="Not interested"
                        >
                          Dismiss
                        </button>
                      </div>
                    </div>
                  </div>
                ))}

                {/* Pagination */}
                {total > limit && (
                  <div className="flex items-center justify-center gap-4 py-4">
                    <button
                      onClick={() => setOffset(Math.max(0, offset - limit))}
                      disabled={offset === 0}
                      className="px-3 py-1.5 rounded-md text-sm text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed bg-gray-800 hover:bg-gray-700"
                    >
                      Previous
                    </button>
                    <span className="text-xs text-gray-500">
                      {offset + 1}-{Math.min(offset + limit, total)} of {total}
                    </span>
                    <button
                      onClick={() => setOffset(offset + limit)}
                      disabled={offset + limit >= total}
                      className="px-3 py-1.5 rounded-md text-sm text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed bg-gray-800 hover:bg-gray-700"
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          /* Digest view */
          <div className="bg-card border border-card rounded-xl p-6">
            {digestLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="w-6 h-6 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
                <span className="ml-3 text-gray-400 text-sm">Loading digest...</span>
              </div>
            ) : digest ? (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{digest}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-500">
                <p className="text-lg mb-2">No digest available</p>
                <p className="text-sm">
                  Digests are generated at 12:30 PM and 6:30 PM, or after scans find enough items.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
