# 📶 WI-FI分享家 (Wi-Fi Sharing)

**WI-FI分享家 (Wi-Fi Sharing)** 是一個基於 Google Agent Development Kit (ADK) 開發的智慧型對話代理（Conversational Agent），專門協助場地主、活動主辦方與家庭用戶管理並快速分享 Wi-Fi 網路連線資訊。

透過結構化對話、Firestore 資料庫存取、Cloud Storage 資源分發、A2UI 卡片式介面以及 Google Omni 多模態影片生成技術，使用者只需透過自然語言即可查詢熱點、取得加密密碼、生成相機秒連的標準 Wi-Fi QR Code，甚至生成專屬的 Wi-Fi 宣傳短片。

---

## 🌟 核心功能與整合架構 (Implemented Capabilities)

本專案實際整合並實作了以下 Google Cloud 服務與工具：

### 1. 網路管理與持久化儲存 (Google Cloud Firestore)
- **資料集合**：`wifi_networks`
- **實作工具**：
  - `list_wifi_networks`：查詢所有啟用之 Wi-Fi 網路清單，支援地點關鍵字過濾（如「5F 會議室」、「咖啡吧」）。
  - `get_wifi_network`：依 SSID 查詢詳細連線參數（SSID、加密模式、密碼、標準連線字串等）。
  - `save_wifi_network`：新增或更新 Wi-Fi 熱點配置至 Firestore，包含時間戳記與隱藏熱點標記。

### 2. QR Code 生成與公開資源分發 (Google Cloud Storage)
- **公開儲存桶**：專屬 Cloud Storage Bucket 存放產出的靜態媒體資源。
- **實作工具**：
  - `generate_wifi_qr_code`：將 Wi-Fi 參數編碼為標準連線協定（`WIFI:T:<sec>;S:<ssid>;P:<password>;H:<hidden>;;`），即時生成 PNG 圖片二進位串流，直接上傳至 Cloud Storage 公開儲存庫，並回傳公開 HTTPS 預覽與下載連結。

### 3. 多模態短片生成 (Google Omni / Interactions API)
- **模型與區域**：`gemini-omni-flash-preview`（`global` 區域）。
- **實作工具**：
  - `generate_wifi_video`：使用 Google GenAI SDK Interactions API，依據場地或 Wi-Fi 主題生成宣傳動畫短片。
  - **雙軌交付**：
    - 透過 `tool_context.save_artifact` 註冊至 ADK Playground 的 Artifacts 側邊面板。
    - 將 MP4 二進位串流直接上傳至 Cloud Storage 公開儲存庫，並提供公開串流網址。

### 4. 結構化卡片介面 (A2UI v0.8)
- 整合 `A2uiSchemaManager`（版本 0.8）與 `BasicCatalog`。
- 透過 `after_model_callback` 攔截模型輸出，將 Wi-Fi 資訊與 Cloud Storage 中的 QR Code 圖片動態組裝為輕量化 A2UI 卡片（Card > Column > Row / Text / Image），提供直覺視覺體驗。

### 5. 獨立 Web 聊天前端 (FastAPI A2A Proxy + Web UI)
- 位於 `frontend/` 目錄：
  - **代理後端**（`frontend/main.py`）：基於 FastAPI 實作 A2A Client，自動與 ADK / Agent Engine 連線並維護使用者的 Context ID 會話記憶。
  - **聊天前端**（`frontend/static/index.html`）：具備現代化科技藍主題版面、使用者與助理專屬頭像、對話氣泡、A2UI 原生卡片渲染器，以及輸入框上方的快捷範例按鈕列。

---

## 📋 規劃中項目 (Planned, Not Yet Implemented)

以下為專案規劃設計但尚未在現有程式碼中實作之功能：
- **Vertex AI Memory Bank**：跨會話之長期偏好記憶（目前採用本機 `in_memory` 會話服務）。
- **Code Execution Sandbox**：以 AgentEngineSandboxCodeExecutor 動態執行 Python 進行 QR 矩陣編碼驗證（目前使用 Python `qrcode` 函式庫本機生成）。
- **可列印桌上立牌 (Printable Tent Cards)**：自動生成包含 Wi-Fi QR Code、品牌 Logo 與連線說明的 PDF 檔。

---

## 📁 專案目錄結構

```text
Wi-Fi-Sharing/
├── app/
│   ├── agent.py                 # Agent 核心邏輯、Firestore/GCS/Omni 工具與 A2UI 設定
│   ├── a2ui_utils.py            # A2UI 回呼處理器 (after_model_callback)
│   ├── fast_api_app.py          # ADK 本機 FastAPI 伺服器
│   └── app_utils/               # A2A 協議適配器與 Session/Artifact 服務
├── frontend/
│   ├── main.py                  # 前端 FastAPI A2A 代理伺服器
│   ├── static/
│   │   └── index.html           # 品牌化聊天 UI 與 A2UI 渲染引擎
│   ├── Dockerfile               # 前端容器化設定檔
│   └── requirements.txt         # 前端依賴清單
├── agents-cli-manifest.yaml     # agents-cli 專案設定檔
├── pyproject.toml               # Python 依賴與虛擬環境定義
└── README.md                    # 專案說明文件
```

---

## 🚀 本機環境安裝與啟動說明 (Setup & Run Instructions)

### 先決條件
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推薦使用的 Python 套件管理工具）
- [Google Cloud SDK (gcloud)](https://cloud.google.com/sdk/docs/install)
- 已完成 GCP 專案認證：
  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project <YOUR_GCP_PROJECT_ID>
  ```

### 1. 安裝專案依賴
```bash
uv sync
```

### 2. 啟動 ADK 本機開發環境 (Playground)
使用 `agents-cli` 啟動包含對話介面與 Artifacts 面板的開發環境：
```bash
agents-cli playground
```
啟動後依終端機提示之本機通訊埠開啟瀏覽器即可進行互動測試。

### 3. 啟動專屬 Web 聊天前端
進入 `frontend` 目錄並啟動 FastAPI A2A 代理伺服器：
```bash
cd frontend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 設定環境變數指定後端 Agent 資源（若連線遠端 Agent Engine）
export AGENT_ENGINE_RESOURCE_NAME="<YOUR_AGENT_ENGINE_RESOURCE_NAME>"
export AGENT_DIRECTORY="app"

python main.py
```
啟動後即可透過瀏覽器連線至本機前端服務進行交談與掃碼測試。
