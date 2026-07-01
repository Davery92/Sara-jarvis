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

    // Calendar/type identity lives in a 2px left edge, never a full-bleed fill
    const edgeClass = isMultiDay
      ? 'border-amber-400/70'
      : isIOSEvent(event)
      ? 'border-purple-400/60'
      : 'border-teal-400/70';

    if (compact) {
      return (
        <button
          onClick={() => setSelectedEvent(event)}
          className={`w-full rounded-r border-l-2 ${edgeClass} px-1.5 py-1 text-left transition-colors hover:bg-white/[0.06]`}
        >
          <div className="truncate text-[13px] leading-snug text-slate-200">
            {isContinuation && <span className="text-amber-400/80">↳ </span>}
            {event.title}
          </div>
          {!isMultiDay && (
            <div className="truncate text-[11px] tabular-nums text-slate-500">{formatTime(event.starts_at)}</div>
          )}
        </button>
      );
    }

    return (
      <button
        onClick={() => setSelectedEvent(event)}
        className={`w-full rounded-r border-l-2 ${edgeClass} px-3 py-2 text-left transition-colors hover:bg-white/[0.04]`}
      >
        <div className="flex items-center gap-2 text-[15px] font-medium text-slate-100">
          {isContinuation && <span className="text-amber-400/80">↳</span>}
          <span className="truncate">{event.title}</span>
          {isMultiDay && <span className="flex-shrink-0 text-xs font-normal text-slate-500">multi-day</span>}
          {isIOSEvent(event) && !isMultiDay && <span className="flex-shrink-0 text-xs font-normal text-slate-500">iOS</span>}
        </div>
        <div className="mt-0.5 text-xs tabular-nums text-slate-500">
          {getTimeDisplay()}
          {event.location && <span> · {event.location}</span>}
        </div>
      </button>
    );
  };

  // Day View
  const renderDayView = () => {
    const dayEvents = getEventsForDate(selectedDate);
    return (
      <div className="mx-auto w-full max-w-[740px]">
        <div className="space-y-1.5 pt-2">
          {dayEvents.length === 0 ? (
            <p className="py-8 text-sm text-slate-500">No events this day.</p>
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
      <div className="grid min-h-full grid-cols-7 divide-x divide-white/[0.06] border-t border-white/[0.06]">
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
              className={`min-h-[360px] cursor-pointer px-1.5 pt-3 transition-colors ${
                isToday ? 'bg-teal-400/[0.04]' : 'hover:bg-white/[0.02]'
              }`}
            >
              <div className="mb-3 px-1.5">
                <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  {day.toLocaleDateString('en-US', { weekday: 'short' })}
                </div>
                <div className={`font-display text-lg ${
                  isToday ? 'font-semibold text-teal-300' : isSelected ? 'font-semibold text-white' : 'text-slate-300'
                }`}>
                  {day.getDate()}
                </div>
              </div>
              <div className="space-y-1">
                {dayEvents.slice(0, 4).map(event => (
                  <EventCard key={event.id} event={event} compact forDate={day} />
                ))}
                {dayEvents.length > 4 && (
                  <div className="px-1.5 text-xs text-slate-500">+{dayEvents.length - 4} more</div>
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
      <div className="grid grid-cols-7">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
          <div key={d} className="pb-2 pl-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 border-l border-t border-white/[0.06]">
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
              className={`min-h-[96px] cursor-pointer border-b border-r border-white/[0.06] p-1.5 transition-colors ${
                isToday ? 'bg-teal-400/[0.04]' : 'hover:bg-white/[0.02]'
              } ${!isCurrentMonth ? 'opacity-40' : ''}`}
            >
              <div className={`pl-0.5 text-sm ${
                isToday ? 'font-semibold text-teal-300' : isCurrentMonth ? 'text-slate-300' : 'text-slate-600'
              }`}>
                {day.getDate()}
              </div>
              {dayEvents.length > 0 && (
                <div className="mt-1 space-y-0.5">
                  {dayEvents.slice(0, 2).map(event => {
                    const isMultiDay = isMultiDayEvent(event);
                    const isCont = isContinuationDay(event, day);
                    return (
                      <div
                        key={event.id}
                        className={`truncate rounded-r border-l-2 px-1 text-xs text-slate-300 ${
                          isMultiDay ? 'border-amber-400/70' : isIOSEvent(event) ? 'border-purple-400/60' : 'border-teal-400/70'
                        }`}
                      >
                        {isCont && <span className="text-amber-400/80">↳</span>}
                        {event.title}
                      </div>
                    );
                  })}
                  {dayEvents.length > 2 && (
                    <div className="pl-1 text-xs text-slate-500">+{dayEvents.length - 2}</div>
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
    <div className="calendar-view flex h-full flex-col">
      {/* Header — one slim row: title + state, navigation, view tabs, primary action */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pb-4">
        <div className="flex min-w-0 items-baseline gap-3">
          <h2 className="font-display text-xl font-semibold text-white">Calendar</h2>
          <span className="hidden truncate text-sm text-slate-400 sm:inline">
            {todayEventsCount} {todayEventsCount === 1 ? 'event' : 'events'} today
            <span className="text-slate-600"> · </span>
            {currentPeriodLabel}
          </span>
          {iosEventCount > 0 && (
            <span
              className="material-icons flex-shrink-0 cursor-default text-[14px] text-slate-600"
              title={`${iosEventCount} events synced from iOS Calendar`}
            >
              sync
            </span>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex items-center">
            <button
              onClick={() => navigate(-1)}
              aria-label="Previous"
              className="rounded-lg px-2 py-1 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              ‹
            </button>
            <button
              onClick={goToToday}
              className="rounded-lg px-2.5 py-1 text-sm text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              Today
            </button>
            <button
              onClick={() => navigate(1)}
              aria-label="Next"
              className="rounded-lg px-2 py-1 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              ›
            </button>
          </div>

          <div className="flex items-center gap-1">
            {(['day', 'week', 'month'] as const).map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`rounded-lg px-2.5 py-1 text-sm transition-colors ${
                  view === v ? 'font-medium text-white' : 'text-slate-500 hover:text-white'
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
            className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300"
          >
            + New event
          </button>
        </div>
      </div>

      {/* Calendar Content */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <p className="py-12 text-sm text-slate-500">Loading calendar…</p>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setSelectedEvent(null)}>
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0c1626] p-6" onClick={e => e.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="font-display text-lg font-semibold text-white">{selectedEvent.title}</h3>
                {isIOSEvent(selectedEvent) && (
                  <p className="mt-0.5 text-xs text-slate-500">
                    Synced from iOS Calendar
                    {selectedEvent.ios_calendar_name && <span> · {selectedEvent.ios_calendar_name}</span>}
                  </p>
                )}
              </div>
              <button
                onClick={() => setSelectedEvent(null)}
                aria-label="Close"
                className="flex-shrink-0 text-slate-500 transition-colors hover:text-white"
              >
                ✕
              </button>
            </div>

            {selectedEvent.description && (
              <p className="mb-4 text-[15px] leading-relaxed text-slate-300">{selectedEvent.description}</p>
            )}

            <div className="mb-6 space-y-1.5 text-sm text-slate-400">
              <div className="flex gap-3">
                <span className="w-12 flex-shrink-0 text-xs uppercase tracking-wide text-slate-500">Starts</span>
                <span className="tabular-nums">{new Date(selectedEvent.starts_at).toLocaleString()}</span>
              </div>
              <div className="flex gap-3">
                <span className="w-12 flex-shrink-0 text-xs uppercase tracking-wide text-slate-500">Ends</span>
                <span className="tabular-nums">{new Date(selectedEvent.ends_at).toLocaleString()}</span>
              </div>
              {selectedEvent.location && (
                <div className="flex gap-3">
                  <span className="w-12 flex-shrink-0 text-xs uppercase tracking-wide text-slate-500">Where</span>
                  <span>{selectedEvent.location}</span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => handleDeleteEvent(selectedEvent.id)}
                className="text-xs text-slate-500 transition-colors hover:text-rose-300"
              >
                {isIOSEvent(selectedEvent) ? 'Hide from Sara' : 'Delete'}
              </button>
              <div className="ml-auto flex items-center gap-2">
                <button
                  onClick={() => setSelectedEvent(null)}
                  className="rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
                >
                  Close
                </button>
                {!isIOSEvent(selectedEvent) && (
                  <button
                    onClick={() => openEditModal(selectedEvent)}
                    className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300"
                  >
                    Edit
                  </button>
                )}
              </div>
            </div>
            {isIOSEvent(selectedEvent) && (
              <p className="mt-3 text-xs text-slate-500">
                To edit, use your iOS Calendar app. Hiding here keeps the event on iPhone but removes it from Sara.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Create/Edit Event Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/60 p-4" style={{ zIndex: 9999 }} onClick={() => { setShowCreateModal(false); setEditMode(false); }}>
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0c1626] p-6" onClick={e => e.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between">
              <h3 className="font-display text-lg font-semibold text-white">{editMode ? 'Edit event' : 'New event'}</h3>
              <button
                onClick={() => { setShowCreateModal(false); setEditMode(false); }}
                aria-label="Close"
                className="text-slate-500 transition-colors hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <input
                type="text"
                placeholder="Event title *"
                value={createForm.title}
                onChange={e => setCreateForm(f => ({ ...f, title: e.target.value }))}
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30"
              />

              <textarea
                placeholder="Description"
                value={createForm.description}
                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))}
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30"
                rows={2}
              />

              <div>
                <label className="mb-1 block text-xs text-slate-500">Date *</label>
                <input
                  type="date"
                  value={createForm.date}
                  onChange={e => setCreateForm(f => ({ ...f, date: e.target.value }))}
                  className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-300/30 [color-scheme:dark]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs text-slate-500">Start *</label>
                  <input
                    type="time"
                    value={createForm.startTime}
                    onChange={e => setCreateForm(f => ({ ...f, startTime: e.target.value }))}
                    className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-300/30 [color-scheme:dark]"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-500">End *</label>
                  <input
                    type="time"
                    value={createForm.endTime}
                    onChange={e => setCreateForm(f => ({ ...f, endTime: e.target.value }))}
                    className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-300/30 [color-scheme:dark]"
                  />
                </div>
              </div>

              <input
                type="text"
                placeholder="Location"
                value={createForm.location}
                onChange={e => setCreateForm(f => ({ ...f, location: e.target.value }))}
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30"
              />
            </div>

            <div className="mt-6 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => { setShowCreateModal(false); setEditMode(false); }}
                className="rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
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
                className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300"
              >
                {editMode ? 'Save changes' : 'Create event'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CalendarView;
