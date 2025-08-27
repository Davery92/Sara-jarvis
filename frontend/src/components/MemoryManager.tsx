import React from 'react'

interface MemoryManagerProps {
  onClose?: () => void
}

export default function MemoryManager({ onClose }: MemoryManagerProps) {
  return (
    <div className="w-full h-full bg-[#27272a] rounded-lg border border-[#3f3f46] overflow-hidden flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-[#3f3f46] flex-shrink-0">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium text-[#f8fafc]">Memory Management</h3>
          {onClose && (
            <button
              onClick={onClose}
              className="text-[#a1a1aa] hover:text-[#f8fafc]"
            >
              ×
            </button>
          )}
        </div>
        <p className="text-sm text-[#a1a1aa] mt-2">
          Memory management tools coming soon
        </p>
      </div>

      {/* Empty State */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 bg-[#3f3f46] rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-[#a1a1aa]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
            </svg>
          </div>
          <h3 className="text-xl font-medium text-[#f8fafc] mb-2">Memory Management</h3>
          <p className="text-[#a1a1aa] max-w-sm">
            Advanced memory curation and management tools will be available here soon.
          </p>
        </div>
      </div>
    </div>
  )
}