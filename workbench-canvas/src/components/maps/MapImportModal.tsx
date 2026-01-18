import { useState, useEffect } from 'react'
import { X, FileJson, GitBranch, Loader2, Lock } from 'lucide-react'
import { useCanvasStore } from '../../store/canvasStore'
import { mapsApi } from '../../services/api'
import { useQueryClient } from '@tanstack/react-query'
import type { MapInstance } from '../../types'

type ImportFormat = 'json' | 'mermaid'

export default function MapImportModal() {
  const { setMapImportModalOpen, setMapPickerOpen, addMap } = useCanvasStore()
  const queryClient = useQueryClient()

  const [format, setFormat] = useState<ImportFormat>('json')
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [isReadonly, setIsReadonly] = useState(false)
  const [isImporting, setIsImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMapImportModalOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [setMapImportModalOpen])

  const handleImport = async () => {
    if (!name.trim()) {
      setError('Please enter a map name')
      return
    }
    if (!content.trim()) {
      setError('Please enter content to import')
      return
    }

    setIsImporting(true)
    setError(null)

    try {
      const response = await mapsApi.import({
        name: name.trim(),
        content: content.trim(),
        format,
        is_readonly: isReadonly,
      })

      // Add to canvas
      const mapInstance: MapInstance = {
        id: response.id,
        name: response.name,
        description: response.description,
        mapData: response.map_data,
        isReadonly: response.is_readonly,
        canvasPosition: { x: 200, y: 200 },
        collapsed: false,
      }

      addMap(mapInstance)
      queryClient.invalidateQueries({ queryKey: ['maps'] })
      setMapImportModalOpen(false)
      setMapPickerOpen(false)
    } catch (e: any) {
      console.error('Import failed:', e)
      setError(e.message || 'Failed to import map')
    } finally {
      setIsImporting(false)
    }
  }

  const jsonExample = `{
  "nodes": [
    { "id": "a", "label": "Start", "position": { "x": 0, "y": 0 } },
    { "id": "b", "label": "Process", "position": { "x": 200, "y": 0 } },
    { "id": "c", "label": "End", "position": { "x": 400, "y": 0 } }
  ],
  "edges": [
    { "source": "a", "target": "b" },
    { "source": "b", "target": "c" }
  ]
}`

  const mermaidExample = `flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Process A]
    B -->|No| D[Process B]
    C --> E[End]
    D --> E`

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-[100]"
      onClick={() => setMapImportModalOpen(false)}
    >
      <div
        className="bg-gray-800 border border-gray-600 rounded-xl shadow-2xl w-[600px] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">Import Map</h2>
          <button
            onClick={() => setMapImportModalOpen(false)}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Format Tabs */}
        <div className="flex border-b border-gray-700">
          <button
            onClick={() => setFormat('json')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
              format === 'json'
                ? 'text-teal-400 border-b-2 border-teal-400 bg-gray-700/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-700/30'
            }`}
          >
            <FileJson size={16} />
            JSON
          </button>
          <button
            onClick={() => setFormat('mermaid')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
              format === 'mermaid'
                ? 'text-teal-400 border-b-2 border-teal-400 bg-gray-700/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-700/30'
            }`}
          >
            <GitBranch size={16} />
            Mermaid
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Map Name */}
          <div>
            <label className="block text-sm text-gray-400 mb-2">Map Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Flowchart"
              className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
            />
          </div>

          {/* Content Input */}
          <div>
            <label className="block text-sm text-gray-400 mb-2">
              {format === 'json' ? 'JSON Content' : 'Mermaid Syntax'}
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={format === 'json' ? 'Paste JSON here...' : 'Paste Mermaid syntax here...'}
              className="w-full h-48 px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white font-mono text-sm placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
            />
          </div>

          {/* Read-only Option */}
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={isReadonly}
              onChange={(e) => setIsReadonly(e.target.checked)}
              className="w-4 h-4 rounded border-gray-600 bg-gray-900 text-teal-500 focus:ring-teal-500 focus:ring-offset-gray-800"
            />
            <span className="text-gray-300 text-sm flex items-center gap-2">
              <Lock size={14} />
              Import as read-only (can move but not edit)
            </span>
          </label>

          {/* Example */}
          <div>
            <button
              onClick={() => setContent(format === 'json' ? jsonExample : mermaidExample)}
              className="text-xs text-teal-400 hover:text-teal-300 underline"
            >
              Load example {format === 'json' ? 'JSON' : 'Mermaid'}
            </button>
            <pre className="mt-2 p-3 bg-gray-900 border border-gray-700 rounded-lg text-xs text-gray-400 font-mono overflow-x-auto">
              {format === 'json' ? jsonExample : mermaidExample}
            </pre>
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-4 border-t border-gray-700">
          <button
            onClick={() => setMapImportModalOpen(false)}
            className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
            disabled={isImporting}
          >
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={isImporting}
            className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isImporting && <Loader2 size={16} className="animate-spin" />}
            Import
          </button>
        </div>
      </div>
    </div>
  )
}
