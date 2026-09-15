"""TTS helpers: Piper detection and audio URL names."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.config import search_roots
from jarvis.piper_tts import piper_available, piper_exe, piper_model
from jarvis.tts import audio_api_path, audio_media_type, child_speech_pacing, first_speakable_sentence


class TtsHelpersTests(unittest.TestCase):
    def test_wav_and_mp3_names(self) -> None:
        self.assertEqual(audio_api_path("tts-abc.wav"), "/api/audio/tts-abc.wav")
        self.assertEqual(audio_media_type("tts-abc.wav"), "audio/wav")
        self.assertEqual(audio_media_type("tts-abc.mp3"), "audio/mpeg")
        with self.assertRaises(ValueError):
            audio_api_path("reply_x.wav")

    def test_pacing(self) -> None:
        out = child_speech_pacing("Hola qué hacés")
        self.assertIn("...", out)

    def test_early_sentence(self) -> None:
        self.assertEqual(
            first_speakable_sentence("Listo. Abrí Chrome."),
            "Listo. Abrí Chrome.",
        )
        self.assertIsNotNone(first_speakable_sentence("Listo, volumen al treinta."))
        self.assertIsNone(first_speakable_sentence("Hola"))

    def test_piper_paths_are_portable(self) -> None:
        roots = search_roots()
        self.assertTrue(roots)
        for item in roots:
            self.assertTrue(item.is_absolute())
        exe = piper_exe()
        model = piper_model()
        if exe is None:
            self.assertFalse(piper_available())
            return
        self.assertEqual(exe.name.lower(), "piper.exe")
        self.assertIn("piper", [p.lower() for p in exe.parts])
        self.assertTrue(any(exe.is_relative_to(root) for root in roots))
        if model is not None:
            self.assertTrue(model.suffix.lower() == ".onnx")
            self.assertTrue(any(model.is_relative_to(root) for root in roots))
            self.assertNotEqual(model.name, "es_MX-claude-medium.onnx")
            if (model.parent / "es_AR-daniela-high.onnx").is_file():
                self.assertEqual(model.name, "es_AR-daniela-high.onnx")


if __name__ == "__main__":
    unittest.main()
