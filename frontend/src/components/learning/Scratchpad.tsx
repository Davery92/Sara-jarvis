import React, { useState, useEffect, useRef } from 'react'

interface ScratchpadProps {
  content: string
  onChange: (content: string) => void
  disabled?: boolean
}

export default function Scratchpad({ content, onChange, disabled = false }: ScratchpadProps) {
  const [localContent, setLocalContent] = useState(content)
  const [isSaving, setIsSaving] = useState(false)
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Sync local content with prop
  useEffect(() => {
    setLocalContent(content)
  }, [content])

  // Debounced save
  const handleChange = (newContent: string) => {
    setLocalContent(newContent)
    setIsSaving(true)

    // Clear existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
    }

    // Set new timeout for saving
    saveTimeoutRef.current = setTimeout(() => {
      onChange(newContent)
      setIsSaving(false)
    }, 1000)
  }

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }
    }
  }, [])

  // Handle keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Tab inserts spaces
    if (e.key === 'Tab') {
      e.preventDefault()
      const textarea = textareaRef.current
      if (textarea) {
        const start = textarea.selectionStart
        const end = textarea.selectionEnd
        const newContent = localContent.substring(0, start) + '  ' + localContent.substring(end)
        handleChange(newContent)
        // Set cursor position after the inserted spaces
        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = start + 2
        }, 0)
      }
    }
  }

  const wordCount = localContent.trim() ? localContent.trim().split(/\s+/).length : 0
  const charCount = localContent.length

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
        <h3 className="font-medium text-white flex items-center gap-2">
          <span className="material-icons text-gray-400 text-lg">edit_note</span>
          Scratchpad
        </h3>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          {isSaving && (
            <span className="text-teal-400">Saving...</span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {disabled ? (
          <div className="flex items-center justify-center h-full p-4">
            <p className="text-gray-500 text-sm text-center">
              Select a topic to use the scratchpad
            </p>
          </div>
        ) : (
          <textarea
            ref={textareaRef}
            value={localContent}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Take notes here...&#10;&#10;Sara can see what you write and respond to it."
            className="w-full h-full bg-transparent text-gray-200 placeholder-gray-600 p-4 resize-none focus:outline-none font-mono text-sm leading-relaxed"
          />
        )}
      </div>

      {/* Footer */}
      {!disabled && (
        <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-500 flex justify-between">
          <span>{wordCount} words</span>
          <span>{charCount} chars</span>
        </div>
      )}
    </div>
  )
}
