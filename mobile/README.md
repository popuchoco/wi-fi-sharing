# Native mobile Wi-Fi client

This is a **native Android/iOS app shell**, not a PWA. Capacitor supplies the
native app runtime and a local plugin calls each platform's Wi-Fi APIs.

## OS-first flow

`Capacitor.getPlatform()` identifies Android or iOS before `NativeWifiBridge`
is called. The bridge returns only the current SSID/security metadata. It does
not enumerate saved profiles or return passwords. The Share button hands the
user to Android Wi-Fi Settings, or shows the iOS system-sharing instructions.

This follows OS permissions: Android requests nearby-Wi-Fi permission on Android
13+ and location permission on older versions; iOS requires the Access Wi-Fi
Information entitlement and qualifying location authorization. iOS entitlement
approval is controlled by Apple and is not guaranteed for distribution.

## Build the web bundle

```sh
npm install
npm run build
```

To generate platform projects on a development machine with the native SDKs:

```sh
npx cap add android
npx cap add ios
npx cap sync
```

Android requires Android Studio/JDK. iOS requires macOS and Xcode. The iOS App
target includes the Access Wi-Fi Information entitlement and location-purpose
strings; the entitlement must also be enabled for the App ID/profile used to
sign a distributed build.

## Credential-sharing boundary

The mobile API returns current SSID/security metadata only. It cannot return
saved passwords. Android's Settings QR and iOS's Passwords/Settings share flow
remain OS-owned. A later milestone can add QR import and local QR generation
after user-provided credentials. The Windows local connector has a one-shot
selected-profile UAC helper in the desktop frontend.
