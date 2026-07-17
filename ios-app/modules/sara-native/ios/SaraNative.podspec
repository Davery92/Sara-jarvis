Pod::Spec.new do |s|
  s.name           = 'SaraNative'
  s.version        = '1.0.0'
  s.summary        = 'Sara iOS system integration: widget data + Live Activities'
  s.description    = 'Writes App Group widget data and controls ActivityKit Live Activities.'
  s.author         = 'Sara'
  s.homepage       = 'https://sara.avery.cloud'
  s.platforms      = { :ios => '16.2' }
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
  s.swift_version = '5.9'

  s.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
