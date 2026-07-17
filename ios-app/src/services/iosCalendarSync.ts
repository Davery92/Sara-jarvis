import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import apiClient from './api';

// Types for iOS calendar data
export interface IOSCalendar {
  id: string;
  title: string;
  color: string;
  source: {
    id: string;
    name: string;
    type: string;
  };
  allowsModifications: boolean;
  isPrimary: boolean;
}

export interface IOSEventAttendee {
  name?: string;
  email?: string;
  status?: string;
}

export interface IOSCalendarEvent {
  id: string;
  calendarId: string;
  title: string;
  notes?: string;
  startDate: string;
  endDate: string;
  location?: string;
  allDay: boolean;
  timeZone?: string;
  organizer?: string;
}

export interface SyncResult {
  success: boolean;
  synced: number;
  errors: number;
  message?: string;
}

// Storage keys
const STORAGE_KEYS = {
  SELECTED_CALENDARS: '@sara_ios_calendars',
  LAST_SYNC: '@sara_ios_calendar_last_sync',
  SYNC_ENABLED: '@sara_ios_calendar_sync_enabled',
};

class IOSCalendarSyncService {
  private isAvailable: boolean = false;
  private isInitialized: boolean = false;
  private calendarModule: any = null;

  /**
   * Initialize the calendar service and request permissions
   */
  async initialize(): Promise<boolean> {
    if (Platform.OS !== 'ios') {
      console.log('[IOSCalendar] Not available on this platform');
      return false;
    }

    try {
      console.log('[IOSCalendar] Loading expo-calendar...');
      const Calendar = require('expo-calendar');
      this.calendarModule = Calendar;

      console.log('[IOSCalendar] Requesting calendar permissions...');
      const { status } = await Calendar.requestCalendarPermissionsAsync();

      if (status !== 'granted') {
        console.log('[IOSCalendar] Permission denied');
        this.isAvailable = false;
        return false;
      }

      console.log('[IOSCalendar] Permission granted');
      this.isAvailable = true;
      this.isInitialized = true;
      return true;
    } catch (error: any) {
      console.log('[IOSCalendar] Initialization failed:', error?.message || error);
      this.isAvailable = false;
      this.isInitialized = false;
      return false;
    }
  }

  /**
   * Check if calendar sync is available
   */
  isCalendarAvailable(): boolean {
    return this.isAvailable && this.isInitialized;
  }

  /**
   * Get permission status without requesting
   */
  async getPermissionStatus(): Promise<'granted' | 'denied' | 'undetermined'> {
    if (Platform.OS !== 'ios') return 'denied';

    try {
      const Calendar = require('expo-calendar');
      const { status } = await Calendar.getCalendarPermissionsAsync();
      return status as 'granted' | 'denied' | 'undetermined';
    } catch (error) {
      console.log('[IOSCalendar] Error checking permissions:', error);
      return 'denied';
    }
  }

  /**
   * Get all calendars from iOS
   */
  async getCalendars(): Promise<IOSCalendar[]> {
    if (!this.isAvailable || !this.calendarModule) {
      // Try to initialize if not already
      if (!this.isInitialized) {
        const initialized = await this.initialize();
        if (!initialized) return [];
      } else {
        return [];
      }
    }

    try {
      const calendars = await this.calendarModule.getCalendarsAsync(
        this.calendarModule.EntityTypes.EVENT
      );

      return calendars.map((cal: any) => ({
        id: cal.id,
        title: cal.title,
        color: cal.color || '#14b8a6',
        source: {
          id: cal.source?.id || '',
          name: cal.source?.name || 'Unknown',
          type: cal.source?.type || 'unknown',
        },
        allowsModifications: cal.allowsModifications ?? false,
        isPrimary: cal.isPrimary ?? false,
      }));
    } catch (error) {
      console.log('[IOSCalendar] Error getting calendars:', error);
      return [];
    }
  }

