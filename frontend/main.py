"""Local-first Wi-Fi sharing UI with an optional, on-demand Help Agent proxy.

Device-local sharing does not need Agent Engine or Google credentials. ADC and
the A2A Agent Runtime are used only after a user opens Help, agrees to cloud
processing, and sends a guide request. The A2A proxy returns text parts to the
Help panel; the Agent has no tools and never receives Wi-Fi credentials or QR
images.

Run the Windows local bridge from PowerShell with DEVICE_WIFI_LOCAL_MODE=1.
AGENT_ENGINE_RESOURCE_NAME is optional unless cloud Help is enabled.
"""

import hmac
import json
import os
import secrets
import time
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

try:  # Supports both `python main.py` from frontend/ and package imports.
    from .chat_security import (
        SlidingWindowRateLimiter,
        is_loopback_host,
        issue_session_cookie,
        verify_session_cookie,
    )
    from .device_wifi import router as device_wifi_router
except ImportError:
    from chat_security import (
        SlidingWindowRateLimiter,
        is_loopback_host,
        issue_session_cookie,
        verify_session_cookie,
    )
    from device_wifi import router as device_wifi_router

# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")

_SESSION_COOKIE = "wifi_chat_session"
_SESSION_MAX_AGE = 12 * 60 * 60
_ACCESS_TOKEN = os.environ.get("CHAT_PROXY_ACCESS_TOKEN", "")
_SESSION_SECRET_VALUE = os.environ.get("CHAT_PROXY_SESSION_SECRET", "")
_SESSION_SECRET_CONFIGURED = len(_SESSION_SECRET_VALUE.encode("utf-8")) >= 32
_SESSION_SECRET = (
    _SESSION_SECRET_VALUE.encode("utf-8")
    if _SESSION_SECRET_CONFIGURED
    else secrets.token_urlsafe(32).encode("utf-8")
)
_ACCESS_TOKEN_CONFIGURED = len(_ACCESS_TOKEN) >= 24
_rate_limiter = SlidingWindowRateLimiter()

# ADC is initialized only when the user opens Help, consents, and sends a guide request.
_creds = None


def _auth_headers() -> dict[str, str]:
    global _creds
    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


def _agent_endpoints() -> tuple[str, str]:
    resource = os.environ.get("AGENT_ENGINE_RESOURCE_NAME")
    if not resource:
        raise HTTPException(
            status_code=503,
            detail="AI 使用導覽尚未設定 Agent Engine；本機 Wi-Fi 分享仍可直接使用。",
        )
    parts = resource.split("/")
    if (
        len(parts) != 6
        or parts[0] != "projects"
        or parts[2] != "locations"
        or parts[4] != "reasoningEngines"
        or not parts[3]
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in parts[3])
    ):
        raise HTTPException(
            status_code=503,
            detail="AI 使用導覽的 Agent Engine 資源設定格式不正確。",
        )
    location = parts[3]
    base = (
        f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/"
        f"{resource}/api/a2a/{AGENT_DIRECTORY}"
    )
    return base, f"{base}/.well-known/agent-card.json"


app = FastAPI()
app.include_router(device_wifi_router)


@app.middleware("http")
async def _security_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin")
    if (
        request.url.path == "/chat"
        or request.url.path.startswith("/auth/")
        or request.url.path.startswith("/device/wifi/")
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


def _is_remote_request(request: Request) -> bool:
    client_host = request.client.host if request.client else None
    return bool(os.environ.get("K_SERVICE")) or not is_loopback_host(client_host)


def _request_session(request: Request) -> tuple[str, bool] | None:
    return verify_session_cookie(request.cookies.get(_SESSION_COOKIE), _SESSION_SECRET)


def _set_session_cookie(
    response: Response, session_id: str, authenticated: bool, request: Request
) -> None:
    expires_at = int(time.time()) + _SESSION_MAX_AGE
    value = issue_session_cookie(session_id, authenticated, _SESSION_SECRET, expires_at)
    response.set_cookie(
        _SESSION_COOKIE,
        value,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        secure=bool(os.environ.get("K_SERVICE")) or request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    from urllib.parse import urlparse

    parsed = urlparse(origin)
    request_host = request.headers.get("host", "").lower()
    return bool(parsed.netloc and parsed.netloc.lower() == request_host)


async def _request_json(request: Request, maximum_bytes: int) -> object:
    """Read a bounded JSON body, including requests without Content-Length."""
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        content_length = 0
    if content_length > maximum_bytes:
        raise HTTPException(status_code=413, detail="請求內容過長。")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum_bytes:
            raise HTTPException(status_code=413, detail="請求內容過長。")
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="請求格式錯誤。") from exc


def _authorized_for_chat(request: Request) -> bool:
    requires_code = _is_remote_request(request) or bool(_ACCESS_TOKEN)
    if not requires_code:
        return True
    if not _ACCESS_TOKEN_CONFIGURED or (
        _is_remote_request(request) and not _SESSION_SECRET_CONFIGURED
    ):
        return False
    session = _request_session(request)
    return bool(session and session[1])


@app.get("/auth/status")
async def auth_status(request: Request):
    session = _request_session(request)
    requires_code = _is_remote_request(request) or bool(_ACCESS_TOKEN)
    configuration_missing = requires_code and (
        not _ACCESS_TOKEN_CONFIGURED
        or (_is_remote_request(request) and not _SESSION_SECRET_CONFIGURED)
    )
    authenticated = bool(
        not configuration_missing
        and (not requires_code or (session and session[1]))
    )
    response = JSONResponse(
        {
            "help_available": bool(os.environ.get("AGENT_ENGINE_RESOURCE_NAME")),
            "requires_auth": requires_code,
            "authenticated": authenticated,
            "configuration_missing": configuration_missing,
        }
    )
    if session is None:
        _set_session_cookie(response, secrets.token_urlsafe(32), not requires_code, request)
    return response


@app.post("/auth/session")
async def create_auth_session(request: Request):
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="跨來源登入請求已拒絕。")
    if not _ACCESS_TOKEN_CONFIGURED or (
        _is_remote_request(request) and not _SESSION_SECRET_CONFIGURED
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "聊天存取設定不足：請設定至少 24 字元的 CHAT_PROXY_ACCESS_TOKEN，"
                "並於遠端部署設定至少 32 字元的 CHAT_PROXY_SESSION_SECRET。"
            ),
        )
    client_host = request.client.host if request.client else "unknown"
    if not _rate_limiter.allow(f"login:{client_host}", limit=8, window_seconds=300):
        raise HTTPException(status_code=429, detail="登入嘗試過多，請稍後再試。")
    body = await _request_json(request, 4096)
    supplied = body.get("access_code") if isinstance(body, dict) else None
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, _ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="存取碼不正確。")
    # Rotate the anonymous pre-login session ID to prevent session fixation.
    session_id = secrets.token_urlsafe(32)
    response = JSONResponse({"authenticated": True})
    _set_session_cookie(response, session_id, True, request)
    return response


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Do not reflect upstream exception text, request URLs, or auth details to
    # the browser. Operational diagnostics stay in server-side logs.
    import logging

    logging.getLogger(__name__).error(
        "Unhandled chat proxy error",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "parts": [{"kind": "text", "text": "服務暫時無法完成請求，請稍後再試。"}]
        },
    )


