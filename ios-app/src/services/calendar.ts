import apiClient from './api';

export interface CalendarEvent {
  id: string;  // Backend uses UUID strings
  user_id: string;
  title: string;
  description?: string;
  start_time: string;
  end_time: string;
  location?: string;
  all_day: boolean;
  reminder_minutes?: number;
  is_completed: boolean;
  // iOS calendar sync fields
  source?: string;  // 'sara' or 'ios_calendar'
  ios_event_id?: string;
  ios_calendar_id?: string;
  ios_calendar_name?: string;
  read_only?: boolean;
  created_at: string;
  updated_at: string;
}

export interface Reminder {
  id: string;  // Backend uses UUID strings
  user_id: string;
  title: string;
  description?: string;
  reminder_time: string;  // Backend uses reminder_time, not due_date
  is_completed: boolean;  // Backend uses is_completed, not completed
  created_at: string;
  updated_at: string;
}

export interface CreateEventParams {
  title: string;
  description?: string;
  start_time: string;
  end_time: string;
  location?: string;
  all_day?: boolean;
  reminder_minutes?: number;
}

export interface UpdateEventParams {
  title?: string;
  description?: string;
  start_time?: string;
  end_time?: string;
  location?: string;
  all_day?: boolean;
  reminder_minutes?: number;
}

export interface CreateReminderParams {
  title: string;
  description?: string;
  reminder_time: string;  // Backend uses reminder_time
}

export interface UpdateReminderParams {
  title?: string;
  description?: string;
  reminder_time?: string;  // Backend uses reminder_time
  is_completed?: boolean;  // Backend uses is_completed
}

class CalendarService {
  // Calendar Events

  /**
   * Get all calendar events within a date range
   */
  async getEvents(startDate?: string, endDate?: string): Promise<CalendarEvent[]> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    return await apiClient.get<CalendarEvent[]>(`/calendar/events?${params}`);
  }

  /**
   * Get a single event by ID
   */
  async getEvent(eventId: string): Promise<CalendarEvent> {
    return await apiClient.get<CalendarEvent>(`/calendar/events/${eventId}`);
  }

  /**
   * Create a new calendar event
   */
  async createEvent(params: CreateEventParams): Promise<CalendarEvent> {
    return await apiClient.post<CalendarEvent>('/calendar/events', params);
  }

  /**
   * Update an existing event
   */
  async updateEvent(eventId: string, params: UpdateEventParams): Promise<CalendarEvent> {
    return await apiClient.put<CalendarEvent>(`/calendar/events/${eventId}`, params);
  }

  /**
   * Delete a calendar event
   */
  async deleteEvent(eventId: string): Promise<void> {
    await apiClient.delete(`/calendar/events/${eventId}`);
  }

  // Reminders

  /**
   * Get all reminders
   */
  async getReminders(completed?: boolean): Promise<Reminder[]> {
    const params = new URLSearchParams();
    if (completed !== undefined) {
      params.append('completed', completed.toString());
    }
    return await apiClient.get<Reminder[]>(`/reminders?${params}`);
  }

  /**
   * Get a single reminder by ID
   */
  async getReminder(reminderId: string): Promise<Reminder> {
    return await apiClient.get<Reminder>(`/reminders/${reminderId}`);
  }

  /**
   * Create a new reminder
   */
  async createReminder(params: CreateReminderParams): Promise<Reminder> {
    return await apiClient.post<Reminder>('/reminders', params);
  }

  /**
   * Update an existing reminder
   */
  async updateReminder(reminderId: string, params: UpdateReminderParams): Promise<Reminder> {
    return await apiClient.put<Reminder>(`/reminders/${reminderId}`, params);
  }

  /**
   * Toggle reminder completion status
   */
  async toggleReminderComplete(reminderId: string, completed: boolean): Promise<Reminder> {
    return await this.updateReminder(reminderId, { is_completed: completed });
  }

  /**
   * Delete a reminder
   */
  async deleteReminder(reminderId: string): Promise<void> {
    await apiClient.delete(`/reminders/${reminderId}`);
  }

  // Helper Methods

  /**
   * Format date for display
   */
  formatDate(dateString: string): string {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  }

  /**
   * Format time for display
   */
  formatTime(dateString: string): string {
    const date = new Date(dateString);
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  /**
   * Format date and time for display
   */
  formatDateTime(dateString: string): string {
    return `${this.formatDate(dateString)} ${this.formatTime(dateString)}`;
  }

  /**
   * Check if event is today
   */
  isToday(dateString: string): boolean {
    const date = new Date(dateString);
    const today = new Date();
    return (
      date.getDate() === today.getDate() &&
      date.getMonth() === today.getMonth() &&
      date.getFullYear() === today.getFullYear()
    );
  }

  /**
   * Check if event is upcoming (within next 7 days)
   */
  isUpcoming(dateString: string): boolean {
    const date = new Date(dateString);
    const today = new Date();
    const weekFromNow = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000);
    return date > today && date <= weekFromNow;
  }

  /**
   * Check if reminder is overdue
   */
  isOverdue(dateString: string): boolean {
    const date = new Date(dateString);
    const now = new Date();
    return date < now;
  }

  /**
   * Get priority color
   */
  getPriorityColor(priority?: 'low' | 'medium' | 'high'): string {
    switch (priority) {
      case 'high':
        return '#ef4444'; // red
      case 'medium':
        return '#f59e0b'; // orange
      case 'low':
        return '#10b981'; // green
      default:
        return '#6b7280'; // gray
    }
  }

  /**
   * Get priority emoji
   */
  getPriorityEmoji(priority?: 'low' | 'medium' | 'high'): string {
    switch (priority) {
      case 'high':
        return '🔴';
      case 'medium':
        return '🟡';
      case 'low':
        return '🟢';
      default:
        return '⚪';
    }
  }
}

export const calendarService = new CalendarService();
export default calendarService;
