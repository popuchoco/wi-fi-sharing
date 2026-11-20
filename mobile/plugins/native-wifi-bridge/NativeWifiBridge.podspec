Pod::Spec.new do |s|
  s.name = 'NativeWifiBridge'
  s.version = '0.1.0'
  s.summary = 'Current Wi-Fi metadata via OS-native APIs'
  s.license = { :type => 'MIT' }
  s.homepage = 'https://github.com/popuchoco/wi-fi-sharing'
  s.author = 'Wi-Fi Sharing'
  s.source = { :path => '.' }
  s.ios.deployment_target = '15.0'
  s.source_files = 'ios/Sources/NativeWifiBridge/**/*.{swift,h,m,c,cc,mm,cpp}'
  s.dependency 'Capacitor'
  s.frameworks = 'NetworkExtension', 'CoreLocation'
  s.swift_version = '5.9'
end
