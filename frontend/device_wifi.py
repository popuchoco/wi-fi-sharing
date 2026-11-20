# ruff: noqa: RUF001 -- Traditional Chinese punctuation is intentional.
"""Local, user-approved Wi-Fi access through the host operating system.

The browser identifies its platform first. These routes are only available when
the frontend is explicitly run as a loopback-only local app; they are disabled
on Agent Engine / Cloud Run so a cloud server can never inspect a visitor's Wi-Fi.
The Windows adapter uses Native Wi-Fi (wlanapi.dll), not shell output parsing.
"""

from __future__ import annotations

import base64
import ctypes
import ipaddress
import os
import platform
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()

_PLAINTEXT_KEY_FLAG = 0x00000004  # WLAN_PROFILE_GET_PLAINTEXT_KEY
_CURRENT_CONNECTION_OPCODE = 7  # wlan_intf_opcode_current_connection
_CONNECTED_STATE = 1  # wlan_interface_state_connected


class WifiBridgeError(RuntimeError):
    """A safe-to-display error from the local OS adapter."""


class PermissionRequired(WifiBridgeError):
    """The OS refused to reveal a profile key without elevated permission."""


@dataclass(frozen=True)
class WifiProfile:
    profile_id: str
    name: str
    interface_id: str


@dataclass(frozen=True)
class WifiCredentials:
    ssid: str
    password: str
    security_type: str
    hidden: bool


def normalize_os(value: str | None) -> str:
    value = (value or "").strip().strip('"').lower()
    if "windows" in value or value.startswith("win"):
        return "windows"
    if "iphone" in value or "ipad" in value or value == "ios":
        return "ios"
    if "android" in value:
        return "android"
    if "mac" in value or "darwin" in value:
        return "macos"
    if "linux" in value or "x11" in value:
        return "linux"
    return "unknown"


def detect_client_os(request: Request) -> str:
    """Read the browser's platform hint, falling back to its user-agent string."""
    platform_hint = request.headers.get("x-device-os") or request.headers.get(
        "sec-ch-ua-platform"
    )
    if platform_hint:
        detected = normalize_os(platform_hint)
        if detected != "unknown":
            return detected

    agent = request.headers.get("user-agent", "").lower()
    if "ipad" in agent or "iphone" in agent or "ipod" in agent:
        return "ios"
    if "android" in agent:
        return "android"
    if "windows" in agent or "win64" in agent or "win32" in agent:
        return "windows"
    if "macintosh" in agent or "mac os" in agent:
        return "macos"
    if "linux" in agent or "x11" in agent:
        return "linux"
    return "unknown"


def _assert_local_request(request: Request) -> None:
    """Protect device APIs from remote callers and cross-origin websites."""
    if os.environ.get("DEVICE_WIFI_LOCAL_MODE") != "1" or os.environ.get("K_SERVICE"):
        raise HTTPException(status_code=404, detail="本機 Wi-Fi 連接器未啟用。")

    client_host = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(client_host).is_loopback:
            raise HTTPException(status_code=403, detail="僅允許本機存取。")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="僅允許本機存取。") from exc

    origin = request.headers.get("origin")
    if origin:
        origin_host = urlparse(origin).hostname or ""
        if origin_host not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(status_code=403, detail="不允許跨來源存取。")


def _assert_matching_windows_client(request: Request) -> None:
    _assert_local_request(request)
    client_os = detect_client_os(request)
    host_os = normalize_os(platform.system())
    if client_os != host_os:
        raise HTTPException(
            status_code=409,
            detail=(
                f"瀏覽器裝置是 {client_os}，本機連接器執行於 {host_os}；"
                "為避免讀取錯誤裝置，未呼叫 Wi-Fi 系統 API。"
            ),
        )
    if host_os != "windows":
        raise HTTPException(
            status_code=501,
            detail=f"目前已接入 Windows Wi-Fi 系統 API；{host_os} 連接器尚未啟用。",
        )


