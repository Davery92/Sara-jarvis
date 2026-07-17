import WidgetKit
import SwiftUI

/// Entry point for the widget extension: the home/lock-screen widget plus the
/// timer Live Activity.
@main
struct SaraWidgetBundle: WidgetBundle {
  var body: some Widget {
    SaraStatusWidget()
    if #available(iOS 16.2, *) {
      SaraTimerLiveActivity()
      SaraEventLiveActivity()
    }
  }
}