  /**
   * Get events from specified calendars within date range
   */
  async getEvents(calendarIds: string[], startDate: Date, endDate: Date): Promise<IOSCalendarEvent[]> {
    if (!this.isAvailable || !this.calendarModule) return [];
    if (calendarIds.length === 0) return [];

    try {
      const events = await this.calendarModule.getEventsAsync(
        calendarIds,
        startDate,
        endDate
      );

      // Debug: log all events returned from iOS
      console.log(`[IOSCalendar] iOS returned ${events.length} events:`);
      events.forEach((e: any) => {
        const startStr = new Date(e.startDate).toISOString().split('T')[0];
        console.log(`[IOSCalendar]   - ${startStr}: ${e.title} (id: ${e.id?.substring(0, 8)}...)`);
      });

      return events.map((event: any) => ({
        id: event.id,
        calendarId: event.calendarId,
        title: event.title || 'Untitled',
        notes: event.notes,
        startDate: event.startDate,
        endDate: event.endDate,
        location: event.location,
        allDay: event.allDay ?? false,
        timeZone: event.timeZone,
        // organizer is only populated by EventKit on iOS; expo-calendar
        // surfaces it as an Attendee-shaped object when present.
        organizer: event.organizer?.name || event.organizer?.email || undefined,
      }));
    } catch (error) {
      console.log('[IOSCalendar] Error getting events:', error);
      return [];
    }
  }

  /**
   * Attendees for a single event. iOS-only (EventKit); expo-calendar doesn't
   * include attendees in getEventsAsync, so this is a separate per-event call.
   * Best-effort — a failure here should never block the rest of the sync.
   */
  async getAttendeesForEvent(eventId: string): Promise<IOSEventAttendee[]> {
    if (!this.isAvailable || !this.calendarModule) return [];
    if (typeof this.calendarModule.getAttendeesForEventAsync !== 'function') return [];
    try {
      const attendees = await this.calendarModule.getAttendeesForEventAsync(eventId);
      return (attendees || [])
        .filter((a: any) => !a.isCurrentUser)
        .map((a: any) => ({ name: a.name || undefined, email: a.email || undefined, status: a.status || undefined }));
    } catch (error) {
      console.log(`[IOSCalendar] Error getting attendees for ${eventId}:`, error);
      return [];
    }
  }

  /**
   * Get selected calendar IDs from storage
   */
  async getSelectedCalendarIds(): Promise<string[]> {
    try {
      const stored = await AsyncStorage.getItem(STORAGE_KEYS.SELECTED_CALENDARS);
      if (stored) {
        return JSON.parse(stored);
      }
      return [];
    } catch (error) {
      console.log('[IOSCalendar] Error reading selected calendars:', error);
      return [];
    }
  }

  /**
   * Save selected calendar IDs to storage
   */
  async setSelectedCalendarIds(calendarIds: string[]): Promise<void> {
    try {
      await AsyncStorage.setItem(
        STORAGE_KEYS.SELECTED_CALENDARS,
        JSON.stringify(calendarIds)
      );
    } catch (error) {
      console.log('[IOSCalendar] Error saving selected calendars:', error);
    }
  }

  /**
   * Check if calendar sync is enabled
   */
  async isSyncEnabled(): Promise<boolean> {
    try {
      const enabled = await AsyncStorage.getItem(STORAGE_KEYS.SYNC_ENABLED);
      return enabled === 'true';
    } catch (error) {
      return false;
    }
  }

  /**
   * Enable or disable calendar sync
   */
  async setSyncEnabled(enabled: boolean): Promise<void> {
    try {
      await AsyncStorage.setItem(STORAGE_KEYS.SYNC_ENABLED, enabled ? 'true' : 'false');
    } catch (error) {
      console.log('[IOSCalendar] Error saving sync enabled state:', error);
    }
  }

  /**
   * Get last sync timestamp
   */
  async getLastSyncTime(): Promise<Date | null> {
    try {
      const timestamp = await AsyncStorage.getItem(STORAGE_KEYS.LAST_SYNC);
      if (timestamp) {
        return new Date(timestamp);
      }
      return null;
    } catch (error) {
      return null;
    }
  }

  /**
   * Update last sync timestamp
   */
  private async updateLastSyncTime(): Promise<void> {
    try {
      await AsyncStorage.setItem(STORAGE_KEYS.LAST_SYNC, new Date().toISOString());
    } catch (error) {
      console.log('[IOSCalendar] Error updating last sync time:', error);
    }
  }

