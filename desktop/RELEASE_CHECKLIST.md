# Desktop 1.0 Release Candidate Checklist

This checklist separates package-preview builds from a trusted public release. The
manual **Desktop package previews** workflow creates unsigned Windows, macOS, Ubuntu,
and Fedora installers for maintainer testing. It does not publish a GitHub Release,
configure auto-updates, or sign the installers. Unsigned artifacts are not public
release candidates: Windows and macOS will show platform trust/install warnings.

The current internal package-preview version is `0.3.0-rc.1`; this is not the public
Desktop 1.0 release candidate.

## Release gates

- [ ] Validate version synchronization with `npm run check:version`,
  `cargo metadata --locked`, and `npm ci`;
  update `desktop/Cargo.toml`, `desktop/package.json`, `desktop/package-lock.json`, and
  `desktop/src-tauri/tauri.conf.json` together before the next version increment.
- [ ] Run `.github/workflows/desktop.yml` successfully on Windows, macOS, and Ubuntu.
- [ ] Run `.github/workflows/desktop-packages.yml` and install/test the generated
  packages on actual target systems; package builds are not runtime smoke tests.
- [ ] Complete the platform smoke tests below using a disposable test Wi-Fi profile.
  Do not capture or attach screenshots containing the QR code or credentials.
- [ ] Configure and verify platform signing before publishing installers.
- [ ] If enabling the Tauri updater, provision an updater keypair and HTTPS endpoint;
  keep the private key outside the repository and store it only in protected CI
  secrets. Do not ship an updater with an empty or placeholder public key.
- [ ] Generate checksums and publish release notes that identify supported OS versions,
  NetworkManager requirement, and unsupported network security types.

## Platform smoke tests

### Windows 10/11

- [ ] Launch as a standard user; verify that the app does not request elevation.
- [ ] Verify profile names load without reading secrets, select a disposable personal
  Wi-Fi profile, and confirm the explicit QR disclosure is shown before access.
- [ ] Verify a denied key read explains that the app will not elevate and points to the
  Windows Wi-Fi settings option for showing/sharing the network password.
- [ ] If elevated access is deliberately available in a test account, verify only the
  selected profile is read and the QR can be scanned by a test client.

### macOS

- [ ] Verify saved profile names load without reading Keychain credentials.
- [ ] Verify the system controls any Keychain access prompt; cancellation produces a
  useful error with the Passwords/Keychain and native Wi-Fi sharing fallback.
- [ ] Check current-SSID privacy behavior and confirm no Location permission is
  requested silently.
- [ ] Verify the QR is generated locally; the **Hide QR Code** action and closing the
  page revoke the page's object URL. Downloaded/shared copies remain outside app control.

### Ubuntu, Debian, and Fedora

- [ ] Verify the NetworkManager dependency and missing-service error on a desktop using
  NetworkManager; direct iwd/networkd-only setups remain unsupported.
- [ ] Verify a profile with a persistent secret and a profile whose secret is available
  only from the active session Secret Agent.
- [ ] Verify the app does not prompt for or invent a password when `GetSecrets` returns
  no secret, and that Enterprise/OWE profiles are rejected clearly.
- [ ] Install and launch the Ubuntu-built `.deb` on Ubuntu 22.04, the Debian-built `.deb`
  on Debian 12+, and the Fedora-built `.rpm` on Fedora 45. Recheck the packaged runtime
  dependencies on each target distribution.

## Signing and updater provisioning

Signing material must be provisioned by the repository owner; it is intentionally not
generated or checked into this worktree.

- **macOS:** provide an Apple Developer ID signing identity and notarization credentials
  to protected GitHub Actions secrets. Follow the official [Tauri macOS signing and
  notarization guide](https://v2.tauri.app/distribute/sign/macos/).
- **Windows:** select a trusted Authenticode signing provider, then configure its
  non-interactive signing command/credentials as protected CI secrets. Follow the
  official [Tauri Windows signing guide](https://v2.tauri.app/distribute/sign/windows/).
- **Updater:** generate a Tauri updater keypair in a secure maintainer environment,
  commit only its public key in Tauri configuration, store the private key/password as
  protected CI secrets, and configure a stable HTTPS update endpoint. Follow the
  official [Tauri updater guide](https://v2.tauri.app/plugin/updater/).

Do not use the unsigned preview workflow for a public download page or automatic
update channel.
