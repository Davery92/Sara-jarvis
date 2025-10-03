/**
 * Calendar View Component
 *
 * Displays user's calendar events with month/week/day views
 */

import React, { useState, useEffect } from 'react';
import { APP_CONFIG } from '../config';

interface CalendarEvent {
  id: string;
  title: string;
  description?: string;
  starts_at: string;
  ends_at: string;
  location?: string;
  created_at?: string;
  updated_at?: string;
}

const CalendarView: React.FC = () => {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentDate, setCurrentDate] = useState(new Date());
  const [view, setView] = useState<'month' | 'week' | 'day'>('week');
  const [showEventModal, setShowEventModal] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [createForm, setCreateForm] = useState({
    title: '',
    description: '',
    starts_at: '',
    ends_at: '',
    location: ''
  });
  const [editForm, setEditForm] = useState({
    title: '',
    description: '',
    starts_at: '',
    ends_at: '',
    location: ''
  });

  // Fetch calendar events
  const fetchEvents = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${APP_CONFIG.apiUrl}/events/`, {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setEvents(data.events || []);
      }
    } catch (error) {
      console.error('Error fetching calendar events:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [currentDate]);

  // Create new event
  const createEvent = async () => {
    try {
      const payload = {
        title: createForm.title,
        description: createForm.description || '',
        starts_at: new Date(createForm.starts_at).toISOString(),
        ends_at: new Date(createForm.ends_at).toISOString(),
        location: createForm.location || ''
      };

      console.log('Creating event with payload:', payload);

      const response = await fetch(`${APP_CONFIG.apiUrl}/events/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        setShowCreateModal(false);
        setCreateForm({
          title: '',
          description: '',
          starts_at: '',
          ends_at: '',
          location: ''
        });
        fetchEvents(); // Refresh events
      } else {
        const error = await response.json();
        console.error('Failed to create event:', error);
        alert(`Failed to create event: ${error.detail || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error creating event:', error);
      alert('Error creating event');
    }
  };

  // Update event
  const updateEvent = async () => {
    if (!editingEvent) return;

    try {
      const payload = {
        title: editForm.title,
        description: editForm.description || '',
        starts_at: new Date(editForm.starts_at).toISOString(),
        ends_at: new Date(editForm.ends_at).toISOString(),
        location: editForm.location || ''
      };

      const response = await fetch(`${APP_CONFIG.apiUrl}/events/${editingEvent.id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        setShowEditModal(false);
        setEditingEvent(null);
        fetchEvents(); // Refresh events
      } else {
        const error = await response.json();
        console.error('Failed to update event:', error);
        alert(`Failed to update event: ${error.detail || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error updating event:', error);
      alert('Error updating event');
    }
  };

  // Delete event
  const deleteEvent = async (eventId: string) => {
    if (!confirm('Are you sure you want to delete this event?')) return;

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/events/${eventId}`, {
        method: 'DELETE',
        credentials: 'include',
      });

      if (response.ok) {
        setShowEventModal(false);
        setSelectedEvent(null);
        fetchEvents(); // Refresh events
      } else {
        alert('Failed to delete event');
      }
    } catch (error) {
      console.error('Error deleting event:', error);
      alert('Error deleting event');
    }
  };

  // Open edit modal
  const openEditModal = (event: CalendarEvent) => {
    setEditingEvent(event);
    setEditForm({
      title: event.title,
      description: event.description || '',
      starts_at: new Date(event.starts_at).toISOString().slice(0, 16),
      ends_at: new Date(event.ends_at).toISOString().slice(0, 16),
      location: event.location || ''
    });
    setShowEventModal(false);
    setShowEditModal(true);
  };

  // Get events for today
  const getTodayEvents = () => {
    const today = new Date().toISOString().split('T')[0];
    return events.filter(event =>
      event.starts_at.startsWith(today)
    );
  };

  // Get events for current week
  const getWeekEvents = () => {
    const startOfWeek = new Date(currentDate);
    startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());

    const endOfWeek = new Date(startOfWeek);
    endOfWeek.setDate(endOfWeek.getDate() + 7);

    return events.filter(event => {
      const eventDate = new Date(event.starts_at);
      return eventDate >= startOfWeek && eventDate < endOfWeek;
    });
  };

  const formatTime = (datetime: string) => {
    return new Date(datetime).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    });
  };

  const formatDate = (datetime: string) => {
    return new Date(datetime).toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric'
    });
  };

  // Week view component
  const renderWeekView = () => {
    const weekEvents = getWeekEvents();
    const startOfWeek = new Date(currentDate);
    startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());

    const weekDays = Array.from({ length: 7 }, (_, i) => {
      const day = new Date(startOfWeek);
      day.setDate(day.getDate() + i);
      return day;
    });

    return (
      <div className="grid grid-cols-7 gap-2">
        {weekDays.map((day, idx) => {
          const dayStr = day.toISOString().split('T')[0];
          const dayEvents = weekEvents.filter(e => e.starts_at.startsWith(dayStr));
          const isToday = dayStr === new Date().toISOString().split('T')[0];

          return (
            <div
              key={idx}
              className={`border rounded-lg p-3 min-h-[200px] ${
                isToday
                  ? 'border-teal-500 bg-teal-500/5'
                  : 'border-gray-700 bg-gray-800/30'
              }`}
            >
              <div className="font-medium text-sm mb-2 text-center">
                <div className={isToday ? 'text-teal-400' : 'text-gray-400'}>
                  {day.toLocaleDateString('en-US', { weekday: 'short' })}
                </div>
                <div className={`text-lg ${isToday ? 'text-teal-300' : 'text-white'}`}>
                  {day.getDate()}
                </div>
              </div>

              <div className="space-y-1">
                {dayEvents.map(event => (
                  <button
                    key={event.id}
                    onClick={() => {
                      setSelectedEvent(event);
                      setShowEventModal(true);
                    }}
                    className="w-full text-left p-2 bg-teal-600/20 border border-teal-500/30 rounded text-xs hover:bg-teal-600/30 transition-colors"
                  >
                    <div className="font-medium text-white truncate">{event.title}</div>
                    <div className="text-gray-400">{formatTime(event.starts_at)}</div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  // Day view component (list of today's events)
  const renderDayView = () => {
    const todayEvents = getTodayEvents();

    return (
      <div className="space-y-4">
        {todayEvents.length === 0 ? (
          <div className="text-center py-12">
            <div className="text-6xl mb-4">📅</div>
            <p className="text-gray-400">No events scheduled for today</p>
          </div>
        ) : (
          todayEvents.map(event => (
            <button
              key={event.id}
              onClick={() => {
                setSelectedEvent(event);
                setShowEventModal(true);
              }}
              className="w-full text-left p-4 bg-gray-800/50 border border-gray-700 rounded-lg hover:border-teal-500/50 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="text-lg font-medium text-white mb-1">{event.title}</h3>
                  {event.description && (
                    <p className="text-gray-400 text-sm mb-2">{event.description}</p>
                  )}
                  <div className="flex items-center space-x-4 text-sm text-gray-500">
                    <span>🕐 {formatTime(event.starts_at)}</span>
                    {event.location && <span>📍 {event.location}</span>}
                  </div>
                </div>
              </div>
            </button>
          ))
        )}
      </div>
    );
  };

  return (
    <div className="calendar-view h-full">
      {/* Header */}
      <div className="bg-card border border-card rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">📅 Calendar</h2>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 transition-colors flex items-center space-x-2"
            >
              <span>+</span>
              <span>New Event</span>
            </button>

            {/* View toggles */}
            <div className="flex border border-gray-700 rounded-lg overflow-hidden">
              {['day', 'week', 'month'].map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v as any)}
                  className={`px-4 py-2 text-sm transition-colors ${
                    view === v
                      ? 'bg-teal-600 text-white'
                      : 'text-gray-400 hover:text-white hover:bg-gray-700'
                  }`}
                >
                  {v.charAt(0).toUpperCase() + v.slice(1)}
                </button>
              ))}
            </div>

            <button
              onClick={() => setCurrentDate(new Date())}
              className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
            >
              Today
            </button>
          </div>
        </div>

        {/* Month/Year selector */}
        <div className="flex items-center justify-between text-gray-400">
          <button
            onClick={() => {
              const newDate = new Date(currentDate);
              newDate.setMonth(newDate.getMonth() - 1);
              setCurrentDate(newDate);
            }}
            className="p-2 hover:text-white"
          >
            ‹
          </button>

          <span className="text-lg font-medium text-white">
            {currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
          </span>

          <button
            onClick={() => {
              const newDate = new Date(currentDate);
              newDate.setMonth(newDate.getMonth() + 1);
              setCurrentDate(newDate);
            }}
            className="p-2 hover:text-white"
          >
            ›
          </button>
        </div>
      </div>

      {/* Calendar content */}
      <div className="bg-card border border-card rounded-xl p-6">
        {loading ? (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-500 mx-auto mb-4"></div>
            <p className="text-gray-400">Loading calendar...</p>
          </div>
        ) : view === 'week' ? (
          renderWeekView()
        ) : (
          renderDayView()
        )}
      </div>

      {/* Event Detail Modal */}
      {showEventModal && selectedEvent && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl max-w-lg w-full p-6">
            <div className="flex items-start justify-between mb-4">
              <h3 className="text-xl font-semibold text-white">{selectedEvent.title}</h3>
              <button
                onClick={() => {
                  setShowEventModal(false);
                  setSelectedEvent(null);
                }}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            {selectedEvent.description && (
              <p className="text-gray-300 mb-4">{selectedEvent.description}</p>
            )}

            <div className="space-y-2 text-sm">
              <div className="flex items-center space-x-2 text-gray-400">
                <span>🕐</span>
                <span>
                  {formatDate(selectedEvent.starts_at)} at {formatTime(selectedEvent.starts_at)}
                </span>
              </div>

              {selectedEvent.location && (
                <div className="flex items-center space-x-2 text-gray-400">
                  <span>📍</span>
                  <span>{selectedEvent.location}</span>
                </div>
              )}

            </div>

            <div className="flex space-x-2 mt-6">
              <button
                onClick={() => deleteEvent(selectedEvent.id)}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                Delete
              </button>
              <button
                onClick={() => openEditModal(selectedEvent)}
                className="flex-1 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 transition-colors"
              >
                Edit
              </button>
              <button
                onClick={() => {
                  setShowEventModal(false);
                  setSelectedEvent(null);
                }}
                className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Event Modal */}
      {showEditModal && editingEvent && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl max-w-lg w-full p-6">
            <div className="flex items-start justify-between mb-4">
              <h3 className="text-xl font-semibold text-white">Edit Event</h3>
              <button
                onClick={() => {
                  setShowEditModal(false);
                  setEditingEvent(null);
                }}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Title *
                </label>
                <input
                  type="text"
                  value={editForm.title}
                  onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  placeholder="Event title"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={editForm.description}
                  onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  rows={3}
                  placeholder="Event description"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    Start Time *
                  </label>
                  <input
                    type="datetime-local"
                    value={editForm.starts_at}
                    onChange={(e) => setEditForm({ ...editForm, starts_at: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    End Time *
                  </label>
                  <input
                    type="datetime-local"
                    value={editForm.ends_at}
                    onChange={(e) => setEditForm({ ...editForm, ends_at: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Location
                </label>
                <input
                  type="text"
                  value={editForm.location}
                  onChange={(e) => setEditForm({ ...editForm, location: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  placeholder="Event location"
                />
              </div>
            </div>

            <div className="flex space-x-2 mt-6">
              <button
                onClick={() => {
                  setShowEditModal(false);
                  setEditingEvent(null);
                }}
                className="flex-1 px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={updateEvent}
                disabled={!editForm.title || !editForm.starts_at || !editForm.ends_at}
                className="flex-1 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Event Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl max-w-lg w-full p-6">
            <div className="flex items-start justify-between mb-4">
              <h3 className="text-xl font-semibold text-white">Create New Event</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Title *
                </label>
                <input
                  type="text"
                  value={createForm.title}
                  onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  placeholder="Event title"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={createForm.description}
                  onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  rows={3}
                  placeholder="Event description"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    Start Time *
                  </label>
                  <input
                    type="datetime-local"
                    value={createForm.starts_at}
                    onChange={(e) => setCreateForm({ ...createForm, starts_at: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    End Time *
                  </label>
                  <input
                    type="datetime-local"
                    value={createForm.ends_at}
                    onChange={(e) => setCreateForm({ ...createForm, ends_at: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Location
                </label>
                <input
                  type="text"
                  value={createForm.location}
                  onChange={(e) => setCreateForm({ ...createForm, location: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-teal-500"
                  placeholder="Event location"
                />
              </div>
            </div>

            <div className="flex space-x-2 mt-6">
              <button
                onClick={() => setShowCreateModal(false)}
                className="flex-1 px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={createEvent}
                disabled={!createForm.title || !createForm.starts_at || !createForm.ends_at}
                className="flex-1 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Create Event
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CalendarView;