def _wifi_profile_id(interface_id: str, name: str) -> str:
    raw = f"{interface_id}\0{name}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_wifi_profile_id(profile_id: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(profile_id + "=" * (-len(profile_id) % 4))
        interface_id, name = raw.decode("utf-8").split("\0", 1)
        uuid.UUID(interface_id)
        if not name or len(name) > 256:
            raise ValueError("Invalid profile name")
        return interface_id, name
    except (ValueError, UnicodeDecodeError) as exc:
        raise WifiBridgeError("無效的 Wi-Fi 設定檔識別碼。") from exc


def parse_profile_xml(xml: str) -> WifiCredentials:
    """Extract one selected profile's credentials from Native Wi-Fi XML."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise WifiBridgeError("Windows 回傳的 Wi-Fi 設定檔格式無法解析。") from exc

    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    def text(path: str, default: str = "") -> str:
        element = root.find(path)
        return (element.text or "").strip() if element is not None else default

    ssid = text(f".//{namespace}SSIDConfig/{namespace}SSID/{namespace}name")
    if not ssid:
        ssid = text(f"{namespace}name")
    if not ssid:
        raise WifiBridgeError("選取的設定檔沒有可用的 SSID。")

    auth = text(f".//{namespace}MSM/{namespace}security/{namespace}authEncryption/{namespace}authentication").upper()
    key = text(f".//{namespace}MSM/{namespace}security/{namespace}sharedKey/{namespace}keyMaterial")
    hidden = text(f".//{namespace}SSIDConfig/{namespace}nonBroadcast", "false").lower() == "true"

    if auth == "OPEN" and not key:
        security_type = "nopass"
    elif "WPA3" in auth or "SAE" in auth:
        security_type = "WPA3"
    elif "WPA2" in auth:
        security_type = "WPA2"
    else:
        security_type = "WPA"

    return WifiCredentials(
        ssid=ssid,
        password=key,
        security_type=security_type,
        hidden=hidden,
    )


def _profile_authentication(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise WifiBridgeError("Windows 回傳的 Wi-Fi 設定檔格式無法解析。") from exc
    namespace = root.tag.split("}", 1)[0] + "}" if root.tag.startswith("{") else ""
    auth = root.find(
        f".//{namespace}MSM/{namespace}security/{namespace}authEncryption/{namespace}authentication"
    )
    return (auth.text or "").strip().upper() if auth is not None else ""


def _wifi_escape(value: str) -> str:
    return "".join(f"\\{char}" if char in "\\;,:\"" else char for char in value)


def make_wifi_qr_png(credentials: WifiCredentials) -> bytes:
    """Generate a QR image in memory; credentials are never uploaded to GCS."""
    try:
        import io

        import qrcode
    except ImportError as exc:
        raise WifiBridgeError("缺少 qrcode 套件，請先安裝 frontend/requirements.txt。") from exc

    payload = (
        f"WIFI:T:{_wifi_escape(credentials.security_type)};"
        f"S:{_wifi_escape(credentials.ssid)};"
        f"P:{_wifi_escape(credentials.password)};"
        f"H:{str(credentials.hidden).lower()};;"
    )
    image = qrcode.make(payload)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


if os.name == "nt":
    from ctypes import wintypes

    class _Guid(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class _Dot11Ssid(ctypes.Structure):
        _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]

    class _WlanAssociationAttributes(ctypes.Structure):
        _fields_ = [
            ("dot11Ssid", _Dot11Ssid),
            ("dot11BssType", wintypes.DWORD),
            ("dot11Bssid", ctypes.c_ubyte * 6),
            ("dot11PhyType", wintypes.DWORD),
            ("uDot11PhyIndex", wintypes.DWORD),
            ("wlanSignalQuality", wintypes.DWORD),
            ("ulRxRate", wintypes.DWORD),
            ("ulTxRate", wintypes.DWORD),
        ]

    class _WlanSecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("bSecurityEnabled", wintypes.BOOL),
            ("bOneXEnabled", wintypes.BOOL),
            ("dot11AuthAlgorithm", wintypes.DWORD),
            ("dot11CipherAlgorithm", wintypes.DWORD),
        ]

    class _WlanConnectionAttributes(ctypes.Structure):
        _fields_ = [
            ("isState", wintypes.DWORD),
            ("wlanConnectionMode", wintypes.DWORD),
            ("strProfileName", wintypes.WCHAR * 256),
            ("wlanAssociationAttributes", _WlanAssociationAttributes),
            ("wlanSecurityAttributes", _WlanSecurityAttributes),
        ]

    class _WlanInterfaceInfo(ctypes.Structure):
        _fields_ = [
            ("InterfaceGuid", _Guid),
            ("strInterfaceDescription", wintypes.WCHAR * 256),
            ("isState", wintypes.DWORD),
        ]

    class _WlanInterfaceInfoList(ctypes.Structure):
        _fields_ = [
            ("dwNumberOfItems", wintypes.DWORD),
            ("dwIndex", wintypes.DWORD),
            ("InterfaceInfo", _WlanInterfaceInfo * 1),
        ]

    class _WlanProfileInfo(ctypes.Structure):
        _fields_ = [("strProfileName", wintypes.WCHAR * 256), ("dwFlags", wintypes.DWORD)]

    class _WlanProfileInfoList(ctypes.Structure):
        _fields_ = [
            ("dwNumberOfItems", wintypes.DWORD),
            ("dwIndex", wintypes.DWORD),
            ("ProfileInfo", _WlanProfileInfo * 1),
        ]


class WindowsWifiAdapter:
    """Thin Native Wi-Fi API wrapper for Windows desktop installations."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise WifiBridgeError("Windows Wi-Fi API 只能在 Windows 上使用。")
        self._api = ctypes.WinDLL("wlanapi.dll")  # type: ignore[attr-defined]
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        api = self._api
        api.WlanOpenHandle.restype = ctypes.c_uint32
        api.WlanOpenHandle.argtypes = [
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        api.WlanCloseHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        api.WlanEnumInterfaces.restype = ctypes.c_uint32
        api.WlanEnumInterfaces.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        api.WlanGetProfileList.restype = ctypes.c_uint32
        api.WlanGetProfileList.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Guid),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        api.WlanGetProfile.restype = ctypes.c_uint32
        api.WlanGetProfile.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Guid),
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        api.WlanQueryInterface.restype = ctypes.c_uint32
        api.WlanQueryInterface.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Guid),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        api.WlanFreeMemory.argtypes = [ctypes.c_void_p]

    def _open(self) -> ctypes.c_void_p:
        handle = ctypes.c_void_p()
        negotiated = ctypes.c_uint32()
        result = self._api.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle))
        if result:
            raise WifiBridgeError(f"Windows WLAN API 初始化失敗（錯誤碼 {result}）。")
        return handle

    @staticmethod
    def _interface_id(interface: Any) -> str:
        raw = ctypes.string_at(ctypes.byref(interface.InterfaceGuid), ctypes.sizeof(_Guid))
        return str(uuid.UUID(bytes_le=raw))

    @staticmethod
    def _guid_from_id(interface_id: str) -> Any:
        try:
            return _Guid.from_buffer_copy(uuid.UUID(interface_id).bytes_le)
        except ValueError as exc:
            raise WifiBridgeError("無效的無線網路介面識別碼。") from exc

    def _interfaces(self, handle: ctypes.c_void_p) -> list[tuple[str, Any]]:
        pointer = ctypes.c_void_p()
        result = self._api.WlanEnumInterfaces(handle, None, ctypes.byref(pointer))
        if result:
            raise WifiBridgeError(f"無法列舉 Wi-Fi 介面（錯誤碼 {result}）。")
        try:
            listing = ctypes.cast(pointer, ctypes.POINTER(_WlanInterfaceInfoList)).contents
            base = ctypes.addressof(listing)
            offset = _WlanInterfaceInfoList.InterfaceInfo.offset
            items = []
            for index in range(listing.dwNumberOfItems):
                address = base + offset + index * ctypes.sizeof(_WlanInterfaceInfo)
                item = ctypes.cast(address, ctypes.POINTER(_WlanInterfaceInfo)).contents
                items.append((self._interface_id(item), _Guid.from_buffer_copy(
                    ctypes.string_at(ctypes.byref(item.InterfaceGuid), ctypes.sizeof(_Guid))
                )))
            return items
        finally:
            self._api.WlanFreeMemory(pointer)

    def current_connection(self) -> dict[str, str] | None:
        handle = self._open()
        try:
            for interface_id, guid in self._interfaces(handle):
                size = ctypes.c_uint32()
                data = ctypes.c_void_p()
                value_type = ctypes.c_uint32()
                result = self._api.WlanQueryInterface(
                    handle,
                    ctypes.byref(guid),
                    _CURRENT_CONNECTION_OPCODE,
                    None,
                    ctypes.byref(size),
                    ctypes.byref(data),
                    ctypes.byref(value_type),
                )
                if result:
                    continue  # disconnected adapters return ERROR_INVALID_STATE
                try:
                    connection = ctypes.cast(
                        data, ctypes.POINTER(_WlanConnectionAttributes)
                    ).contents
                    if connection.isState != _CONNECTED_STATE:
                        continue
                    ssid_info = connection.wlanAssociationAttributes.dot11Ssid
                    raw_ssid = bytes(ssid_info.ucSSID[: ssid_info.uSSIDLength])
                    return {
                        "ssid": raw_ssid.decode("utf-8", errors="replace"),
                        "profile_name": connection.strProfileName,
                        "interface_id": interface_id,
                    }
                finally:
                    self._api.WlanFreeMemory(data)
            return None
        finally:
            self._api.WlanCloseHandle(handle, None)

    def profiles(self) -> list[WifiProfile]:
        handle = self._open()
        try:
            profiles: list[WifiProfile] = []
            for interface_id, guid in self._interfaces(handle):
                pointer = ctypes.c_void_p()
                result = self._api.WlanGetProfileList(
                    handle, ctypes.byref(guid), None, ctypes.byref(pointer)
                )
                if result:
                    raise WifiBridgeError(f"無法讀取 Wi-Fi 設定檔清單（錯誤碼 {result}）。")
                try:
                    listing = ctypes.cast(pointer, ctypes.POINTER(_WlanProfileInfoList)).contents
                    base = ctypes.addressof(listing)
                    offset = _WlanProfileInfoList.ProfileInfo.offset
                    for index in range(listing.dwNumberOfItems):
                        address = base + offset + index * ctypes.sizeof(_WlanProfileInfo)
                        item = ctypes.cast(address, ctypes.POINTER(_WlanProfileInfo)).contents
                        name = item.strProfileName
                        profiles.append(
                            WifiProfile(
                                profile_id=_wifi_profile_id(interface_id, name),
                                name=name,
                                interface_id=interface_id,
                            )
                        )
                finally:
                    self._api.WlanFreeMemory(pointer)
            return profiles
        finally:
            self._api.WlanCloseHandle(handle, None)

    def reveal_profile(self, profile_id: str) -> WifiCredentials:
        interface_id, name = _decode_wifi_profile_id(profile_id)
        handle = self._open()
        xml_pointer = ctypes.c_wchar_p()
        try:
            guid = self._guid_from_id(interface_id)
            # First retrieve profile metadata without requesting the protected
            # key. Open networks can be shared without any elevated access.
            flags = ctypes.c_uint32(0)
            granted_access = ctypes.c_uint32()
            result = self._api.WlanGetProfile(
                handle,
                ctypes.byref(guid),
                name,
                None,
                ctypes.byref(xml_pointer),
                ctypes.byref(flags),
                ctypes.byref(granted_access),
            )
            if result == 5:  # ERROR_ACCESS_DENIED
                raise PermissionRequired(
                    "Windows 不允許此程序讀取所選 Wi-Fi 設定檔。"
                )
            if result:
                raise WifiBridgeError(f"無法讀取所選 Wi-Fi 設定檔（錯誤碼 {result}）。")
            metadata_xml = ctypes.wstring_at(xml_pointer)
            self._api.WlanFreeMemory(ctypes.cast(xml_pointer, ctypes.c_void_p))
            xml_pointer = ctypes.c_wchar_p()

            auth = _profile_authentication(metadata_xml)
            if auth == "OPEN":
                return parse_profile_xml(metadata_xml)

            # Windows grants plaintext-key access to local Administrators by
            # default. Do not request it for a non-elevated process.
            if not ctypes.windll.shell32.IsUserAnAdmin():  # type: ignore[attr-defined]
                raise PermissionRequired(
                    "Windows 需要系統管理員權限才能讀取此網路的明文密碼；目前版本不會提權聊天 Proxy。請使用 Windows 系統分享流程，或等待獨立的限權授權工具。"
                )

            flags = ctypes.c_uint32(_PLAINTEXT_KEY_FLAG)
            result = self._api.WlanGetProfile(
                handle,
                ctypes.byref(guid),
                name,
                None,
                ctypes.byref(xml_pointer),
                ctypes.byref(flags),
                ctypes.byref(granted_access),
            )
            if result == 5:
                raise PermissionRequired(
                    "Windows 不允許此程序讀取明文 Wi-Fi 金鑰；目前版本不會提權聊天 Proxy。請使用 Windows 系統分享流程。"
                )
            if result:
                raise WifiBridgeError(f"無法讀取所選 Wi-Fi 設定檔（錯誤碼 {result}）。")
            return parse_profile_xml(ctypes.wstring_at(xml_pointer))
        finally:
            if xml_pointer:
                self._api.WlanFreeMemory(ctypes.cast(xml_pointer, ctypes.c_void_p))
            self._api.WlanCloseHandle(handle, None)


