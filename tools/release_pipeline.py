"""Release pipeline: build ZIP + version.json shaped for GitHub Releases CDN."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import __version__  # noqa: E402
from jarvis.pc_updater import build_manifest_dict, sha256_file  # noqa: E402
from tools.build_pc_update import build  # noqa: E402


def github_download_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def latest_version_json_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/version.json"


def run_pipeline(
    *,
    version: str,
    repo: str,
    notes: str,
    changelog: list[str],
    min_android: str,
    out_dir: Path,
) -> tuple[Path, Path, dict]:
    tag = f"pc-v{version}"
    zip_name = f"ilaria-pc-{version}.zip"
    zip_url = github_download_url(repo, tag, zip_name) if repo else ""
    zip_path, manifest_path = build(out_dir, version, zip_url, notes)
    digest = sha256_file(zip_path)
    if not zip_url:
        zip_url = zip_path.resolve().as_uri()
    manifest = build_manifest_dict(
        version,
        zip_url,
        digest,
        notes=notes,
        changelog=changelog or ([notes] if notes else []),
        min_required_android_client=min_android,
    )
    # Keep both keys for older/newer updaters
    manifest["download_url"] = zip_url
    manifest["zip_url"] = zip_url
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Mirror channel hint into jarvis package for installs without remote fetch yet
    channel = {
        "version": version,
        "min_required_android_client": min_android,
        "changelog": manifest.get("changelog") or [],
    }
    (ROOT / "jarvis" / "channel.json").write_text(
        json.dumps(channel, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return zip_path, manifest_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Ilaria PC release pipeline (GitHub CDN)")
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--repo", default=os.getenv("ILARIA_GITHUB_REPO", "").strip())
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--changelog",
        action="append",
        default=[],
        help="Repeatable changelog bullet",
    )
    parser.add_argument("--min-android", default="1.5.4")
    parser.add_argument("--out", default=str(ROOT / "dist" / "pc-update"))
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Also call tools/publish_pc_update.py (needs gh auth + --repo)",
    )
    args = parser.parse_args()
    version = args.version.strip()
    repo = args.repo.strip()
    zip_path, man_path, manifest = run_pipeline(
        version=version,
        repo=repo,
        notes=args.notes,
        changelog=list(args.changelog),
        min_android=args.min_android,
        out_dir=Path(args.out),
    )
    print(f"[+] ZIP: {zip_path} ({zip_path.stat().st_size} bytes)")
    print(f"[+] Manifest: {man_path}")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if repo:
        print(f"[+] Clientes (.env):")
        print(f"    ILARIA_UPDATE_URL={latest_version_json_url(repo)}")
        print(f"    ILARIA_AUTO_UPDATE=1")
    if args.publish:
        if not repo:
            print("[!] --publish requiere --repo dueño/repo")
            return 2
        from tools.publish_pc_update import main as publish_main

        sys.argv = [
            "publish_pc_update.py",
            "--version",
            version,
            "--repo",
            repo,
            "--notes",
            args.notes or f"PC {version}",
            "--out",
            args.out,
        ]
        return publish_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
