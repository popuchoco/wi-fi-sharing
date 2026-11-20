import asyncio

import pytest
from fastapi import HTTPException, Request

import frontend.device_wifi as device_wifi
from frontend.device_wifi import (
    WifiCredentials,
    _decode_wifi_profile_id,
    _wifi_profile_id,
    detect_client_os,
    make_wifi_qr_png,
    normalize_os,
    parse_profile_xml,
)


def test_normalize_os_platform_labels():
    assert normalize_os('"Windows"') == "windows"
    assert normalize_os("iPhone") == "ios"
    assert normalize_os("MacIntel") == "macos"
    assert normalize_os("Android") == "android"


def test_detect_client_os_prefers_client_platform_header():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/device/wifi/identity",
            "headers": [(b"x-device-os", b"Android"), (b"user-agent", b"Windows")],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 43210),
            "scheme": "http",
        }
    )
    assert detect_client_os(request) == "android"


def test_wifi_profile_id_round_trip():
    interface_id = "a5b4736a-28a6-4f10-9e4b-5d2d37d0af64"
    profile_id = _wifi_profile_id(interface_id, "Guest:Net;5G")
    assert _decode_wifi_profile_id(profile_id) == (interface_id, "Guest:Net;5G")


def test_windows_adapter_exposes_saved_profile_operations():
    assert callable(device_wifi.WindowsWifiAdapter.profiles)
    assert callable(device_wifi.WindowsWifiAdapter.reveal_profile)


def test_protected_profile_uses_narrow_elevation_helper(monkeypatch):
    class ProtectedAdapter:
        def reveal_profile(self, _profile_id):
            raise device_wifi.PermissionRequired("elevation required")

    profile_id = _wifi_profile_id(
        "a5b4736a-28a6-4f10-9e4b-5d2d37d0af64", "Guest"
    )
    monkeypatch.setattr(device_wifi, "_adapter", lambda: ProtectedAdapter())
    monkeypatch.setattr(
        device_wifi, "_run_narrow_elevated_qr_helper", lambda value: value.encode()
    )

    assert device_wifi._create_profile_qr(profile_id) == profile_id.encode()


def test_parse_windows_profile_xml():
    xml = """<?xml version="1.0"?>
    <WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
      <name>Work WiFi</name>
      <SSIDConfig><SSID><name>Work;WiFi</name></SSID><nonBroadcast>true</nonBroadcast></SSIDConfig>
      <MSM><security><authEncryption>
        <authentication>WPA2PSK</authentication>
        <encryption>AES</encryption>
      </authEncryption><sharedKey><keyMaterial>correct-horse-battery</keyMaterial></sharedKey></security></MSM>
    </WLANProfile>"""
    assert parse_profile_xml(xml) == WifiCredentials(
        ssid="Work;WiFi",
        password="correct-horse-battery",
        security_type="WPA2",
        hidden=True,
    )


def test_generate_qr_png_in_memory():
    image = make_wifi_qr_png(
        WifiCredentials("Cafe;Guest", "p:ass,word", "WPA2", False)
    )
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_os_mismatch_stops_before_system_api(monkeypatch):
    monkeypatch.setenv("DEVICE_WIFI_LOCAL_MODE", "1")
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(device_wifi.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        device_wifi,
        "_adapter",
        lambda: (_ for _ in ()).throw(AssertionError("system API must not run")),
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/device/wifi/current",
            "headers": [
                (b"x-device-os", b"Android"),
                (b"origin", b"http://localhost:8088"),
            ],
            "query_string": b"",
            "server": ("localhost", 8088),
            "client": ("127.0.0.1", 43210),
            "scheme": "http",
        }
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(device_wifi.device_wifi_current(request))
    assert error.value.status_code == 409
