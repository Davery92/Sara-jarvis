/**
 * universalCapture — flushes whatever the share extension queued into the
 * real content inbox (SARA_ALIVE §5.2).
 *
 * The extension (targets/share/ShareViewController.swift) has no live
 * session and can't call the backend itself, so it just stashes items in the
 * App Group and dismisses. This is the other half: read & clear that queue
 * (consumePendingShares — mirrors consumePendingSiriPrompt exactly) and post
 * each item through the existing content-inbox endpoints, using this app's
 * real, live session.
 *
 * Deliberately NOT the smart "kernel files it as a note/task/event" version
 * the felt-layer plan ultimately wants — that needs real backend classification
 * work. This closes the actual gap: capture from any app, reliably, landing
 * somewhere real (today: the content inbox) instead of nowhere.
 */
// expo-file-system v19's default export dropped cacheDirectory/writeAsStringAsync
// for a new File/Directory class API; /legacy keeps the simple string-path API
// this one-shot temp-file write just needs.
import * as FileSystem from 'expo-file-system/legacy';
import { consumePendingShares, type PendingShare } from '../../modules/sara-native';
import { apiClient } from './api';

async function postImage(share: PendingShare): Promise<void> {
  if (!share.content_base64) return;
  const tmpPath = `${FileSystem.cacheDirectory}capture_${Date.now()}.jpg`;
  await FileSystem.writeAsStringAsync(tmpPath, share.content_base64, {
    encoding: FileSystem.EncodingType.Base64,
  });
  try {
    await apiClient.uploadImageToInbox(tmpPath);
  } finally {
    await FileSystem.deleteAsync(tmpPath, { idempotent: true });
  }
}

export async function flushPendingCaptures(): Promise<void> {
  let shares: PendingShare[] = [];
  try {
    shares = consumePendingShares();
  } catch {
    return;
  }
  if (shares.length === 0) return;

  for (const share of shares) {
    try {
      if (share.type === 'url') {
        await apiClient.shareToInbox(share.content, share.note || undefined);
      } else if (share.type === 'text') {
        await apiClient.shareTextToInbox(share.content, share.note || undefined);
      } else if (share.type === 'image') {
        await postImage(share);
      }
    } catch (e) {
      // Best-effort: one bad item in the queue shouldn't block the rest, and
      // there's no user-facing retry surface for a background flush — the
      // item is already gone from the App Group queue either way.
      console.warn('[universalCapture] failed to post a captured item:', e);
    }
  }
}
