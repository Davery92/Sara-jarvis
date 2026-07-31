import UIKit
import Social
import MobileCoreServices
import UniformTypeIdentifiers

/// Universal capture (SARA_ALIVE §5.2): the share-sheet entry point.
///
/// This extension is a separate process from the main app with no live
/// session — same constraint the "Ask Sara" Siri intent already solves.
/// Same fix: write the shared item into the App Group as a small pending
/// queue, dismiss immediately, and let the main app (which does have a live
/// session) flush the queue on next foreground via
/// `SaraNative.consumePendingShares()` — mirrors `consumePendingSiriPrompt`.
///
/// Kept deliberately dumb: no network call from inside the extension (tight
/// memory/time budget, no auth), no kernel filing decision here — that's the
/// main app's job once it can actually call the backend.
class ShareViewController: SLComposeServiceViewController {
  static let appGroup = "group.cloud.avery.sara-ios"
  static let pendingKey = "pending_shares"
  static let maxQueued = 20

  override func isContentValid() -> Bool {
    return true
  }

  override func didSelectPost() {
    let comment = (contentText ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
    let group = DispatchGroup()
    var results: [[String: Any]] = []
    let lock = NSLock()

    for item in items {
      for provider in (item.attachments ?? []) {
        if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
          group.enter()
          provider.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) { data, _ in
            defer { group.leave() }
            guard let url = data as? URL else { return }
            lock.lock(); results.append(["type": "url", "content": url.absoluteString, "note": comment]); lock.unlock()
          }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
          group.enter()
          provider.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { data, _ in
            defer { group.leave() }
            guard let text = data as? String, !text.isEmpty else { return }
            lock.lock(); results.append(["type": "text", "content": text, "note": comment]); lock.unlock()
          }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
          group.enter()
          provider.loadItem(forTypeIdentifier: UTType.image.identifier, options: nil) { data, _ in
            defer { group.leave() }
            if let savedPath = Self.persistImage(data) {
              lock.lock(); results.append(["type": "image", "content": savedPath, "note": comment]); lock.unlock()
            }
          }
        }
      }
    }

    group.notify(queue: .main) {
      // Plain-text-only share with a comment but no matching provider (rare) —
      // fall back to the typed comment itself so nothing is silently dropped.
      if results.isEmpty && !comment.isEmpty {
        results.append(["type": "text", "content": comment, "note": ""])
      }
      Self.enqueue(results)
      self.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }
  }

  override func configurationItems() -> [Any]! {
    return []
  }

  /// Copies image data into the App Group's shared container so the main app
  /// (a different process) can read it after this extension is torn down.
  /// Returns the path relative to the container, or nil on failure.
  private static func persistImage(_ data: Any?) -> String? {
    guard let container = FileManager.default.containerURL(
      forSecurityApplicationGroupIdentifier: appGroup
    ) else { return nil }

    let capturesDir = container.appendingPathComponent("pending_captures", isDirectory: true)
    try? FileManager.default.createDirectory(at: capturesDir, withIntermediateDirectories: true)

    let filename = "\(UUID().uuidString).jpg"
    let dest = capturesDir.appendingPathComponent(filename)

    var imageData: Data? = nil
    if let url = data as? URL, let d = try? Data(contentsOf: url) {
      imageData = d
    } else if let image = data as? UIImage {
      imageData = image.jpegData(compressionQuality: 0.85)
    } else if let d = data as? Data {
      imageData = d
    }
    guard let bytes = imageData else { return nil }
    do {
      try bytes.write(to: dest)
      return "pending_captures/\(filename)"
    } catch {
      return nil
    }
  }

  /// Appends to the pending-shares queue (capped so a burst of shares before
  /// the app is ever opened can't grow this unbounded).
  private static func enqueue(_ newItems: [[String: Any]]) {
    guard !newItems.isEmpty, let defaults = UserDefaults(suiteName: appGroup) else { return }
    var queue = (defaults.array(forKey: pendingKey) as? [[String: Any]]) ?? []
    let stamped = newItems.map { item -> [String: Any] in
      var i = item
      i["queued_at"] = ISO8601DateFormatter().string(from: Date())
      return i
    }
    queue.append(contentsOf: stamped)
    if queue.count > maxQueued {
      queue = Array(queue.suffix(maxQueued))
    }
    defaults.set(queue, forKey: pendingKey)
  }
}
