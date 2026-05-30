/** @type {import("@bacons/apple-targets").Config} */
module.exports = {
  type: "widget",
  icon: "../../assets/icon.png",
  colors: {
    $accent: "#0d7ff2",
    $widgetBackground: { light: "#ffffff", dark: "#18181b" },
  },
  // Must match the App Group declared in app.json entitlements and the native module.
  entitlements: {
    "com.apple.security.application-groups": ["group.cloud.avery.sara-ios"],
  },
  frameworks: ["SwiftUI", "WidgetKit", "ActivityKit"],
  deploymentTarget: "16.2",
};
