# iOS System Integration — Siri, Widgets, Live Activities (P3)

Adds three "flagship assistant" iOS capabilities. All compile via EAS; none can be
verified from a dev container, so this doc covers the one-time setup and what to check
after the first build.

## What was added

| Feature | Where |
|---|---|
| **Siri / App Intents** — "Hey Siri, Ask Sara…" | `plugins/withSaraAppIntents.js` (injects `SaraAppIntents.swift` into the **main** target) → opens `sara://ask?q=…` → `src/services/siriDeepLink.ts` routes it into chat as a quick-reply |
| **Home + Lock Screen widgets** | `targets/widget/` (`@bacons/apple-targets`): `SaraWidget.swift` (systemSmall/medium + accessory families). Data via App Group, written by `src/services/widgetBridge.ts` → `modules/sara-native` |
| **Live Activities** (timer countdown) | `targets/widget/SaraLiveActivity.swift` (lock screen + Dynamic Island) + `modules/sara-native` (ActivityKit control) wired into `src/context/TimerContext.tsx` |

**Local native module** `modules/sara-native/` exposes to JS: `setWidgetData`, `reloadWidgets`,
`areActivitiesEnabled`, `startTimerActivity`, `endTimerActivity`, `endAllActivities`.

**App Group:** `group.cloud.avery.sara-ios` (declared in `app.json` entitlements, the widget
target's `expo-target.config.js`, and the native module). The `SaraTimerAttributes` struct is
**duplicated** in `modules/sara-native/ios/` and `targets/widget/` — ActivityKit matches by type
name across the two modules. Keep them identical.

## One-time setup (required before the first build)

1. **Install the new deps** (lockfile changed):
   ```bash
   cd ios-app
   npm install
   npx expo install expo-build-properties   # aligns the version to SDK 54
   ```
2. **Apple Team ID** — `@bacons/apple-targets` needs it to sign the widget extension. Either:
   - set `APPLE_TEAM_ID` in your EAS build env / `eas.json`, or
   - add `["@bacons/apple-targets", { "appleTeamId": "XXXXXXXXXX" }]` in `app.json`.
3. **Register the App Group** in the Apple Developer portal and add it to BOTH App IDs
   (`cloud.avery.sara-ios` and `cloud.avery.sara-ios.widget`). With EAS managed credentials,
   `eas build` will usually create the extension's App ID + profile and prompt to enable the
   capability — accept it. (App Groups are the most common first-build snag.)
4. **Build:** `eas build --platform ios --profile preview` (or development/production).

## Verify after the build

- **Siri:** Settings → Siri & Search → "Ask Sara" should appear. Say "Ask Sara" → it should
  open the app, prompt for your question, and the chat should auto-send it.
- **Widget:** long-press home screen → add "Sara". Add a lock-screen accessory widget too.
  It should show the emotional-state emoji + next event; foreground the app to refresh.
- **Live Activity:** start a timer → a lock-screen banner + Dynamic Island countdown should
  appear and tick down on its own; stopping the timer ends it.

## Known risks / first-build watch-list

- **App Intents in the main target** (`withSaraAppIntents.js`) adds `SaraAppIntents.swift` via
  `addSourceFile(..., { target: getFirstTarget().uuid }, group)`. If Siri shortcuts don't show,
  confirm the file landed in the **app** target (not the widget) in the generated Xcode project.
- **`getFirstTarget()`** assumes the main app is target #0; verify if the build can't find the
  intents.
- **Deployment target 16.2** is set via `expo-build-properties` (Live Activities need 16.1+).
- The widget/Live-Activity SwiftUI uses iOS 16.2/17 APIs guarded with `#available` /
  `if #available`; if the extension fails to compile, check those guards first.
- `sara://ask` deep link: handled by `siriDeepLink.ts` listener; React Navigation's `linking`
  config ignores the unmapped `ask` host, so there's no routing conflict.
