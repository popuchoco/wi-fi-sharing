# Device Wi-Fi Share — Product Plan and OS Integration

## Product outcome

Let a user share a Wi-Fi network already known to the device, without asking them
to retype the SSID and password. The user must identify the target network and
confirm sharing; the app must not silently export every stored credential.

## Required sequence

1. **Detect the client OS** in the client runtime. The browser sends a normalized
   OS hint (`windows`, `macos`, `ios`, `android`, or `linux`). This is routing
   metadata, not a security identity.
2. **Select the matching device adapter.** A system API is called only from a
   process running on the same device/OS. A cloud backend must never pretend its
   own server OS is the visitor's device OS.
3. **Read metadata first.** Query the current connection and list available
   profile names without reading passwords.
4. **Require an explicit network selection and share action.** Read one profile's
   credentials only after that action and only if the OS grants access.
5. **Generate the Wi-Fi QR locally.** Return an in-memory PNG to the UI. Do not
   send credentials to Gemini/A2A, Firestore, logs, or public Cloud Storage.
6. **Share or download only after the user sees the QR.** Hiding the QR or closing
   the page revokes its object URL on a best-effort basis; exported copies remain
   outside the app's control.

## Milestones

### M1 — Share the currently connected network

- Detect OS before invoking an adapter.
- Query the OS for current SSID/security metadata.
- Mark the active profile in the selectable list.
- Generate and share a Wi-Fi QR locally after user confirmation.
- If the OS does not expose the password to this app, use the OS share flow or
  ask the user to import the OS-generated QR / enter the password.

### M2 — Choose another saved network

- Offer only OS-authorized, user-selectable profile names.
- Reveal a selected profile's password only after a second explicit action and
  only where the OS/API permits it.
- On restricted platforms, fall back to the system's own share/QR UI or user-led
  import; do not promise silent access to saved credentials.

### M3 — Desktop 1.0 Release Candidate (in progress)

- Explain each native OS's credential-access boundary before the user attempts to
  reveal a selected profile; permission failures include an OS-owned fallback path.
- Require a named confirmation immediately before reading the selected credential;
  state plainly that the QR image contains the Wi-Fi password and can be copied.
- Build unsigned package previews on their intended builders: Windows MSI/NSIS,
  macOS DMG, Ubuntu 22.04 and Debian 12 DEB, and Fedora 45 RPM.
- Run manual install, upgrade, remove, and native Wi-Fi smoke tests on real target
  operating systems; CI compilation alone is not release validation.
- Keep signing, notarization, public release, and Tauri updater disabled until the
  repository owner provisions signing identities and a protected updater keypair.
- Keep mobile maturity and Help Agent tools out of this release scope; they remain
  follow-up milestones after desktop distribution is verified.

## Adapter support matrix

| OS | Current connection | Saved profile list / password | Product path |
|---|---|---|---|
| Windows desktop | Native Wi-Fi API (`WlanQueryInterface`) | `WlanGetProfile`; plaintext keys are normally restricted to Administrators | Rust desktop adapter does not auto-elevate; selected secured profile needs OS-granted plaintext access. The separate Python browser compatibility bridge can use its one-shot UAC helper. |
| Android | Native connectivity/Wi-Fi APIs, subject to runtime permission and API level | Ordinary apps cannot enumerate all system profiles; Android Settings can show a selected network's share QR | Implemented Capacitor adapter for current SSID/security metadata and Settings handoff for saved-network QR. |
| iOS/iPadOS | `NEHotspotNetwork.fetchCurrent` can return current network info only with required entitlement/authorization conditions | Passwords/Settings lets the user inspect/share; third-party apps have no general-purpose API to enumerate saved profiles | Implemented Capacitor adapter source for current metadata and OS-sharing guidance; requires Apple entitlement/authorization and macOS/Xcode to build/test. |
| macOS | CoreWLAN | Preferred network profiles; Keychain governs selected secret access | Rust desktop adapter lists CoreWLAN profiles and reads a selected personal-network password from user/system Keychain. Current SSID requires Location Services authorization; no silent prompt is issued. |
| Linux desktop | NetworkManager D-Bus | Saved Wi-Fi profiles; secrets are separate from `GetSettings` | Rust adapter for NetworkManager desktops (Ubuntu/Fedora/Debian). `GetSecrets` returns only persistent or session-agent secrets and never prompts. Other network stacks are not covered yet. |

