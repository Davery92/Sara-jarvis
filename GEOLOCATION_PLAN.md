# Geolocation for Sara — Location Awareness + Location-Triggered Reminders

## Context

Sara currently has no idea where David is when he's away from home (HA covers home/not_home only). The goal: Sara knows David's location ("she knows where I am") and can act on it — "when I leave this client site, remind me to go to the store", "when I get home remind me to do X".

**What already exists (found during exploration):**
- `ios-app/src/services/locationTracking.ts` — a written-but-**orphaned** significant-location service (never imported, posts to wrong path `/presence/location`, `stopTracking()` is a no-op). `expo-location@19` + `expo-task-manager@14` are already in package.json, but app.json has **no** location plugin, no `NSLocation*` keys, no `location` background mode — so background/geofencing is not configured.
- `backend/app/routes/presence.py:203` — `POST /location` endpoint exists: classifies coords against Neo4j `PKG_Place` nodes (<500m) and feeds the activity state machine. **Bug**: both `/location` and `/desktop-activity` call `update_fields(user_id, {dict})` positionally, but the signature is `update_fields(user_id, source="unknown", **kwargs)` → the dict lands in `source`, kwargs is empty, function returns immediately. The context write has always been a silent no-op. Also `UnifiedContextSnapshot` has no location fields at all.
- Reminders fire via Celery `notification_predispatch` (`app/tasks/inproc_schedulers.py:147`) → `send_push_to_user` (`app/routes/push_tokens.py:699`), which already sends `priority="high"` + `_bypass_attention=True` (so it actually buzzes despite the attention queue).
- Standing orders (`standing_order_service.py`) already support a `presence` trigger_type, evaluated from `reactive_engine.py` on HA events.
- Event bus (`event_bus.py`) → `SalienceSubscriber` (explicit event-type subscriptions) → deliberation. New event types must be registered in `salience_subscriber.py` + scored in `salience.py`.
- iOS has the full pattern to copy: `backgroundHealthSync.ts` (TaskManager + background fetch), post-login init in `AuthenticatedOverlays.tsx`, push categories in `pushNotifications.ts`, Switch toggles in `src/screens/settings/SettingsScreen.tsx`.
- Migrations: alembic (latest `079_attention_policy_snapshot.py`); periodic jobs are seeded as `scheduled_job` rows in migrations (pattern: `070_reminder_event_link.py`).

## Architecture

**Hybrid geofencing** — iOS native region monitoring is primary (wakes the app on enter/exit even when killed, ≤20 regions), server-side transition detection is the backup and powers general awareness:

```
iPhone
 ├─ startLocationUpdatesAsync (TaskManager, significant-change tier)
 │    └─ POST /api/location/report ──────────────┐
 └─ startGeofencingAsync (regions synced from backend)
      └─ POST /api/location/geofence-event ──────┤
                                                 ▼
                              backend location_service
                               ├─ classify coords → known_place (SQL haversine, PKG fallback)
                               ├─ detect enter/exit transitions (Redis last-place state)
                               ├─ update unified context (current_place, at_place_since, …)
                               ├─ feed activity_state_machine (home/gym/away signals)
                               ├─ emit LOCATION_PLACE_ENTERED/EXITED → salience → deliberation
                               ├─ fire matching location_trigger rows → Reminder + push
                               └─ evaluate standing orders (trigger_type='presence')
```

Places live in Postgres (`known_place`) as system of record; each save is mirrored to PKG via the existing fire-and-forget `personal_kg.upsert_fact()` so the semantic layer knows them too.

---

## Phase 1 — Backend foundation

**New migration `alembic/versions/080_location_awareness.py`:**
- `known_place`: id, user_id, name, place_type (home/work/gym/client_site/store/other), latitude, longitude, radius_m (default 150), source (user/chat/learned), visit_count, last_seen_at, is_active, created_at.
- `location_trigger`: id, user_id, trigger_on ('enter'|'exit'), place_id FK nullable, ad-hoc latitude/longitude/radius_m (for "this client site" with no saved place), label (place name snapshot), reminder_title, reminder_description, recurring bool (default false), cooldown_minutes (default 60, for recurring), status ('armed'|'fired'|'cancelled'|'expired'), expires_at (default now+24h for one-shots, NULL for recurring), last_fired_at, created_at.
- `location_event`: id, user_id, latitude, longitude, accuracy, place_id nullable, event_type ('report'|'enter'|'exit'), source ('ios_significant'|'ios_geofence'|'manual'), created_at. (History for future auto-place-discovery; index on user_id+created_at.)
- Seed `scheduled_job` row: hourly `location_trigger_expiry` task (marks past-`expires_at` armed triggers expired).

