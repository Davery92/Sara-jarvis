import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface InterestNode {
  id: string
  label: string
  description?: string
  fascination: number
  depth: number
  confidence: number
  status: string
  source?: string
  times_engaged?: number
  created_at: string
}

interface InterestEdge {
  id: string
  source_node_id: string
  target_node_id: string
  relationship?: string
  strength: number
}

interface GraphData {
  nodes: InterestNode[]
  edges: InterestEdge[]
  total: number
}

function FascinationBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="w-full bg-gray-700 rounded-full h-1.5">
      <div className={`${color} h-1.5 rounded-full`} style={{ width: `${Math.min(100, value)}%` }} />
    </div>
  )
}

export default function ACSInterestGraphSection() {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<InterestNode[] | null>(null)
  const [showFrontier, setShowFrontier] = useState(false)
  const [frontier, setFrontier] = useState<InterestNode[] | null>(null)

  const fetchGraph = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/interest-graph`, { credentials: 'include' })
      if (res.ok) {
        setData(await res.json())
        setError(null)
      } else {
        setError('Failed to load interest graph')
      }
    } catch {
      setError('Failed to load interest graph')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchGraph() }, [fetchGraph])

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) { setSearchResults(null); return }
    try {
      const res = await fetch(
        `${APP_CONFIG.apiUrl}/api/acs/interest-graph/search?q=${encodeURIComponent(searchQuery)}`,
        { credentials: 'include' }
      )
      if (res.ok) {
        const data = await res.json()
        setSearchResults(Array.isArray(data) ? data : data.results || data.nodes || [])
      }
    } catch { /* ignore */ }
  }, [searchQuery])

  const fetchFrontier = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/interest-graph/frontier`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setFrontier(Array.isArray(data) ? data : data.nodes || [])
        setShowFrontier(true)
      }
    } catch { /* ignore */ }
  }, [])

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>
  if (!data) return null

  const displayNodes = searchResults ?? (showFrontier && frontier ? frontier : data.nodes)

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="flex gap-4 text-sm">
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 px-4 py-2">
          <span className="text-gray-500">Nodes:</span>{' '}
          <span className="text-white font-medium">{data.total ?? data.nodes.length}</span>
        </div>
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 px-4 py-2">
          <span className="text-gray-500">Edges:</span>{' '}
          <span className="text-white font-medium">{data.edges.length}</span>
        </div>
      </div>

      {/* Search + Frontier */}
      <div className="flex gap-2">
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="Search interests..."
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-indigo-500"
        />
        <button onClick={handleSearch}
          className="px-3 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors">
          Search
        </button>
        <button onClick={() => { if (showFrontier) { setShowFrontier(false); setFrontier(null) } else fetchFrontier() }}
          className={`px-3 py-2 text-sm rounded-lg transition-colors ${
            showFrontier ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
          }`}>
          Frontier
        </button>
        {(searchResults || showFrontier) && (
          <button onClick={() => { setSearchResults(null); setShowFrontier(false); setSearchQuery('') }}
            className="px-3 py-2 text-sm bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg transition-colors">
            Clear
          </button>
        )}
      </div>

      {/* Node cards */}
      {displayNodes.length === 0 ? (
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-8 text-center">
          <p className="text-gray-400">No interests found.</p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {displayNodes.map(node => (
            <div key={node.id} className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-white font-medium">{node.label}</h3>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  node.status === 'active' ? 'bg-emerald-900/30 text-emerald-400' : 'bg-gray-700 text-gray-400'
                }`}>{node.status}</span>
              </div>
              {node.description && (
                <p className="text-xs text-gray-400 mb-2">{node.description}</p>
              )}
              <div className="space-y-1.5 mb-3">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-gray-500 w-20">Fascination</span>
                  <FascinationBar value={node.fascination} color="bg-indigo-500" />
                  <span className="text-gray-400 w-8 text-right">{Math.round(node.fascination)}</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-gray-500 w-20">Depth</span>
                  <FascinationBar value={node.depth} color="bg-emerald-500" />
                  <span className="text-gray-400 w-8 text-right">{Math.round(node.depth)}</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-gray-500 w-20">Confidence</span>
                  <FascinationBar value={node.confidence} color="bg-amber-500" />
                  <span className="text-gray-400 w-8 text-right">{Math.round(node.confidence)}</span>
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                {node.source && <span>{node.source}</span>}
                {node.times_engaged !== undefined && <span>{node.times_engaged} engagements</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
