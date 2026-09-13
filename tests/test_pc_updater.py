"""PC incremental updater tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.pc_updater import (  # noqa: E402
    apply_zip,
    check_and_apply,
    load_manifest,
    parse_version,
    sha256_file,
    version_gt,
)


class PcUpdaterTests(unittest.TestCase):
    def test_version_compare(self) -> None:
        self.assertEqual(parse_version("1.5.4"), (1, 5, 4))
        self.assertTrue(version_gt("1.5.0", "1.4.5"))
        self.assertFalse(version_gt("1.4.5", "1.5.0"))

    def test_rejects_data_and_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = root / "evil.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("data/secrets.txt", "nope")
                zf.writestr("../outside.txt", "nope")
                zf.writestr("jarvis/ok.py", "ok = 1\n")
            written = apply_zip(zip_path, root=root)
            self.assertEqual(written, ["jarvis/ok.py"])
            self.assertTrue((root / "jarvis" / "ok.py").is_file())
            self.assertFalse((root / "data" / "secrets.txt").exists())

    def test_sha_and_apply_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            (install / "jarvis").mkdir()
            (install / "jarvis" / "old.py").write_text("old\n", encoding="utf-8")

            zip_path = root / "u.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("jarvis/old.py", "new\n")
                zf.writestr("main.py", "print('hi')\n")
            digest = sha256_file(zip_path)
            apply_zip(zip_path, root=install, expected_sha=digest)
            self.assertEqual((install / "jarvis" / "old.py").read_text(encoding="utf-8"), "new\n")
            self.assertTrue((install / "main.py").is_file())

            with self.assertRaises(ValueError):
                apply_zip(zip_path, root=install, expected_sha="0" * 64)

    def test_manifest_and_skip_without_url(self) -> None:
        man = load_manifest(
            {
                "version": "9.9.9",
                "zip_url": "file:///tmp/x.zip",
                "sha256": "abc",
                "notes": "test",
            }
        )
        self.assertEqual(man.version, "9.9.9")
        res = check_and_apply(manifest_url="")
        self.assertEqual(res.status, "skipped")

    def test_end_to_end_file_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Point ROOT/DATA via applying into a fake install + monkeypatch
            install = root / "app"
            install.mkdir()
            (install / "jarvis").mkdir()
            (install / "jarvis" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")

            zip_path = root / "pkg.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("jarvis/__init__.py", '__version__ = "1.0.1"\n')
            digest = sha256_file(zip_path)
            manifest = {
                "version": "99.0.0",
                "min_version": "0.0.0",
                "zip_url": zip_path.resolve().as_uri(),
                "sha256": digest,
                "notes": "e2e",
            }
            man_path = root / "version.json"
            man_path.write_text(json.dumps(manifest), encoding="utf-8")

            from jarvis import pc_updater as mod

            old_root = mod.ROOT
            old_data = mod.DATA_DIR
            old_ver = mod.LOCAL_VERSION
            try:
                mod.ROOT = install  # type: ignore[misc]
                mod.DATA_DIR = root / "data"  # type: ignore[misc]
                mod.DATA_DIR.mkdir(parents=True, exist_ok=True)
                mod.LOCAL_VERSION = "1.0.0"  # type: ignore[misc]
                result = mod.check_and_apply(manifest_url=man_path.resolve().as_uri())
                self.assertEqual(result.status, "updated", result.message)
                self.assertIn("1.0.1", (install / "jarvis" / "__init__.py").read_text(encoding="utf-8"))
            finally:
                mod.ROOT = old_root  # type: ignore[misc]
                mod.DATA_DIR = old_data  # type: ignore[misc]
                mod.LOCAL_VERSION = old_ver  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