def _adapter() -> WindowsWifiAdapter:
    try:
        return WindowsWifiAdapter()
    except OSError as exc:
        raise WifiBridgeError("無法載入 Windows Native Wi-Fi API。") from exc


@router.get("/device/wifi/identity")
async def device_wifi_identity(request: Request) -> dict[str, Any]:
    _assert_local_request(request)
    client_os = detect_client_os(request)
    host_os = normalize_os(platform.system())
    return {
        "client_os": client_os,
        "host_os": host_os,
        "os_matches": client_os == host_os,
        "adapter": "windows-wlanapi" if host_os == "windows" else None,
        "current_connection": client_os == host_os and host_os == "windows",
        "saved_profile_names": client_os == host_os and host_os == "windows",
        "credential_reveal": client_os == host_os and host_os == "windows",
    }


@router.get("/device/wifi/current")
async def device_wifi_current(request: Request) -> dict[str, Any]:
    _assert_matching_windows_client(request)
    try:
        current = _adapter().current_connection()
        return {"connected": current is not None, "network": current}
    except WifiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/device/wifi/profiles")
async def device_wifi_profiles(request: Request) -> dict[str, Any]:
    _assert_matching_windows_client(request)
    try:
        current = _adapter().current_connection()
        profiles = _adapter().profiles()
        return {
            "profiles": [
                {
                    "id": item.profile_id,
                    "name": item.name,
                    "is_current": bool(
                        current
                        and current["interface_id"] == item.interface_id
                        and current["profile_name"] == item.name
                    ),
                }
                for item in profiles
            ]
        }
    except WifiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/device/wifi/profiles/{profile_id}/qr")
async def device_wifi_profile_qr(
    profile_id: str, request: Request
) -> Response:
    _assert_matching_windows_client(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="請求內容格式錯誤。") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="請求內容格式錯誤。")
    if body.get("confirmed") is not True:
        raise HTTPException(
            status_code=400,
            detail="請先明確確認要分享所選 Wi-Fi 網路。",
        )
    try:
        credentials = _adapter().reveal_profile(profile_id)
        png = make_wifi_qr_png(credentials)
    except PermissionRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WifiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )
