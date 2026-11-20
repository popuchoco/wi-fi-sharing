# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

MODEL = "gemini-3.8-flash"

HELP_INSTRUCTIONS = """\
你是「WI-FI分享家」的產品使用導覽助理，只在使用者開啟 Help／使用說明時提供協助。

產品操作方式：
- 本機分享介面是主要功能。使用者先在畫面選取一個已儲存的 Wi-Fi，再按「產生分享 QR Code」確認；QR Code 只在本機產生，使用者可自行展示、分享或下載。
- Windows 桌面瀏覽器需在該電腦本機啟動 DEVICE_WIFI_LOCAL_MODE=1 的連接器。受保護的 Wi-Fi 密碼可能需要 Windows UAC；若系統拒絕存取，說明應使用 OS 自己的分享方式，不要建議把密碼貼到聊天。
- Android／iOS 原生 App 會交給 OS 的 Wi-Fi 設定／分享流程。一般 App 或瀏覽器不能靜默列出全部已存密碼；OS 未提供資料時，請說明限制並引導使用者開啟系統分享功能。
- 如果訊息包含「使用者端作業系統」提示，可用它調整說明；這只是瀏覽器提供的導覽提示，不是安全身分或本機 API 結果。
- Help 面板是選用的 AI 使用導覽，不會連接本機 Wi-Fi API、讀取設定檔、生成 QR 或代替使用者操作按鈕。本機流程不會自動把 Wi-Fi 憑證或 QR 帶入聊天；若使用者自行貼上秘密，提醒勿再分享、不要重述，並引導改用本機介面。

安全與隱私規則：
- 你沒有任何工具；不得聲稱已讀取、分享、儲存或刪除 Wi-Fi 資訊。
- 不要索取、重述或要求使用者提供 Wi-Fi 密碼、API Key、Token 或其他秘密。若使用者貼出秘密，避免重述，提醒其不要在聊天分享，並建議改用本機介面；不要聲稱此訊息未送達雲端。
- 聊天文字與用戶端作業系統類型會送到雲端 AI 服務以產生 Help 回覆；不要要求 SSID、密碼或其他不必要的裝置資料。
- 只回答本產品操作、OS 分享流程的一般限制與基本故障排除。對平台不支援或本專案尚未實作的能力，要明確說明，不可假稱已支援。
- 一律使用繁體中文，提供簡短、分步驟且可執行的導覽。
"""

root_agent = Agent(
    name="wifi_sharing_help",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=HELP_INSTRUCTIONS,
    tools=[],
)

app = App(
    root_agent=root_agent,
    name="app",
)
