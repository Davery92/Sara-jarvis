import React, { useState, useCallback, useEffect } from 'react'
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Edge,
  Node,
  BackgroundVariant,
  Panel,
  NodeTypes,
  Handle,
  Position,
  NodeProps
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { APP_CONFIG } from '../../config'

interface TopicCanvasProps {
  topicId: string | null
}

interface ConceptNodeData extends Record<string, unknown> {
  label: string
  mastery?: number
  description?: string
}

// Custom Concept Node
function ConceptNode({ data, selected }: NodeProps<Node<ConceptNodeData>>) {
  const mastery = data.mastery || 0
  const masteryColor = mastery >= 0.8 ? 'border-green-500' : mastery >= 0.5 ? 'border-yellow-500' : 'border-gray-600'

  return (
    <div
      className={`px-4 py-3 rounded-md border-2 ${masteryColor} ${
        selected ? 'bg-teal-900/50 ring-2 ring-teal-400' : 'bg-gray-800'
      } min-w-[120px] text-center shadow-lg`}
    >
      <Handle type="target" position={Position.Top} className="!bg-teal-500" />
      <div className="text-white font-medium text-sm">{data.label}</div>
      {data.description && (
        <div className="text-gray-400 text-xs mt-1 line-clamp-2">{data.description}</div>
      )}
      {data.mastery !== undefined && (
        <div className="mt-2 flex items-center justify-center gap-1">
          <div className="h-1 w-16 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full ${mastery >= 0.8 ? 'bg-green-500' : mastery >= 0.5 ? 'bg-yellow-500' : 'bg-gray-500'}`}
              style={{ width: `${mastery * 100}%` }}
            />
          </div>
          <span className="text-xs text-gray-500">{Math.round(mastery * 100)}%</span>
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-teal-500" />
    </div>
  )
}

const nodeTypes: NodeTypes = {
  concept: ConceptNode
}

const defaultNodes: Node<ConceptNodeData>[] = [
  {
    id: '1',
    type: 'concept',
    position: { x: 250, y: 50 },
    data: { label: 'Main Topic', mastery: 0.3 }
  }
]

const defaultEdges: Edge[] = []

export default function TopicCanvas({ topicId }: TopicCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<ConceptNodeData>>(defaultNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(defaultEdges)
  const [isEditing, setIsEditing] = useState(false)
  const [selectedNode, setSelectedNode] = useState<Node<ConceptNodeData> | null>(null)
  const [newNodeLabel, setNewNodeLabel] = useState('')

  // Load artifact from backend when topic changes
  useEffect(() => {
    if (topicId) {
      loadArtifact(topicId)
    } else {
      setNodes(defaultNodes)
      setEdges(defaultEdges)
    }
  }, [topicId])

  const loadArtifact = async (tid: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/artifacts?topic_id=${tid}&artifact_type=concept_map`, {
        credentials: 'include'
      })
      if (response.ok) {
        const artifacts = await response.json()
        if (artifacts.length > 0) {
          const content = artifacts[0].content
          if (content.nodes && content.edges) {
            setNodes(content.nodes)
            setEdges(content.edges)
          }
        }
      }
    } catch (error) {
      console.error('Failed to load artifact:', error)
    }
  }

  const saveArtifact = async () => {
    if (!topicId) return

    try {
      // Check if artifact exists
      const checkResponse = await fetch(`${APP_CONFIG.apiUrl}/api/learn/artifacts?topic_id=${topicId}&artifact_type=concept_map`, {
        credentials: 'include'
      })

      const artifacts = await checkResponse.json()
      const content = { nodes, edges }

      if (artifacts.length > 0) {
        // Update existing
        await fetch(`${APP_CONFIG.apiUrl}/api/learn/artifacts/${artifacts[0].id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ content })
        })
      } else {
        // Create new
        await fetch(`${APP_CONFIG.apiUrl}/api/learn/artifacts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            topic_id: topicId,
            artifact_type: 'concept_map',
            title: 'Concept Map',
            content
          })
        })
      }
    } catch (error) {
      console.error('Failed to save artifact:', error)
    }
  }

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge({
      ...params,
      animated: true,
      style: { stroke: '#14b8a6' }
    }, eds)),
    [setEdges]
  )

  const handleAddNode = () => {
    if (!newNodeLabel.trim()) return

    const newNode: Node<ConceptNodeData> = {
      id: Date.now().toString(),
      type: 'concept',
      position: { x: Math.random() * 300 + 100, y: Math.random() * 200 + 100 },
      data: { label: newNodeLabel.trim(), mastery: 0 }
    }
    setNodes((nds) => [...nds, newNode])
    setNewNodeLabel('')
  }

  const handleDeleteNode = () => {
    if (!selectedNode) return
    setNodes((nds) => nds.filter((n) => n.id !== selectedNode.id))
    setEdges((eds) => eds.filter((e) => e.source !== selectedNode.id && e.target !== selectedNode.id))
    setSelectedNode(null)
  }

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node<ConceptNodeData>) => {
    setSelectedNode(node)
  }, [])

  if (!topicId) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-900">
        <div className="text-center">
          <span className="material-icons text-5xl text-gray-600 mb-4">account_tree</span>
          <p className="text-gray-500">Select a topic to view or create a concept map</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full w-full bg-gray-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        className="bg-gray-900"
        defaultEdgeOptions={{
          animated: true,
          style: { stroke: '#14b8a6', strokeWidth: 2 }
        }}
      >
        <Controls className="!bg-gray-800 !border-gray-700 !shadow-lg [&>button]:!bg-gray-800 [&>button]:!border-gray-700 [&>button]:hover:!bg-gray-700 [&>button>svg]:!fill-gray-300" />
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#374151" />

        {/* Toolbar Panel */}
        <Panel position="top-left" className="flex gap-2">
          <div className="bg-gray-800 rounded-lg p-2 flex items-center gap-2 shadow-lg border border-gray-700">
            <input
              type="text"
              value={newNodeLabel}
              onChange={(e) => setNewNodeLabel(e.target.value)}
              placeholder="New concept..."
              className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-500 w-40 focus:outline-none focus:border-teal-500"
              onKeyDown={(e) => e.key === 'Enter' && handleAddNode()}
            />
            <button
              onClick={handleAddNode}
              disabled={!newNodeLabel.trim()}
              className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-700 text-white px-3 py-1.5 rounded text-sm"
            >
              Add
            </button>
          </div>

          {selectedNode && (
            <div className="bg-gray-800 rounded-lg p-2 flex items-center gap-2 shadow-lg border border-gray-700">
              <span className="text-sm text-gray-300 px-2">
                Selected: <span className="text-white font-medium">{selectedNode.data.label}</span>
              </span>
              <button
                onClick={handleDeleteNode}
                className="bg-red-600 hover:bg-red-700 text-white px-3 py-1.5 rounded text-sm"
              >
                Delete
              </button>
            </div>
          )}
        </Panel>

        {/* Save Panel */}
        <Panel position="top-right">
          <div className="bg-gray-800 rounded-lg p-2 shadow-lg border border-gray-700">
            <button
              onClick={saveArtifact}
              className="bg-teal-600 hover:bg-teal-700 text-white px-4 py-1.5 rounded text-sm flex items-center gap-2"
            >
              <span className="material-icons text-sm">save</span>
              Save Map
            </button>
          </div>
        </Panel>

        {/* Help Panel */}
        <Panel position="bottom-left">
          <div className="bg-gray-800/80 rounded-lg px-3 py-2 text-xs text-gray-400 border border-gray-700">
            <p>Drag nodes to reposition • Connect nodes by dragging from handles</p>
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
}
