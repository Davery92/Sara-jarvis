/**
 * MindmapArtifact Component
 *
 * Interactive mindmap editor using ReactFlow for the canvas panel.
 * Supports node types: topic (blue), idea (green), task (yellow), note (gray)
 */
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
import { Artifact, MindmapContent, MindmapNode, MindmapEdge } from '../types'
import { Plus, Trash2, Circle, Lightbulb, CheckSquare, StickyNote } from 'lucide-react'

interface MindmapArtifactProps {
  artifact: Artifact
  isEditing?: boolean
  onUpdate?: (content: MindmapContent) => Promise<void>
}

interface MindmapNodeData {
  label: string
  color?: string
  notes?: string
  nodeType: 'topic' | 'idea' | 'task' | 'note'
}

// Node type colors
const nodeColors = {
  topic: { bg: 'bg-blue-600', border: 'border-blue-400', ring: 'ring-blue-400' },
  idea: { bg: 'bg-green-600', border: 'border-green-400', ring: 'ring-green-400' },
  task: { bg: 'bg-yellow-600', border: 'border-yellow-400', ring: 'ring-yellow-400' },
  note: { bg: 'bg-gray-600', border: 'border-gray-400', ring: 'ring-gray-400' }
}

// Custom Mindmap Node
function MindmapNodeComponent({ data, selected }: NodeProps<Node<MindmapNodeData>>) {
  const colors = nodeColors[data.nodeType || 'topic']

  return (
    <div
      className={`px-4 py-3 rounded-xl border-2 ${colors.border} ${
        selected ? `${colors.bg}/80 ring-2 ${colors.ring}` : 'bg-gray-800'
      } min-w-[100px] max-w-[200px] text-center shadow-lg transition-all`}
    >
      <Handle type="target" position={Position.Top} className="!bg-teal-500 !w-3 !h-3" />
      <div className="text-white font-medium text-sm break-words">{data.label}</div>
      {data.notes && (
        <div className="text-gray-400 text-xs mt-1 line-clamp-2">{data.notes}</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-teal-500 !w-3 !h-3" />
    </div>
  )
}

const nodeTypes: NodeTypes = {
  mindmap: MindmapNodeComponent
}

// Convert internal nodes to MindmapContent format
function toMindmapContent(
  nodes: Node<MindmapNodeData>[],
  edges: Edge[],
  viewport: { x: number; y: number; zoom: number }
): MindmapContent {
  return {
    nodes: nodes.map(n => ({
      id: n.id,
      type: (n.data.nodeType || 'topic') as 'topic' | 'idea' | 'task' | 'note',
      position: n.position,
      data: {
        label: n.data.label,
        color: n.data.color,
        notes: n.data.notes
      }
    })),
    edges: edges.map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: e.type as 'default' | 'smoothstep' | undefined
    })),
    viewport
  }
}

// Convert MindmapContent to internal nodes
function fromMindmapContent(content: MindmapContent): {
  nodes: Node<MindmapNodeData>[]
  edges: Edge[]
} {
  return {
    nodes: (content.nodes || []).map(n => ({
      id: n.id,
      type: 'mindmap',
      position: n.position,
      data: {
        label: n.data.label,
        color: n.data.color,
        notes: n.data.notes,
        nodeType: n.type
      }
    })),
    edges: (content.edges || []).map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: e.type || 'smoothstep',
      animated: true,
      style: { stroke: '#14b8a6', strokeWidth: 2 }
    }))
  }
}