# Each signed browser session gets its own upstream context; entries expire.
_contexts: dict[str, tuple[str, float]] = {}
# Cache the agent card after the first fetch.
_card: AgentCard | None = None


async def _get_card(
    client: httpx.AsyncClient, a2a_base: str, card_url: str
) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(card_url)
        resp.raise_for_status()
        card = AgentCard(**resp.json())
        # Agent Runtime does not serve a public card URL, so point the client at
        # the passthrough base for message sends.
        card.url = a2a_base
        _card = card
    return _card


def _extract_parts(parts: list) -> list[dict]:
    """Pass text-only Help Agent replies to the chat UI."""
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if isinstance(root, TextPart) and getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
    return out


@app.post("/chat")
async def chat(req: Request):
    if not _same_origin(req):
        raise HTTPException(status_code=403, detail="跨來源聊天請求已拒絕。")
    if not _authorized_for_chat(req):
        config_missing = not _ACCESS_TOKEN_CONFIGURED or (
            _is_remote_request(req) and not _SESSION_SECRET_CONFIGURED
        )
        status = 503 if config_missing else 401
        raise HTTPException(status_code=status, detail="請先完成聊天存取驗證。")
    session = _request_session(req)
    if session is None:
        raise HTTPException(status_code=401, detail="聊天工作階段已失效，請重新整理頁面。")
    session_id = session[0]
    client_host = req.client.host if req.client else "unknown"
    if not _rate_limiter.allow(f"chat:{session_id}:{client_host}", limit=20, window_seconds=60):
        raise HTTPException(status_code=429, detail="訊息送出過於頻繁，請稍後再試。")
    body = await _request_json(req, 64 * 1024)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="聊天請求格式錯誤。")
    message = body.get("message", "")
    if not isinstance(message, str) or not message.strip() or len(message) > 8000:
        raise HTTPException(status_code=400, detail="訊息需為 1–8000 個字元。")
    if body.get("consent_to_cloud_processing") is not True:
        raise HTTPException(status_code=403, detail="請先同意將訊息傳送至 Google AI 服務處理。")
    a2a_base, card_url = _agent_endpoints()
    client_os = body.get("client_os")
    if client_os not in {"windows", "macos", "ios", "android", "linux", "unknown"}:
        client_os = "unknown"
    message = f"[使用者端作業系統：{client_os}]\n{message}"

    now = time.monotonic()
    for old_session, (_, expiry) in list(_contexts.items()):
        if expiry <= now:
            _contexts.pop(old_session, None)
    previous = _contexts.get(session_id)
    context_id = previous[0] if previous else None
    parts: list[dict] = []

    try:
        auth_headers = _auth_headers()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="AI 使用導覽的雲端認證尚未設定。",
        ) from exc

    async with httpx.AsyncClient(headers=auth_headers, timeout=120) as client:
        card = await _get_card(client, a2a_base, card_url)
        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=message))],
            context_id=context_id,
        )

        last_task = None
        got_artifact_update = False
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[session_id] = (
                        task.context_id,
                        time.monotonic() + 24 * 60 * 60,
                    )
            if isinstance(update, TaskArtifactUpdateEvent):
                got_artifact_update = True
                parts.extend(_extract_parts(update.artifact.parts))

        # Non-streaming fallback: pull parts from the final task's artifacts.
        if not got_artifact_update and last_task is not None:
            for artifact in getattr(last_task, "artifacts", None) or []:
                parts.extend(_extract_parts(artifact.parts))

    if not parts:
        # The turn produced no text or UI (e.g. the agent only ran tools, or a
        # tool stalled). Be honest rather than silent.
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    # The local OS connector must never be exposed to the LAN. Cloud Run still
    # binds all interfaces as required by the platform.
    local_device_mode = (
        os.environ.get("DEVICE_WIFI_LOCAL_MODE") == "1"
        and not os.environ.get("K_SERVICE")
    )
    host = "127.0.0.1" if local_device_mode else "0.0.0.0"
    uvicorn.run(app, host=host, port=int(os.environ.get("PORT", 8088)))
