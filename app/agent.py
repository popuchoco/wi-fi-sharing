# ruff: noqa
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

import base64
import datetime
import io
from typing import Any, Optional

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.cloud import firestore, storage
from google.genai import types
import qrcode

from .a2ui_utils import a2ui_callback

MODEL = "gemini-3.8-flash"

# IMPORTANT: Hardcode the GCP Project ID as a string.
# Do NOT read from google.auth.default() or GOOGLE_CLOUD_PROJECT,
# which returns the project number on Agent Platform and breaks Firestore.
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-04-e87625cd390f"
COLLECTION_NAME = "wifi_networks"
GCS_BUCKET_NAME = "wifi-sharing-qwiklabs-gcp-04-e87625cd390f"
AGENT_ENGINE_RESOURCE_NAME = "projects/1060190494686/locations/us-east1/reasoningEngines/8616150247741063168"
SANDBOX_RESOURCE_NAME = "projects/1060190494686/locations/us-east1/reasoningEngines/8616150247741063168/sandboxEnvironments/6080283908438491136"

_db_client: Optional[firestore.Client] = None
_storage_client: Optional[storage.Client] = None


def _get_db() -> firestore.Client:
    """Lazily initializes and returns the Firestore client."""
    global _db_client
    if _db_client is None:
        _db_client = firestore.Client(project=FIRESTORE_PROJECT_ID)
    return _db_client


def _get_storage() -> storage.Client:
    """Lazily initializes and returns the Cloud Storage client."""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    return _storage_client


def list_wifi_networks(location: Optional[str] = None) -> list[dict[str, Any]]:
    """查詢所有可用之 Wi-Fi 網路清單。可選指定地點過濾。

    Args:
        location: 可選，若指定則僅回傳位置包含該關鍵字的 Wi-Fi 網路。

    Returns:
        包含各 Wi-Fi 網路名稱 (SSID)、加密方式、位置、說明與啟用狀態的清單。
    """
    db = _get_db()
    docs = db.collection(COLLECTION_NAME).stream()
    results = []
    for doc in docs:
        data = doc.to_dict()
        if not data.get("is_active", True):
            continue
        if location:
            loc_field = data.get("location", "")
            if location.lower() not in loc_field.lower():
                continue
        results.append({
            "ssid": data.get("ssid"),
            "security_type": data.get("security_type", "WPA2"),
            "location": data.get("location", "未指定"),
            "description": data.get("description", ""),
            "hidden": data.get("hidden", False),
        })
    return results


def get_wifi_network(ssid: str) -> dict[str, Any]:
    """根據 Wi-Fi 名稱 (SSID) 查詢詳細連線資訊，包括密碼與標準 QR Code 連線字串。

    Args:
        ssid: Wi-Fi 網路名稱 (SSID)。

    Returns:
        該 Wi-Fi 的完整詳細資料，包含 ssid, password, security_type, location, description 以及標準連線字串 wifi_qr_payload。
    """
    db = _get_db()
    doc_id = ssid.lower().replace(" ", "-")
    doc_ref = db.collection(COLLECTION_NAME).document(doc_id)
    doc = doc_ref.get()

    if not doc.exists:
        query = db.collection(COLLECTION_NAME).where("ssid", "==", ssid).limit(1).stream()
        match = list(query)
        if match:
            doc = match[0]
        else:
            return {"error": f"找不到名稱為 '{ssid}' 的 Wi-Fi 網路設定。"}

    data = doc.to_dict()
    sec = data.get("security_type", "WPA2")
    pwd = data.get("password", "")
    net_ssid = data.get("ssid", ssid)
    hidden_flag = "true" if data.get("hidden", False) else "false"

    qr_payload = f"WIFI:T:{sec};S:{net_ssid};P:{pwd};H:{hidden_flag};;"

    return {
        "ssid": net_ssid,
        "password": pwd,
        "security_type": sec,
        "location": data.get("location", ""),
        "description": data.get("description", ""),
        "hidden": data.get("hidden", False),
        "is_active": data.get("is_active", True),
        "wifi_qr_payload": qr_payload,
    }


def save_wifi_network(
    ssid: str,
    password: str,
    security_type: str = "WPA2",
    location: str = "一般區域",
    description: str = "",
    hidden: bool = False,
) -> dict[str, Any]:
    """新增或更新一組 Wi-Fi 網路設定至 Firestore 資料庫。

    Args:
        ssid: Wi-Fi 網路名稱 (SSID)。
        password: Wi-Fi 連線密碼。
        security_type: 加密模式，可為 WPA2, WPA, WPA3 或 nopass，預設為 WPA2。
        location: 熱點所在實體位置（例如：3F 會議室、1F 大廳）。
        description: 備註或訪客使用規範。
        hidden: 是否為隱藏熱點，預設 False。

    Returns:
        儲存結果狀態與更新後資料。
    """
    db = _get_db()
    doc_id = ssid.lower().replace(" ", "-")
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    doc_data = {
        "ssid": ssid,
        "password": password,
        "security_type": security_type,
        "location": location,
        "description": description,
        "hidden": hidden,
        "is_active": True,
        "updated_at": now_iso,
    }

    db.collection(COLLECTION_NAME).document(doc_id).set(doc_data)
    hidden_flag = "true" if hidden else "false"
    qr_payload = f"WIFI:T:{security_type};S:{ssid};P:{password};H:{hidden_flag};;"

    return {
        "status": "success",
        "message": f"已成功儲存 Wi-Fi 網路 '{ssid}' 設定至 Firestore 資料庫。",
        "data": {**doc_data, "wifi_qr_payload": qr_payload},
    }


