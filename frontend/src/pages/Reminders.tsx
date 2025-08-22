import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, Reminder } from '../api/client'

export default function Reminders() {
  const [isCreating, setIsCreating] = useState(false)
  const [filter, setFilter] = useState<'all' | 'pending' | 'completed'>('all')
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    due_date: '',
    priority: 'medium' as 'low' | 'medium' | 'high',
  })
  
  const queryClient = useQueryClient()

  // Get reminders
  const { data: allReminders = [], isLoading } = useQuery({
    queryKey: ['reminders'],
    queryFn: () => apiClient.getReminders(),
  })

  // Filter reminders based on selected filter
  const filteredReminders = allReminders.filter(reminder => {
    switch (filter) {
      case 'pending':
        return !reminder.completed
      case 'completed':
        return reminder.completed
      default:
        return true
    }
  }).sort((a, b) => {
    // Sort by due date, then by priority
    const dateA = new Date(a.due_date).getTime()
    const dateB = new Date(b.due_date).getTime()
    if (dateA !== dateB) return dateA - dateB
    
    const priorityOrder = { high: 3, medium: 2, low: 1 }
    return priorityOrder[b.priority] - priorityOrder[a.priority]
  })

  // Create reminder mutation
  const createMutation = useMutation({
    mutationFn: (data: Omit<Reminder, 'id' | 'created_at'>) => apiClient.createReminder(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders'] })
      setIsCreating(false)
      resetForm()
    },
  })

  // Update reminder mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Reminder> }) => apiClient.updateReminder(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders'] })
    },
  })

  // Mark complete mutation
  const completeMutation = useMutation({
    mutationFn: (id: string) => apiClient.markReminderComplete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders'] })
    },
  })

  // Delete reminder mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteReminder(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders'] })
    },
  })

  const resetForm = () => {
    setFormData({
      title: '',
      description: '',
      due_date: '',
      priority: 'medium',
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.title.trim() || !formData.due_date) return

    await createMutation.mutateAsync({
      title: formData.title.trim(),
      description: formData.description.trim(),
      due_date: new Date(formData.due_date),
      priority: formData.priority,
      completed: false,
    })
  }

  const handleToggleComplete = async (reminder: Reminder) => {
    if (reminder.completed) {
      // If already completed, update to incomplete
      await updateMutation.mutateAsync({
        id: reminder.id,
        data: { completed: false }
      })
    } else {
      // Mark as complete
      await completeMutation.mutateAsync(reminder.id)
    }
  }

  const handleDelete = async (id: string, title: string) => {
    if (window.confirm(`Are you sure you want to delete "${title}"?`)) {
      await deleteMutation.mutateAsync(id)
    }
  }

  const formatDate = (date: Date) => {
    const now = new Date()
    const reminderDate = new Date(date)
    const diffTime = reminderDate.getTime() - now.getTime()
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return 'Today'
    if (diffDays === 1) return 'Tomorrow'
    if (diffDays === -1) return 'Yesterday'
    if (diffDays < 0) return `${Math.abs(diffDays)} days ago`
    if (diffDays <= 7) return `In ${diffDays} days`
    
    return reminderDate.toLocaleDateString()
  }

  const isOverdue = (date: Date, completed: boolean) => {
    if (completed) return false
    return new Date(date) < new Date()
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'bg-red-100 text-red-800 border-red-200'
      case 'medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200'
      case 'low': return 'bg-green-100 text-green-800 border-green-200'
      default: return 'bg-gray-100 text-gray-800 border-gray-200'
    }
  }

  const getMinDateTime = () => {
    const now = new Date()
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset())
    return now.toISOString().slice(0, 16)
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reminders</h1>
          <p className="text-gray-600 mt-2">Keep track of important tasks and deadlines</p>
        </div>
        <button
          onClick={() => setIsCreating(true)}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 transition-colors duration-200"
        >
          New Reminder
        </button>
      </div>

      {/* Create Form */}
      {isCreating && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Create New Reminder</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Title *</label>
              <input
                type="text"
                value={formData.title}
                onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                placeholder="Reminder title..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                placeholder="Optional description..."
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Due Date *</label>
                <input
                  type="datetime-local"
                  value={formData.due_date}
                  onChange={(e) => setFormData(prev => ({ ...prev, due_date: e.target.value }))}
                  min={getMinDateTime()}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
                <select
                  value={formData.priority}
                  onChange={(e) => setFormData(prev => ({ ...prev, priority: e.target.value as 'low' | 'medium' | 'high' }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
            </div>

            <div className="flex items-center space-x-3">
              <button
                type="submit"
                disabled={createMutation.isPending || !formData.title.trim() || !formData.due_date}
                className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
              >
                {createMutation.isPending ? 'Creating...' : 'Create Reminder'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsCreating(false)
                  resetForm()
                }}
                className="text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-100 transition-colors duration-200"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="mb-6">
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {[
              { key: 'all', label: 'All', count: allReminders.length },
              { key: 'pending', label: 'Pending', count: allReminders.filter(r => !r.completed).length },
              { key: 'completed', label: 'Completed', count: allReminders.filter(r => r.completed).length },
            ].map(tab => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key as typeof filter)}
                className={`py-2 px-1 border-b-2 font-medium text-sm transition-colors duration-200 ${
                  filter === tab.key
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label} ({tab.count})
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Reminders List */}
      {isLoading ? (
        <div className="text-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading reminders...</p>
        </div>
      ) : filteredReminders.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl mb-4">⏰</div>
          <h3 className="text-lg font-medium text-gray-900 mb-2">
            {filter === 'all' ? 'No reminders yet' : `No ${filter} reminders`}
          </h3>
          <p className="text-gray-500">
            {filter === 'all' 
              ? 'Create your first reminder to get started'
              : `You don't have any ${filter} reminders`
            }
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredReminders.map((reminder) => (
            <div
              key={reminder.id}
              className={`bg-white rounded-lg shadow-sm border p-4 hover:shadow-md transition-shadow duration-200 ${
                isOverdue(reminder.due_date, reminder.completed) ? 'border-red-200' : 'border-gray-200'
              } ${reminder.completed ? 'opacity-75' : ''}`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start space-x-3 flex-1">
                  <button
                    onClick={() => handleToggleComplete(reminder)}
                    disabled={completeMutation.isPending || updateMutation.isPending}
                    className={`mt-1 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors duration-200 ${
                      reminder.completed
                        ? 'bg-green-500 border-green-500 text-white'
                        : 'border-gray-300 hover:border-green-500'
                    }`}
                  >
                    {reminder.completed && (
                      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    )}
                  </button>

                  <div className="flex-1 min-w-0">
                    <h3 className={`text-lg font-medium ${reminder.completed ? 'line-through text-gray-500' : 'text-gray-900'}`}>
                      {reminder.title}
                    </h3>
                    {reminder.description && (
                      <p className={`mt-1 text-sm ${reminder.completed ? 'text-gray-400' : 'text-gray-600'}`}>
                        {reminder.description}
                      </p>
                    )}
                    <div className="mt-2 flex items-center space-x-4">
                      <span className={`text-sm ${isOverdue(reminder.due_date, reminder.completed) ? 'text-red-600 font-medium' : 'text-gray-500'}`}>
                        {formatDate(reminder.due_date)} at {new Date(reminder.due_date).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })}
                      </span>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${getPriorityColor(reminder.priority)}`}>
                        {reminder.priority}
                      </span>
                      {isOverdue(reminder.due_date, reminder.completed) && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 border border-red-200">
                          Overdue
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <button
                  onClick={() => handleDelete(reminder.id, reminder.title)}
                  disabled={deleteMutation.isPending}
                  className="text-gray-400 hover:text-red-600 p-1 rounded transition-colors duration-200"
                  title="Delete reminder"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
