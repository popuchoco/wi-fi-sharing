# 📶 WI-FI分享家

以「Wi-Fi 分享留在使用者裝置」為核心的本機優先原型。主畫面直接提供
作業系統偵測、可用網路選擇與本機 QR 產生；聊天 Agent 不再是主要產品入口，
只有使用者打開「使用說明」並同意雲端處理後，才會作為選用的操作導覽出現。

## 目前產品範圍

- **Web 本機分享介面**：Windows 桌面版可在本機列出設定檔名稱；使用者選定
  網路並按下產生按鈕後，才向 Windows API 讀取該設定檔憑證並在本機產生 QR。
- **原生行動端**：`mobile/` 是 Capacitor Android/iOS App 原型；OS 允許時讀取
  目前連線中繼資料。已儲存網路與密碼仍透過 Android/iOS 的系統設定分享流程，
  不由一般 App 靜默列舉或讀取。
- **可選 Help Agent**：只提供使用步驟與基本排錯，沒有 Wi-Fi、Firestore、QR、
  檔案或其他工具，不能代表使用者操作系統。聊天文字及瀏覽器提供的 OS 類型
  會在使用者同意後送往已設定的 Google Agent Runtime。

## 隱私邊界

- OS 偵測在瀏覽器端完成；瀏覽器不能把伺服器 OS 當作使用者裝置 OS。
- Web 本機連接器只在明確啟用的 Windows 本機 loopback 服務工作；不可部署到
  Cloud Run 以讀取訪客裝置。密碼只在按下 QR 產生時由 Windows 本機流程讀取。
- 本機分享程式不會自動把 Wi-Fi 憑證與 QR 帶入 Help Agent、Google AI、
  Firestore 或 Cloud Storage。若使用者自行把秘密貼到 Help 對話，該文字會依同意
  傳送給雲端 AI，因此介面與 Agent 都會提醒不要貼上。
- 開啟 Help 不會立即發送聊天；使用者必須先勾選雲端處理同意，才可送出導覽。
  請勿在聊天輸入 Wi-Fi 密碼、API Key、Token 或其他秘密。
- 遠端 Help 可設定 `CHAT_PROXY_ACCESS_TOKEN` 與獨立的
  `CHAT_PROXY_SESSION_SECRET`。這是小型私有部署的共用存取碼，不是正式的
  多使用者身分驗證。後端有訊息大小、長度與頻率限制；多副本正式服務應使用
  共享限流器和正式身分提供者。
- 停用上傳不會清除過去的雲端物件、資料匯出或 Git 歷史。曾提交到 Git 的示範
  Wi-Fi 密碼仍可能留在舊 commit；若曾使用真實密碼，請在路由器輪替。

## 啟動 Windows 本機分享介面

需要 Windows、Python 3.11+ 及 `frontend/requirements.txt` 套件。PowerShell：

```powershell
cd frontend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DEVICE_WIFI_LOCAL_MODE = "1"
python main.py
```

開啟 <http://127.0.0.1:8088>。本機分享不需要 Google Cloud SDK、ADC、Agent
Engine 資源或聊天存取碼。若 Windows 不允許一般程序讀取選定網路的密碼，
本機流程會另行要求 UAC；聊天 Proxy 不會提權。只在可信任的本機裝置操作。

若要使用選用 AI Help，另外設定 `AGENT_ENGINE_RESOURCE_NAME` 並提供可用的
Google Cloud ADC。Help 只有在使用者開啟面板、同意雲端處理並送出請求時才會
初始化認證和連線。遠端部署另需設定兩個聊天存取變數。

## 行動端

```sh
cd mobile
npm install
npm run build
```

Android 原生建置需要 Android Studio/JDK；iOS 建置需要 macOS/Xcode。參閱
[`mobile/README.md`](mobile/README.md) 與
[`DEVICE_WIFI_PRODUCT_PLAN.md`](DEVICE_WIFI_PRODUCT_PLAN.md) 的平台限制、規劃與
OS 整合細節。一般行動瀏覽器不允許網頁掃描已存 Wi-Fi；請使用原生 App 和 OS
分享流程。
