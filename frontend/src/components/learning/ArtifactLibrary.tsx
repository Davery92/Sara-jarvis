import React from 'react'
import { LearningArtifact } from './LearningSection'

interface ArtifactLibraryProps {
  artifacts: LearningArtifact[]
  loading: boolean
  onOpenArtifact: (artifact: LearningArtifact) => void
  onRefresh: () => void
}

function getArtifactMeta(artifact: LearningArtifact) {
  const c = artifact.content as Record<string, any>
  const moduleCode = c?.module_code || ''
  const moduleTitle = c?.module_title || ''
  const wordCount = c?.word_count || 0
  const readTime = c?.estimated_read_time_minutes || (wordCount ? Math.ceil(wordCount / 200) : 0)
  const markdown = c?.lesson_markdown || c?.guide_markdown || ''
  const generatedAt = c?.generated_at || artifact.created_at
  return { moduleCode, moduleTitle, wordCount, readTime, markdown, generatedAt }
}

function typeLabel(artifactType: string): string {
  if (artifactType === 'lesson') return 'Lesson'
  if (artifactType === 'study_guide_pareto') return 'Pareto Guide'
  if (artifactType === 'study_guide_deep') return 'Deep Guide'
  return artifactType.replace(/_/g, ' ')
}

function typeIcon(artifactType: string): string {
  if (artifactType === 'lesson') return 'menu_book'
  if (artifactType === 'study_guide_pareto') return 'bolt'
  if (artifactType === 'study_guide_deep') return 'psychology'
  return 'article'
}

function typeBadgeColor(artifactType: string): string {
  if (artifactType === 'lesson') return 'bg-teal-900/50 text-teal-300'
  if (artifactType === 'study_guide_pareto') return 'bg-amber-900/50 text-amber-300'
  if (artifactType === 'study_guide_deep') return 'bg-indigo-900/50 text-indigo-300'
  return 'bg-gray-800 text-gray-300'
}

export default function ArtifactLibrary({ artifacts, loading, onOpenArtifact, onRefresh }: ArtifactLibraryProps) {
  // Group by module_code
  const grouped = new Map<string, LearningArtifact[]>()
  for (const a of artifacts) {
    const { moduleCode } = getArtifactMeta(a)
    const key = moduleCode || '_ungrouped'
    const list = grouped.get(key) || []
    list.push(a)
    grouped.set(key, list)
  }

  const sortedGroups = Array.from(grouped.entries()).sort(([a], [b]) => a.localeCompare(b))

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <span className="material-icons animate-spin mr-2">refresh</span>
        Loading artifacts...
      </div>
    )
  }

  if (artifacts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500 px-8">
        <span className="material-icons text-5xl mb-3 text-gray-600">local_library</span>
        <p className="text-lg font-medium text-gray-400 mb-1">No lessons or guides yet</p>
        <p className="text-sm text-center max-w-md">
          Use the Blueprint Importer to generate study guides and lessons for this topic.
        </p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-gray-300">
            {artifacts.length} artifact{artifacts.length !== 1 ? 's' : ''}
          </h3>
          <button
            onClick={onRefresh}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors"
          >
            <span className="material-icons text-sm">refresh</span>
            Refresh
          </button>
        </div>

        <div className="space-y-6">
          {sortedGroups.map(([moduleCode, items]) => {
            const firstMeta = getArtifactMeta(items[0])
            return (
              <div key={moduleCode}>
                {moduleCode !== '_ungrouped' && (
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-mono text-teal-400 bg-teal-900/30 px-2 py-0.5 rounded">
                      {moduleCode}
                    </span>
                    {firstMeta.moduleTitle && (
                      <span className="text-sm text-gray-300">{firstMeta.moduleTitle}</span>
                    )}
                  </div>
                )}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {items.map((artifact) => {
                    const meta = getArtifactMeta(artifact)
                    return (
                      <button
                        key={artifact.id}
                        onClick={() => onOpenArtifact(artifact)}
                        className="text-left bg-gray-800 hover:bg-gray-750 border border-gray-700 hover:border-teal-600/50 rounded-lg p-4 transition-all group"
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <span className="material-icons text-gray-500 group-hover:text-teal-400 transition-colors">
                            {typeIcon(artifact.artifact_type)}
                          </span>
                          <span className={`px-2 py-0.5 rounded text-[11px] ${typeBadgeColor(artifact.artifact_type)}`}>
                            {typeLabel(artifact.artifact_type)}
                          </span>
                        </div>
                        <div className="text-sm font-medium text-white mb-1 line-clamp-2">
                          {artifact.title || meta.moduleTitle || 'Untitled'}
                        </div>
                        <div className="flex items-center gap-3 text-[11px] text-gray-500">
                          {meta.wordCount > 0 && (
                            <span>{meta.wordCount.toLocaleString()} words</span>
                          )}
                          {meta.readTime > 0 && (
                            <span>{meta.readTime} min read</span>
                          )}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
