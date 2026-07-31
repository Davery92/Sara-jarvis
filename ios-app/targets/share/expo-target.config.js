/** @type {import("@bacons/apple-targets").Config} */
module.exports = {
  type: "share",
  icon: "../../assets/icon.png",
  // Must match the App Group declared in app.json entitlements and the native module.
  entitlements: {
    "com.apple.security.application-groups": ["group.cloud.avery.sara-ios"],
  },
  deploymentTarget: "16.2",
};
