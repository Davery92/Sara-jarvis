/**
 * Location Awareness
 *
 * Two complementary geofence sources feed the backend:
 * 1. Significant-location-change background updates (coarse, periodic) — lets
 *    Sara know roughly where David is even without a specific trigger armed.
 * 2. Native CLRegion monitoring (exact enter/exit) for places/reminders that
 *    matter — wakes the app even when killed, so location-triggered reminders
 *    ("remind me when I leave this client site") fire reliably.
 *
 * Only activates when the user grants "Always" location permission and
 * enables the toggle in Settings.
 */

import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import * as Notifications from 'expo-notifications';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient } from './api';

const STORAGE_KEY = 'sara:location_tracking_enabled';
const LOCATION_TASK = 'SARA_LOCATION_UPDATES_TASK';
const GEOFENCE_TASK = 'SARA_GEOFENCE_TASK';

const MIN_DISTANCE_M = 200; // Minimum distance before reporting (meters)
const MIN_INTERVAL_MS = 5 * 60 * 1000; // Minimum 5 minutes between reports

let lastReportedAt = 0;
let lastLat = 0;
let lastLon = 0;

interface GeofenceRegion {
  identifier: string;
  kind: 'place' | 'trigger';
  latitude: number;
  longitude: number;
  radius_m: number;
  notify_on_entry: boolean;
  notify_on_exit: boolean;
}

/**
 * Haversine distance in meters between two lat/lon pairs.
 */
function haversineDistance(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ── Significant-location-change background task ──

TaskManager.defineTask(LOCATION_TASK, async ({ data, error }) => {
  if (error) {
    console.log('[Location] Background task error:', error);
    return;
  }
  const { locations } = (data as { locations: Location.LocationObject[] }) || { locations: [] };
  const location = locations?.[locations.length - 1];
  if (!location) return;
  await onLocationUpdate(location);
});

async function onLocationUpdate(location: Location.LocationObject): Promise<void> {
  const now = Date.now();
  if (now - lastReportedAt < MIN_INTERVAL_MS) return;

  const { latitude, longitude, accuracy } = location.coords;

  if (lastLat !== 0 && lastLon !== 0) {
    const dist = haversineDistance(lastLat, lastLon, latitude, longitude);
    if (dist < MIN_DISTANCE_M) return;
  }

  lastReportedAt = now;
  lastLat = latitude;
  lastLon = longitude;

  try {
    await apiClient.post('/api/location/report', {
      latitude,
      longitude,
      accuracy: accuracy ?? undefined,
      source: 'ios_significant',
    });
    console.log(`[Location] Reported: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
  } catch (err) {
    console.warn('[Location] Report failed:', err);
  }
}

// ── Native geofencing (exact enter/exit) ──

TaskManager.defineTask(GEOFENCE_TASK, async ({ data, error }) => {
  if (error) {
    console.log('[Location] Geofence task error:', error);
    return;
  }
  const { eventType, region } = (data as {
    eventType: Location.GeofencingEventType;
    region: Location.LocationRegion;
  }) || {};
  if (!region) return;

  const event = eventType === Location.GeofencingEventType.Enter ? 'enter' : 'exit';
  const identifier = region.identifier || '';

  try {
    await apiClient.post('/api/location/geofence-event', {
      region_id: identifier,
      event,
      latitude: region.latitude,
      longitude: region.longitude,
    });
    console.log(`[Location] Geofence ${event}: ${identifier}`);
  } catch (err) {
    console.warn('[Location] Geofence event report failed, falling back to local notice:', err);
    // Network failure shouldn't silently drop a location-triggered reminder —
    // surface something locally so it's not lost entirely.
    try {
      await Notifications.scheduleNotificationAsync({
        content: {
          title: 'Sara: location reminder',
          body: `You just ${event === 'enter' ? 'arrived at' : 'left'} a saved place, but I couldn't reach the server to check for reminders.`,
          sound: true,
        },
        trigger: null,
      });
    } catch {}
  }
});

