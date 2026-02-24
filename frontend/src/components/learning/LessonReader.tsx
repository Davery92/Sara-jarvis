import React from 'react'
import MarkdownRenderer from '../MarkdownRenderer'
import { LearningArtifact } from './LearningSection'

interface LessonReaderProps {
  artifact: LearningArtifact
  onClose?: () => void
  onDetach?: () => void
  isDetached?: boolean
  showHeader?: boolean
  showDetachButton?: boolean
  showCloseButton?: boolean
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

export default function LessonReader({
  artifact,
  onClose,
  onDetach,
  isDetached = false,
  showHeader = true,
  showDetachButton = false,
  showCloseButton = true
}: LessonReaderProps) {
  const c = artifact.content as Record<string, any>
  const moduleCode = c?.module_code || ''
  const moduleTitle = c?.module_title || ''
  const wordCount = c?.word_count || 0
  const readTime = c?.estimated_read_time_minutes || (wordCount ? Math.ceil(wordCount / 200) : 0)
  const markdown = c?.lesson_markdown || c?.guide_markdown || ''
  const sources: Array<{ title?: string; url?: string }> = c?.sources || []
  const generatedAt = c?.generated_at || artifact.created_at

  const title = artifact.title || moduleTitle || 'Untitled'

  const body = (
    <div className="flex-1 overflow-auto px-6 py-5">
      <div className="max-w-3xl mx-auto">
        {markdown ? (
          <div className="prose prose-invert prose-sm max-w-none text-gray-200 leading-relaxed">
            <MarkdownRenderer content={markdown} />
          </div>
        ) : (
          <div className="text-center text-gray-500 py-12">
            <span className="material-icons text-4xl mb-2">article</span>
            <p>No content available for this artifact.</p>
          </div>
        )}

        {/* Sources */}
        {sources.length > 0 && (
          <div className="mt-8 pt-6 border-t border-gray-700">
            <h4 className="text-sm font-medium text-gray-400 mb-3">Sources</h4>
            <ul className="space-y-1.5">
              {sources.map((source, i) => (
                <li key={i} className="text-sm">
                  {source.url ? (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-teal-400 hover:text-teal-300 underline"
                    >
                      {source.title || source.url}
                    </a>
                  ) : (
                    <span className="text-gray-400">{source.title || 'Unknown source'}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )

  if (!showHeader) {
    return (
      <div className="flex flex-col h-full bg-gray-900">
        {body}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700 bg-gray-900/95 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-3 min-w-0">
          <span className="material-icons text-teal-400">{typeIcon(artifact.artifact_type)}</span>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-white truncate">{title}</div>
            <div className="flex items-center gap-2 text-[11px] text-gray-400">
              {moduleCode && <span className="font-mono text-teal-400">{moduleCode}</span>}
              <span>{typeLabel(artifact.artifact_type)}</span>
              {wordCount > 0 && <span>{wordCount.toLocaleString()} words</span>}
              {readTime > 0 && <span>{readTime} min read</span>}
              {generatedAt && (
                <span>{new Date(generatedAt).toLocaleDateString()}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {showDetachButton && onDetach && (
            <button
              onClick={onDetach}
              className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              title={isDetached ? 'Attach back' : 'Detach panel'}
            >
              <span className="material-icons text-sm">
                {isDetached ? 'vertical_align_bottom' : 'open_in_new'}
              </span>
            </button>
          )}
          {showCloseButton && onClose && (
            <button
              onClick={onClose}
              className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
            >
              <span className="material-icons text-sm">close</span>
            </button>
          )}
        </div>
      </div>

      {body}
    </div>
  )
}