  /**
   * Sync selected calendars to Sara's backend
   * Main sync function - called on app open
   */
  async syncSelectedCalendars(): Promise<SyncResult> {
    console.log('[IOSCalendar] Starting calendar sync...');

    // Check if sync is enabled
    const syncEnabled = await this.isSyncEnabled();
    if (!syncEnabled) {
      console.log('[IOSCalendar] Sync is disabled');
      return { success: true, synced: 0, errors: 0, message: 'Sync disabled' };
    }

    // Initialize if needed
    if (!this.isAvailable) {
      const initialized = await this.initialize();
      if (!initialized) {
        return { success: false, synced: 0, errors: 0, message: 'Calendar not available' };
      }
    }

    // Get selected calendars
    const selectedCalendarIds = await this.getSelectedCalendarIds();
    if (selectedCalendarIds.length === 0) {
      console.log('[IOSCalendar] No calendars selected');
      return { success: true, synced: 0, errors: 0, message: 'No calendars selected' };
    }

    try {
      // Date range: today to 30 days ahead
      const startDate = new Date();
      startDate.setHours(0, 0, 0, 0);

      const endDate = new Date();
      endDate.setDate(endDate.getDate() + 30);
      endDate.setHours(23, 59, 59, 999);

      // Get events from iOS
      const events = await this.getEvents(selectedCalendarIds, startDate, endDate);
      console.log(`[IOSCalendar] Found ${events.length} events to sync`);

      if (events.length === 0) {
        await this.updateLastSyncTime();
        return { success: true, synced: 0, errors: 0 };
      }

      // Get calendar names for display
      const calendars = await this.getCalendars();
      const calendarMap = new Map(calendars.map(c => [c.id, c]));

      // Attendees are a separate per-event EventKit call (not included in
      // getEventsAsync) — fetch them for every event in the sync window.
      // Best-effort: a per-event failure falls back to no attendees rather
      // than failing the whole sync (getAttendeesForEvent already swallows
      // its own errors).
      const attendeesByEventId = new Map<string, IOSEventAttendee[]>();
      await Promise.all(events.map(async event => {
        const attendees = await this.getAttendeesForEvent(event.id);
        if (attendees.length > 0) attendeesByEventId.set(event.id, attendees);
      }));

      // Transform events for backend
      // expo-calendar returns dates as ISO strings in the event's timezone
      // We need to ensure they're sent as proper UTC ISO strings
      const eventsToSync = events.map(event => {
        // Parse the date strings and convert to UTC ISO format
        const startDate = new Date(event.startDate);
        const endDate = new Date(event.endDate);

        return {
          ios_event_id: event.id,
          ios_calendar_id: event.calendarId,
          ios_calendar_name: calendarMap.get(event.calendarId)?.title || 'Unknown',
          title: event.title,
          description: event.notes || null,
          start_time: startDate.toISOString(),  // Converts to UTC with 'Z' suffix
          end_time: endDate.toISOString(),      // Converts to UTC with 'Z' suffix
          location: event.location || null,
          all_day: event.allDay,
          attendees: attendeesByEventId.get(event.id) || undefined,
          organizer: event.organizer || null,
        };
      });

      // Send to backend, including the sync window + calendar IDs so the
      // backend can reconcile deletions (events removed on iOS that still
      // exist on Sara's side inside the window).
      const response = await apiClient.post<{ synced: number; errors: number; deleted?: number }>(
        '/api/calendar/ios-sync',
        {
          events: eventsToSync,
          window_start: startDate.toISOString(),
          window_end: endDate.toISOString(),
          calendar_ids: selectedCalendarIds,
        }
      );

      await this.updateLastSyncTime();

      console.log(`[IOSCalendar] Sync complete: ${response.synced} synced, ${response.deleted ?? 0} deleted, ${response.errors} errors`);
      return {
        success: true,
        synced: response.synced,
        errors: response.errors,
      };
    } catch (error: any) {
      console.log('[IOSCalendar] Sync failed:', error?.message || error);
      return {
        success: false,
        synced: 0,
        errors: 1,
        message: error?.message || 'Sync failed',
      };
    }
  }

  /**
   * Clear all synced iOS events from backend
   * Called when user disables calendar sync
   */
  async clearSyncedEvents(): Promise<boolean> {
    try {
      await apiClient.delete('/api/calendar/ios-sync');
      return true;
    } catch (error) {
      console.log('[IOSCalendar] Error clearing synced events:', error);
      return false;
    }
  }
}

// Export singleton instance
export const iosCalendarSyncService = new IOSCalendarSyncService();
export default iosCalendarSyncService;
