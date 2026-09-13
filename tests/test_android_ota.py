"""Android OTA metadata."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.android_ota import advertised


class AndroidOtaTests(unittest.TestCase):
    def test_reads_gradle_version(self) -> None:
        info = advertised()
        self.assertEqual(info["app"], "Ilaria")
        self.assertGreater(info["versionCode"], 0)
        self.assertTrue(info["versionName"])


if __name__ == "__main__":
    unittest.main()
