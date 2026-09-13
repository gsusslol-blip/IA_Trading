"""Serve the latest Android APK from dist/ for LAN in-app updates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jarvis.config import ROOT

_CODE = re.compile(r"versionCode\s*=\s*(\d+)")
_NAME = re.compile(r'versionName\s*=\s*"([^"]+)"')


def apk_path() -> Path:
    return ROOT / "dist" / "Ilaria-android.apk"


def advertised() -> dict[str, Any]:
    gradle = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    code_m = _CODE.search(gradle)
    name_m = _NAME.search(gradle)
    code = int(code_m.group(1)) if code_m else 0
    name = name_m.group(1) if name_m else "0"
    path = apk_path()
    ready = path.is_file() and path.stat().st_size > 100_000
    return {
        "app": "Ilaria",
        "versionCode": code,
        "versionName": name,
        "ready": ready,
        "bytes": path.stat().st_size if ready else 0,
        "apk": "/api/android/apk",
    }
