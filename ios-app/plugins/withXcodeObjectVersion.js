/**
 * withXcodeObjectVersion — bump the Xcode project's objectVersion (P3 fix).
 *
 * @bacons/apple-targets v4 attaches the widget extension's Swift sources via an
 * Xcode "synchronized folder" (PBXFileSystemSynchronizedRootGroup). That feature
 * is only honored at objectVersion >= 70 (Xcode 16 writes 77), but Expo SDK 54's
 * iOS template sets objectVersion = 54 — so xcodebuild silently ignores the synced
 * group and the widget extension builds EMPTY (no widget in the gallery).
 *
 * Bumping to 77 makes EAS's Xcode 16 honor the synced folder. Classic groups (the
 * main app) still work at 77, so this is safe. Must run after @bacons/apple-targets.
 */
const { withXcodeProject } = require('@expo/config-plugins')

const TARGET_OBJECT_VERSION = 77

const withXcodeObjectVersion = (config) =>
  withXcodeProject(config, (cfg) => {
    const project = cfg.modResults
    // The xcode lib keeps the parsed pbxproj under .hash.project
    if (project?.hash?.project) {
      project.hash.project.objectVersion = TARGET_OBJECT_VERSION
    }
    return cfg
  })

module.exports = withXcodeObjectVersion
