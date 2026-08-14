# Sara iPhone and Apple Watch Build/Update Runbook

Date: 2026-07-26

Purpose: repeatable instructions for updating Sara on David's iPhone and Apple Watch without repeating the initial Apple-account, device-trust, identifier, and provisioning setup.

This runbook contains no Apple ID or Mac passwords. Never put either password in this repository, a shell script, an SSH command, or an EAS environment variable.

## 1. Current Build Topology

- Source of truth: /home/david/jarvis/ios-app on the Ubuntu server.
- Mac build workspace: /Users/david/sara-ios-build.
- Mac SSH user and stable Tailscale address: david@100.69.217.66.
- SSH key on Ubuntu: /home/david/.ssh/sara_agent.
- Current Xcode: /Applications/Xcode-27-beta-4.app.
- iPhone bundle: cloud.avery.sara-ios.
- Widget bundle: cloud.avery.sara-ios.widget.
- Watch bundle: cloud.avery.sara-ios.watch.
- Apple team: 7MAK5MEJ6W.
- The Watch app is embedded in the Sara iPhone app and may also be installed directly during development.

The repository must remain the source of truth. Do not make permanent changes only inside the generated Mac ios directory. Encode native project changes in app.json, targets/watch, a local Expo module, or an Expo config plugin so a clean prebuild and EAS Build reproduce them.

## 2. Decide What Kind of Update This Is

| Change | Required deployment |
| --- | --- |
| Backend-only Python/database change | Deploy/restart backend; no phone build |
| React Native TypeScript, text, or bundled asset | Full build today |
| Watch Swift or Watch UI | Full iPhone/Watch build |
| Local native module Swift or podspec | Full iPhone/Watch build |
| app.json, Expo plugin, entitlement, capability, target, or Info.plist | Full iPhone/Watch build |
| Expo SDK, React Native, CocoaPod, or native dependency | Full iPhone/Watch build |

This project does not currently configure expo-updates with an updates URL and runtime version. Therefore, do not use eas update for normal releases yet. Even after it is configured, EAS Update can only replace compatible JavaScript and assets; it can never replace Watch or other native code.

## 3. Before Every Binary Build

1. Confirm the intended Git branch and inspect the working tree:

~~~bash
cd /home/david/jarvis
git branch --show-current
git status --short
~~~

2. Preserve unrelated user work. Do not reset, clean, or discard a dirty worktree merely to produce a build.

3. Increment the iOS build number for distributable updates. Keep the marketing version in ios-app/app.json aligned with the release. Direct development installs can overwrite the same build, but unique build numbers make iPhone and Watch update behavior reliable.

4. Run the relevant backend and TypeScript tests before syncing to the Mac.

## 4. Sync Ubuntu Source to the Mac

Run from the Ubuntu server:

~~~bash
cd /home/david/jarvis
rsync -az --delete \
  --exclude='.git/' \
  --exclude='node_modules/' \
  --exclude='ios/' \
  --exclude='.expo/' \
  --exclude='DerivedData/' \
  --exclude='build-sara-*.sh' \
  --exclude='*.log' \
  -e 'ssh -i /home/david/.ssh/sara_agent -o IdentitiesOnly=yes' \
  ios-app/ david@100.69.217.66:/Users/david/sara-ios-build/
~~~

The exclusions protect Mac dependencies, generated Xcode output, build artifacts, and the local interactive build scripts from --delete.

Prefer the stable Tailscale identity over the changing LAN address. Find it
from the Ubuntu server with:

~~~bash
tailscale status | grep davids-macbook-air
~~~

If package.json or the lockfile changed, install dependencies on the Mac:

~~~bash
ssh -i /home/david/.ssh/sara_agent \
  -o IdentitiesOnly=yes \
  david@100.69.217.66 \
  'cd /Users/david/sara-ios-build && npm install'
~~~

## 5. Regenerate the Native Project

Run a clean Expo prebuild after syncing. This proves that all Watch, scene-lifecycle, entitlement, and module changes are reproducible:

~~~bash
ssh -i /home/david/.ssh/sara_agent \
  -o IdentitiesOnly=yes \
  david@100.69.217.66 \
  'export DEVELOPER_DIR=/Applications/Xcode-27-beta-4.app/Contents/Developer;
   export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin;
   cd /Users/david/sara-ios-build &&
   npx expo prebuild -p ios --clean'
~~~

