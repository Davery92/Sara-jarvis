import React from 'react'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface TimelineItem {
  id: string
  type: 'note' | 'episode' | 'document' | 'insight'
  title: string
  content: string
  timestamp: string
  metadata?: any
}

interface TimelineViewProps {
  notes: Note[]
  onItemClick?: (item: TimelineItem) => void
}

export default function TimelineView({ notes, onItemClick }: TimelineViewProps) {
  return (
    <div className="w-full h-full bg-[#27272a] rounded-lg border border-[#3f3f46] overflow-hidden flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-[#3f3f46] flex-shrink-0">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium text-[#f8fafc]">Knowledge Timeline</h3>
        </div>
        <p className="text-sm text-[#a1a1aa] mt-2">
          Timeline view coming soon
        </p>
      </div>

      {/* Empty State */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 bg-[#3f3f46] rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-[#a1a1aa]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-xl font-medium text-[#f8fafc] mb-2">Knowledge Timeline</h3>
          <p className="text-[#a1a1aa] max-w-sm">
            A chronological view of your notes, conversations, and insights will be available here soon.
          </p>
        </div>
      </div>
    </div>
  )
}