"""Incremental PC code updates: fetch version.json + ZIP, never touch models/data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from jarvis import __version__ as LOCAL_VERSION

try:
    from jarvis.config import DATA_DIR, ROOT
except Exception:  # noqa: BLE001 — tooling/CI may lack dotenv
    ROOT = Path(__file__).resolve().parent.parent
    DATA_DIR = ROOT / "data"
    DATA_DIR.mkdir(exist_ok=True)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[.-].*)?$")

# Only these relative roots may be replaced from an update ZIP.
ALLOWED_TOP = frozenset(
    {
        "jarvis",
        "main.py",
        "requirements.txt",
        "run.bat",
        "check-phone-healing.bat",
        "build-apk.bat",
        "tools",
        "tests",
    }
)

SKIP_NAME_PARTS = (
    "__pycache__",
    ".pyc",
    ".pyo",
    ".venv",
    "data/",
    ".android-sdk",
    "android/app/build",
    "bin/piper",
)


@dataclass(frozen=True)
class RemoteManifest:
    version: str
    zip_url: str
    sha256: str
    notes: str = ""
    min_version: str = "0.0.0"
    release_date: str = ""
    changelog: tuple[str, ...] = ()
    min_required_android_client: str = "1.0.0"


@dataclass(frozen=True)
class UpdateResult:
    status: str  # skipped | up_to_date | updated | error
    message: str
    from_version: str = LOCAL_VERSION
    to_version: str = LOCAL_VERSION


def parse_version(raw: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match((raw or "").strip())
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def version_gt(left: str, right: str) -> bool:
    return parse_version(left) > parse_version(right)


def version_ge(left: str, right: str) -> bool:
    return parse_version(left) >= parse_version(right)


def update_url() -> str:
    """Public manifest URL. Empty = updates disabled."""
    return (os.getenv("ILARIA_UPDATE_URL") or "").strip()


def updates_dir() -> Path:
    folder = DATA_DIR / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def channel_cache_path() -> Path:
    return updates_dir() / "channel.json"


def save_channel_cache(manifest: RemoteManifest | dict[str, Any]) -> None:
    if isinstance(manifest, RemoteManifest):
        data = {
            "version": manifest.version,
            "download_url": manifest.zip_url,
            "zip_url": manifest.zip_url,
            "sha256": manifest.sha256,
            "release_date": manifest.release_date,
            "changelog": list(manifest.changelog),
            "min_required_android_client": manifest.min_required_android_client,
            "min_version": manifest.min_version,
            "notes": manifest.notes,
        }
    else:
        data = dict(manifest)
    channel_cache_path().write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_channel_cache() -> dict[str, Any]:
    path = channel_cache_path()
    if not path.is_file():
        bundled = Path(__file__).resolve().parent / "channel.json"
        if bundled.is_file():
            return json.loads(bundled.read_text(encoding="utf-8"))
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def min_required_android_client() -> str:
    data = load_channel_cache()
    return str(data.get("min_required_android_client") or "1.0.0").strip() or "1.0.0"


def _fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    if url.lower().startswith("file:"):
        parsed = urlparse(url)
        path = Path(url2pathname(parsed.path))
        if not path.is_file():
            raise FileNotFoundError(url)
        return path.read_bytes()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Ilaria-Updater/{LOCAL_VERSION}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_manifest(raw: bytes | str | dict[str, Any]) -> RemoteManifest:
    if isinstance(raw, dict):
        data = raw
    else:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        data = json.loads(text)
    version = str(data.get("version") or "").strip()
    zip_url = str(
        data.get("zip_url") or data.get("download_url") or data.get("url") or ""
    ).strip()
    sha256 = str(data.get("sha256") or "").strip().lower()
    if not version or not zip_url:
        raise ValueError("version.json incompleto (version + download_url/zip_url).")
    changelog_raw = data.get("changelog") or []
    if isinstance(changelog_raw, str):
        changelog = (changelog_raw,) if changelog_raw.strip() else ()
    else:
        changelog = tuple(str(item).strip() for item in changelog_raw if str(item).strip())
    notes = str(data.get("notes") or "").strip()
    if not notes and changelog:
        notes = "; ".join(changelog)
    return RemoteManifest(
        version=version,
        zip_url=zip_url,
        sha256=sha256,
        notes=notes,
        min_version=str(data.get("min_version") or "0.0.0"),
        release_date=str(data.get("release_date") or ""),
        changelog=changelog,
        min_required_android_client=str(
            data.get("min_required_android_client") or "1.0.0"
        ).strip()
        or "1.0.0",
    )


def fetch_manifest(url: str | None = None) -> RemoteManifest:
    target = (url or update_url()).strip()
    if not target:
        raise ValueError("ILARIA_UPDATE_URL no configurada.")
    return load_manifest(_fetch_bytes(target))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_rel(path: str) -> Path | None:
    cleaned = path.replace("\\", "/").lstrip("/")
    if not cleaned or cleaned.endswith("/"):
        return None
    if ".." in cleaned.split("/"):
        return None
    lower = cleaned.lower()
    if any(part in lower for part in SKIP_NAME_PARTS):
        return None
    top = cleaned.split("/", 1)[0]
    if top not in ALLOWED_TOP and cleaned not in ALLOWED_TOP:
        return None
    return Path(cleaned)


def apply_zip(zip_path: Path, root: Path | None = None, expected_sha: str = "") -> list[str]:
    """Extract allowlisted files onto the install root. Returns written relative paths."""
    install = (root or ROOT).resolve()
    if expected_sha:
        got = sha256_file(zip_path)
        if got.lower() != expected_sha.lower():
            raise ValueError(f"SHA256 no coincide: {got} != {expected_sha}")

    written: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            rel = _safe_rel(info.filename)
            if rel is None:
                continue
            dest = (install / rel).resolve()
            if not str(dest).startswith(str(install)):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            written.append(rel.as_posix())
    if not written:
        raise ValueError("El ZIP no tenia archivos permitidos.")
    return written


def backup_paths(paths: list[str], root: Path | None = None) -> Path:
    install = (root or ROOT).resolve()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = updates_dir() / f"backup-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    for rel in paths:
        src = install / rel
        if not src.is_file():
            continue
        dest = backup / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    (backup / "manifest.json").write_text(
        json.dumps({"from_version": LOCAL_VERSION, "files": paths}, indent=2),
        encoding="utf-8",
    )
    return backup


def check_and_apply(*, force: bool = False, manifest_url: str | None = None) -> UpdateResult:
    """
    If ILARIA_UPDATE_URL is set and remote version is newer, download + apply ZIP.
    Never deletes data/, .venv, models, or .env.
    """
    url = (manifest_url if manifest_url is not None else update_url()).strip()
    if not url:
        return UpdateResult("skipped", "Updates desactivados (sin ILARIA_UPDATE_URL).")

    try:
        remote = fetch_manifest(url)
    except Exception as exc:  # noqa: BLE001 — soft-fail on boot
        return UpdateResult("error", f"No pude leer version.json: {exc}")

    try:
        save_channel_cache(remote)
    except OSError:
        pass

    if not force and not version_gt(remote.version, LOCAL_VERSION):
        return UpdateResult(
            "up_to_date",
            f"Ya estas en v{LOCAL_VERSION} (remoto {remote.version}).",
            to_version=remote.version,
        )

    if version_gt(remote.min_version, LOCAL_VERSION):
        return UpdateResult(
            "error",
            f"Esta instalacion (v{LOCAL_VERSION}) es muy vieja; minimo {remote.min_version}.",
            to_version=remote.version,
        )

    try:
        zip_bytes = _fetch_bytes(remote.zip_url, timeout=120.0)
    except Exception as exc:  # noqa: BLE001
        return UpdateResult("error", f"No pude bajar el ZIP: {exc}", to_version=remote.version)

    folder = updates_dir()
    zip_path = folder / f"ilaria-{remote.version}.zip"
    zip_path.write_bytes(zip_bytes)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            planned = [p.as_posix() for name in zf.namelist() if (p := _safe_rel(name)) is not None]
        if not planned:
            raise ValueError("ZIP vacio o sin rutas permitidas.")
        backup_paths(planned)
        apply_zip(zip_path, expected_sha=remote.sha256)
    except Exception as exc:  # noqa: BLE001
        return UpdateResult("error", f"Fallo al aplicar update: {exc}", to_version=remote.version)

    state = {
        "applied_version": remote.version,
        "previous_version": LOCAL_VERSION,
        "notes": remote.notes,
        "at": time.time(),
    }
    (folder / "last_apply.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return UpdateResult(
        "updated",
        f"Actualizado {LOCAL_VERSION} → {remote.version}. Reinicio del proceso recomendado.",
        from_version=LOCAL_VERSION,
        to_version=remote.version,
    )


def maybe_update_on_boot() -> UpdateResult:
    """Called from main.py. Opt-in via env; never blocks boot on network errors."""
    enabled = (os.getenv("ILARIA_AUTO_UPDATE") or "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return UpdateResult("skipped", "ILARIA_AUTO_UPDATE=off")
    result = check_and_apply()
    print(f"[updater] {result.status}: {result.message}")
    return result


def build_manifest_dict(
    version: str,
    zip_url: str,
    sha256: str,
    notes: str = "",
    *,
    changelog: list[str] | None = None,
    min_required_android_client: str = "1.5.4",
    release_date: str = "",
) -> dict[str, Any]:
    items = changelog if changelog is not None else ([notes] if notes else [])
    return {
        "version": version,
        "release_date": release_date or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "changelog": items,
        "download_url": zip_url,
        "zip_url": zip_url,
        "sha256": sha256,
        "min_version": "1.4.0",
        "min_required_android_client": min_required_android_client,
        "notes": notes or "; ".join(items),
    }
