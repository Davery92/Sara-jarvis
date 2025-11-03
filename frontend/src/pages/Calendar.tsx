import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, CalendarEvent } from '../api/client'
import ActiveWorkout from '../components/fitness/ActiveWorkout'
import { APP_CONFIG } from '../config'

export default function Calendar() {
  const [currentDate, setCurrentDate] = useState(new Date())
  const [setSelectedDate] = useState<Date | null>(null)
  const [setView] = useState<'month' | 'week' | 'day'>('month')
  const [isCreating, setIsCreating] = useState(false)
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null)
  const [activeWorkoutSessionId, setActiveWorkoutSessionId] = useState<string | null>(null)
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    start_time: '',
    end_time: '',
    location: '',
    attendees: [] as string[],
  })
  const [attendeeInput, setAttendeeInput] = useState('')
  
  const queryClient = useQueryClient()

  // Get calendar events
  const { data: events = [], isLoading } = useQuery({
    queryKey: ['calendar-events'],
    queryFn: () => apiClient.getCalendarEvents(),
  })

  // Create event mutation
  const createMutation = useMutation({
    mutationFn: (data: Omit<CalendarEvent, 'id' | 'created_at'>) => apiClient.createCalendarEvent(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar-events'] })
      setIsCreating(false)
      setSelectedDate(null)
      resetForm()
    },
  })

  // Update event mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CalendarEvent> }) => apiClient.updateCalendarEvent(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar-events'] })
      setEditingEvent(null)
      resetForm()
    },
  })

  // Delete event mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteCalendarEvent(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar-events'] })
      setEditingEvent(null)
    },
  })

  const resetForm = () => {
    setFormData({
      title: '',
      description: '',
      start_time: '',
      end_time: '',
      location: '',
      attendees: [],
    })
    setAttendeeInput('')
  }

  const handleCreateNew = (date?: Date) => {
    setIsCreating(true)
    setEditingEvent(null)
    setSelectedDate(date || null)
    resetForm()
    
    if (date) {
      const startTime = new Date(date)
      startTime.setHours(9, 0, 0, 0) // Default to 9 AM
      const endTime = new Date(date)
      endTime.setHours(10, 0, 0, 0) // Default to 10 AM
      
      setFormData(prev => ({
        ...prev,
        start_time: startTime.toISOString().slice(0, 16),
        end_time: endTime.toISOString().slice(0, 16),
      }))
    }
  }

  const handleEdit = (event: CalendarEvent) => {
    setEditingEvent(event)
    setIsCreating(false)
    setFormData({
      title: event.title,
      description: event.description || '',
      start_time: new Date(event.start_time).toISOString().slice(0, 16),
      end_time: new Date(event.end_time).toISOString().slice(0, 16),
      location: event.location || '',
      attendees: event.attendees || [],
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.title.trim() || !formData.start_time || !formData.end_time) return

    const eventData = {
      title: formData.title.trim(),
      description: formData.description.trim() || undefined,
      start_time: new Date(formData.start_time),
      end_time: new Date(formData.end_time),
      location: formData.location.trim() || undefined,
      attendees: formData.attendees.length > 0 ? formData.attendees : undefined,
    }

    if (editingEvent) {
      await updateMutation.mutateAsync({ id: editingEvent.id, data: eventData })
    } else {
      await createMutation.mutateAsync(eventData)
    }
  }

  const handleDelete = async () => {
    if (!editingEvent) return
    
    if (window.confirm(`Are you sure you want to delete "${editingEvent.title}"?`)) {
      await deleteMutation.mutateAsync(editingEvent.id)
    }
  }

  const handleAddAttendee = () => {
    const email = attendeeInput.trim()
    if (email && !formData.attendees.includes(email) && /\S+@\S+\.\S+/.test(email)) {
      setFormData(prev => ({
        ...prev,
        attendees: [...prev.attendees, email],
      }))
      setAttendeeInput('')
    }
  }

  const handleRemoveAttendee = (email: string) => {
    setFormData(prev => ({
      ...prev,
      attendees: prev.attendees.filter(a => a !== email),
    }))
  }

  // Calendar helpers
  const getDaysInMonth = (date: Date) => {
    return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
  }

  const getFirstDayOfMonth = (date: Date) => {
    return new Date(date.getFullYear(), date.getMonth(), 1).getDay()
  }

  const getEventsForDate = (date: Date) => {
    return events.filter(event => {
      const eventStart = new Date(event.start_time)
      return eventStart.toDateString() === date.toDateString()
    }).sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())
  }

  const navigateMonth = (direction: 'prev' | 'next') => {
    setCurrentDate(prev => {
      const newDate = new Date(prev)
      if (direction === 'prev') {
        newDate.setMonth(prev.getMonth() - 1)
      } else {
        newDate.setMonth(prev.getMonth() + 1)
      }
      return newDate
    })
  }

  const isToday = (date: Date) => {
    const today = new Date()
    return date.toDateString() === today.toDateString()
  }

  const formatTime = (date: Date) => {
    return new Date(date).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    })
  }

  const renderCalendarGrid = () => {
    const daysInMonth = getDaysInMonth(currentDate)
    const firstDay = getFirstDayOfMonth(currentDate)
    const days = []

    // Empty cells for days before the first day of the month
    for (let i = 0; i < firstDay; i++) {
      days.push(<div key={`empty-${i}`} className="h-24 sm:h-24 md:h-28 lg:h-32"></div>)
    }

    // Days of the month
    for (let day = 1; day <= daysInMonth; day++) {
      const date = new Date(currentDate.getFullYear(), currentDate.getMonth(), day)
      const dayEvents = getEventsForDate(date)

      days.push(
        <div
          key={day}
          onClick={() => handleCreateNew(date)}
          className={`h-24 sm:h-24 md:h-28 lg:h-32 border border-gray-200 p-1 sm:p-2 cursor-pointer hover:bg-gray-50 transition-colors duration-200 flex flex-col ${
            isToday(date) ? 'bg-blue-50 border-blue-200' : 'bg-white'
          }`}
        >
          <div className={`text-xs sm:text-sm font-medium mb-1 flex-shrink-0 ${
            isToday(date) ? 'text-blue-600' : 'text-gray-900'
          }`}>
            {day}
          </div>
          <div className="space-y-0.5 flex-1 overflow-hidden">
            {dayEvents.slice(0, 1).map((event) => {
              // Check if this is a workout event (title starts with 🏋️)
              const isWorkoutEvent = event.title.startsWith('🏋️')
              const eventStyle = isWorkoutEvent
                ? 'bg-purple-100 text-purple-800 border-l-2 border-purple-500 hover:bg-purple-200'
                : 'bg-indigo-100 text-indigo-800 hover:bg-indigo-200'

              return (
                <div
                  key={event.id}
                  onClick={async (e) => {
                    e.stopPropagation()
                    // Check if workout event
                    if (isWorkoutEvent) {
                      // Fetch session ID from backend
                      try {
                        const response = await fetch(
                          `${APP_CONFIG.apiUrl}/api/fitness/sessions/by-event/${event.id}`,
                          { credentials: 'include' }
                        )
                        if (response.ok) {
                          const data = await response.json()
                          setActiveWorkoutSessionId(data.session_id)
                        } else {
                          // Fallback to edit if no session found
                          handleEdit(event)
                        }
                      } catch (error) {
                        console.error('Failed to fetch workout session:', error)
                        handleEdit(event)
                      }
                    } else {
                      handleEdit(event)
                    }
                  }}
                  className={`text-[10px] sm:text-xs ${eventStyle} px-1 sm:px-2 py-0.5 sm:py-1 rounded truncate transition-colors duration-200 cursor-pointer`}
                >
                  <span className="hidden sm:inline">{formatTime(event.start_time)} </span>{event.title}
                </div>
              )
            })}
            {dayEvents.length > 1 && (
              <div className="text-[10px] sm:text-xs text-gray-500 px-1 truncate">
                +{dayEvents.length - 1} more
              </div>
            )}
          </div>
        </div>
      )
    }

    return days
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Calendar</h1>
          <p className="text-gray-600 mt-2">Manage your events and schedule</p>
        </div>
        <button
          onClick={() => handleCreateNew()}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 transition-colors duration-200 tap-target"
        >
          <span className="hidden sm:inline">New Event</span>
          <span className="sm:hidden">+ Event</span>
        </button>
      </div>

      {/* Calendar Navigation */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-4">
          <button
            onClick={() => navigateMonth('prev')}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors duration-200"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h2 className="text-xl font-semibold text-gray-900">
            {currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
          </h2>
          <button
            onClick={() => navigateMonth('next')}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors duration-200"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
        
        <button
          onClick={() => setCurrentDate(new Date())}
          className="text-indigo-600 hover:text-indigo-800 px-3 py-2 rounded-lg hover:bg-indigo-50 transition-colors duration-200"
        >
          Today
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Calendar Grid */}
        <div className="lg:col-span-3">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            {/* Day headers */}
            <div className="grid grid-cols-7 bg-gray-50 border-b border-gray-200">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => (
                <div key={day} className="p-2 sm:p-3 text-center text-xs sm:text-sm font-medium text-gray-700">
                  <span className="hidden sm:inline">{day}</span>
                  <span className="sm:hidden">{day[0]}</span>
                </div>
              ))}
            </div>

            {/* Calendar grid */}
            <div className="grid grid-cols-7">
              {isLoading ? (
                <div className="col-span-7 p-12 text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mx-auto mb-4"></div>
                  <p className="text-gray-600">Loading calendar...</p>
                </div>
              ) : (
                renderCalendarGrid()
              )}
            </div>
          </div>
        </div>

        {/* Event Form / Details - Desktop Sidebar */}
        <div className="hidden lg:block lg:col-span-1">
          {(isCreating || editingEvent) && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                {editingEvent ? 'Edit Event' : 'New Event'}
              </h3>
              
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Title *</label>
                  <input
                    type="text"
                    value={formData.title}
                    onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                    placeholder="Event title..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Start Time *</label>
                  <input
                    type="datetime-local"
                    value={formData.start_time}
                    onChange={(e) => setFormData(prev => ({ ...prev, start_time: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">End Time *</label>
                  <input
                    type="datetime-local"
                    value={formData.end_time}
                    onChange={(e) => setFormData(prev => ({ ...prev, end_time: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
                  <input
                    type="text"
                    value={formData.location}
                    onChange={(e) => setFormData(prev => ({ ...prev, location: e.target.value }))}
                    placeholder="Event location..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                    placeholder="Event description..."
                    rows={3}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Attendees</label>
                  <div className="flex space-x-2 mb-2">
                    <input
                      type="email"
                      value={attendeeInput}
                      onChange={(e) => setAttendeeInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          handleAddAttendee()
                        }
                      }}
                      placeholder="Email address..."
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    />
                    <button
                      type="button"
                      onClick={handleAddAttendee}
                      className="bg-gray-100 text-gray-700 px-3 py-2 rounded-lg hover:bg-gray-200 transition-colors duration-200"
                    >
                      Add
                    </button>
                  </div>
                  {formData.attendees.length > 0 && (
                    <div className="space-y-1">
                      {formData.attendees.map((email) => (
                        <div key={email} className="flex items-center justify-between bg-gray-50 px-2 py-1 rounded">
                          <span className="text-sm text-gray-700">{email}</span>
                          <button
                            type="button"
                            onClick={() => handleRemoveAttendee(email)}
                            className="text-gray-400 hover:text-red-600 ml-2"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex flex-col space-y-2">
                  <button
                    type="submit"
                    disabled={createMutation.isPending || updateMutation.isPending || !formData.title.trim() || !formData.start_time || !formData.end_time}
                    className="w-full bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
                  >
                    {createMutation.isPending || updateMutation.isPending 
                      ? (editingEvent ? 'Updating...' : 'Creating...')
                      : (editingEvent ? 'Update Event' : 'Create Event')
                    }
                  </button>
                  
                  {editingEvent && (
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={deleteMutation.isPending}
                      className="w-full bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
                    >
                      {deleteMutation.isPending ? 'Deleting...' : 'Delete Event'}
                    </button>
                  )}
                  
                  <button
                    type="button"
                    onClick={() => {
                      setIsCreating(false)
                      setEditingEvent(null)
                      setSelectedDate(null)
                      resetForm()
                    }}
                    className="w-full text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-100 transition-colors duration-200"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>

      {/* Mobile Event Form Modal */}
      {(isCreating || editingEvent) && (
        <div className="lg:hidden fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
          <div className="bg-white w-full sm:max-w-lg sm:rounded-lg rounded-t-xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-gray-200 flex-shrink-0">
              <h3 className="text-lg font-semibold text-gray-900">
                {editingEvent ? 'Edit Event' : 'New Event'}
              </h3>
              <button
                onClick={() => {
                  setIsCreating(false)
                  setEditingEvent(null)
                  setSelectedDate(null)
                  resetForm()
                }}
                className="text-gray-400 hover:text-gray-600 text-2xl tap-target"
              >
                ×
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4 p-4 overflow-y-auto flex-1">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Title *</label>
                <input
                  type="text"
                  value={formData.title}
                  onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                  placeholder="Event title..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Start Time *</label>
                <input
                  type="datetime-local"
                  value={formData.start_time}
                  onChange={(e) => setFormData(prev => ({ ...prev, start_time: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">End Time *</label>
                <input
                  type="datetime-local"
                  value={formData.end_time}
                  onChange={(e) => setFormData(prev => ({ ...prev, end_time: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
                <input
                  type="text"
                  value={formData.location}
                  onChange={(e) => setFormData(prev => ({ ...prev, location: e.target.value }))}
                  placeholder="Event location..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="Event description..."
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Attendees</label>
                <div className="flex space-x-2 mb-2">
                  <input
                    type="email"
                    value={attendeeInput}
                    onChange={(e) => setAttendeeInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        handleAddAttendee()
                      }
                    }}
                    placeholder="Email address..."
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                  <button
                    type="button"
                    onClick={handleAddAttendee}
                    className="bg-gray-100 text-gray-700 px-3 py-2 rounded-lg hover:bg-gray-200 transition-colors duration-200 tap-target"
                  >
                    Add
                  </button>
                </div>
                {formData.attendees.length > 0 && (
                  <div className="space-y-1">
                    {formData.attendees.map((email) => (
                      <div key={email} className="flex items-center justify-between bg-gray-50 px-2 py-1 rounded">
                        <span className="text-sm text-gray-700">{email}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveAttendee(email)}
                          className="text-gray-400 hover:text-red-600 ml-2 tap-target"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col space-y-2 pt-4">
                <button
                  type="submit"
                  disabled={createMutation.isPending || updateMutation.isPending || !formData.title.trim() || !formData.start_time || !formData.end_time}
                  className="w-full bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200 tap-target"
                >
                  {createMutation.isPending || updateMutation.isPending
                    ? (editingEvent ? 'Updating...' : 'Creating...')
                    : (editingEvent ? 'Update Event' : 'Create Event')
                  }
                </button>

                {editingEvent && (
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={deleteMutation.isPending}
                    className="w-full bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200 tap-target"
                  >
                    {deleteMutation.isPending ? 'Deleting...' : 'Delete Event'}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Active Workout Modal */}
      {activeWorkoutSessionId && (
        <ActiveWorkout
          sessionId={activeWorkoutSessionId}
          onClose={() => setActiveWorkoutSessionId(null)}
        />
      )}
    </div>
  )
}