Prebuild normally runs CocoaPods. If native module source files were copied after prebuild or the Pods project is stale, run:

~~~bash
ssh -i /home/david/.ssh/sara_agent \
  -o IdentitiesOnly=yes \
  david@100.69.217.66 \
  'export DEVELOPER_DIR=/Applications/Xcode-27-beta-4.app/Contents/Developer;
   export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin;
   cd /Users/david/sara-ios-build &&
   npx pod-install ios'
~~~

## 6. Build Locally for the Physical Watch and iPhone

The current interactive build script is:

    /Users/david/sara-ios-build/build-sara-watch-local.sh

Run it in the visible Mac Terminal, not a background SSH shell:

~~~bash
/Users/david/sara-ios-build/build-sara-watch-local.sh
~~~

When macOS asks to unlock the login keychain, enter the Mac login password. Do not enter either Apple ID password. The script builds the SaraWatch scheme in Release configuration; that scheme also builds and embeds the parent Sara iPhone app and widget.

Expected result:

    ** BUILD SUCCEEDED **
    SARA_RELEASE_BUILD_SUCCEEDED

Expected artifacts:

    /Users/david/sara-ios-build/DerivedData/Build/Products/Release-iphoneos/Sara.app
    /Users/david/sara-ios-build/DerivedData/Build/Products/Release-watchos/SaraWatch.app

If Xcode times out waiting for the physical Watch destination, build a signed
generic watchOS product instead. This still builds the parent iPhone app,
widget, and embedded Watch companion; device connectivity is only needed for
the later install:

~~~bash
export DEVELOPER_DIR=/Applications/Xcode-27-beta-4.app/Contents/Developer
cd /Users/david/sara-ios-build
xcodebuild \
  -workspace ios/Sara.xcworkspace \
  -scheme SaraWatch \
  -configuration Release \
  -destination 'generic/platform=watchOS' \
  -derivedDataPath DerivedData \
  -allowProvisioningUpdates \
  IPHONEOS_DEPLOYMENT_TARGET=18.0 \
  build
~~~

Run this fallback in the visible Mac Terminal. A background SSH-launched build
can compile successfully but fail signing with `errSecInternalComponent`
because it cannot use the login keychain's private key.

## 7. Install the Update

Keep the iPhone unlocked and connected to the Mac with Apple's USB-C cable. Keep the Watch unlocked, in Developer Mode, and connected to Wi-Fi when a direct Watch install is needed.

List current CoreDevice identifiers:

~~~bash
export DEVELOPER_DIR=/Applications/Xcode-27-beta-4.app/Contents/Developer
xcrun devicectl list devices
~~~

Do not permanently assume the identifiers below; confirm them in the list. At the time this runbook was written:

    iPhone: 88AF88BF-78E9-529F-91F8-4B44D9DAF10D
    Watch:  C3F1E1CA-FCA1-55DF-9D78-3D03E4993BEA

Install the parent app:

~~~bash
xcrun devicectl device install app \
  --device 88AF88BF-78E9-529F-91F8-4B44D9DAF10D \
  /Users/david/sara-ios-build/DerivedData/Build/Products/Release-iphoneos/Sara.app
~~~

The parent contains the Watch companion. With automatic Watch app installation enabled, watchOS may update it automatically. If it does not, use the Watch app on the iPhone and press Update or Install for Sara.

For development, when the Watch reports connected in devicectl, install it directly:

~~~bash
xcrun devicectl device install app \
  --device C3F1E1CA-FCA1-55DF-9D78-3D03E4993BEA \
  /Users/david/sara-ios-build/DerivedData/Build/Products/Release-watchos/SaraWatch.app
~~~

The direct Watch step is optional for normal distribution and useful for immediate testing.

## 8. Launch and Verify

Launch Sara on the iPhone:

~~~bash
xcrun devicectl device process launch \
  --device 88AF88BF-78E9-529F-91F8-4B44D9DAF10D \
  --terminate-existing \
  cloud.avery.sara-ios
~~~

Launch Sara on the Watch:

~~~bash
xcrun devicectl device process launch \
  --device C3F1E1CA-FCA1-55DF-9D78-3D03E4993BEA \
  --terminate-existing \
  cloud.avery.sara-ios.watch
~~~

Capture a Watch screenshot:

~~~bash
xcrun devicectl device capture screenshot \
  --device C3F1E1CA-FCA1-55DF-9D78-3D03E4993BEA \
  --destination /Users/david/sara-ios-build/watch-verification.png
