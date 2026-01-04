/**
 * CalendarWidget - Shows upcoming calendar events
 */

export function CalendarWidget({ events, loading }) {
  if (loading) {
    return (
      <div class="card calendar-widget">
        <div class="card-header">
          <span class="card-title">Today's Schedule</span>
        </div>
        <div class="loading-state">Loading events...</div>
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <div class="card calendar-widget">
        <div class="card-header">
          <span class="card-title">Today's Schedule</span>
        </div>
        <div class="empty-state">No events today</div>
      </div>
    );
  }

  const formatTime = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  };

  const isNow = (start, end) => {
    const now = new Date();
    const startDate = new Date(start);
    const endDate = end ? new Date(end) : new Date(startDate.getTime() + 3600000);
    return now >= startDate && now <= endDate;
  };

  const isPast = (end) => {
    if (!end) return false;
    return new Date() > new Date(end);
  };

  return (
    <div class="card calendar-widget">
      <div class="card-header">
        <span class="card-title">Today's Schedule</span>
      </div>
      <div class="event-list">
        {events.slice(0, 5).map((event, idx) => (
          <div
            key={event.id || idx}
            class={`event-item ${isNow(event.start, event.end) ? 'current' : ''} ${isPast(event.end) ? 'past' : ''}`}
          >
            <span class="event-time">{formatTime(event.start)}</span>
            <span class="event-title">{event.title || event.summary}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