**New `app/models/location.py`** — KnownPlace, LocationTrigger, LocationEvent (follow `reminder.py` style, `extend_existing=True`).

**New `app/services/location_service.py`** — the single brain:
- `classify(lat, lon)` → nearest active `known_place` within radius (SQL haversine; keep the existing PKG_Place Neo4j query as fallback).
- `process_report(user_id, lat, lon, accuracy, source)` → log `location_event`, classify, compare to last place (Redis key `sara:location:last_place:{user_id}`), on transition call `_handle_transition(enter/exit, place)`; always `update_fields(user_id, source="location", current_place=…, at_place_since=…, last_location_at=…)`.
- `_handle_transition()` → emit `LOCATION_PLACE_ENTERED/EXITED` on the event bus, feed `activity_state_machine` (home_arrival / gym_arrival / left_home → AWAY), fire triggers, evaluate standing orders (`standing_order_service.evaluate_trigger("presence", …)`).
- `fire_matching_triggers(user_id, event, place, lat, lon)` → match armed `location_trigger` rows (by place_id, or haversine vs ad-hoc coords); for each match: create a `Reminder` (due now) and push immediately via `send_push_to_user` (same payload shape as `_dispatch_reminder` in `inproc_schedulers.py`); one-shots → status='fired'; recurring → bump `last_fired_at`, respect cooldown.
- `geofence_payload(user_id)` → regions the phone should monitor: all active places + ad-hoc armed triggers (cap 18, prioritize armed triggers, then home, then most-visited).

**New `app/routes/location.py`** (register in `main_simple.py` next to the presence router, outside try/except per gotcha):
- `POST /api/location/report` → `process_report` (this is the new canonical endpoint).
- `POST /api/location/geofence-event` `{region_id, event: enter|exit, latitude, longitude}` → `_handle_transition` directly (trusted signal, no distance re-check).
- `GET /api/location/geofences` → `geofence_payload` (iOS syncs regions from this).
- `GET/POST/PATCH/DELETE /api/location/places` — CRUD; POST mirrors to PKG via `upsert_fact`.
- `GET /api/location/triggers`, `DELETE /api/location/triggers/{id}`.

**Fixes/edits to existing files:**
- `presence.py`: fix both broken `update_fields(user_id, {dict})` calls → keyword form; make old `POST /location` delegate to `location_service.process_report` (keeps any existing callers working).
- `unified_context.py`: add snapshot fields `current_place`, `current_place_type`, `at_place_since`, `last_location_at`, `location_latitude`, `location_longitude`. Add `current_place` to `NOTABLE_FIELDS` in `context_writer.py` (so arrivals land in `changes_since_last_chat`).
- `event_bus.py`: add `LOCATION_PLACE_ENTERED = "location.place_entered"`, `LOCATION_PLACE_EXITED = "location.place_exited"`.
- `salience_subscriber.py`: subscribe to both; `salience.py`: score them (arrivals/exits ~1.0 — meaningful but not auto-deliberation alone; home arrival after long absence higher).
- `app/tasks/inproc_schedulers.py` (or new `app/tasks/location.py`): `location_trigger_expiry` Celery task.

## Phase 2 — Chat tools (the UX)

