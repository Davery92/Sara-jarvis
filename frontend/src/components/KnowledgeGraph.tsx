import React, { useRef, useEffect, useState, useMemo, useCallback } from 'react'
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
  type: 'content' | 'entity' | 'topic' | 'tag' | 'note' | 'episode' | 'document'
  importance: number
  content?: string
  group: number
  metadata?: {
    role?: string
    source?: string
    mime_type?: string
    created_at?: string
    content_type?: string
    entity_type?: string
    topic_type?: string
    tag_category?: string
    confidence?: number
    urgency_score?: number
    importance_score?: number
  }
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode
  target: string | GraphNode
  strength: number
  type: 'reference' | 'semantic' | 'temporal' | 'HAS_CHUNK' | 'HAS_ENTITY' | 'HAS_TOPIC' | 'HAS_TAG' | 'SHARES_ENTITIES' | 'SHARES_TOPICS' | 'SHARES_CONTEXT'
  properties?: any
  originalType?: string
  connection_strength?: number
  auto_generated?: boolean
}

interface KnowledgeGraphProps {
  notes: Note[]
  onNodeClick?: (nodeId: string, nodeType: string) => void
  selectedNoteId?: number | null
  useApiData?: boolean // If true, fetch graph data from API
}

interface ConnectionDetails {
  source: GraphNode
  target: GraphNode
  type: string
  strength: number
  properties?: any
}

