"""Build an incremental PC update ZIP + version.json (no models, no data/)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import __version__  # noqa: E402
from jarvis.pc_updater import ALLOWED_TOP, build_manifest_dict  # noqa: E402

INCLUDE_FILES = ("main.py", "requirements.txt", "run.bat")
INCLUDE_DIRS = ("jarvis", "tools", "tests")


def _should_skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if "__pycache__" in parts or ".pyc" in path.suffix.lower():
        return True
    if "data" in parts or ".venv" in parts or ".android-sdk" in parts:
        return True
    if path.name.endswith(".pyc"):
        return True
    return False


def collect_files() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    for folder in INCLUDE_DIRS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not _should_skip(path):
                # only allowlisted tops
                rel = path.relative_to(ROOT).as_posix()
                top = rel.split("/", 1)[0]
                if top in ALLOWED_TOP or rel in ALLOWED_TOP:
                    files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def build(out_dir: Path, version: str, zip_url: str, notes: str, min_android: str = "1.5.4") -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"ilaria-pc-{version}.zip"
    files = collect_files()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            zf.write(path, rel)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest = build_manifest_dict(
        version,
        zip_url or zip_path.resolve().as_uri(),
        digest,
        notes,
        min_required_android_client=min_android,
    )
    manifest_path = out_dir / "version.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return zip_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Ilaria PC incremental update")
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--out", default=str(ROOT / "dist" / "pc-update"))
    parser.add_argument(
        "--zip-url",
        default="",
        help="Public URL where the ZIP will be hosted. Default: local file:// URI.",
    )
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    zip_path, manifest_path = build(Path(args.out), args.version, args.zip_url, args.notes)
    print(f"[+] ZIP: {zip_path} ({zip_path.stat().st_size} bytes)")
    print(f"[+] Manifest: {manifest_path}")
    print(manifest_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