**New `app/tools/location.py`**, registered in `registry.py`:
- `location_reminder_create(reminder_title, trigger_on: enter|exit, place: string, description?, recurring?)` — resolves `place`: "here"/"this place"/"this client site" → current coords from unified snapshot (label from ongoing calendar event's title/location if one is active, else classified place, else "current location"); otherwise fuzzy-match `known_place` by name; if no match and we have current coords, create ad-hoc trigger. One-shot by default with 24h expiry; `recurring=true` for "every time I get home…".
- `location_reminder_list` / `location_reminder_cancel`.
- `places_save(name, place_type?, use_current_location=true)` — "remember this place as Jones' office"; `places_list`, `places_delete`.
- Update the system prompt tool guidance in `main_simple.py` (where other tools are described) so Sara knows she can do this, and knows David's current place comes from the snapshot.

## Phase 3 — Sara knows where you are (context injection)

- `main_simple.py` `_fetch_personality` block (~line 8683): when snapshot has `current_place`, add a line to the activity context: `Location: Jones Client Site (client_site, arrived 45m ago)` — or `away from home since HH:MM` when moving/unclassified.
- `deliberation_prompt.py` (~line 56, next to Activity/Room): same location line, so autonomous deliberation can reason about location ("David just left a client site at 4pm…").

## Phase 4 — iOS pipeline

- `app.json`: add `expo-location` plugin with `locationAlwaysAndWhenInUsePermission` text, `isIosBackgroundLocationEnabled: true`; add `"location"` to `UIBackgroundModes`. (Requires a new dev-client build — native config change.)
- Rewrite `src/services/locationTracking.ts`:
  - Replace `watchPositionAsync` with **TaskManager-defined** `Location.startLocationUpdatesAsync(LOCATION_TASK, { accuracy: Balanced, distanceInterval: 250, deferredUpdatesInterval: 5min, pausesUpdatesAutomatically: true, showsBackgroundLocationIndicator: false })` — runs when app is killed; keep the existing haversine/interval throttle; POST to `/api/location/report` via the `apiClient` Bearer pattern.
  - Add `Location.startGeofencingAsync(GEOFENCE_TASK, regions)` with regions from `GET /api/location/geofences` (region `identifier` = place/trigger id). On enter/exit → POST `/api/location/geofence-event`; on network failure, fall back to a local notification (`Notifications.scheduleNotificationAsync`) with the trigger's reminder title so it never silently drops.
  - `resyncGeofences()` — called post-login, on app foreground, and from the existing background health sync task (piggyback, no new background task needed).
  - Fix `stopTracking()` to actually call `Location.stopLocationUpdatesAsync` / `stopGeofencingAsync`.
- `AuthenticatedOverlays.tsx`: init location tracking post-login (same spot as `registerBackgroundHealthSync`), gated on the AsyncStorage toggle.
- `src/screens/settings/SettingsScreen.tsx`: add "Location awareness" Switch (existing Switch pattern, ~line 843) wired to `setLocationTrackingEnabled` + permission request flow.

## Phase 5 — Verify

1. Backend: rebuild + restart via `docker compose -f docker-compose.dev.yml build backend && up -d backend` (deployed-code-lags gotcha), run alembic migration, check `/health`.
2. Simulate with curl (mint JWT as in the webapp-screenshot pattern):
   - `POST /api/location/places` (create "home" + a "client site" at test coords).
   - Chat: "when I leave this client site remind me to go to the store" → verify `location_trigger` row (tool call path).
   - `POST /api/location/report` inside client-site radius, then a report 1km away → verify: exit transition detected, reminder created, push logged in `notification_log`, trigger status='fired', `LOCATION_PLACE_EXITED` in observation/agent_run_log, snapshot fields updated (`read_snapshot`).
   - `POST /api/location/geofence-event` directly → same firing path.
   - Recurring trigger: two enter events inside cooldown → fires once.
3. Chat context: send a chat message, confirm the location line appears in the personality/activity context (debug logs or `/debug` endpoints).
4. iOS: needs a new dev-client build (native config changed) — build via `npx expo prebuild` / EAS as usual for this project; then on-device: enable toggle, grant Always permission, verify reports arrive and a geofence exit fires a push. (Device testing is on David; simulator can fake locations via Features→Location.)

## Explicitly deferred (later enhancements)
- Auto-place discovery from `location_event` clusters (nightly consolidation candidate).
- Geocoding calendar-event location strings → pre-armed geofences before meetings.
- "Leave now for your next meeting" travel-time nudges.
- Webapp Places management page.
