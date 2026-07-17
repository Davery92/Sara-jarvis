import React, { useState, useEffect, useCallback, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_URL || 'http://10.185.1.180:8000'

interface PKGNode {
  id: string
  type: string
  confidence: number
  times_confirmed?: number
  [key: string]: any
}

interface PKGEdge {
  source: string
  target: string
  type: string
}

interface PKGContentProps {
  data: { category?: string }
  windowId: string
}

const TYPE_COLORS: Record<string, string> = {
  Person: '#60a5fa',     // blue
  Preference: '#34d399', // green
  Routine: '#a78bfa',    // purple
  Goal: '#fbbf24',       // gold
  Interest: '#f472b6',   // pink
  Health: '#fb923c',     // orange
  Place: '#2dd4bf',      // teal
  Fact: '#94a3b8',       // gray
}

export default function PKGContent({ data, windowId }: PKGContentProps) {
  const [nodes, setNodes] = useState<PKGNode[]>([])
  const [edges, setEdges] = useState<PKGEdge[]>([])
  const [stats, setStats] = useState<any>(null)
  const [selectedNode, setSelectedNode] = useState<PKGNode | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>(data?.category || '')
  const [searchQuery, setSearchQuery] = useState('')
  const [view, setView] = useState<'graph' | 'list'>('list')
  const [loading, setLoading] = useState(true)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: '100' })
      if (filterCategory) params.append('category', filterCategory)
      if (searchQuery) params.append('search', searchQuery)

      const [browseRes, statsRes, graphRes] = await Promise.all([
        fetch(`${API_BASE}/api/pkg/browse?${params}`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/pkg/stats`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/pkg/graph?limit=100`, { credentials: 'include' }),
      ])

      if (browseRes.ok) {
        const browseData = await browseRes.json()
        // Ensure unique nodes by pkg_id
        const seen = new Set<string>()
        const uniqueFacts = (browseData.facts || []).filter((f: any) => {
          if (!f.pkg_id || seen.has(f.pkg_id)) return false
          seen.add(f.pkg_id)
          return true
        })
        setNodes(uniqueFacts.map((f: any) => ({ ...f, id: f.pkg_id })))
      }
      if (statsRes.ok) setStats(await statsRes.json())
      if (graphRes.ok) {
        const gd = await graphRes.json()
        setEdges(gd.edges || [])
      }
    } catch (e) {
      console.error('PKG fetch failed:', e)
    }
    setLoading(false)
  }, [filterCategory, searchQuery])

  useEffect(() => { fetchData() }, [fetchData])

  // Simple canvas graph rendering
  useEffect(() => {
    if (view !== 'graph' || !canvasRef.current || nodes.length === 0) return

    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const w = canvas.width = canvas.parentElement?.clientWidth || 600
    const h = canvas.height = canvas.parentElement?.clientHeight || 400

    // Position nodes in a force-directed-like layout (simple circular)
    const positions: Record<string, { x: number; y: number }> = {}
    const cx = w / 2
    const cy = h / 2
    const radius = Math.min(w, h) * 0.35

    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / nodes.length
      positions[node.id] = {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      }
    })

    // Draw
    ctx.clearRect(0, 0, w, h)

    // Edges
    ctx.strokeStyle = 'rgba(255,255,255,0.1)'
    ctx.lineWidth = 1
    edges.forEach(edge => {
      const from = positions[edge.source]
      const to = positions[edge.target]
      if (from && to) {
        ctx.beginPath()
        ctx.moveTo(from.x, from.y)
        ctx.lineTo(to.x, to.y)
        ctx.stroke()
      }
    })

    // Nodes
    nodes.forEach(node => {
      const pos = positions[node.id]
      if (!pos) return
      const color = TYPE_COLORS[node.type] || '#94a3b8'
      const size = 4 + (node.confidence || 0.5) * 8

      ctx.beginPath()
      ctx.arc(pos.x, pos.y, size, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()

      // Label
      ctx.fillStyle = 'rgba(255,255,255,0.6)'
      ctx.font = '10px system-ui'
      ctx.textAlign = 'center'
      const label = node.name || node.topic || node.activity || node.description?.slice(0, 15) || node.type
      ctx.fillText(label, pos.x, pos.y + size + 12)
    })
  }, [view, nodes, edges])

  const handleDelete = async (nodeId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/pkg/${nodeId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (res.ok) {
        setNodes(prev => prev.filter(n => n.id !== nodeId))
        setSelectedNode(null)
      }
    } catch (e) {
      console.error('Delete failed:', e)
    }
  }

  const categories = ['Person', 'Preference', 'Routine', 'Goal', 'Interest', 'Health', 'Place', 'Fact']

  return (
    <div className="h-full flex flex-col bg-[#1a1a2e] text-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <span className="text-lg">🧠</span>
          <span className="font-medium">Personal Knowledge Graph</span>
          {stats && <span className="text-xs text-white/40">{stats.total || 0} facts</span>}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setView(view === 'list' ? 'graph' : 'list')}
            className={`px-2 py-1 text-xs rounded ${view === 'graph' ? 'bg-purple-600' : 'bg-white/10'}`}
          >
            {view === 'list' ? 'Graph' : 'List'}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 p-2 border-b border-white/5">
        <input
          type="text"
          placeholder="Search..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          className="bg-white/5 text-white text-xs rounded px-2 py-1 flex-1 outline-none"
        />
        <select
          value={filterCategory}
          onChange={e => setFilterCategory(e.target.value)}
          className="bg-white/5 text-white text-xs rounded px-2 py-1 outline-none"
        >
          <option value="">All types</option>
          {categories.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {/* Stats bar */}
      {stats?.by_type && (
        <div className="flex items-center gap-1 px-3 py-1 border-b border-white/5 overflow-x-auto">
          {Object.entries(stats.by_type).map(([type, count]: [string, any]) => (
            count > 0 && (
              <span
                key={type}
                className="text-[10px] px-1.5 py-0.5 rounded-full whitespace-nowrap cursor-pointer"
                style={{ backgroundColor: TYPE_COLORS[type] + '20', color: TYPE_COLORS[type] }}
                onClick={() => setFilterCategory(filterCategory === type ? '' : type)}
              >
                {type}: {count}
              </span>
            )
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-hidden flex">
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-white/40">Loading...</div>
        ) : view === 'graph' ? (
          <div className="flex-1 relative">
            <canvas ref={canvasRef} className="w-full h-full" />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {nodes.length === 0 ? (
              <div className="text-center text-white/30 py-8">No facts found</div>
            ) : (
              nodes.map(node => (
                <div
                  key={node.id}
                  className={`p-2 rounded cursor-pointer transition-colors ${
                    selectedNode?.id === node.id ? 'bg-white/10' : 'hover:bg-white/5'
                  }`}
                  onClick={() => setSelectedNode(selectedNode?.id === node.id ? null : node)}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: TYPE_COLORS[node.type] || '#94a3b8' }}
                    />
                    <span className="text-xs font-medium" style={{ color: TYPE_COLORS[node.type] }}>
                      {node.type}
                    </span>
                    <span className="text-xs text-white/70 flex-1 truncate">
                      {formatNodeSummary(node)}
                    </span>
                    <span className="text-[10px] text-white/30">
                      {(node.confidence * 100).toFixed(0)}%
                    </span>
                  </div>

                  {selectedNode?.id === node.id && (
                    <div className="mt-2 pl-4 space-y-1 text-[11px]">
                      {Object.entries(node)
                        .filter(([k]) => !['id', 'type', 'pkg_id', 'dedup_key', 'version', 'superseded_by'].includes(k))
                        .map(([k, v]) => (
                          <div key={k} className="flex gap-2">
                            <span className="text-white/30 w-24 flex-shrink-0">{k}:</span>
                            <span className="text-white/60">{String(v)}</span>
                          </div>
                        ))
                      }
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(node.id) }}
                        className="mt-1 text-red-400/60 hover:text-red-400 text-[10px]"
                      >
                        Delete this fact
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function formatNodeSummary(node: PKGNode): string {
  switch (node.type) {
    case 'Person': return `${node.name || '?'} — ${node.relationship_to_david || ''}`
    case 'Preference': return `${node.domain}/${node.key}: ${node.value} (${node.strength})`
    case 'Routine': return `${node.activity} on ${node.day_of_week || '?'} at ${node.typical_time || '?'}`
    case 'Goal': return `${node.description} [${node.status}]`
    case 'Interest': return `${node.topic} (${node.depth})`
    case 'Health': return `${node.metric}: ${node.current_value} (${node.trend})`
    case 'Place': return `${node.name} (${node.type === 'Place' ? node.significance : node.type})`
    case 'Fact': return `${node.subject} ${node.predicate} ${node.object}`
    default: return JSON.stringify(node).slice(0, 60)
  }
}
