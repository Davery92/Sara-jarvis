import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layers, Check, Trash2, Plus, Sparkles, X } from 'lucide-react'
import { useCanvasStore } from '../store/canvasStore'
import { saraApi } from '../services/api'
import type { SaraBrief } from '../types/sara'

interface ScenePickerProps {
  isOpen: boolean
  onClose: () => void
}

const SCENE_ICONS: Record<string, string> = {
  Morning: '🌅',
  Focus: '🎯',
  Learning: '📚',
  'Wind Down': '🌙',
}

export default function ScenePicker({ isOpen, onClose }: ScenePickerProps) {
  const { scenes, activeSceneId, loadScene, saveScene, deleteScene } = useCanvasStore()
  const [isSaving, setIsSaving] = useState(false)
  const [sceneName, setSceneName] = useState('')

  const { data: brief } = useQuery<SaraBrief>({
    queryKey: ['sara-brief'],
    queryFn: saraApi.getBrief,
    refetchInterval: 120_000,
    retry: 1,
  })

  const timePeriod = brief?.time_period || ''

  if (!isOpen) return null

  const builtInScenes = scenes.filter(s => s.isBuiltIn)
  const userScenes = scenes.filter(s => !s.isBuiltIn)

  const handleSave = () => {
    if (!sceneName.trim()) return
    saveScene(sceneName.trim())
    setSceneName('')
    setIsSaving(false)
  }

  return (
    <div className="fixed top-14 right-48 z-50">
      <div className="w-72 bg-canvas-surface border border-canvas-border rounded-xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-canvas-border">
          <div className="flex items-center gap-2">
            <Layers size={16} className="text-teal-500" />
            <span className="text-sm font-semibold text-white">Scenes</span>
          </div>
          <button onClick={onClose} className="p-1 text-canvas-muted hover:text-white rounded">
            <X size={14} />
          </button>
        </div>

        {/* Built-in Scenes */}
        <div className="p-2">
          <div className="text-[10px] uppercase tracking-wider text-canvas-muted px-2 mb-1">Workspaces</div>
          {builtInScenes.map(scene => {
            const isActive = activeSceneId === scene.id
            const isSuggested = scene.suggestedTimePeriods?.includes(timePeriod)

            return (
              <button
                key={scene.id}
                onClick={() => { loadScene(scene.id); onClose() }}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                  isActive ? 'bg-teal-500/15 border border-teal-500/30' : 'hover:bg-canvas-elevated border border-transparent'
                }`}
              >
                <span className="text-lg flex-shrink-0">{SCENE_ICONS[scene.name] || '📋'}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={`text-sm ${isActive ? 'text-teal-400 font-medium' : 'text-white'}`}>
                      {scene.name}
                    </span>
                    {isActive && <Check size={12} className="text-teal-400" />}
                    {isSuggested && !isActive && (
                      <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded-full">
                        <Sparkles size={8} />
                        Suggested
                      </span>
                    )}
                  </div>
                  {scene.description && (
                    <div className="text-xs text-canvas-muted mt-0.5 truncate">{scene.description}</div>
                  )}
                </div>
              </button>
            )
          })}
        </div>

        {/* User Scenes */}
        {userScenes.length > 0 && (
          <div className="px-2 pb-2">
            <div className="text-[10px] uppercase tracking-wider text-canvas-muted px-2 mb-1 mt-1">Saved</div>
            {userScenes.map(scene => {
              const isActive = activeSceneId === scene.id
              return (
                <div
                  key={scene.id}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${
                    isActive ? 'bg-teal-500/15' : 'hover:bg-canvas-elevated'
                  }`}
                >
                  <button
                    onClick={() => { loadScene(scene.id); onClose() }}
                    className="flex-1 text-left"
                  >
                    <span className={`text-sm ${isActive ? 'text-teal-400 font-medium' : 'text-white'}`}>
                      {scene.name}
                    </span>
                    {scene.description && (
                      <div className="text-xs text-canvas-muted truncate">{scene.description}</div>
                    )}
                  </button>
                  <button
                    onClick={() => deleteScene(scene.id)}
                    className="p-1 text-canvas-muted hover:text-red-400 rounded flex-shrink-0"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        {/* Save Current */}
        <div className="p-2 border-t border-canvas-border">
          {isSaving ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={sceneName}
                onChange={e => setSceneName(e.target.value)}
                onKeyDown={e => {
                  e.stopPropagation()
                  if (e.key === 'Enter') handleSave()
                  if (e.key === 'Escape') setIsSaving(false)
                }}
                placeholder="Scene name..."
                className="flex-1 px-2 py-1.5 bg-canvas-bg rounded border border-canvas-border text-sm text-white placeholder-canvas-muted focus:outline-none focus:border-teal-500"
                autoFocus
              />
              <button
                onClick={handleSave}
                disabled={!sceneName.trim()}
                className="px-3 py-1.5 bg-teal-500 hover:bg-teal-600 disabled:opacity-50 rounded text-sm text-white"
              >
                Save
              </button>
            </div>
          ) : (
            <button
              onClick={() => setIsSaving(true)}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm text-canvas-muted hover:text-white hover:bg-canvas-elevated rounded-lg transition-colors"
            >
              <Plus size={14} />
              Save current layout
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
