import React, { useState } from 'react'
import { LearningTopic } from './LearningSection'

interface TopicSidebarProps {
  topics: LearningTopic[]
  currentTopic: LearningTopic | null
  onSelectTopic: (topic: LearningTopic | null) => void
  onCreateTopic: (title: string, description?: string, parentId?: string, autoResearch?: boolean) => void
  onDeleteTopic?: (topicId: string) => void
  loading: boolean
}

export default function TopicSidebar({
  topics,
  currentTopic,
  onSelectTopic,
  onCreateTopic,
  onDeleteTopic,
  loading
}: TopicSidebarProps) {
  const [showNewTopicForm, setShowNewTopicForm] = useState(false)
  const [newTopicTitle, setNewTopicTitle] = useState('')
  const [newTopicDescription, setNewTopicDescription] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [autoResearch, setAutoResearch] = useState(true)

  const handleCreateTopic = (e: React.FormEvent) => {
    e.preventDefault()
    if (newTopicTitle.trim()) {
      onCreateTopic(newTopicTitle.trim(), newTopicDescription.trim() || undefined, undefined, autoResearch)
      setNewTopicTitle('')
      setNewTopicDescription('')
      setShowNewTopicForm(false)
      setAutoResearch(true)
    }
  }

  const filteredTopics = topics.filter(topic =>
    topic.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (topic.description && topic.description.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-teal-500'
      case 'completed':
        return 'bg-green-500'
      case 'archived':
        return 'bg-gray-500'
      default:
        return 'bg-gray-500'
    }
  }

  const getMasteryColor = (level: number) => {
    if (level >= 0.8) return 'text-green-400'
    if (level >= 0.5) return 'text-yellow-400'
    if (level >= 0.2) return 'text-orange-400'
    return 'text-gray-500'
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-white flex items-center gap-2">
            <span className="material-icons text-teal-400 text-lg">school</span>
            Topics
          </h3>
          <button
            onClick={() => setShowNewTopicForm(!showNewTopicForm)}
            className="text-gray-400 hover:text-teal-400 transition-colors"
            title="New Topic"
          >
            <span className="material-icons text-xl">add_circle</span>
          </button>
        </div>

        {/* Search */}
        <div className="relative">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search topics..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 pl-9 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-teal-500"
          />
          <span className="material-icons absolute left-2.5 top-2 text-gray-500 text-lg">search</span>
        </div>
      </div>

      {/* New Topic Form */}
      {showNewTopicForm && (
        <div className="px-4 py-3 border-b border-gray-700 bg-gray-800/50">
          <form onSubmit={handleCreateTopic} className="space-y-2">
            <input
              type="text"
              value={newTopicTitle}
              onChange={(e) => setNewTopicTitle(e.target.value)}
              placeholder="Topic title..."
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-teal-500"
              autoFocus
            />
            <textarea
              value={newTopicDescription}
              onChange={(e) => setNewTopicDescription(e.target.value)}
              placeholder="Description (optional)..."
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-teal-500 resize-none"
              rows={2}
            />
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={autoResearch}
                onChange={(e) => setAutoResearch(e.target.checked)}
                className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-teal-500 focus:ring-teal-500 focus:ring-offset-gray-900"
              />
              <span className="flex items-center gap-1">
                <span className="material-icons text-sm text-teal-400">auto_awesome</span>
                Auto-find sources
              </span>
            </label>
            <div className="flex gap-2">
              <button
                type="submit"
                className="flex-1 bg-teal-600 hover:bg-teal-700 text-white text-sm py-1.5 rounded-lg"
              >
                Create
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowNewTopicForm(false)
                  setNewTopicTitle('')
                  setNewTopicDescription('')
                }}
                className="px-3 text-gray-400 hover:text-white"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Topics List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <span className="text-gray-500">Loading...</span>
          </div>
        ) : filteredTopics.length === 0 ? (
          <div className="text-center py-8 px-4">
            <span className="material-icons text-4xl text-gray-600 mb-2">menu_book</span>
            <p className="text-gray-500 text-sm">
              {searchQuery ? 'No matching topics' : 'No topics yet'}
            </p>
            {!searchQuery && (
              <button
                onClick={() => setShowNewTopicForm(true)}
                className="mt-3 text-teal-400 hover:text-teal-300 text-sm"
              >
                Create your first topic
              </button>
            )}
          </div>
        ) : (
          <div className="py-2">
            {filteredTopics.map(topic => (
              <button
                key={topic.id}
                onClick={() => onSelectTopic(topic)}
                className={`w-full text-left px-4 py-3 hover:bg-gray-800 transition-colors border-l-2 ${
                  currentTopic?.id === topic.id
                    ? 'bg-gray-800 border-teal-500'
                    : 'border-transparent'
                }`}
              >
                <div className="flex items-start gap-3 group">
                  <div className={`w-2 h-2 rounded-full mt-2 ${getStatusColor(topic.status)}`} />
                  <div className="flex-1 min-w-0">
                    <p className={`font-medium truncate ${
                      currentTopic?.id === topic.id ? 'text-white' : 'text-gray-300'
                    }`}>
                      {topic.title}
                    </p>
                    {topic.description && (
                      <p className="text-gray-500 text-xs mt-0.5 line-clamp-2">
                        {topic.description}
                      </p>
                    )}
                    <div className="flex items-center gap-3 mt-1.5 text-xs">
                      <span className={getMasteryColor(topic.mastery_level)}>
                        {Math.round(topic.mastery_level * 100)}% mastery
                      </span>
                      <span className="text-gray-600">
                        P{topic.priority}
                      </span>
                    </div>
                  </div>
                  {onDeleteTopic && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm(`Delete "${topic.title}"?`)) {
                          onDeleteTopic(topic.id)
                        }
                      }}
                      className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all mt-1 flex-shrink-0"
                      title="Delete topic"
                    >
                      <span className="material-icons text-sm">delete</span>
                    </button>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Footer Stats */}
      <div className="px-4 py-3 border-t border-gray-700 text-xs text-gray-500">
        {topics.length} topic{topics.length !== 1 ? 's' : ''} • {topics.filter(t => t.status === 'active').length} active
      </div>
    </div>
  )
}