/**
 * Check if location tracking is enabled by the user.
 */
export async function isLocationTrackingEnabled(): Promise<boolean> {
  const val = await AsyncStorage.getItem(STORAGE_KEY);
  return val === 'true';
}

/**
 * Toggle location tracking on/off.
 */
export async function setLocationTrackingEnabled(enabled: boolean): Promise<boolean> {
  if (enabled) {
    // Set before starting so startTracking()'s internal resyncGeofences() call
    // (which checks this flag) doesn't skip itself on first-time enable.
    await AsyncStorage.setItem(STORAGE_KEY, 'true');
    const started = await startTracking();
    if (!started) {
      await AsyncStorage.setItem(STORAGE_KEY, 'false');
    }
    return started;
  }
  await AsyncStorage.setItem(STORAGE_KEY, 'false');
  await stopTracking();
  return true;
}

/**
 * Start significant-location-change monitoring + sync geofence regions.
 */
export async function startTracking(): Promise<boolean> {
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      console.log('[Location] Foreground permission denied');
      return false;
    }

    const bgStatus = await Location.requestBackgroundPermissionsAsync();
    if (bgStatus.status !== 'granted') {
      console.log('[Location] Background permission denied — tracking limited to foreground');
    }

    await Location.startLocationUpdatesAsync(LOCATION_TASK, {
      accuracy: Location.Accuracy.Balanced,
      distanceInterval: MIN_DISTANCE_M,
      deferredUpdatesInterval: MIN_INTERVAL_MS,
      pausesUpdatesAutomatically: true,
      showsBackgroundLocationIndicator: false,
    });

    await resyncGeofences();

    console.log('[Location] Tracking started');
    return true;
  } catch (err) {
    console.error('[Location] Failed to start tracking:', err);
    return false;
  }
}

/**
 * Stop all location monitoring (significant-change updates + geofencing).
 */
export async function stopTracking(): Promise<void> {
  try {
    if (await TaskManager.isTaskRegisteredAsync(LOCATION_TASK)) {
      await Location.stopLocationUpdatesAsync(LOCATION_TASK);
    }
  } catch (err) {
    console.warn('[Location] Failed to stop location updates:', err);
  }

  try {
    if (await TaskManager.isTaskRegisteredAsync(GEOFENCE_TASK)) {
      await Location.stopGeofencingAsync(GEOFENCE_TASK);
    }
  } catch (err) {
    console.warn('[Location] Failed to stop geofencing:', err);
  }

  console.log('[Location] Tracking stopped');
}

/**
 * Pull the current set of regions to monitor from the backend and re-register
 * native geofencing. Call after login, on app foreground, and periodically
 * from the background health sync task so armed triggers/places stay current
 * without a dedicated background task of their own.
 */
export async function resyncGeofences(): Promise<void> {
  const enabled = await isLocationTrackingEnabled();
  if (!enabled) return;

  try {
    const bgStatus = await Location.getBackgroundPermissionsAsync();
    if (bgStatus.status !== 'granted') {
      console.log('[Location] No background permission — skipping geofence sync');
      return;
    }

    const resp = await apiClient.get<{ regions: GeofenceRegion[] }>('/api/location/geofences');
    const regions = resp.regions || [];

    if (regions.length === 0) {
      if (await TaskManager.isTaskRegisteredAsync(GEOFENCE_TASK)) {
        await Location.stopGeofencingAsync(GEOFENCE_TASK);
      }
      return;
    }

    await Location.startGeofencingAsync(
      GEOFENCE_TASK,
      regions.map((r) => ({
        identifier: r.identifier,
        latitude: r.latitude,
        longitude: r.longitude,
        radius: r.radius_m,
        notifyOnEnter: r.notify_on_entry,
        notifyOnExit: r.notify_on_exit,
      }))
    );

    console.log(`[Location] Synced ${regions.length} geofence region(s)`);
  } catch (err) {
    console.warn('[Location] Geofence resync failed:', err);
  }
}