~~~

Minimum acceptance checks:

1. Sara stays open on the iPhone.
2. Sara stays open on the Watch.
3. The Watch shows the current catalog after the phone opens.
4. A rest day does not relabel the newest template as today's workout.
5. Starting from Watch creates one Sara workout and begins HealthKit tracking.
6. The phone recognizes the same active workout.
7. One test set logged on either device appears on the other exactly once.
8. HealthKit and notification permissions remain intact.

## 9. How the Watch's Today Catalog Refreshes

The iPhone is the network owner. It fetches the compact workout catalog from Sara's backend and publishes the latest catalog to the Watch with WatchConnectivity application context:

- after authenticated iPhone startup;
- whenever the iPhone app returns to the foreground.

The Watch caches the catalog so workouts remain available offline. The generated_for_date field prevents an old cached choice from being labeled Today on a later date. Until the phone refreshes, an expired catalog remains usable under Other workouts instead of making a false daily recommendation.

Opening Sara on the iPhone once after the day or plan changes is the guaranteed refresh. A future background-refresh enhancement may reduce that need, but iOS does not guarantee exact background execution at midnight.

## 10. EAS Cloud Build Alternative

Use EAS when a shareable internal IPA is preferred or the physical Mac build is unavailable:

~~~bash
cd /home/david/jarvis/ios-app
eas build --platform ios --profile preview
~~~

Before the first EAS Watch update after the successful Xcode device registration:

1. Run eas credentials --platform ios.
2. Select the SaraWatch target.
3. Regenerate its Ad Hoc provisioning profile.
4. Confirm the profile includes the physical Apple Watch UDID, not only the paired iPhone.
5. Then run the preview build.

EAS may require the Apple Developer account holder to authenticate or complete two-factor authentication when credentials expire or must be regenerated. It should not require that login for every ordinary build while valid credentials remain stored.

Install the resulting iPhone artifact from its EAS link. The embedded companion then appears as an update or install in the iPhone Watch app.

If Watch installation reaches 100 percent and returns to Install, inspect the Watch target's embedded provisioning profile first. That symptom previously meant the profile did not contain the physical Watch.

## 11. Signing and Device Lifecycle

The following setup is not repeated for every update:

- bundle identifier registration;
- HealthKit capability registration;
- Developer Mode;
- iPhone and Mac trust;
- Apple Watch and Mac trust;
- Apple team selection;
- SSH key installation.

Repeat device registration only for a new iPhone or Watch. Refresh certificates and provisioning profiles when they expire, are revoked, or capabilities change. The previously displayed EAS distribution certificate expires on 2026-12-14, so plan to let EAS regenerate distribution signing near that date. Local Xcode development signing has its own profile lifecycle.

## 12. Troubleshooting

### Signing reports errSecInternalComponent

The Mac login keychain is locked or unavailable to the noninteractive SSH session. Run the build script in the visible Mac Terminal and enter the Mac login password. Never hardcode it.

### Swift types are not found after copying a native module

Verify every file exists under:

    /Users/david/sara-ios-build/modules/sara-workout-native/ios

Then rerun npx pod-install ios or clean prebuild. CocoaPods only compiles source files present when its project is generated.

### Watch remains connecting in devicectl

Wake and unlock the Watch, confirm Developer Mode and Wi-Fi, keep the paired iPhone unlocked and USB-connected, and wait for devicectl list devices to show connected. The embedded companion can still update through the iPhone Watch app when direct developer connectivity is temporarily unavailable.

### Watch installs but asks to open the phone for a plan

Open the newly built Sara iPhone app while authenticated. Confirm the backend returns GET /api/fitness/workout-session/v2/catalog with HTTP 200. Both phone and Watch must use the same native build when the wire contract changes.

### Phone stops launching after an Xcode or SDK update

Run a clean prebuild and confirm withSaraSceneLifecycle remains registered in app.json. Apps built with the iOS 27 SDK require the scene lifecycle generated by that plugin.

## 13. Release Record

For each installed build, record:

- Git commit and branch;
- app version and build number;
- local Mac or EAS build;
- Xcode and SDK version;
- iPhone and watchOS versions;
- signing profile type;
- install result;
- catalog sync result;
- start-from-Watch result;
- start-from-phone result;
- known limitations.

This turns the next update into a controlled release instead of another provisioning investigation.
