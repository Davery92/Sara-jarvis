import React, { useRef, useEffect, useState } from 'react'
import * as d3 from 'd3'
import { generateNoteConnections } from '../utils/linkParser'
import { APP_CONFIG } from '../config'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface Episode {
  id: string
  role: string
  content: string
  importance: number
  source: string
  created_at: string
}

interface Document {
  id: string
  title: string
  content_text: string
  mime_type: string
  created_at: string
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: string
  title: string
  type: 'note' | 'episode' | 'document'
  importance: number
  content?: string
  group: number
  metadata?: {
    role?: string
    source?: string
    mime_type?: string
    created_at?: string
  }
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode
  target: string | GraphNode
  strength: number
  type: 'reference' | 'semantic' | 'temporal'
}

interface KnowledgeGraphProps {
  notes: Note[]
  onNodeClick?: (nodeId: string, nodeType: string) => void
  selectedNoteId?: number | null
  useApiData?: boolean // If true, fetch graph data from API
}

export default function KnowledgeGraph({ notes, onNodeClick, selectedNoteId, useApiData = false }: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [graphData, setGraphData] = React.useState<{nodes: GraphNode[], links: GraphLink[]} | null>(null)
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(false)
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(new Set(['note', 'episode', 'document']))

  // Fetch graph data from Neo4j
  useEffect(() => {
    const fetchGraphData = async () => {
      setLoading(true)
      try {
        // Try to fetch from Neo4j knowledge graph first
        const graphResponse = await fetch(`${APP_CONFIG.apiUrl}/knowledge-graph/?depth=2`, {
          credentials: 'include'
        })
        
        if (graphResponse.ok) {
          const graphData = await graphResponse.json()
          setGraphData(graphData)
          console.log('✅ Loaded graph data from Neo4j:', graphData)
        } else {
          // Fallback to old method if Neo4j is not available
          console.warn('Neo4j not available, falling back to PostgreSQL data')
          await fetchFallbackData()
        }
      } catch (error) {
        console.error('Failed to fetch Neo4j graph data:', error)
        // Fallback to old method
        await fetchFallbackData()
      } finally {
        setLoading(false)
      }
    }

    const fetchFallbackData = async () => {
      try {
        // Fetch episodes
        const episodesResponse = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes?page=1&per_page=100`, {
          credentials: 'include'
        })
        if (episodesResponse.ok) {
          const episodesData = await episodesResponse.json()
          setEpisodes(episodesData.episodes || [])
        }

        // Fetch documents
        const documentsResponse = await fetch(`${APP_CONFIG.apiUrl}/documents`, {
          credentials: 'include'
        })
        if (documentsResponse.ok) {
          const documentsData = await documentsResponse.json()
          setDocuments(documentsData || [])
        }
      } catch (error) {
        console.error('Failed to fetch fallback data:', error)
      }
    }

    fetchGraphData()
  }, [])

  useEffect(() => {
    if (!svgRef.current) return

    // Clear previous graph
    d3.select(svgRef.current).selectAll("*").remove()

    const svg = d3.select(svgRef.current)
    const width = 800
    const height = 600

    svg.attr("width", width).attr("height", height)

    let nodes: GraphNode[] = []
    let links: GraphLink[] = []

    // Use Neo4j data if available, otherwise fall back to PostgreSQL data
    if (graphData && graphData.nodes && graphData.nodes.length > 0) {
      // Convert Neo4j graph data to D3 format
      nodes = graphData.nodes
        .filter(node => {
          const nodeType = determineNodeTypeFromLabels(node.labels)
          return visibleTypes.has(nodeType)
        })
        .map(node => {
          const nodeType = determineNodeTypeFromLabels(node.labels)
          const props = node.properties
          
          return {
            id: props.id,
            title: getNodeTitle(props, nodeType),
            type: nodeType,
            importance: calculateNodeImportance(props, nodeType),
            content: getNodeContent(props, nodeType),
            group: getNodeGroup(nodeType),
            metadata: props
          }
        })

      // Convert relationships to links
      links = graphData.relationships
        .filter(rel => {
          // Only include links where both nodes are visible
          const sourceVisible = nodes.some(n => n.id === rel.source)
          const targetVisible = nodes.some(n => n.id === rel.target)
          return sourceVisible && targetVisible
        })
        .map(rel => ({
          source: rel.source,
          target: rel.target,
          strength: rel.properties?.strength || rel.properties?.similarity || 0.5,
          type: mapRelationshipType(rel.type)
        }))

      console.log('📊 Using Neo4j graph data:', { nodes: nodes.length, links: links.length })
    } else {
      // Fallback to old PostgreSQL-based method
      console.log('📊 Using fallback PostgreSQL data')
      
      // Add notes
      if (visibleTypes.has('note')) {
        const noteNodes: GraphNode[] = notes.map(note => ({
          id: `note-${note.id}`,
          title: note.title || 'Untitled',
          type: 'note',
          importance: Math.min(note.content.length / 100, 5),
          content: note.content,
          group: 1,
          metadata: {
            created_at: note.created_at
          }
        }))
        nodes.push(...noteNodes)
      }

      // Add episodes
      if (visibleTypes.has('episode')) {
        const episodeNodes: GraphNode[] = episodes.map(episode => ({
          id: `episode-${episode.id}`,
          title: `${episode.role}: ${episode.content.substring(0, 30)}...`,
          type: 'episode',
          importance: episode.importance || 0.5,
          content: episode.content,
          group: 2,
          metadata: {
            role: episode.role,
            source: episode.source,
            created_at: episode.created_at
          }
        }))
        nodes.push(...episodeNodes)
      }

      // Add documents
      if (visibleTypes.has('document')) {
        const documentNodes: GraphNode[] = documents.map(doc => ({
          id: `document-${doc.id}`,
          title: doc.title || 'Untitled Document',
          type: 'document',
          importance: Math.min(doc.content_text?.length / 200 || 0, 5),
          content: doc.content_text,
          group: 3,
          metadata: {
            mime_type: doc.mime_type,
            created_at: doc.created_at
          }
        }))
        nodes.push(...documentNodes)
      }

      // Generate fallback connections (existing logic)
      links = generateFallbackConnections(nodes)
    }

    if (nodes.length === 0) return

    // Create force simulation
    const simulation = d3.forceSimulation<GraphNode>(nodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(links).id(d => d.id).strength(d => d.strength * 0.1))
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(30))

    // Create container group
    const container = svg.append("g")

    // Add zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => {
        container.attr("transform", event.transform)
      })

    svg.call(zoom)

    // Create links with different styles for different types
    const link = container.append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", d => {
        switch (d.type) {
          case 'reference': return "#0d7ff2" // Blue for explicit references
          case 'semantic': return "#4ade80" // Green for semantic connections
          case 'temporal': return "#f59e0b" // Orange for temporal connections
          default: return "#3f3f46"
        }
      })
      .attr("stroke-opacity", d => 0.3 + (d.strength * 0.7))
      .attr("stroke-width", d => 1 + Math.sqrt(d.strength) * 2)
      .attr("stroke-dasharray", d => d.type === 'semantic' ? "5,5" : null)

    // Create nodes
    const node = container.append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(d3.drag<SVGGElement, GraphNode>()
        .on("start", (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart()
          d.fx = d.x
          d.fy = d.y
        })
        .on("drag", (event, d) => {
          d.fx = event.x
          d.fy = event.y
        })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0)
          d.fx = null
          d.fy = null
        }))

    // Add circles for nodes with type-specific styling
    node.append("circle")
      .attr("r", d => 8 + d.importance * 2)
      .attr("fill", d => {
        if (d.id === `note-${selectedNoteId}`) return "#0d7ff2" // Selected note
        switch (d.type) {
          case 'note': return "#4ade80" // Green for notes
          case 'episode': return "#0d7ff2" // Blue for episodes
          case 'document': return "#f59e0b" // Orange for documents
          default: return "#6b7280"
        }
      })
      .attr("stroke", d => {
        switch (d.type) {
          case 'note': return "#16a34a"
          case 'episode': return "#0c6fd1"
          case 'document': return "#d97706"
          default: return "#1f2937"
        }
      })
      .attr("stroke-width", 2)
      .attr("stroke-dasharray", d => d.type === 'episode' ? "3,3" : null) // Dashed for episodes

    // Add labels
    node.append("text")
      .text(d => d.title)
      .attr("x", 12)
      .attr("y", "0.31em")
      .attr("font-family", "Inter, sans-serif")
      .attr("font-size", "12px")
      .attr("fill", "#f8fafc")
      .clone(true).lower()
      .attr("fill", "none")
      .attr("stroke", "#18181b")
      .attr("stroke-width", 3)

    // Add click handlers
    node.on("click", (event, d) => {
      if (onNodeClick) {
        onNodeClick(d.id, d.type)
      }
    })

    // Add hover effects
    node.on("mouseenter", function(event, d) {
      d3.select(this).select("circle")
        .transition()
        .duration(200)
        .attr("r", (8 + d.importance * 2) * 1.2)
    })
    
    node.on("mouseleave", function(event, d) {
      d3.select(this).select("circle")
        .transition()
        .duration(200)
        .attr("r", 8 + d.importance * 2)
    })

    // Update positions on simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", d => (d.source as GraphNode).x!)
        .attr("y1", d => (d.source as GraphNode).y!)
        .attr("x2", d => (d.target as GraphNode).x!)
        .attr("y2", d => (d.target as GraphNode).y!)

      node.attr("transform", d => `translate(${d.x},${d.y})`)
    })

    // Cleanup function
    return () => {
      simulation.stop()
    }

  }, [notes, episodes, documents, selectedNoteId, onNodeClick, visibleTypes, graphData])

  // Helper functions for Neo4j data conversion
  const determineNodeTypeFromLabels = (labels: string[]): string => {
    if (labels.includes('Note')) return 'note'
    if (labels.includes('Episode')) return 'episode'
    if (labels.includes('Document')) return 'document'
    return 'unknown'
  }

  const getNodeTitle = (props: any, nodeType: string): string => {
    if (props.title) return props.title
    if (nodeType === 'episode') {
      return `${props.role || 'user'}: ${(props.content || '').substring(0, 30)}...`
    }
    if (props.content) return props.content.substring(0, 40) + '...'
    return 'Untitled'
  }

  const calculateNodeImportance = (props: any, nodeType: string): number => {
    if (props.importance) return props.importance
    if (nodeType === 'note') return Math.min((props.content?.length || 0) / 100, 5)
    if (nodeType === 'episode') return props.importance || 0.5
    if (nodeType === 'document') return Math.min((props.content_text?.length || 0) / 200, 5)
    return 1
  }

  const getNodeContent = (props: any, nodeType: string): string => {
    return props.content || props.content_text || ''
  }

  const getNodeGroup = (nodeType: string): number => {
    switch (nodeType) {
      case 'note': return 1
      case 'episode': return 2
      case 'document': return 3
      default: return 0
    }
  }

  const mapRelationshipType = (neoType: string): 'reference' | 'semantic' | 'temporal' => {
    if (neoType === 'REFERENCES') return 'reference'
    if (neoType === 'TEMPORAL_NEAR') return 'temporal'
    return 'semantic'
  }

  const generateFallbackConnections = (nodes: GraphNode[]): GraphLink[] => {
    const links: GraphLink[] = []
    const processedConnections = new Set<string>()

    // Generate note-to-note connections using existing parser
    notes.forEach(note => {
      const connections = generateNoteConnections(note, notes)
      connections.forEach(conn => {
        const connectionKey = `note-${conn.sourceId}-note-${conn.targetId}`
        const reverseKey = `note-${conn.targetId}-note-${conn.sourceId}`
        
        if (!processedConnections.has(connectionKey) && !processedConnections.has(reverseKey)) {
          links.push({
            source: `note-${conn.sourceId}`,
            target: `note-${conn.targetId}`,
            strength: conn.strength,
            type: conn.type
          })
          processedConnections.add(connectionKey)
        }
      })
    })

    // Generate cross-type semantic connections
    nodes.forEach((node1, i) => {
      nodes.slice(i + 1).forEach(node2 => {
        // Skip if same type and already processed by note parser
        if (node1.type === 'note' && node2.type === 'note') return
        
        if (node1.content && node2.content) {
          const similarity = calculateSemanticSimilarity(node1.content, node2.content)
          if (similarity > 0.1) {
            const connectionKey = `${node1.id}-${node2.id}`
            const reverseKey = `${node2.id}-${node1.id}`
            
            if (!processedConnections.has(connectionKey) && !processedConnections.has(reverseKey)) {
              links.push({
                source: node1.id,
                target: node2.id,
                strength: similarity,
                type: 'semantic'
              })
              processedConnections.add(connectionKey)
            }
          }
        }
      })
    })

    return links
  }

  // Helper function for semantic similarity (from linkParser)
  const calculateSemanticSimilarity = (text1: string, text2: string): number => {
    const words1 = text1.toLowerCase().split(/\s+/).filter(w => w.length > 3)
    const words2 = text2.toLowerCase().split(/\s+/).filter(w => w.length > 3)
    
    if (words1.length === 0 || words2.length === 0) return 0
    
    const commonWords = words1.filter(word => words2.includes(word))
    const totalWords = new Set([...words1, ...words2]).size
    
    return commonWords.length / totalWords
  }

  const getTotalItems = (): number => {
    if (graphData && graphData.nodes && graphData.nodes.length > 0) {
      return graphData.nodes.filter(node => {
        const nodeType = determineNodeTypeFromLabels(node.labels)
        return visibleTypes.has(nodeType)
      }).length
    }
    return (visibleTypes.has('note') ? notes.length : 0) + 
           (visibleTypes.has('episode') ? episodes.length : 0) + 
           (visibleTypes.has('document') ? documents.length : 0)
  }

  const getNodeCounts = () => {
    if (graphData && graphData.nodes && graphData.nodes.length > 0) {
      const counts = { note: 0, episode: 0, document: 0 }
      graphData.nodes.forEach(node => {
        const nodeType = determineNodeTypeFromLabels(node.labels)
        if (nodeType in counts) {
          counts[nodeType as keyof typeof counts]++
        }
      })
      return counts
    }
    return {
      note: notes.length,
      episode: episodes.length,
      document: documents.length
    }
  }

  const totalItems = getTotalItems()
  const nodeCounts = getNodeCounts()

  const toggleContentType = (type: string) => {
    setVisibleTypes(prev => {
      const newTypes = new Set(prev)
      if (newTypes.has(type)) {
        newTypes.delete(type)
      } else {
        newTypes.add(type)
      }
      return newTypes
    })
  }

  return (
    <div className="w-full h-full bg-[#27272a] rounded-lg border border-[#3f3f46] overflow-hidden">
      <div className="p-4 border-b border-[#3f3f46]">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-lg font-medium text-[#f8fafc]">Knowledge Graph</h3>
          {loading && (
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-[#0d7ff2] border-t-transparent"></div>
          )}
        </div>
        
        <div className="flex items-center justify-between">
          <p className="text-sm text-[#a1a1aa]">
            {totalItems} items • Drag to explore • Click to navigate
          </p>
          
          <div className="flex items-center gap-2">
            <button
              onClick={() => toggleContentType('note')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('note')
                  ? 'bg-[#4ade80] text-black border-[#16a34a]'
                  : 'bg-transparent text-[#4ade80] border-[#4ade80] hover:bg-[#4ade80] hover:text-black'
              }`}
            >
              Notes ({nodeCounts.note})
            </button>
            <button
              onClick={() => toggleContentType('episode')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('episode')
                  ? 'bg-[#0d7ff2] text-white border-[#0c6fd1]'
                  : 'bg-transparent text-[#0d7ff2] border-[#0d7ff2] hover:bg-[#0d7ff2] hover:text-white'
              }`}
            >
              Episodes ({nodeCounts.episode})
            </button>
            <button
              onClick={() => toggleContentType('document')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('document')
                  ? 'bg-[#f59e0b] text-black border-[#d97706]'
                  : 'bg-transparent text-[#f59e0b] border-[#f59e0b] hover:bg-[#f59e0b] hover:text-black'
              }`}
            >
              Docs ({nodeCounts.document})
            </button>
          </div>
        </div>
      </div>
      <div className="relative w-full h-[calc(100%-80px)]">
        <svg
          ref={svgRef}
          className="w-full h-full"
          style={{ background: 'transparent' }}
        />
        {totalItems === 0 && !loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <span className="material-symbols-outlined text-6xl text-[#a1a1aa] mb-4 block">hub</span>
              <h3 className="text-lg font-medium mb-2 text-[#f8fafc]">No content to visualize</h3>
              <p className="text-[#a1a1aa]">Create notes, have conversations, or upload documents to see the knowledge graph</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}