## Implementation in this repository

- The primary `frontend/static/index.html` screen is local sharing, not chat. It
  detects the client OS on the client before deciding whether a local adapter
  can be called. Opening Help is optional; the Help Agent is contacted only
  after the user opens Help and opts into cloud processing.
- Help is an instruction-only guide with no Wi-Fi, file, QR, or cloud-storage
  tools. The browser sends only the Help message and normalized client OS after
  consent; no Wi-Fi profile data or QR is included.
- `desktop/` is the cross-platform Rust/Tauri desktop app. `wifi-core` owns the
  platform-neutral domain and local QR generation; `wifi-platform` selects a
  platform-specific adapter at compile time (Windows WLAN API, macOS CoreWLAN +
  Keychain, Linux NetworkManager D-Bus); `src-tauri` exposes only identity,
  profile-list, and confirmed single-profile QR commands to the bundled UI.
- `frontend/device_wifi.py` implements the Windows adapter using
  `wlanapi.dll`: current connection, saved profile names, and user-selected
  profile lookup. `frontend/windows_wifi_elevated.py` is a one-shot UAC helper
  for the selected protected network; it has no HTTP listener or cloud credentials.
  It is only used by the browser compatibility bridge; the Rust desktop app
  does not auto-elevate.
- Local-only endpoints live under `/device/wifi/*`. They require
  `DEVICE_WIFI_LOCAL_MODE=1`, reject non-loopback callers, compare client and
  host OS, and are disabled on Cloud Run/Agent Engine.
- QR PNG creation happens in memory on the local frontend process. The QR image
  is not uploaded to the repo's public Cloud Storage bucket.
- `mobile/` is the native Android/iOS app shell. It detects `Capacitor.getPlatform()`
  before calling the platform plugin; current-network permission is requested
  only after the user taps the read button. Android returns current metadata and opens
  Wi-Fi Settings for an OS-generated saved-network QR. iOS uses
  `NEHotspotNetwork.fetchCurrent` for allowed metadata and provides OS-owned
  credential-sharing instructions; the public iOS API does not return saved passwords.
- Native desktop Help is an offline usage guide. It does not send chat or Wi-Fi
  data to the cloud. The optional cloud Help workflow remains in the browser app.

## Local Windows developer run

From `frontend/` in PowerShell:

```powershell
$env:DEVICE_WIFI_LOCAL_MODE = "1"
python main.py
```

Open `http://127.0.0.1:8088`. The local bridge binds only to loopback. Current
SSID/profile names do not require reading the password. Windows normally
requires an elevated process to return a plaintext stored key; after the user
selects one profile, a separate one-shot helper requests UAC and writes only a
temporary QR PNG. The chat proxy itself remains unprivileged. Android/iOS build
steps and platform-specific requirements are in `mobile/README.md`.

## Rust desktop build

The native desktop app does not require the Python loopback bridge. From the
repository root, install the target OS prerequisites in `desktop/README.md`,
then run:

```sh
cd desktop
npm ci
npm run dev
npm run test
npm run build
```

The new CI matrix is configured to compile the Rust workspace on Windows, macOS,
and Ubuntu 22.04. Build
Linux distribution packages on their target/oldest supported distribution
because the WebKitGTK and glibc ABI baseline depends on the build host.

## Platform references

- Microsoft Native Wi-Fi `WlanQueryInterface` and current connection structure:
  https://learn.microsoft.com/windows/win32/api/wlanapi/nf-wlanapi-wlanqueryinterface
- Microsoft `WlanGetProfile` plaintext-key access rules:
  https://learn.microsoft.com/windows/win32/api/wlanapi/nf-wlanapi-wlangetprofile
- Android saved-profile restrictions and APIs:
  https://developer.android.com/reference/android/net/wifi/WifiManager
- Android user-mediated share QR:
  https://support.google.com/android/answer/9075847
- Apple current Wi-Fi API overview:
  https://developer.apple.com/documentation/technotes/tn3111-ios-wifi-api-overview
- Apple user-facing saved Wi-Fi password and sharing flow:
  https://support.apple.com/en-us/104961
