/**
 * NoteArtifact Component
 *
 * Markdown editor for viewing and editing existing notes in the canvas.
 * Supports auto-save back to the notes system with 1-second debounce.
 */
import React, { useState, useCallback } from 'react'
import { Copy, Check, FileText, Code, Save, AlertCircle, CheckCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Artifact, NoteContent, ArtifactContent } from '../types'
import { useNoteSync } from '../hooks/useNoteSync'

interface NoteArtifactProps {
  artifact: Artifact
  isEditing?: boolean
  onUpdate?: (content: ArtifactContent) => Promise<void>
}

export function NoteArtifact({ artifact, isEditing = true }: NoteArtifactProps) {
  const noteContent = artifact.content as NoteContent
  // Default to source/edit mode for better editing experience
  const [viewMode, setViewMode] = useState<'preview' | 'source'>('source')
  const [copied, setCopied] = useState(false)

  // Use the note sync hook for auto-save
  const {
    content,
    title,
    setContent,
    setTitle,
    isDirty,
    isSaving,
    lastSaved,
    error,
    save
  } = useNoteSync({
    noteId: noteContent.note_id,
    initialContent: noteContent.content,
    initialTitle: noteContent.title,
    enabled: isEditing
  })

  // Copy content to clipboard
  const copyContent = useCallback(() => {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [content])

  // Markdown components for rendering
  const markdownComponents = {
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '')
      const language = match ? match[1] : ''

      if (!inline && language) {
        return (
          <SyntaxHighlighter
            style={oneDark}
            language={language}
            PreTag="div"
            customStyle={{
              margin: '1rem 0',
              borderRadius: '0.5rem',
              fontSize: '0.875rem',
            }}
            {...props}
          >
            {String(children).replace(/\n$/, '')}
          </SyntaxHighlighter>
        )
      }

      return (
        <code
          className="px-1.5 py-0.5 bg-gray-800 rounded text-pink-400 text-sm"
          {...props}
        >
          {children}
        </code>
      )
    },
    h1: ({ children }: any) => (
      <h1 className="text-2xl font-bold text-white mt-6 mb-4 pb-2 border-b border-gray-700">
        {children}
      </h1>
    ),
    h2: ({ children }: any) => (
      <h2 className="text-xl font-bold text-white mt-5 mb-3">
        {children}
      </h2>
    ),
    h3: ({ children }: any) => (
      <h3 className="text-lg font-semibold text-white mt-4 mb-2">
        {children}
      </h3>
    ),
    p: ({ children }: any) => (
      <p className="text-gray-300 leading-relaxed mb-4">
        {children}
      </p>
    ),
    ul: ({ children }: any) => (
      <ul className="list-disc list-inside text-gray-300 mb-4 space-y-1">
        {children}
      </ul>
    ),
    ol: ({ children }: any) => (
      <ol className="list-decimal list-inside text-gray-300 mb-4 space-y-1">
        {children}
      </ol>
    ),
    blockquote: ({ children }: any) => (
      <blockquote className="border-l-4 border-teal-500 pl-4 italic text-gray-400 my-4">
        {children}
      </blockquote>
    ),
    a: ({ href, children }: any) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-teal-400 hover:text-teal-300 underline"
      >
        {children}
      </a>
    ),
    table: ({ children }: any) => (
      <div className="overflow-x-auto my-4">
        <table className="min-w-full border border-gray-700 rounded">
          {children}
        </table>
      </div>
    ),
    th: ({ children }: any) => (
      <th className="px-4 py-2 bg-gray-800 border-b border-gray-700 text-left text-white font-semibold">
        {children}
      </th>
    ),
    td: ({ children }: any) => (
      <td className="px-4 py-2 border-b border-gray-700 text-gray-300">
        {children}
      </td>
    ),
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header with title */}
      {isEditing && (
        <div className="px-4 py-3 bg-gray-800 border-b border-gray-700">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full bg-transparent text-xl font-semibold text-white focus:outline-none placeholder-gray-500"
            placeholder="Note title..."
          />
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode('preview')}
            className={`p-2 rounded flex items-center gap-2 text-sm ${
              viewMode === 'preview'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            <FileText size={16} />
            Preview
          </button>
          <button
            onClick={() => setViewMode('source')}
            className={`p-2 rounded flex items-center gap-2 text-sm ${
              viewMode === 'source'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            <Code size={16} />
            {isEditing ? 'Edit' : 'Source'}
          </button>
        </div>

        <div className="flex items-center gap-3">
          {/* Save status indicator */}
          {isEditing && (
            <div className="flex items-center gap-2 text-sm">
              {error ? (
                <span className="text-red-400 flex items-center gap-1">
                  <AlertCircle size={14} />
                  Error saving
                </span>
              ) : isSaving ? (
                <span className="text-gray-400 flex items-center gap-1">
                  <Save size={14} className="animate-pulse" />
                  Saving...
                </span>
              ) : isDirty ? (
                <span className="text-yellow-400 flex items-center gap-1">
                  <AlertCircle size={14} />
                  Unsaved
                </span>
              ) : lastSaved ? (
                <span className="text-green-400 flex items-center gap-1">
                  <CheckCircle size={14} />
                  Saved
                </span>
              ) : null}
            </div>
          )}

          <button
            onClick={copyContent}
            className="p-2 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
            title="Copy content"
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
          </button>

          {isEditing && isDirty && (
            <button
              onClick={save}
              disabled={isSaving}
              className="px-3 py-1.5 bg-teal-600 hover:bg-teal-700 disabled:bg-gray-700 text-white rounded text-sm flex items-center gap-1"
            >
              <Save size={14} />
              Save
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isEditing && viewMode === 'source' ? (
          // Editor
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="w-full h-full p-6 bg-gray-950 text-gray-100 font-mono text-sm resize-none focus:outline-none"
            spellCheck={false}
            placeholder="Write your note in markdown..."
          />
        ) : viewMode === 'source' ? (
          // Source view (read-only)
          <pre className="p-6 bg-gray-950 text-gray-300 font-mono text-sm whitespace-pre-wrap">
            {content}
          </pre>
        ) : (
          // Preview
          <div className="p-6 bg-gray-900 prose prose-invert max-w-none">
            {!isEditing && title && (
              <h1 className="text-2xl font-bold text-white mb-6 pb-2 border-b border-gray-700">
                {title}
              </h1>
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {/* Footer with note info */}
      {noteContent.folder_id && (
        <div className="px-4 py-2 bg-gray-800 border-t border-gray-700 text-xs text-gray-500">
          Note ID: {noteContent.note_id}
        </div>
      )}
    </div>
  )
}

export default NoteArtifact
