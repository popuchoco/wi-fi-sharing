"""Narrow Windows UAC helper: reveal one selected profile and emit one QR PNG.

This process has no HTTP listener, Google credentials, chat proxy, or Cloud
Storage client. The only result it writes is an ephemeral Wi-Fi QR image.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from device_wifi import WindowsWifiAdapter, make_wifi_qr_png


def _validated_output_path(raw_path: str) -> Path:
    temp_root = Path(tempfile.gettempdir()).resolve()
    output = Path(raw_path).resolve()
    parent = output.parent
    if (
        output.name != "result.png"
        or parent.parent != temp_root
        or not parent.name.startswith("wifi-share-")
    ):
        raise ValueError("Output path must be the one-shot Wi-Fi temp target.")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        output = _validated_output_path(args.output)
        qr_png = make_wifi_qr_png(WindowsWifiAdapter().reveal_profile(args.profile_id))
        output.write_bytes(qr_png)
        return 0
    except Exception:
        # Never print profile data, key material, or the generated QR payload.
        return 1


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Windows-only helper")
    raise SystemExit(main())
