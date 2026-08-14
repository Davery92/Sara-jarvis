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
const MAX_SAMPLE_AGE_MS = 10 * 60 * 1000;

let lastReportedAt = 0;
let lastLat = 0;
let lastLon = 0;

// Phase 10A-fix: geofence/location POSTs must work from CELLULAR. A home geofence
// fires exactly while crossing the boundary — when the phone is on cellular
// (arriving) or just off WiFi (leaving) — so the dev client's LAN backend
// (http://10.185.1.180:8000) is almost never reachable at that instant. These two
// tiny endpoints always go over the WAN/Tailscale URL first, then fall back to the
// app's normal base (LAN in dev), and queue for replay if both fail.
const LOCATION_WAN_URL = 'https://sara-api.avery.cloud';
const TOKEN_KEY = '@sara_auth_token';
const LOCATION_QUEUE_KEY = 'sara:location_event_queue';
const ARMED_REGIONS_KEY = 'sara:armed_region_ids';

interface GeofenceRegion {
  identifier: string;
  kind: 'place' | 'trigger';
  latitude: number;
  longitude: number;
  radius_m: number;
  notify_on_entry: boolean;
  notify_on_exit: boolean;
  has_trigger?: boolean;  // place with an armed location_trigger riding on it
}

/** POST to a location endpoint over WAN first, then the LAN/base client. */
async function postLocation(path: string, body: Record<string, unknown>): Promise<boolean> {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  const withTime = { ...body, event_time: body.event_time ?? new Date().toISOString() };
  // 1. WAN/Tailscale — reachable from cellular by definition.
  try {
    const res = await fetch(`${LOCATION_WAN_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(withTime),
    });
    if (res.ok) return true;
  } catch { /* fall through */ }
  // 2. Normal client (LAN in dev) — works when actually on the home network.
  try {
    await apiClient.post(path, withTime);
    return true;
  } catch { /* fall through */ }
  return false;
}

async function queueLocationEvent(path: string, body: Record<string, unknown>): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(LOCATION_QUEUE_KEY);
    const queue: Array<{ path: string; body: Record<string, unknown> }> = raw ? JSON.parse(raw) : [];
    queue.push({ path, body: { ...body, event_time: body.event_time ?? new Date().toISOString() } });
    // Cap the queue so a long offline stretch can't grow unbounded.
    await AsyncStorage.setItem(LOCATION_QUEUE_KEY, JSON.stringify(queue.slice(-50)));
  } catch { /* best effort */ }
}

/** Replay any queued location events (call on foreground / next report). */
export async function flushQueuedLocationEvents(): Promise<void> {
  let queue: Array<{ path: string; body: Record<string, unknown> }> = [];
  try {
    const raw = await AsyncStorage.getItem(LOCATION_QUEUE_KEY);
    queue = raw ? JSON.parse(raw) : [];
  } catch { return; }
  if (!queue.length) return;
  const remaining: typeof queue = [];
  for (const item of queue) {
    const ok = await postLocation(item.path, item.body);
    if (!ok) remaining.push(item);
  }
  try {
    if (remaining.length) await AsyncStorage.setItem(LOCATION_QUEUE_KEY, JSON.stringify(remaining));
    else await AsyncStorage.removeItem(LOCATION_QUEUE_KEY);
  } catch { /* noop */ }
}

/** True if a failed geofence at this region is worth a local "couldn't reach" notice. */
async function regionIsArmed(identifier: string): Promise<boolean> {
  try {
    const raw = await AsyncStorage.getItem(ARMED_REGIONS_KEY);
    const armed: string[] = raw ? JSON.parse(raw) : [];
    return armed.includes(identifier);
  } catch { return false; }
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

async function onLocationUpdate(location: Location.LocationObject, force = false): Promise<boolean> {
  const now = Date.now();
  const sampleAge = now - location.timestamp;
  if (sampleAge > MAX_SAMPLE_AGE_MS || sampleAge < -MIN_INTERVAL_MS) {
    console.warn(`[Location] Ignoring stale/invalid sample (${Math.round(sampleAge / 1000)}s old)`);
    return false;
  }
  if (!force && now - lastReportedAt < MIN_INTERVAL_MS) return false;

  const { latitude, longitude, accuracy } = location.coords;

  if (lastLat !== 0 && lastLon !== 0) {
    const dist = haversineDistance(lastLat, lastLon, latitude, longitude);
    if (!force && dist < MIN_DISTANCE_M) return false;
  }

  lastReportedAt = now;
  lastLat = latitude;
  lastLon = longitude;

  const ok = await postLocation('/api/location/report', {
    latitude,
    longitude,
    accuracy: accuracy ?? undefined,
    source: 'ios_significant',
    observed_at: new Date(location.timestamp).toISOString(),
  });
  if (ok) {
    console.log(`[Location] Reported: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
    // A successful report means we have connectivity — flush any queued geofence events.
    flushQueuedLocationEvents().catch(() => {});
  } else {
    console.warn('[Location] Report failed (WAN + LAN); queued events will retry later');
  }
  return ok;
}

/** Request a new foreground fix instead of relying on iOS's cached background sample. */
export async function refreshCurrentLocation(): Promise<boolean> {
  if (!(await isLocationTrackingEnabled())) return false;
  try {
    const permission = await Location.getForegroundPermissionsAsync();
    if (permission.status !== 'granted') return false;
    const location = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return await onLocationUpdate(location, true);
  } catch (error) {
    console.warn('[Location] Current location refresh failed:', error);
    return false;
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

  const body = {
    region_id: identifier,
    event,
    latitude: region.latitude,
    longitude: region.longitude,
    event_time: new Date().toISOString(),
  };
  const ok = await postLocation('/api/location/geofence-event', body);
  if (ok) {
    console.log(`[Location] Geofence ${event}: ${identifier}`);
    return;
  }
  // Both WAN and LAN failed — queue for replay on next foreground/report.
  await queueLocationEvent('/api/location/geofence-event', body);
  console.warn('[Location] Geofence event queued (server unreachable):', identifier);
  // Only surface a local notice if an armed reminder was actually riding on this
  // region — otherwise fail silently to the log (no noise notifications).
  if (await regionIsArmed(identifier)) {
    try {
      await Notifications.scheduleNotificationAsync({
        content: {
          title: 'Sara: location reminder',
          body: `You just ${event === 'enter' ? 'arrived at' : 'left'} a saved place — I'll check your reminder as soon as I'm back online.`,
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

    await refreshCurrentLocation();
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

    // Cache which region ids have an armed reminder, so a failed geofence POST only
    // surfaces a local notice when there's actually something to check (10A-fix).
    try {
      const armed = regions
        .filter((r) => r.kind === 'trigger' || r.has_trigger)
        .map((r) => r.identifier);
      await AsyncStorage.setItem(ARMED_REGIONS_KEY, JSON.stringify(armed));
    } catch { /* noop */ }
    // Foreground sync is a good moment to replay any queued events.
    flushQueuedLocationEvents().catch(() => {});

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
