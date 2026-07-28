/** @type {import("@bacons/apple-targets").Config} */

/**
 * Sara Watch — companion watchOS app (plan §7.1).
 *
 * Deliberately a NEW target rather than a change to `targets/widget`: the
 * widget is an iOS app-extension in the phone's process family, and converting
 * it would take the Live Activities down with it.
 *
 * `@bacons/apple-targets` maps `type: "watch"` onto a real watchOS application
 * product — SDKROOT=watchos, TARGETED_DEVICE_FAMILY=4, an "Embed Watch
 * Content" phase on the iOS app, and INFOPLIST_KEY_WKCompanionAppBundleIdentifier
 * wired to the main target — so the companion relationship comes from
 * reproducible config, not a hand-edited Xcode project (§7.1).
 *
 * The plugin also registers this target with EAS credential discovery, which
 * is what lets the first build create the Watch bundle identifier and its
 * provisioning profile from Linux (§12.5) without anyone opening the Apple
 * Developer portal first.
 *
 * Deployment target is watchOS 10.0: `startMirroringToCompanionDevice` and
 * `sendToRemoteWorkoutSession` — the whole cross-device transport (§7.4) —
 * are watchOS 10 APIs. Raise it only if David's Watch is newer and something
 * actually needs it.
 */
module.exports = {
  type: "watch",
  name: "SaraWatch",
  displayName: "Sara",
  // Leading dot = appended to the main app id -> cloud.avery.sara-ios.watch.
  bundleIdentifier: ".watch",
  icon: "../../assets/icon.png",
  deploymentTarget: "10.0",
  colors: {
    $accent: "#14b8a6",
  },
  frameworks: ["SwiftUI", "HealthKit", "WatchKit", "WatchConnectivity"],
  entitlements: {
    // The Watch owns the primary HKWorkoutSession, so it needs its own
    // HealthKit entitlement — the phone's does not cover it (§2.5).
    "com.apple.developer.healthkit": true,
    "com.apple.developer.healthkit.background-delivery": true,
  },
};