const KnowledgeGraph = React.memo(function KnowledgeGraph({ notes, onNodeClick, selectedNoteId, useApiData = false }: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [graphData, setGraphData] = React.useState<{nodes: GraphNode[], links: GraphLink[]} | null>(null)
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(false)
  
  // Track the last data hash to prevent unnecessary re-renders
  const lastDataHashRef = useRef<string>('')
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(new Set(['content', 'entity', 'topic', 'tag', 'note', 'episode', 'document']))
  const [selectedConnection, setSelectedConnection] = useState<ConnectionDetails | null>(null)
  const [showConnectionModal, setShowConnectionModal] = useState(false)
  const [connectionDetails, setConnectionDetails] = useState<any>(null)
  const [loadingConnectionDetails, setLoadingConnectionDetails] = useState(false)

  // Fetch graph data from Neo4j (only once on mount)
  useEffect(() => {
    let isMounted = true
    
    const fetchGraphData = async () => {
      if (!isMounted) return
      setLoading(true)
      
      try {
        // Try to fetch from Neo4j knowledge graph first
        const graphResponse = await fetch(`${APP_CONFIG.apiUrl}/knowledge-graph/?depth=2`, {
          credentials: 'include'
        })
        
        if (!isMounted) return
        
        if (graphResponse.ok) {
          const data = await graphResponse.json()
          if (isMounted) {
            // Only update if the data has actually changed
            const dataHash = JSON.stringify({
              nodeCount: data.nodes?.length || 0,
              relCount: data.relationships?.length || 0,
              firstNodeId: data.nodes?.[0]?.properties?.id || data.nodes?.[0]?.id,
              lastNodeId: data.nodes?.[data.nodes?.length - 1]?.properties?.id || data.nodes?.[data.nodes?.length - 1]?.id
            })
            
            if (dataHash !== lastDataHashRef.current) {
              lastDataHashRef.current = dataHash
              setGraphData(data)
              console.log('✅ Loaded graph data from Neo4j:', data)
            } else {
              console.log('🔄 Graph data unchanged, skipping update')
            }
          }
        } else {
          // Fallback to old method if Neo4j is not available
          console.warn('Neo4j not available, falling back to PostgreSQL data')
          await fetchFallbackData()
        }
      } catch (error) {
        console.error('Failed to fetch Neo4j graph data:', error)
        // Fallback to old method
        if (isMounted) {
          await fetchFallbackData()
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    const fetchFallbackData = async () => {
      if (!isMounted) return
      
      try {
        // Fetch episodes
        const episodesResponse = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes?page=1&per_page=100`, {
          credentials: 'include'
        })
        if (episodesResponse.ok && isMounted) {
          const episodesData = await episodesResponse.json()
          setEpisodes(episodesData.episodes || [])
        }

        // Fetch documents
        const documentsResponse = await fetch(`${APP_CONFIG.apiUrl}/documents`, {
          credentials: 'include'
        })
        if (documentsResponse.ok && isMounted) {
          const documentsData = await documentsResponse.json()
          setDocuments(documentsData || [])
        }
      } catch (error) {
        console.error('Failed to fetch fallback data:', error)
      }
    }

    fetchGraphData()
    
    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    if (!svgRef.current || loading) return
    
    // If we have no meaningful data, show empty state instead of bouncing
    const hasMeaningfulData = (graphData && graphData.nodes && graphData.nodes.length > 0) || 
                             notes.length > 0 || 
                             (episodes.length > 0 && episodes.some(e => e.content && e.content.trim().length > 50)) ||
                             documents.length > 0
    
    if (!hasMeaningfulData) {
      // Clear the SVG and show empty state - don't render D3 graph
      d3.select(svgRef.current).selectAll("*").remove()
      return
    }

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
          type: mapRelationshipType(rel.type),
          properties: rel.properties,
          originalType: rel.type
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
          case 'HAS_CHUNK': return "#8b5cf6" // Purple for content chunks
          case 'HAS_ENTITY': return "#06b6d4" // Cyan for entities
          case 'HAS_TOPIC': return "#10b981" // Emerald for topics
          case 'HAS_TAG': return "#f59e0b" // Orange for tags
          case 'SHARES_ENTITIES': return "#06b6d4" // Cyan for shared entities
          case 'SHARES_TOPICS': return "#10b981" // Emerald for shared topics
          case 'SHARES_CONTEXT': return "#8b5cf6" // Purple for shared context
          default: return "#3f3f46"
        }
      })
      .attr("stroke-opacity", d => 0.3 + (d.strength * 0.7))
      .attr("stroke-width", d => 1 + Math.sqrt(d.strength) * 2)
      .attr("stroke-dasharray", d => d.type === 'semantic' ? "5,5" : null)
      .style("cursor", "pointer")

    // Add connection labels (initially hidden)
    const linkLabels = container.append("g")
      .selectAll("text")
      .data(links)
      .join("text")
      .attr("font-family", "Inter, sans-serif")
      .attr("font-size", "10px")
      .attr("fill", "#f8fafc")
      .attr("text-anchor", "middle")
      .attr("pointer-events", "none")
      .style("opacity", 0)
      .text(d => {
        const typeLabels = {
          'reference': 'Reference',
          'semantic': 'Semantic',
          'temporal': 'Temporal'
        }
        return typeLabels[d.type] || d.type
      })

    // Add hover effects for links
    link.on("mouseenter", function(event, d) {
      d3.select(this)
        .transition()
        .duration(200)
        .attr("stroke-opacity", 0.8)
        .attr("stroke-width", (1 + Math.sqrt(d.strength) * 2) * 1.5)
      
      // Show label for this link
      linkLabels.filter(label => label === d)
        .transition()
        .duration(200)
        .style("opacity", 1)
    })
    
    link.on("mouseleave", function(event, d) {
      d3.select(this)
        .transition()
        .duration(200)
        .attr("stroke-opacity", 0.3 + (d.strength * 0.7))
        .attr("stroke-width", 1 + Math.sqrt(d.strength) * 2)
      
      // Hide label for this link
      linkLabels.filter(label => label === d)
        .transition()
        .duration(200)
        .style("opacity", 0)
    })

    // Add click handler for connections
    link.on("click", async function(event, d) {
      event.stopPropagation()
      
      const sourceNode = nodes.find(n => n.id === (typeof d.source === 'string' ? d.source : d.source.id))
      const targetNode = nodes.find(n => n.id === (typeof d.target === 'string' ? d.target : d.target.id))
      
      if (sourceNode && targetNode) {
        setSelectedConnection({
          source: sourceNode,
          target: targetNode,
          type: d.originalType || d.type,
          strength: d.strength,
          properties: d.properties
        })
        setShowConnectionModal(true)
        
        // Fetch detailed connection information
        setLoadingConnectionDetails(true)
        try {
          const response = await fetch(`${APP_CONFIG.apiUrl}/knowledge-graph/connection-details`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({
              source_id: sourceNode.id,
              target_id: targetNode.id
            })
          })
          
          if (response.ok) {
            const details = await response.json()
            setConnectionDetails(details)
          } else {
            console.error('Failed to fetch connection details')
            setConnectionDetails(null)
          }
        } catch (error) {
          console.error('Error fetching connection details:', error)
          setConnectionDetails(null)
        } finally {
          setLoadingConnectionDetails(false)
        }
      }
    })

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
          case 'content': return "#8b5cf6" // Purple for content nodes
          case 'entity': return "#06b6d4" // Cyan for entities
          case 'topic': return "#10b981" // Emerald for topics
          case 'tag': return "#f59e0b" // Orange for tags
          case 'note': return "#4ade80" // Green for notes (legacy)
          case 'episode': return "#0d7ff2" // Blue for episodes (legacy)
          case 'document': return "#f59e0b" // Orange for documents (legacy)
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

      // Position link labels at the midpoint of each connection
      linkLabels
        .attr("x", d => ((d.source as GraphNode).x! + (d.target as GraphNode).x!) / 2)
        .attr("y", d => ((d.source as GraphNode).y! + (d.target as GraphNode).y!) / 2)

      node.attr("transform", d => `translate(${d.x},${d.y})`)
    })

    // Cleanup function
    return () => {
      simulation.stop()
    }

  }, [notes, episodes, documents, selectedNoteId, onNodeClick, visibleTypes, graphData, loading])

  // Memoize the visibleTypes array to prevent unnecessary re-renders
  const visibleTypesArray = useMemo(() => Array.from(visibleTypes), [visibleTypes])

  // Helper functions for Neo4j data conversion
  const determineNodeTypeFromLabels = (labels: string[]): string => {
    if (labels.includes('Content')) return 'content'
    if (labels.includes('Entity')) return 'entity'
    if (labels.includes('Topic')) return 'topic'
    if (labels.includes('Tag')) return 'tag'
    // Legacy types
    if (labels.includes('Note')) return 'note'
    if (labels.includes('Episode')) return 'episode'
    if (labels.includes('Document')) return 'document'
    return 'unknown'
  }

  const getNodeTitle = (props: any, nodeType: string): string => {
    if (props.title) return props.title
    if (props.name) return props.name
    
    // Enhanced schema types
    if (nodeType === 'entity') return props.name || 'Entity'
    if (nodeType === 'topic') return props.name || 'Topic'
    if (nodeType === 'tag') return props.name || 'Tag'
    if (nodeType === 'content') return props.title || props.name || 'Content'
    
    // Legacy types
    if (nodeType === 'episode') {
      return `${props.role || 'user'}: ${(props.content || '').substring(0, 30)}...`
    }
    if (props.content) return props.content.substring(0, 40) + '...'
    return 'Untitled'
  }

  const calculateNodeImportance = (props: any, nodeType: string): number => {
    if (props.importance_score) return props.importance_score
    if (props.confidence) return props.confidence
    if (props.importance) return props.importance
    
    // Enhanced schema importance
    if (nodeType === 'content') return props.importance_score || Math.min((props.content?.length || 0) / 200, 5)
    if (nodeType === 'entity') return props.confidence || 0.5
    if (nodeType === 'topic') return props.confidence || 0.5
    if (nodeType === 'tag') return props.confidence || 0.3
    
    // Legacy types
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
      case 'content': return 1
      case 'entity': return 2
      case 'topic': return 3
      case 'tag': return 4
      case 'note': return 5    // Legacy
      case 'episode': return 6 // Legacy
      case 'document': return 7 // Legacy
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
      const counts = { content: 0, entity: 0, topic: 0, tag: 0, note: 0, episode: 0, document: 0 }
      graphData.nodes.forEach(node => {
        const nodeType = determineNodeTypeFromLabels(node.labels)
        if (nodeType in counts) {
          counts[nodeType as keyof typeof counts]++
        }
      })
      return counts
    }
    return {
      content: 0,
      entity: 0,
      topic: 0,
      tag: 0,
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

  const formatConnectionDetails = (connection: ConnectionDetails) => {
    const details = []
    
    // Connection type description
    const typeDescriptions = {
      'REFERENCES': 'Explicit reference (e.g., [[Note Link]])',
      'SEMANTIC_SIMILAR': 'Semantically similar content',
      'TEMPORAL_NEAR': 'Created close in time',
      'reference': 'Explicit reference',
      'semantic': 'Semantic similarity', 
      'temporal': 'Temporal proximity'
    }
    
    details.push({
      label: 'Connection Type',
      value: typeDescriptions[connection.type] || connection.type
    })
    
    details.push({
      label: 'Strength',
      value: `${(connection.strength * 100).toFixed(1)}%`
    })
    
    // Add property-specific details
    if (connection.properties) {
      if (connection.properties.similarity) {
        details.push({
          label: 'Similarity Score',
          value: `${(connection.properties.similarity * 100).toFixed(1)}%`
        })
      }
      if (connection.properties.time_proximity) {
        details.push({
          label: 'Time Proximity',
          value: connection.properties.time_proximity.toFixed(2)
        })
      }
      if (connection.properties.created_at) {
        try {
          const date = new Date(connection.properties.created_at)
          if (!isNaN(date.getTime())) {
            details.push({
              label: 'Connection Created',
              value: date.toLocaleString()
            })
          }
        } catch (e) {
          // Skip invalid dates
        }
      }
    }
    
    return details
  }

  return (
    <>
      <div className="w-full h-full bg-[#27272a] rounded-lg border border-[#3f3f46] overflow-hidden">
        <div className="p-4 border-b border-[#3f3f46]">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-medium text-[#f8fafc]">Knowledge Graph</h3>
            {loading && (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-[#0d7ff2] border-t-transparent"></div>
            )}
          </div>
        
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm text-[#a1a1aa]">
            {totalItems} items • Drag to explore • Click nodes to navigate • Click connections for details
          </p>
          
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => toggleContentType('content')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('content')
                  ? 'bg-[#8b5cf6] text-white border-[#7c3aed]'
                  : 'bg-transparent text-[#8b5cf6] border-[#8b5cf6] hover:bg-[#8b5cf6] hover:text-white'
              }`}
            >
              Content ({nodeCounts.content || 0})
            </button>
            <button
              onClick={() => toggleContentType('entity')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('entity')
                  ? 'bg-[#06b6d4] text-white border-[#0891b2]'
                  : 'bg-transparent text-[#06b6d4] border-[#06b6d4] hover:bg-[#06b6d4] hover:text-white'
              }`}
            >
              Entities ({nodeCounts.entity || 0})
            </button>
            <button
              onClick={() => toggleContentType('topic')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('topic')
                  ? 'bg-[#10b981] text-white border-[#059669]'
                  : 'bg-transparent text-[#10b981] border-[#10b981] hover:bg-[#10b981] hover:text-white'
              }`}
            >
              Topics ({nodeCounts.topic || 0})
            </button>
            <button
              onClick={() => toggleContentType('tag')}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                visibleTypes.has('tag')
                  ? 'bg-[#f59e0b] text-black border-[#d97706]'
                  : 'bg-transparent text-[#f59e0b] border-[#f59e0b] hover:bg-[#f59e0b] hover:text-black'
              }`}
            >
              Tags ({nodeCounts.tag || 0})
            </button>
            {/* Legacy node types */}
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
          </div>
        </div>
        
        {/* Connection Legend */}
        <div className="flex items-center gap-3 text-xs flex-wrap">
          <div className="flex items-center gap-1">
            <div className="w-4 h-0 border-t-2 border-[#8b5cf6]"></div>
            <span className="text-[#a1a1aa]">Content</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-4 h-0 border-t-2 border-[#06b6d4]"></div>
            <span className="text-[#a1a1aa]">Entities</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-4 h-0 border-t-2 border-[#10b981]"></div>
            <span className="text-[#a1a1aa]">Topics</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-4 h-0 border-t-2 border-[#0d7ff2]"></div>
            <span className="text-[#a1a1aa]">Reference</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-4 h-0 border-t-2 border-[#4ade80] border-dashed"></div>
            <span className="text-[#a1a1aa]">Semantic</span>
          </div>
        </div>
      </div>
      <div className="relative w-full h-[calc(100%-100px)]">
        <svg
          ref={svgRef}
          className="w-full h-full"
          style={{ background: 'transparent' }}
        />
{(() => {
          const hasMeaningfulData = (graphData && graphData.nodes && graphData.nodes.length > 0) || 
                                   notes.length > 0 || 
                                   (episodes.length > 0 && episodes.some(e => e.content && e.content.trim().length > 50)) ||
                                   documents.length > 0
          
          return !hasMeaningfulData && !loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="text-6xl text-[#a1a1aa] mb-4">🧠</div>
                <h3 className="text-lg font-medium mb-2 text-[#f8fafc]">Knowledge Graph Empty</h3>
                <p className="text-[#a1a1aa] mb-4 max-w-md">
                  {notes.length === 0 && episodes.length === 0 && documents.length === 0
                    ? "No content available. Create notes, have conversations, or upload documents to build your knowledge graph."
                    : "Neo4j is not available. Content intelligence features (entities, topics, tags) require Neo4j to be running."
                  }
                </p>
                {episodes.length > 0 && (
                  <div className="text-xs text-[#6b7280] bg-[#374151] px-3 py-2 rounded">
                    📊 {episodes.length} conversation episodes found but no processed content available
                  </div>
                )}
              </div>
            </div>
          )
        })()}
      </div>
    </div>

    {/* Connection Details Modal */}
    {showConnectionModal && selectedConnection && (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-[#1c1c1e] border border-[#3f3f46] rounded-lg p-6 max-w-md w-full mx-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-[#f8fafc]">Connection Details</h3>
            <button 
              onClick={() => {
                setShowConnectionModal(false)
                setConnectionDetails(null)
                setSelectedConnection(null)
              }}
              className="text-[#a1a1aa] hover:text-[#f8fafc] transition-colors"
            >
              ✕
            </button>
          </div>
          
          <div className="space-y-4">
            {/* Connected Nodes */}
            <div>
              <h4 className="text-sm font-medium text-[#f8fafc] mb-2">Connected Items</h4>
              <div className="space-y-2">
                <div className="flex items-center gap-2 p-2 bg-[#27272a] rounded">
                  <div className={`w-3 h-3 rounded-full ${
                    selectedConnection.source.type === 'note' ? 'bg-[#4ade80]' :
                    selectedConnection.source.type === 'episode' ? 'bg-[#0d7ff2]' : 'bg-[#f59e0b]'
                  }`}></div>
                  <span className="text-sm text-[#f8fafc] truncate">{selectedConnection.source.title}</span>
                </div>
                <div className="flex justify-center">
                  <div className="text-[#a1a1aa]">↕</div>
                </div>
                <div className="flex items-center gap-2 p-2 bg-[#27272a] rounded">
                  <div className={`w-3 h-3 rounded-full ${
                    selectedConnection.target.type === 'note' ? 'bg-[#4ade80]' :
                    selectedConnection.target.type === 'episode' ? 'bg-[#0d7ff2]' : 'bg-[#f59e0b]'
                  }`}></div>
                  <span className="text-sm text-[#f8fafc] truncate">{selectedConnection.target.title}</span>
                </div>
              </div>
            </div>

            {/* Connection Properties */}
            <div>
              <h4 className="text-sm font-medium text-[#f8fafc] mb-2">Connection Properties</h4>
              <div className="space-y-2">
                {formatConnectionDetails(selectedConnection).map((detail, index) => (
                  <div key={index} className="flex justify-between items-center py-1">
                    <span className="text-sm text-[#a1a1aa]">{detail.label}:</span>
                    <span className="text-sm text-[#f8fafc] font-medium">{detail.value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Detailed Connection Analysis */}
            <div>
              <h4 className="text-sm font-medium text-[#f8fafc] mb-2">Why Connected?</h4>
              {loadingConnectionDetails ? (
                <div className="flex items-center justify-center p-4">
                  <div className="animate-spin rounded-full h-6 w-6 border-2 border-[#0d7ff2] border-t-transparent"></div>
                  <span className="ml-2 text-sm text-[#a1a1aa]">Analyzing connection...</span>
                </div>
              ) : connectionDetails ? (
                <div className="space-y-3">
                  {/* Semantic Analysis */}
                  {connectionDetails.shared_content_analysis && (
                    <div className="bg-[#27272a] p-3 rounded">
                      <div className="text-sm text-[#f8fafc] font-medium mb-2">Shared Content Analysis</div>
                      
                      {connectionDetails.shared_content_analysis.shared_words?.length > 0 && (
                        <div className="mb-2">
                          <div className="text-xs text-[#a1a1aa] mb-1">Key shared words:</div>
                          <div className="flex flex-wrap gap-1">
                            {connectionDetails.shared_content_analysis.shared_words.slice(0, 5).map((word: any, index: number) => (
                              <span key={index} className="text-xs bg-[#0d7ff2] text-white px-2 py-1 rounded">
                                {word.word} ({word.frequency_source + word.frequency_target}x)
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      
                      {connectionDetails.shared_content_analysis.shared_phrases?.length > 0 && (
                        <div className="mb-2">
                          <div className="text-xs text-[#a1a1aa] mb-1">Common phrases:</div>
                          {connectionDetails.shared_content_analysis.shared_phrases.slice(0, 3).map((phrase: string, index: number) => (
                            <div key={index} className="text-xs text-[#4ade80] italic">"{phrase}"</div>
                          ))}
                        </div>
                      )}
                      
                      <div className="text-xs text-[#a1a1aa]">
                        {connectionDetails.shared_content_analysis.total_shared_words} shared words • 
                        {(connectionDetails.shared_content_analysis.similarity_ratio * 100).toFixed(1)}% content overlap
                      </div>
                    </div>
                  )}
                  
                  {/* Reference Analysis */}
                  {connectionDetails.reference_analysis && (
                    <div className="bg-[#27272a] p-3 rounded">
                      <div className="text-sm text-[#f8fafc] font-medium mb-2">Explicit References Found</div>
                      {connectionDetails.reference_analysis.references_found?.length > 0 ? (
                        <div className="space-y-1">
                          {connectionDetails.reference_analysis.references_found.map((ref: string, index: number) => (
                            <div key={index} className="text-xs text-[#4ade80] font-mono bg-[#1a1a1a] px-2 py-1 rounded">
                              {ref}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-xs text-[#a1a1aa]">No explicit references found</div>
                      )}
                    </div>
                  )}
                  
                  {/* Temporal Analysis */}
                  {connectionDetails.temporal_analysis && (
                    <div className="bg-[#27272a] p-3 rounded">
                      <div className="text-sm text-[#f8fafc] font-medium mb-2">Temporal Proximity</div>
                      <div className="text-xs text-[#a1a1aa]">
                        {connectionDetails.temporal_analysis.created_within}
                        {connectionDetails.temporal_analysis.temporal_proximity === 'very_close' && 
                          <span className="text-[#4ade80] ml-2">Very Close</span>
                        }
                        {connectionDetails.temporal_proximity === 'close' && 
                          <span className="text-[#f59e0b] ml-2">Close</span>
                        }
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-sm text-[#a1a1aa] bg-[#27272a] p-3 rounded">
                  {selectedConnection.type === 'REFERENCES' || selectedConnection.type === 'reference' ? 
                    'This connection was created because one item explicitly references the other using [[Link]] syntax or by title mention.' :
                  selectedConnection.type === 'SEMANTIC_SIMILAR' || selectedConnection.type === 'semantic' ?
                    'This connection was created because the items have similar content based on semantic analysis and word overlap.' :
                  selectedConnection.type === 'TEMPORAL_NEAR' || selectedConnection.type === 'temporal' ?
                    'This connection was created because the items were created close together in time.' :
                    'This connection represents a relationship detected between the items.'
                  }
                </div>
              )}
            </div>
          </div>

          <div className="mt-6 flex justify-end">
            <button 
              onClick={() => {
                setShowConnectionModal(false)
                setConnectionDetails(null)
                setSelectedConnection(null)
              }}
              className="px-4 py-2 bg-[#0d7ff2] text-white rounded hover:bg-[#0c6fd1] transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}, (prevProps, nextProps) => {
  // Only re-render if props that actually affect the visualization have changed
  return (
    prevProps.selectedNoteId === nextProps.selectedNoteId &&
    prevProps.useApiData === nextProps.useApiData &&
    prevProps.notes.length === nextProps.notes.length &&
    prevProps.notes.every((note, index) => 
      nextProps.notes[index]?.id === note.id &&
      nextProps.notes[index]?.updated_at === note.updated_at
    )
  )
})

export default KnowledgeGraph