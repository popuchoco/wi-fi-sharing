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
6. **Share or download only after the user sees the QR.** Closing the dialog
   revokes its in-memory object URL.

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

## Adapter support matrix

| OS | Current connection | Saved profile list / password | Product path |
|---|---|---|---|
| Windows desktop | Native Wi-Fi API (`WlanQueryInterface`) | `WlanGetProfile`; plaintext keys are normally restricted to Administrators | Local Windows adapter. This repository implements the adapter and local QR route. A future installer should use a narrow UAC helper rather than elevate the chat proxy. |
| Android | Native connectivity/Wi-Fi APIs, subject to runtime permission and API level | Ordinary apps cannot enumerate all system profiles; Android Settings can show a selected network's share QR | Native Android bridge for metadata; OS Settings QR/import for credentials. |
| iOS/iPadOS | `NEHotspotNetwork.fetchCurrent` can return current network info only with required entitlement/authorization conditions | Passwords/Settings lets the user inspect/share; third-party apps have no general-purpose API to enumerate saved profiles | Native iOS bridge for allowed metadata; OS-mediated share/QR or user-led import for credentials. |
| macOS | CoreWLAN/native APIs | Keychain and app authorization govern secret access | Separate macOS adapter; not implemented in this milestone. |

## Implementation in this repository

- `frontend/static/index.html` detects the client OS before requesting device data.
- `frontend/device_wifi.py` implements the first Windows adapter using
  `wlanapi.dll`: current connection, saved profile names, and user-selected
  profile lookup.
- Local-only endpoints live under `/device/wifi/*`. They require
  `DEVICE_WIFI_LOCAL_MODE=1`, reject non-loopback callers, compare client and
  host OS, and are disabled on Cloud Run/Agent Engine.
- QR PNG creation happens in memory on the local frontend process. The QR image
  is not uploaded to the repo's public Cloud Storage bucket.
- Android, iOS, and macOS native adapters remain follow-up implementation work;
  those platforms will use their system-mediated credential sharing rather than
  pretending a browser can read OS secrets.

## Local Windows developer run

From `frontend/` in PowerShell:

```powershell
$env:DEVICE_WIFI_LOCAL_MODE = "1"
python main.py
```

Open `http://127.0.0.1:8088`. The local bridge binds only to loopback. Current
SSID/profile names do not require reading the password. Windows normally
requires an elevated process to return a plaintext stored key; the current
prototype reports that requirement instead of self-elevating. Do not run the
full chat proxy as Administrator for production use. Production Windows support
should move only the selected-profile operation into a small, separately
approved elevation helper.

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
