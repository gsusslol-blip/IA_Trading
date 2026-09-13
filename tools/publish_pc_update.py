"""Build PC update ZIP and publish to GitHub Releases (CDN for ILARIA_UPDATE_URL)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import __version__  # noqa: E402
from tools.build_pc_update import build  # noqa: E402


def github_asset_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def latest_manifest_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/version.json"


def rewrite_manifest(manifest_path: Path, zip_url: str) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["zip_url"] = zip_url
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def run_gh(args: list[str]) -> None:
    cmd = ["gh", *args]
    print("[+] ", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Ilaria PC update to GitHub Releases")
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--repo", default=os.getenv("ILARIA_GITHUB_REPO", "").strip())
    parser.add_argument("--notes", default="")
    parser.add_argument("--out", default=str(ROOT / "dist" / "pc-update"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only build ZIP + version.json with GitHub URLs; do not call gh.",
    )
    parser.add_argument(
        "--skip-gh",
        action="store_true",
        help="Same as dry-run for publish step.",
    )
    args = parser.parse_args()
    version = args.version.strip()
    tag = f"pc-v{version}"
    zip_name = f"ilaria-pc-{version}.zip"
    repo = args.repo.strip()
    if not repo:
        print("[!] Pasá --repo dueño/repo o ILARIA_GITHUB_REPO=dueño/repo")
        print("    (sin remote todavía: usá --dry-run para generar los artefactos)")
        if not args.dry_run and not args.skip_gh:
            return 2
        # Placeholder URLs for local packaging
        zip_url = ""
    else:
        zip_url = github_asset_url(repo, tag, zip_name)

    out = Path(args.out)
    zip_path, manifest_path = build(out, version, zip_url, args.notes)
    if zip_url:
        rewrite_manifest(manifest_path, zip_url)
    else:
        # keep file:// from build
        pass

    print(f"[+] Artefactos en {out}")
    print(f"    ZIP: {zip_path.name}")
    print(f"    Manifest: {manifest_path.name}")
    if repo:
        print(f"[+] Clientes deben usar:")
        print(f"    ILARIA_UPDATE_URL={latest_manifest_url(repo)}")

    if args.dry_run or args.skip_gh:
        print("[+] dry-run: no se publicó a GitHub.")
        return 0

    # Require gh auth
    try:
        subprocess.run(["gh", "auth", "status"], check=True, cwd=str(ROOT))
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("[!] gh no está autenticado. Corré: gh auth login")
        print("    Los artefactos ya están listos para subir a mano.")
        return 3

    title = f"Ilaria PC {version}"
    body = args.notes or f"Incremental PC update {version} (código only, sin modelos)."
    # Create release if missing, then upload assets (clobber)
    list_proc = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if list_proc.returncode != 0:
        run_gh(
            [
                "release",
                "create",
                tag,
                str(zip_path),
                str(manifest_path),
                "--repo",
                repo,
                "--title",
                title,
                "--notes",
                body,
            ]
        )
    else:
        run_gh(
            [
                "release",
                "upload",
                tag,
                str(zip_path),
                str(manifest_path),
                "--repo",
                repo,
                "--clobber",
            ]
        )
    print(f"[+] Publicado: https://github.com/{repo}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