def generate_wifi_qr_code(
    ssid: str,
    password: Optional[str] = None,
    security_type: Optional[str] = None,
    hidden: bool = False,
) -> dict[str, Any]:
    """生成指定 Wi-Fi 網路的連線 QR Code 圖片，並上傳至 Cloud Storage 提供公開掃描網址。

    Args:
        ssid: Wi-Fi 網路名稱 (SSID)。若不提供密碼，會自動從已儲存的資料庫中查詢。
        password: 可選，若未在資料庫中或欲生成臨時密碼可手動指定。
        security_type: 可選，WPA2, WPA, WPA3, nopass。預設從資料庫取得或預設 WPA2。
        hidden: 是否為隱藏熱點，預設 False。

    Returns:
        包含 ssid, wifi_qr_payload, qr_code_url, 與說明訊息的字典。
    """
    # Auto-fetch from Firestore if password not provided
    if not password:
        net_info = get_wifi_network(ssid)
        if "error" in net_info:
            return {"error": f"在資料庫中找不到 '{ssid}' 的密碼，請提供密碼以生成 QR Code。"}
        password = net_info.get("password", "")
        if not security_type:
            security_type = net_info.get("security_type", "WPA2")
        hidden = net_info.get("hidden", False)

    sec = security_type or "WPA2"
    hidden_flag = "true" if hidden else "false"
    qr_payload = f"WIFI:T:{sec};S:{ssid};P:{password};H:{hidden_flag};;"

    # Generate QR Code image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # Upload to Cloud Storage
    storage_client = _get_storage()
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    safe_name = ssid.lower().replace(" ", "_").replace("-", "_")
    filename = f"wifi_qr_{safe_name}.png"
    blob = bucket.blob(filename)
    blob.upload_from_file(buf, content_type="image/png")

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"

    return {
        "status": "success",
        "ssid": ssid,
        "security_type": sec,
        "wifi_qr_payload": qr_payload,
        "qr_code_url": public_url,
        "message": f"已成功為 '{ssid}' 生成 Wi-Fi 連線 QR Code 圖片，可透過公開連結預覽與掃描連線。",
    }


def generate_wifi_video(
    prompt: str,
    ssid: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, Any]:
    """使用 Google Omni 模型 (gemini-omni-flash-preview) 生成 Wi-Fi 或場地連線簡短宣傳短片。

    Args:
        prompt: 影片內容描述，例如 'A cozy cafe setting with glowing animated Wi-Fi wave welcoming guests'。
        ssid: 可選，欲宣傳之 Wi-Fi 網路名稱 (SSID)。
        tool_context: ADK 工具上下文，用於將影片儲存至 Artifacts 面板。

    Returns:
        包含影片公開 Cloud Storage 網址 (https://storage.googleapis.com/<bucket>/<object>) 與狀態的字典。
    """
    full_prompt = prompt
    if ssid:
        full_prompt = f"Wi-Fi network '{ssid}': {prompt}"

    # Google's Omni model (gemini-omni-flash-preview) in the global region
    omni_client = genai.Client(
        vertexai=True,
        project=FIRESTORE_PROJECT_ID,
        location="global",
    )
    interaction = omni_client.interactions.create(
        model="gemini-omni-flash-preview",
        input=full_prompt,
    )

    if not hasattr(interaction, "output_video") or not interaction.output_video or not interaction.output_video.data:
        return {"error": "未能成功自 Omni 模型取得生成的影片資料。"}

    raw_data = interaction.output_video.data
    if isinstance(raw_data, str):
        video_bytes = base64.b64decode(raw_data)
    else:
        video_bytes = raw_data

    safe_name = (ssid or "wifi").lower().replace(" ", "_").replace("-", "_")
    timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"wifi_video_{safe_name}_{timestamp_str}.mp4"

    # 1. Save artifact with tool_context.save_artifact so it shows up in Playground's Artifacts panel
    if tool_context is not None:
        part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
        tool_context.save_artifact(filename=filename, artifact=part)

    # 2. Upload video bytes to public Cloud Storage bucket without writing to local file
    # Bucket name hardcoded as string: "wifi-sharing-qwiklabs-gcp-04-e87625cd390f"
    bucket_name = "wifi-sharing-qwiklabs-gcp-04-e87625cd390f"
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_string(video_bytes, content_type="video/mp4")

    public_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"

    return {
        "status": "success",
        "video_url": public_url,
        "filename": filename,
        "message": f"影片已生成並上傳至 Cloud Storage：{public_url}",
    }


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "你是「WI-FI分享家」（Wi-Fi Sharing Specialist），一位親切、專業的智慧連線助理。"
        "你的主要任務是協助使用者管理、查詢與快速分享場所中的 Wi-Fi 網路資訊。"
        "你可以使用 Firestore 工具查詢可用的 Wi-Fi 熱點（list_wifi_networks）、取得指定 Wi-Fi 的連線密碼與規格（get_wifi_network）、登記新熱點（save_wifi_network），以及生成可供手機掃描秒連的 QR Code 圖片（generate_wifi_qr_code），以及使用 Omni 模型生成 Wi-Fi 宣傳短片（generate_wifi_video）。"
        "當使用者要求生成或索取 QR Code 時，請務必呼叫 generate_wifi_qr_code 工具，並將回傳的公開圖片網址填入 A2UI 的 Image 元件中呈現。"
        "當使用者要求生成連線影片或宣傳影片時，請呼叫 generate_wifi_video 工具。"
        "請一律以繁體中文（Traditional Chinese）回答。"
    ),
    workflow_description="Analyze the request, call relevant tools to fetch Wi-Fi data or generate QR codes, and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="simple_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        list_wifi_networks,
        get_wifi_network,
        save_wifi_network,
        generate_wifi_qr_code,
        generate_wifi_video,
    ],
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
