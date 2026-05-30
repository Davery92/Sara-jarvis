/**
 * Calendar View Component
 * Clean, functional calendar with day/week/month views
 */

import React, { useState, useEffect, useMemo } from 'react';
import { APP_CONFIG } from '../config';

interface CalendarEvent {
  id: string;
  title: string;
  description?: string;
  starts_at: string;
  ends_at: string;
  start_time?: string;  // Alternative field name from /calendar/events
  end_time?: string;    // Alternative field name from /calendar/events
  location?: string;
  source?: string;      // 'sara' or 'ios_calendar'
  ios_calendar_name?: string;
  read_only?: boolean;
}

// Helper to format date as YYYY-MM-DD in local time
const toLocalDateString = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

// Helper to parse ISO string to local date string
const getEventDateString = (isoString: string): string => {
  const date = new Date(isoString);
  return toLocalDateString(date);
};

const CalendarView: React.FC = () => {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [view, setView] = useState<'month' | 'week' | 'day'>('week');
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [createForm, setCreateForm] = useState({
    title: '',
    description: '',
    date: '',
    startTime: '09:00',
    endTime: '10:00',
    location: ''
  });

  // Fetch events once on mount
  useEffect(() => {
    fetchEvents();
  }, []);

  const fetchEvents = async () => {
    try {
      setLoading(true);
      // Use /calendar/events which includes iOS-synced events
      const response = await fetch(`${APP_CONFIG.apiUrl}/calendar/events`, {
        credentials: 'include',
      });
      console.log('[CALENDAR] Fetch response status:', response.status);
      if (response.ok) {
        const data = await response.json();
        // /calendar/events returns array directly, normalize field names
        const eventList = (Array.isArray(data) ? data : (data.events || [])).map((e: any) => ({
          ...e,
          // Normalize field names (start_time -> starts_at for display)
          starts_at: e.starts_at || e.start_time,
          ends_at: e.ends_at || e.end_time,
        }));
        console.log('[CALENDAR] Loaded', eventList.length, 'events (includes iOS synced)');
        setEvents([...eventList]);
      } else {
        console.error('Fetch failed with status:', response.status, await response.text());
      }
    } catch (error) {
      console.error('Error fetching calendar events:', error);
    } finally {
      setLoading(false);
    }
  };

  // Get events for a specific date (includes multi-day events)
  const getEventsForDate = (date: Date): CalendarEvent[] => {
    const dateStr = toLocalDateString(date);
    const dateStart = new Date(date);
    dateStart.setHours(0, 0, 0, 0);
    const dateEnd = new Date(date);
    dateEnd.setHours(23, 59, 59, 999);

    return events.filter(e => {
      const eventStart = new Date(e.starts_at);
      const eventEnd = new Date(e.ends_at);
      // Event spans this date if: eventStart <= dateEnd AND eventEnd >= dateStart
      return eventStart <= dateEnd && eventEnd >= dateStart;
    });
  };

  // Check if event is a multi-day event
  const isMultiDayEvent = (event: CalendarEvent): boolean => {
    const start = new Date(event.starts_at);
    const end = new Date(event.ends_at);
    return toLocalDateString(start) !== toLocalDateString(end);
  };

  // Check if this is a continuation day (not the start day) for a multi-day event
  const isContinuationDay = (event: CalendarEvent, date: Date): boolean => {
    const eventStartStr = getEventDateString(event.starts_at);
    const dateStr = toLocalDateString(date);
    return isMultiDayEvent(event) && eventStartStr !== dateStr;
  };

  // Navigation
  const goToToday = () => setSelectedDate(new Date());

  const navigate = (direction: number) => {
    const newDate = new Date(selectedDate);
    if (view === 'day') {
      newDate.setDate(newDate.getDate() + direction);
    } else if (view === 'week') {
      newDate.setDate(newDate.getDate() + (direction * 7));
    } else {
      newDate.setMonth(newDate.getMonth() + direction);
    }
    setSelectedDate(newDate);
  };

  // Format helpers
  const formatTime = (iso: string) => {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    });
  };

  // Create event
  const handleCreateEvent = async () => {
    if (!createForm.title || !createForm.date || !createForm.startTime || !createForm.endTime) {
      alert('Please fill in all required fields');
      return;
    }

    try {
      const startsAt = new Date(`${createForm.date}T${createForm.startTime}:00`);
      const endsAt = new Date(`${createForm.date}T${createForm.endTime}:00`);

      const response = await fetch(`${APP_CONFIG.apiUrl}/calendar/events`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: createForm.title,
          description: createForm.description,
          start_time: startsAt.toISOString(),
          end_time: endsAt.toISOString(),
          location: createForm.location
        }),
      });

      if (response.ok) {
        setShowCreateModal(false);
        setCreateForm({ title: '', description: '', date: '', startTime: '09:00', endTime: '10:00', location: '' });
        fetchEvents();
      } else {
        const err = await response.json();
        alert(err.detail || 'Failed to create event');
      }
    } catch (error) {
      alert('Error creating event');
    }
  };

  // Delete event
  const handleDeleteEvent = async (eventId: string) => {
    const isIOS = selectedEvent?.read_only || selectedEvent?.source === 'ios_calendar';
    const confirmMsg = isIOS
      ? 'Hide this iOS Calendar event from Sara?\n\nIt will stay on your iPhone. Sara will stop showing it and won\'t re-add it on next sync.'
      : 'Delete this event?';
    if (!confirm(confirmMsg)) return;
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/calendar/events/${eventId}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (response.ok) {
        setSelectedEvent(null);
        fetchEvents();
      } else {
        const err = await response.json().catch(() => ({}));
        alert(err.detail || 'Failed to delete event');
      }
    } catch (error) {
      alert('Error deleting event');
    }
  };

  // Edit event - open modal with event data
  const openEditModal = (event: CalendarEvent) => {
    // Don't allow editing iOS events
    if (event.read_only || event.source === 'ios_calendar') {
      alert('This event is synced from iOS Calendar and cannot be edited here. Edit it in your iOS Calendar app.');
      return;
    }
    const startDate = new Date(event.starts_at);
    const endDate = new Date(event.ends_at);
    setCreateForm({
      title: event.title,
      description: event.description || '',
      date: toLocalDateString(startDate),
      startTime: startDate.toTimeString().slice(0, 5),
      endTime: endDate.toTimeString().slice(0, 5),
      location: event.location || ''
    });
    (window as any).__editingEventId = event.id;
    setEditMode(true);
    setShowCreateModal(true);
    setSelectedEvent(null);
  };

  // Update event
  const handleUpdateEvent = async () => {
    if (!selectedEvent && !editMode) return;
    if (!createForm.title || !createForm.date || !createForm.startTime || !createForm.endTime) {
      alert('Please fill in all required fields');
      return;
    }

    // Find the event ID from the form (we need to track it)
    const eventId = (window as any).__editingEventId;
    if (!eventId) {
      alert('Error: No event selected for editing');
      return;
    }

    try {
      const startsAt = new Date(`${createForm.date}T${createForm.startTime}:00`);
      const endsAt = new Date(`${createForm.date}T${createForm.endTime}:00`);

      const response = await fetch(`${APP_CONFIG.apiUrl}/calendar/events/${eventId}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: createForm.title,
          description: createForm.description,
          start_time: startsAt.toISOString(),
          end_time: endsAt.toISOString(),
          location: createForm.location
        }),
      });

      if (response.ok) {
        setShowCreateModal(false);
        setEditMode(false);
        setCreateForm({ title: '', description: '', date: '', startTime: '09:00', endTime: '10:00', location: '' });
        (window as any).__editingEventId = null;
        fetchEvents();
      } else {
        const err = await response.json();
        alert(err.detail || 'Failed to update event');
      }
    } catch (error) {
      alert('Error updating event');
    }
  };

  // Get week days for current week
  const weekDays = useMemo(() => {
    const start = new Date(selectedDate);
    start.setDate(start.getDate() - start.getDay());
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      return d;
    });
  }, [selectedDate]);

  // Get month grid (6 weeks x 7 days)
  const monthGrid = useMemo(() => {
    const year = selectedDate.getFullYear();
    const month = selectedDate.getMonth();
    const firstDay = new Date(year, month, 1);
    const startDate = new Date(firstDay);
    startDate.setDate(startDate.getDate() - firstDay.getDay());

    const days: Date[] = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      days.push(d);
    }
    return days;
  }, [selectedDate]);

  const todayStr = toLocalDateString(new Date());
  const selectedDateStr = toLocalDateString(selectedDate);

  // Check if event is from iOS
  const isIOSEvent = (event: CalendarEvent) => event.source === 'ios_calendar' || event.read_only;
  const todayEventsCount = getEventsForDate(new Date()).length;
  const selectedEventsCount = getEventsForDate(selectedDate).length;
  const iosEventCount = events.filter(isIOSEvent).length;
  const currentPeriodLabel =
    view === 'day'
      ? selectedDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
      : view === 'week'
      ? `Week of ${weekDays[0].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${weekDays[6].toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
      : selectedDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  // Render event card
  const EventCard = ({ event, compact = false, forDate }: { event: CalendarEvent; compact?: boolean; forDate?: Date }) => {
    const isMultiDay = isMultiDayEvent(event);
    const isContinuation = forDate ? isContinuationDay(event, forDate) : false;

    // For multi-day events, show date range instead of time
    const getTimeDisplay = () => {
      if (isMultiDay) {
        const startDate = new Date(event.starts_at);
        const endDate = new Date(event.ends_at);
        const startStr = startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const endStr = endDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        return `${startStr} → ${endStr}`;
      }
      return `${formatTime(event.starts_at)} - ${formatTime(event.ends_at)}`;
    };

    return (
      <button
        onClick={() => setSelectedEvent(event)}
        className={`w-full text-left rounded transition-colors ${
          compact
            ? `p-1 text-xs truncate ${isMultiDay ? 'bg-amber-600/30 hover:bg-amber-600/50' : isIOSEvent(event) ? 'bg-purple-600/30 hover:bg-purple-600/50' : 'bg-teal-600/30 hover:bg-teal-600/50'}`
            : `p-3 border ${isMultiDay ? 'bg-amber-800/30 border-amber-700 hover:border-amber-500/50' : isIOSEvent(event) ? 'bg-purple-800/30 border-purple-700 hover:border-purple-500/50' : 'bg-gray-800/50 border-gray-700 hover:border-teal-500/50'}`
        }`}
      >
        <div className={`font-medium text-white ${compact ? 'truncate' : ''} flex items-center gap-2`}>
          {isContinuation && <span className="text-amber-400">↳</span>}
          {event.title}
          {isMultiDay && !compact && (
            <span className="text-xs px-1.5 py-0.5 bg-amber-600/50 rounded text-amber-200">Multi-day</span>
          )}
          {isIOSEvent(event) && !compact && !isMultiDay && (
            <span className="text-xs px-1.5 py-0.5 bg-purple-600/50 rounded text-purple-200">iOS</span>
          )}
        </div>
        {!compact && (
          <div className="text-sm text-gray-400 mt-1">
            {getTimeDisplay()}
            {event.location && <span className="ml-2">📍 {event.location}</span>}
          </div>
        )}
      </button>
    );
  };

  // Day View
  const renderDayView = () => {
    const dayEvents = getEventsForDate(selectedDate);
    return (
      <div>
        <div className="text-center mb-4">
          <div className="text-2xl font-bold text-white">
            {selectedDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </div>
        </div>
        <div className="space-y-2">
          {dayEvents.length === 0 ? (
            <div className="text-center py-12 text-gray-400">No events for this day</div>
          ) : (
            dayEvents.map(event => <EventCard key={event.id} event={event} forDate={selectedDate} />)
          )}
        </div>
      </div>
    );
  };

  // Week View
  const renderWeekView = () => {
    return (
      <div className="grid grid-cols-7 gap-2">
        {weekDays.map((day, idx) => {
          const dayStr = toLocalDateString(day);
          const isToday = dayStr === todayStr;
          const isSelected = dayStr === selectedDateStr;
          const dayEvents = getEventsForDate(day);

          return (
            <div
              key={idx}
              onClick={() => {
                setSelectedDate(new Date(day));
                setView('day');
              }}
              className={`border rounded-lg p-2 min-h-[180px] cursor-pointer transition-colors ${
                isToday ? 'border-teal-500 bg-teal-500/10' :
                isSelected ? 'border-blue-500 bg-blue-500/10' :
                'border-gray-700 bg-gray-800/30 hover:bg-gray-800/50'
              }`}
            >
              <div className="text-center mb-2">
                <div className={`text-xs ${isToday ? 'text-teal-400' : 'text-gray-400'}`}>
                  {day.toLocaleDateString('en-US', { weekday: 'short' })}
                </div>
                <div className={`text-lg font-bold ${isToday ? 'text-teal-300' : 'text-white'}`}>
                  {day.getDate()}
                </div>
              </div>
              <div className="space-y-1">
                {dayEvents.slice(0, 3).map(event => (
                  <EventCard key={event.id} event={event} compact forDate={day} />
                ))}
                {dayEvents.length > 3 && (
                  <div className="text-xs text-gray-400 text-center">+{dayEvents.length - 3} more</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  // Month View
  const renderMonthView = () => (
    <div>
      <div className="grid grid-cols-7 gap-1 mb-1">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
          <div key={d} className="text-center text-xs text-gray-400 py-1">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {monthGrid.map((day, idx) => {
          const dayStr = toLocalDateString(day);
          const isToday = dayStr === todayStr;
          const isCurrentMonth = day.getMonth() === selectedDate.getMonth();
          const dayEvents = getEventsForDate(day);

          return (
            <div
              key={idx}
              onClick={() => {
                setSelectedDate(new Date(day));
                setView('day');
              }}
              className={`p-1 min-h-[80px] border rounded cursor-pointer transition-colors ${
                isToday ? 'border-teal-500 bg-teal-500/10' :
                isCurrentMonth ? 'border-gray-700 bg-gray-800/30 hover:bg-gray-800/50' :
                'border-gray-800 bg-gray-900/30 opacity-50'
              }`}
            >
              <div className={`text-sm font-medium ${isToday ? 'text-teal-300' : isCurrentMonth ? 'text-white' : 'text-gray-500'}`}>
                {day.getDate()}
              </div>
              {dayEvents.length > 0 && (
                <div className="mt-1">
                  {dayEvents.slice(0, 2).map(event => {
                    const isMultiDay = isMultiDayEvent(event);
                    const isCont = isContinuationDay(event, day);
                    return (
                      <div
                        key={event.id}
                        className={`text-xs rounded px-1 truncate mb-0.5 ${isMultiDay ? 'bg-amber-600/30' : 'bg-teal-600/30'}`}
                      >
                        {isCont && <span className="text-amber-400">↳</span>}
                        {event.title}
                      </div>
                    );
                  })}
                  {dayEvents.length > 2 && (
                    <div className="text-xs text-gray-400">+{dayEvents.length - 2}</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="calendar-view h-full flex flex-col gap-3">
      <section className="assistant-panel-soft rounded-md px-4 py-3.5 md:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 max-w-2xl">
            <div className="assistant-kicker mb-2">Time & Commitments</div>
            <div className="flex flex-col gap-2 md:flex-row md:items-end md:gap-3">
              <h2 className="font-display text-2xl font-semibold text-white">Calendar</h2>
              <p className="max-w-xl text-sm leading-6 text-[var(--assistant-text-soft)]">
                Keep the schedule readable and move through day, week, and month context without extra chrome.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <div className="assistant-panel flex min-w-[144px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">Current View</span>
              <span className="text-sm font-medium text-white">{view.charAt(0).toUpperCase() + view.slice(1)}</span>
            </div>
            <div className="assistant-panel flex min-w-[104px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">Today</span>
              <span className="font-display text-lg text-white">{todayEventsCount}</span>
            </div>
            <div className="assistant-panel flex min-w-[156px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">Selected Range</span>
              <span className="font-display text-lg text-white">{selectedEventsCount}</span>
            </div>
            <div className="assistant-panel flex min-w-[124px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">iOS Sync</span>
              <span className="font-display text-lg text-white">{iosEventCount}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="assistant-panel-soft rounded-md p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="assistant-kicker mb-2">Navigation</div>
            <div className="font-display text-2xl text-white">{currentPeriodLabel}</div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] p-1">
              <button onClick={() => navigate(-1)} className="rounded-md px-3 py-1.5 text-white transition hover:bg-white/[0.08]">‹</button>
              <button onClick={goToToday} className="rounded-md px-3 py-1.5 text-sm text-white transition hover:bg-white/[0.08]">Today</button>
              <button onClick={() => navigate(1)} className="rounded-md px-3 py-1.5 text-white transition hover:bg-white/[0.08]">›</button>
            </div>

            <div className="flex rounded-md border border-white/10 bg-white/[0.03] p-1">
              {(['day', 'week', 'month'] as const).map(v => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`rounded-md px-3 py-1.5 text-sm transition ${
                    view === v ? 'bg-cyan-500 text-slate-950 font-semibold' : 'text-[var(--assistant-text-soft)] hover:text-white'
                  }`}
                >
                  {v.charAt(0).toUpperCase() + v.slice(1)}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => {
                console.log('Opening create modal, date:', selectedDateStr);
                setCreateForm(f => ({ ...f, date: selectedDateStr }));
                setShowCreateModal(true);
              }}
              className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
            >
              + New Event
            </button>
          </div>
        </div>
      </section>

      {/* Calendar Content */}
      <div className="assistant-panel-soft flex-1 rounded-md p-4">
        {loading ? (
          <div className="text-center py-12">
            <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-b-2 border-teal-500"></div>
            <p className="text-[var(--assistant-text-soft)]">Loading calendar…</p>
          </div>
        ) : (
          <>
            {view === 'day' && renderDayView()}
            {view === 'week' && renderWeekView()}
            {view === 'month' && renderMonthView()}
          </>
        )}
      </div>

      {/* Event Detail Modal */}
      {selectedEvent && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setSelectedEvent(null)}>
          <div className="assistant-panel max-w-md w-full rounded-md p-6" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-4">
              <div className="flex items-center gap-2">
                <h3 className="text-xl font-semibold text-white">{selectedEvent.title}</h3>
                {isIOSEvent(selectedEvent) && (
                  <span className="text-xs px-2 py-1 bg-purple-600/50 rounded text-purple-200">iOS Calendar</span>
                )}
              </div>
              <button onClick={() => setSelectedEvent(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            {selectedEvent.description && (
              <p className="text-gray-300 mb-4">{selectedEvent.description}</p>
            )}

            <div className="space-y-2 text-sm text-gray-400 mb-6">
              <div>🕐 {new Date(selectedEvent.starts_at).toLocaleString()}</div>
              <div>🏁 {new Date(selectedEvent.ends_at).toLocaleString()}</div>
              {selectedEvent.location && <div>📍 {selectedEvent.location}</div>}
              {selectedEvent.ios_calendar_name && (
                <div className="text-purple-300">📱 {selectedEvent.ios_calendar_name}</div>
              )}
            </div>

            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => handleDeleteEvent(selectedEvent.id)}
                className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
              >
                {isIOSEvent(selectedEvent) ? 'Hide from Sara' : 'Delete'}
              </button>
              {!isIOSEvent(selectedEvent) && (
                <button
                  onClick={() => openEditModal(selectedEvent)}
                  className="flex-1 px-4 py-2 bg-teal-600 text-white rounded hover:bg-teal-700"
                >
                  Edit
                </button>
              )}
              <button
                onClick={() => setSelectedEvent(null)}
                className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600"
              >
                Close
              </button>
            </div>
            {isIOSEvent(selectedEvent) && (
              <p className="mt-3 text-xs text-gray-400 italic">
                To edit, use your iOS Calendar app. Hiding here keeps the event on iPhone but removes it from Sara.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Create/Edit Event Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4" style={{ zIndex: 9999 }} onClick={() => { setShowCreateModal(false); setEditMode(false); }}>
          <div className="assistant-panel max-w-md w-full rounded-md p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl font-semibold text-white">{editMode ? 'Edit Event' : 'New Event'}</h3>
              <button onClick={() => { setShowCreateModal(false); setEditMode(false); }} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-4">
              <input
                type="text"
                placeholder="Event title *"
                value={createForm.title}
                onChange={e => setCreateForm(f => ({ ...f, title: e.target.value }))}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white"
              />

              <textarea
                placeholder="Description"
                value={createForm.description}
                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white"
                rows={2}
              />

              <div>
                <label className="block text-sm text-gray-400 mb-1">Date *</label>
                <input
                  type="date"
                  value={createForm.date}
                  onChange={e => setCreateForm(f => ({ ...f, date: e.target.value }))}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white [color-scheme:dark]"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Start *</label>
                  <input
                    type="time"
                    value={createForm.startTime}
                    onChange={e => setCreateForm(f => ({ ...f, startTime: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white [color-scheme:dark]"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">End *</label>
                  <input
                    type="time"
                    value={createForm.endTime}
                    onChange={e => setCreateForm(f => ({ ...f, endTime: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white [color-scheme:dark]"
                  />
                </div>
              </div>

              <input
                type="text"
                placeholder="Location"
                value={createForm.location}
                onChange={e => setCreateForm(f => ({ ...f, location: e.target.value }))}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white"
              />
            </div>

            <div className="flex gap-2 mt-6">
              <button
                type="button"
                onClick={() => { setShowCreateModal(false); setEditMode(false); }}
                className="flex-1 px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (editMode) {
                    handleUpdateEvent();
                  } else {
                    handleCreateEvent();
                  }
                }}
                className="flex-1 px-4 py-2 bg-teal-600 text-white font-medium rounded hover:bg-teal-700"
              >
                {editMode ? 'Save Changes' : 'Create Event'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CalendarView;
