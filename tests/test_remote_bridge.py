"""Street Telegram shortcuts → diario / recipes (no network)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.brain_parser import log_to_diario
from jarvis.remote_bridge import handle_remote_text, try_street_shortcut
from jarvis.welcome_reporter import generar_welcome_report_cotidiano


class RemoteBridgeTests(unittest.TestCase):
    def test_note_shortcut_writes_diario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.remote_bridge.DATA_DIR", root), patch(
                "jarvis.brain_parser.DATA_DIR", root
            ):
                reply = try_street_shortcut(
                    "anotá comprar carne para las milanesas",
                    username="gsuss",
                )
                self.assertIsNotNone(reply)
                assert reply is not None
                self.assertIn("bitácora", reply.lower())
                diarios = list((root / "users" / "gsuss" / "workspace").glob("diario_*.txt"))
                self.assertEqual(len(diarios), 1)
                body = diarios[0].read_text(encoding="utf-8")
                self.assertIn("Nota remota desde Telegram", body)
                self.assertIn("carne", body)

    def test_recipes_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.remote_bridge.DATA_DIR", root):
                reply = try_street_shortcut("qué puedo cocinar", username="gsuss")
                self.assertIsNotNone(reply)
                assert reply is not None
                self.assertIn("RECETAS", reply.upper())
                self.assertIn("Milanesas", reply)

    def test_welcome_picks_today_remote_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "users" / "gsuss" / "workspace"
            ws.mkdir(parents=True)
            with patch("jarvis.brain_parser.DATA_DIR", root):
                log_to_diario("gsuss", "Nota remota desde Telegram: comprar pan")
            report = generar_welcome_report_cotidiano("gsuss", workspace=ws)
            hits = report.get("pendientes_detectados") or []
            self.assertTrue(any("pan" in str(h).lower() for h in hits))

    def test_freeform_without_brain(self) -> None:
        msg = handle_remote_text("hola qué hora es", brain=None)
        self.assertIn("cerebro", msg.lower())

    def test_sync_shortcut_err_without_tunnel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "users" / "gsuss" / "workspace"
            ws.mkdir(parents=True)
            with patch("jarvis.remote_bridge.DATA_DIR", root), patch(
                "jarvis.tunnel_manager.current_public_url", return_value=None
            ), patch("jarvis.tunnel_manager.sync_path", return_value=ws / "network_sync.json"):
                reply = try_street_shortcut("ILARIA_REQUEST_SYNC_URL", username="gsuss")
                self.assertIsNotNone(reply)
                assert reply is not None
                self.assertTrue(reply.startswith("SYNC_ERR:"))

    def test_sync_ack_with_written_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "network_sync.json"
            path.write_text(
                '{"remote_url": "https://demo.ngrok-free.app", "last_update": 1}',
                encoding="utf-8",
            )
            with patch("jarvis.tunnel_manager.current_public_url", return_value=None), patch(
                "jarvis.tunnel_manager.sync_path", return_value=path
            ):
                from jarvis.tunnel_manager import sync_ack_message

                msg = sync_ack_message()
            self.assertTrue(msg.startswith("SYNC_ACK:https://demo.ngrok-free.app"))
            self.assertIn("ilaria://sync?url=", msg)

    def test_qr_svg_for_deep_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "sync_qr.svg"
            with patch("jarvis.tunnel_manager.qr_svg_path", return_value=svg):
                from jarvis.tunnel_manager import generar_qr_deep_link

                out = generar_qr_deep_link("https://demo.ngrok-free.app")
            self.assertIsNotNone(out)
            assert out is not None
            self.assertTrue(out.is_file())
            raw = out.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("svg", raw.lower())


if __name__ == "__main__":
    unittest.main()
