# Rust 桌面應用程式

桌面版使用 Tauri 2。WebView 重用 `frontend/static/` 的本機優先介面；OS
偵測、已存網路清單、使用者選定後的憑證存取與 QR 產生由 Rust 原生程序負責。
安裝後不需要啟動 Python 或本機 HTTP 服務。

## 架構

```text
frontend/static/                 共用介面（瀏覽器相容版與桌面版）
desktop/src-tauri/               Tauri 外殼、指令、CSP 與套件資訊
desktop/crates/wifi-core/        跨平台領域模型、zeroize 憑證、QR 產生
desktop/crates/wifi-platform/    Windows／CoreWLAN／NetworkManager 系統介接器
desktop/assets/app-icon.svg      桌面套件圖示的向量來源檔
mobile/                          既有 Capacitor Android/iOS App
frontend/main.py                 既有 Web Help/API 與 Windows 瀏覽器連接器
```

介面會先呼叫 Rust `wifi_identity`，再以 `wifi_profiles` 列出設定檔名稱；
列清單時不讀取密碼。只有使用者按「產生分享 QR Code」後，才會呼叫
`wifi_generate_qr` 存取該項選定設定檔。憑證型別不實作序列化或 `Debug`，可控的
密碼緩衝區使用 `zeroize`；QR 在本機產生。桌面版 Help 是離線操作說明，不會呼叫
雲端 Help Agent。

## 平台支援與限制

| 桌面 OS | 原生 API | 設定檔清單 | 選定憑證／限制 |
|---|---|---|---|
| Windows 10/11 | Windows Native Wi-Fi（`wlanapi.dll`） | 已存 WLAN 設定檔與目前連線 | 支援開放、WEP、WPA-PSK/WPA3-SAE。Windows 預設通常只允許系統管理員讀取明文金鑰；App 不會自行提權。若系統政策允許，請以有權限的使用者工作階段啟動。企業網路與無法辨識的安全類型會拒絕產生 QR。 |
| macOS 10.13+ | CoreWLAN | 優先網路設定檔 | 使用者確認分享後，才從使用者或系統 Keychain 讀取選定個人網路的密碼。目前 SSID 可能需要授權定位服務才能取得；App 不會靜默要求定位權限。 |
| Linux 桌面 | NetworkManager D-Bus | NetworkManager 已存 Wi-Fi 設定檔 | 選定後才呼叫 `GetSecrets`。此方法不會跳出對話框索取密碼，只會回傳持久化密碼或目前工作階段 Secret Agent 提供的密碼。支援開放、WEP、WPA-PSK 與 SAE；企業網路及 OWE 不支援。需要 NetworkManager。 |

Ubuntu、Fedora、Debian 桌面在使用 NetworkManager 並安裝 WebKitGTK 4.1 開發套件時
可建置使用。直接使用 iwd/networkd、沒有 NetworkManager 的系統目前不支援。
即使能列出設定檔名稱，OS 仍可能拒絕存取密碼；此時 App 會顯示錯誤，不會提權，
也不會改讀其他設定檔。

## 建置前置條件

所有平台都需要 Rust stable 與 Node.js/npm。執行以下指令前，請先安裝目標 OS 的
Tauri 2 原生相依套件。

### Ubuntu／Debian

Ubuntu 22.04+ 與 Debian 12+ 是 WebKitGTK 4.1 文件所列的基礎版本：

```sh
sudo apt update
sudo apt install -y \
  libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev \
  libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

### Fedora

```sh
sudo dnf install -y \
  webkit2gtk4.1-devel openssl-devel curl wget file \
  libappindicator-gtk3-devel librsvg2-devel libxdo-devel
sudo dnf group install -y "C Development Tools and Libraries"
```

### macOS

安裝 Xcode 或 Xcode Command Line Tools（`xcode-select --install`）。CoreWLAN Rust
繫結也會透過 SwiftPM 建置 Swift bridge。

### Windows

安裝含 C++ 桌面工作負載的 Visual Studio Build Tools 與 Microsoft Edge WebView2
Runtime，並使用 MSVC 目標的 Rust stable toolchain。

## 執行、檢查與建置

在專案根目錄執行：

```sh
cd desktop
npm ci
npm run dev       # 啟動原生桌面 App
npm run check     # 編譯整個 Rust workspace
npm run test      # 執行 workspace 測試
npm run build     # 建置目前主機平台支援的套件格式
```

若更新圖示，請在 `desktop/` 目錄重新產生已納入版控的桌面圖示：

```sh
npx tauri icon assets/app-icon.svg --output src-tauri/icons
```

請在各目標 OS 上建置，不要把 Linux 套件當成可任意跨發行版打包。Linux 套件會
依賴建置環境的 glibc/WebKitGTK ABI；若要支援較舊的 Ubuntu/Debian，請在仍提供
WebKitGTK 4.1 的最低目標系統上建置，再於每個目標發行版驗證 `.deb`。Fedora `.rpm`
應在 Fedora 建置與測試。對外發佈 macOS 套件前，還需要程式碼簽署與 notarization。

GitHub Actions 的 **Desktop package previews** 可手動建置 Windows MSI/NSIS、macOS
DMG、Ubuntu 22.04／Debian 12 DEB 與 Fedora 45 RPM，並提供 14 天的測試用 artifacts。這些是未簽署
預覽包，不會建立公開 Release 或自動更新通道。正式發佈前請完成
[`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)，並在真實目標 OS 驗證安裝、原生 Wi-Fi
權限及解除安裝流程。

Windows 瀏覽器連接器與 Capacitor 行動版仍保留作為相容路徑；它們和 Rust 原生桌面
程式是分開的，並各自保留原有平台限制。

## 平台/API 參考

- [Tauri 2 前置條件](https://v2.tauri.app/start/prerequisites/)與[桌面發佈](https://v2.tauri.app/distribute/)
- [CoreWLAN Rust 繫結：設定檔、Keychain 與定位服務行為](https://docs.rs/corewlan/latest/corewlan/)
- [NetworkManager `GetSecrets` 語意](https://networkmanager.dev/docs/api/1.46/gdbus-org.freedesktop.NetworkManager.Settings.Connection.html)
- [Microsoft `WlanGetProfile` 明文金鑰權限](https://learn.microsoft.com/windows/win32/api/wlanapi/nf-wlanapi-wlangetprofile)