export function MindmapArtifact({ artifact, isEditing = false, onUpdate }: MindmapArtifactProps) {
  const content = artifact.content as MindmapContent
  const initial = fromMindmapContent(content)

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<MindmapNodeData>>(initial.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges)
  const [selectedNode, setSelectedNode] = useState<Node<MindmapNodeData> | null>(null)
  const [newNodeLabel, setNewNodeLabel] = useState('')
  const [newNodeType, setNewNodeType] = useState<'topic' | 'idea' | 'task' | 'note'>('idea')
  const [editingLabel, setEditingLabel] = useState<string | null>(null)
  const [editLabelValue, setEditLabelValue] = useState('')
  const [viewport, setViewport] = useState(content.viewport || { x: 0, y: 0, zoom: 1 })

  // Sync with external content changes
  useEffect(() => {
    const updated = fromMindmapContent(artifact.content as MindmapContent)
    setNodes(updated.nodes)
    setEdges(updated.edges)
  }, [artifact.id])

  // Save changes when nodes/edges change (debounced)
  useEffect(() => {
    if (!isEditing || !onUpdate) return

    const timeout = setTimeout(() => {
      const newContent = toMindmapContent(nodes, edges, viewport)
      onUpdate(newContent)
    }, 500)

    return () => clearTimeout(timeout)
  }, [nodes, edges, viewport, isEditing, onUpdate])

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge({
      ...params,
      type: 'smoothstep',
      animated: true,
      style: { stroke: '#14b8a6', strokeWidth: 2 }
    }, eds)),
    [setEdges]
  )

  const handleAddNode = () => {
    if (!newNodeLabel.trim()) return

    const newNode: Node<MindmapNodeData> = {
      id: `node-${Date.now()}`,
      type: 'mindmap',
      position: {
        x: Math.random() * 300 + 100,
        y: Math.random() * 200 + 100
      },
      data: {
        label: newNodeLabel.trim(),
        nodeType: newNodeType
      }
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

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node<MindmapNodeData>) => {
    setSelectedNode(node)
  }, [])

  const handleNodeDoubleClick = useCallback((_: React.MouseEvent, node: Node<MindmapNodeData>) => {
    if (!isEditing) return
    setEditingLabel(node.id)
    setEditLabelValue(node.data.label)
  }, [isEditing])

  const handleLabelSave = () => {
    if (!editingLabel || !editLabelValue.trim()) return

    setNodes((nds) => nds.map((n) =>
      n.id === editingLabel
        ? { ...n, data: { ...n.data, label: editLabelValue.trim() } }
        : n
    ))
    setEditingLabel(null)
    setEditLabelValue('')
  }

  const handleMoveEnd = useCallback((_: any, vp: { x: number; y: number; zoom: number }) => {
    setViewport(vp)
  }, [])

  const NodeTypeButton = ({ type, icon: Icon, label }: { type: typeof newNodeType, icon: any, label: string }) => (
    <button
      onClick={() => setNewNodeType(type)}
      className={`p-2 rounded ${newNodeType === type ? nodeColors[type].bg : 'bg-gray-700'} hover:opacity-80 transition-opacity`}
      title={label}
    >
      <Icon size={16} className="text-white" />
    </button>
  )

  return (
    <div className="h-full w-full bg-gray-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={isEditing ? onNodesChange : undefined}
        onEdgesChange={isEditing ? onEdgesChange : undefined}
        onConnect={isEditing ? onConnect : undefined}
        onNodeClick={handleNodeClick}
        onNodeDoubleClick={handleNodeDoubleClick}
        onMoveEnd={handleMoveEnd}
        nodeTypes={nodeTypes}
        defaultViewport={viewport}
        fitView={!content.viewport}
        nodesDraggable={isEditing}
        nodesConnectable={isEditing}
        elementsSelectable={isEditing}
        className="bg-gray-900"
        defaultEdgeOptions={{
          type: 'smoothstep',
          animated: true,
          style: { stroke: '#14b8a6', strokeWidth: 2 }
        }}
      >
        <Controls className="!bg-gray-800 !border-gray-700 !shadow-lg [&>button]:!bg-gray-800 [&>button]:!border-gray-700 [&>button]:hover:!bg-gray-700 [&>button>svg]:!fill-gray-300" />
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#374151" />

        {/* Add Node Toolbar (only in edit mode) */}
        {isEditing && (
          <Panel position="top-left" className="flex gap-2">
            <div className="bg-gray-800 rounded-lg p-2 flex items-center gap-2 shadow-lg border border-gray-700">
              {/* Node type selector */}
              <div className="flex gap-1 mr-2">
                <NodeTypeButton type="topic" icon={Circle} label="Topic" />
                <NodeTypeButton type="idea" icon={Lightbulb} label="Idea" />
                <NodeTypeButton type="task" icon={CheckSquare} label="Task" />
                <NodeTypeButton type="note" icon={StickyNote} label="Note" />
              </div>

              <input
                type="text"
                value={newNodeLabel}
                onChange={(e) => setNewNodeLabel(e.target.value)}
                placeholder={`New ${newNodeType}...`}
                className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-500 w-40 focus:outline-none focus:border-teal-500"
                onKeyDown={(e) => e.key === 'Enter' && handleAddNode()}
              />
              <button
                onClick={handleAddNode}
                disabled={!newNodeLabel.trim()}
                className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-700 text-white p-1.5 rounded"
              >
                <Plus size={18} />
              </button>
            </div>

            {selectedNode && (
              <div className="bg-gray-800 rounded-lg p-2 flex items-center gap-2 shadow-lg border border-gray-700">
                <span className="text-sm text-gray-300 px-2">
                  <span className="text-white font-medium">{selectedNode.data.label}</span>
                </span>
                <button
                  onClick={handleDeleteNode}
                  className="bg-red-600 hover:bg-red-700 text-white p-1.5 rounded"
                  title="Delete node"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            )}
          </Panel>
        )}

        {/* Help Panel */}
        <Panel position="bottom-left">
          <div className="bg-gray-800/80 rounded-lg px-3 py-2 text-xs text-gray-400 border border-gray-700">
            {isEditing ? (
              <p>Drag nodes to reposition | Connect by dragging handles | Double-click to edit</p>
            ) : (
              <p>View mode | Click Edit to modify the mindmap</p>
            )}
          </div>
        </Panel>

        {/* Legend */}
        <Panel position="bottom-right">
          <div className="bg-gray-800/80 rounded-lg px-3 py-2 text-xs border border-gray-700 flex gap-3">
            <span className="flex items-center gap-1"><Circle size={12} className="text-blue-400" /> Topic</span>
            <span className="flex items-center gap-1"><Lightbulb size={12} className="text-green-400" /> Idea</span>
            <span className="flex items-center gap-1"><CheckSquare size={12} className="text-yellow-400" /> Task</span>
            <span className="flex items-center gap-1"><StickyNote size={12} className="text-gray-400" /> Note</span>
          </div>
        </Panel>
      </ReactFlow>

      {/* Edit Label Modal */}
      {editingLabel && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-4 shadow-xl border border-gray-700 w-80">
            <h3 className="text-white font-medium mb-3">Edit Label</h3>
            <input
              type="text"
              value={editLabelValue}
              onChange={(e) => setEditLabelValue(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-teal-500"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleLabelSave()
                if (e.key === 'Escape') setEditingLabel(null)
              }}
            />
            <div className="flex gap-2 mt-3 justify-end">
              <button
                onClick={() => setEditingLabel(null)}
                className="px-3 py-1.5 text-sm text-gray-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleLabelSave}
                className="bg-teal-600 hover:bg-teal-700 text-white px-3 py-1.5 rounded text-sm"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MindmapArtifact
