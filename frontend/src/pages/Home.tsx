import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { apiClient, Reminder, CalendarEvent, Note } from '../api/client'
import { APP_CONFIG } from '../config'

export default function Home() {
  const { user } = useAuth()
  const [currentTime, setCurrentTime] = useState(new Date())

  // Update time every minute
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date())
    }, 60000)

    return () => clearInterval(timer)
  }, [])

  // Fetch today's reminders
  const { data: reminders = [] } = useQuery({
    queryKey: ['reminders'],
    queryFn: () => apiClient.getReminders(),
    select: (data) => {
      const today = new Date()
      today.setHours(23, 59, 59, 999)
      return data
        .filter(reminder => !reminder.completed && new Date(reminder.due_date) <= today)
        .sort((a, b) => new Date(a.due_date).getTime() - new Date(b.due_date).getTime())
        .slice(0, 5)
    }
  })

  // Fetch today's events
  const { data: events = [] } = useQuery({
    queryKey: ['calendar-events'],
    queryFn: () => apiClient.getCalendarEvents(),
    select: (data) => {
      const today = new Date()
      const tomorrow = new Date(today)
      tomorrow.setDate(tomorrow.getDate() + 1)
      
      return data
        .filter(event => {
          const eventDate = new Date(event.start_time)
          return eventDate >= today && eventDate < tomorrow
        })
        .sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())
        .slice(0, 5)
    }
  })

  // Fetch recent notes
  const { data: recentNotes = [] } = useQuery({
    queryKey: ['notes'],
    queryFn: () => apiClient.getNotes(),
    select: (data) => data
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 5)
  })

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    })
  }

  const formatDate = (date: Date) => {
    return date.toLocaleDateString('en-US', { 
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    })
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'bg-red-100 text-red-800'
      case 'medium': return 'bg-yellow-100 text-yellow-800'
      case 'low': return 'bg-green-100 text-green-800'
      default: return 'bg-gray-100 text-gray-800'
    }
  }

  const quickActions = [
    { name: 'Start Chat', href: '/chat', icon: '💬', color: 'bg-blue-500 hover:bg-blue-600' },
    { name: 'Add Note', href: '/notes', icon: '📝', color: 'bg-green-500 hover:bg-green-600' },
    { name: 'Upload Document', href: '/documents', icon: '📄', color: 'bg-purple-500 hover:bg-purple-600' },
    { name: 'Set Reminder', href: '/reminders', icon: '⏰', color: 'bg-orange-500 hover:bg-orange-600' },
  ]

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Welcome Header */}
      <div className="mb-8">
        <div className="bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg p-6 text-white">
          <h1 className="text-2xl font-bold mb-2">
            Welcome back, {user?.name || 'User'}!
          </h1>
          <p className="text-indigo-100 mb-4">
            {APP_CONFIG.ui.welcomeMessage}
          </p>
          <div className="text-indigo-100">
            <p className="text-lg font-medium">{formatDate(currentTime)}</p>
            <p className="text-sm">{formatTime(currentTime)}</p>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Actions</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {quickActions.map((action) => (
            <Link
              key={action.name}
              to={action.href}
              className={`${action.color} text-white p-4 rounded-lg shadow-sm hover:shadow-md transition-all duration-200 text-center`}
            >
              <div className="text-2xl mb-2">{action.icon}</div>
              <div className="font-medium">{action.name}</div>
            </Link>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
        {/* Today's Reminders */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900">Today's Reminders</h3>
            <Link 
              to="/reminders" 
              className="text-indigo-600 hover:text-indigo-800 text-sm font-medium"
            >
              View all
            </Link>
          </div>
          
          {reminders.length === 0 ? (
            <p className="text-gray-500 text-center py-4">No reminders for today</p>
          ) : (
            <div className="space-y-3">
              {reminders.map((reminder) => (
                <div key={reminder.id} className="flex items-start space-x-3 p-3 bg-gray-50 rounded-lg">
                  <div className="flex-shrink-0 mt-1">
                    <span className="text-orange-500">⏰</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {reminder.title}
                    </p>
                    {reminder.description && (
                      <p className="text-xs text-gray-500 mt-1 truncate">
                        {reminder.description}
                      </p>
                    )}
                    <div className="flex items-center mt-2 space-x-2">
                      <span className="text-xs text-gray-500">
                        {formatTime(new Date(reminder.due_date))}
                      </span>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getPriorityColor(reminder.priority)}`}>
                        {reminder.priority}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Today's Events */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900">Today's Events</h3>
            <Link 
              to="/calendar" 
              className="text-indigo-600 hover:text-indigo-800 text-sm font-medium"
            >
              View all
            </Link>
          </div>
          
          {events.length === 0 ? (
            <p className="text-gray-500 text-center py-4">No events for today</p>
          ) : (
            <div className="space-y-3">
              {events.map((event) => (
                <div key={event.id} className="flex items-start space-x-3 p-3 bg-gray-50 rounded-lg">
                  <div className="flex-shrink-0 mt-1">
                    <span className="text-blue-500">📅</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {event.title}
                    </p>
                    {event.description && (
                      <p className="text-xs text-gray-500 mt-1 truncate">
                        {event.description}
                      </p>
                    )}
                    <div className="flex items-center mt-2 space-x-2">
                      <span className="text-xs text-gray-500">
                        {formatTime(new Date(event.start_time))} - {formatTime(new Date(event.end_time))}
                      </span>
                      {event.location && (
                        <span className="text-xs text-gray-500">
                          📍 {event.location}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Notes */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900">Recent Notes</h3>
            <Link 
              to="/notes" 
              className="text-indigo-600 hover:text-indigo-800 text-sm font-medium"
            >
              View all
            </Link>
          </div>
          
          {recentNotes.length === 0 ? (
            <p className="text-gray-500 text-center py-4">No notes yet</p>
          ) : (
            <div className="space-y-3">
              {recentNotes.map((note) => (
                <div key={note.id} className="p-3 bg-gray-50 rounded-lg">
                  <Link 
                    to={`/notes?id=${note.id}`}
                    className="block hover:bg-gray-100 rounded-lg transition-colors duration-200"
                  >
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {note.title}
                    </p>
                    <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                      {note.content.substring(0, 100)}
                      {note.content.length > 100 ? '...' : ''}
                    </p>
                    <div className="flex items-center mt-2 space-x-2">
                      <span className="text-xs text-gray-500">
                        {new Date(note.updated_at).toLocaleDateString()}
                      </span>
                      {note.tags.length > 0 && (
                        <div className="flex space-x-1">
                          {note.tags.slice(0, 2).map((tag) => (
                            <span key={tag} className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-indigo-100 text-indigo-800">
                              {tag}
                            </span>
                          ))}
                          {note.tags.length > 2 && (
                            <span className="text-xs text-gray-500">+{note.tags.length - 2}</span>
                          )}
                        </div>
                      )}
                    </div>
                  </Link>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
export default Home
