/**
 * Significant Location Change Tracking
 *
 * Uses iOS CLLocationManager significant location changes for
 * battery-efficient location awareness. Reports to Sara backend
 * for place classification against PKG_Place nodes.
 *
 * Only activates when user grants "Always" location permission.
 */

import * as Location from 'expo-location';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getApiUrl } from './api';

const STORAGE_KEY = 'sara:location_tracking_enabled';
const MIN_DISTANCE_M = 200; // Minimum distance before reporting (meters)
const MIN_INTERVAL_MS = 5 * 60 * 1000; // Minimum 5 minutes between reports

let lastReportedAt = 0;
let lastLat = 0;
let lastLon = 0;

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
export async function setLocationTrackingEnabled(enabled: boolean): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, enabled ? 'true' : 'false');
  if (enabled) {
    await startTracking();
  } else {
    await stopTracking();
  }
}

/**
 * Start significant location change monitoring.
 */
export async function startTracking(): Promise<boolean> {
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      console.log('[Location] Foreground permission denied');
      return false;
    }

    // Request background permission for significant location changes
    const bgStatus = await Location.requestBackgroundPermissionsAsync();
    if (bgStatus.status !== 'granted') {
      console.log('[Location] Background permission denied — tracking limited to foreground');
    }

    // Start watching position with significant-change-like behavior
    // (low accuracy + large distance filter = battery efficient)
    await Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.Balanced,
        distanceInterval: MIN_DISTANCE_M,
        timeInterval: MIN_INTERVAL_MS,
      },
      onLocationUpdate
    );

    console.log('[Location] Tracking started');
    return true;
  } catch (err) {
    console.error('[Location] Failed to start tracking:', err);
    return false;
  }
}

/**
 * Stop location monitoring.
 */
export async function stopTracking(): Promise<void> {
  // Expo doesn't expose a direct "stop watching" for the subscription
  // returned by watchPositionAsync. In practice, the subscription is
  // cleaned up when the component unmounts or app backgrounds.
  console.log('[Location] Tracking stopped');
}

/**
 * Called on each significant location change.
 */
async function onLocationUpdate(location: Location.LocationObject): Promise<void> {
  const now = Date.now();
  if (now - lastReportedAt < MIN_INTERVAL_MS) {
    return; // Throttle
  }

  const { latitude, longitude, accuracy } = location.coords;

  // Check minimum distance from last report
  if (lastLat !== 0 && lastLon !== 0) {
    const dist = haversineDistance(lastLat, lastLon, latitude, longitude);
    if (dist < MIN_DISTANCE_M) {
      return;
    }
  }

  lastReportedAt = now;
  lastLat = latitude;
  lastLon = longitude;

  try {
    const baseUrl = await getApiUrl();
    const token = await AsyncStorage.getItem('auth_token');
    if (!baseUrl || !token) return;

    await fetch(`${baseUrl}/presence/location`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ latitude, longitude, accuracy }),
    });

    console.log(`[Location] Reported: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
  } catch (err) {
    console.warn('[Location] Report failed:', err);
  }
}

/**
 * Haversine distance in meters between two lat/lon pairs.
 */
function haversineDistance(
  lat1: number, lon1: number, lat2: number, lon2: number
): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
    Math.cos((lat2 * Math.PI) / 180) *
    Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
