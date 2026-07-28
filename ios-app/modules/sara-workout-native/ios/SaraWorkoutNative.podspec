Pod::Spec.new do |s|
  s.name           = 'SaraWorkoutNative'
  s.version        = '1.0.0'
  s.summary        = 'Sara multidevice workout: HealthKit mirroring + coaching audio'
  s.description    = <<~DESC
    Owns the iPhone side of the Apple multidevice workout lifecycle — launching
    and mirroring the Watch workout session, relaying versioned messages — plus
    the AVAudioSession coordinator that ducks other audio for Sara's spoken
    coaching. Deliberately separate from SaraNative: that module's WidgetKit /
    ActivityKit work has no lifecycle, and this one is nothing but lifecycle.
  DESC
  s.author         = 'Sara'
  s.homepage       = 'https://sara.avery.cloud'
  # HKWorkoutSession mirroring (startWatchApp + workoutSessionMirroringStartHandler)
  # is iOS 17+; the app targets iOS 18 anyway.
  s.platforms      = { :ios => '17.0' }
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.frameworks = 'HealthKit', 'AVFoundation', 'WatchConnectivity'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
  s.swift_version = '5.9'

  s.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
