"""Fast HUD smoke tests. Isolated sqlite — never the live data/ store.

Run:  .venv\\Scripts\\python.exe tests/smoke_test.py
Does not import jarvis.main (that module does not exist).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from jarvis.accounts import AccountStore
from jarvis.config import Settings
from jarvis.hud import COOKIE, create_hud
from jarvis.state import AppState


def _blank_settings() -> Settings:
    """No LLM keys → Brain.reply uses local_reply (fast, still HTTP 200)."""
    return Settings(
        groq_api_key="",
        openai_api_key="",
        gemini_api_key="",
        llm_provider="groq",
        telegram_bot_token="",
        telegram_user_id=None,
        hud_host="127.0.0.1",
        hud_port=8787,
        assistant_name="Ilaria",
        user_name="señor",
        tts_voice="es-AR-ElenaNeural",
        timezone="America/Argentina/Buenos_Aires",
        llm_model="",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        ha_url="",
        ha_token="",
        tts_provider="edge",
    )


class HudSmokeTests(unittest.TestCase):
    def test_health_register_login_chat_alerts(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="ilaria-smoke-",
            ignore_cleanup_errors=True,
        ) as raw:
            tmp = Path(raw)
            accounts = AccountStore(path=tmp / "accounts.sqlite")
            app = create_hud(AppState(_blank_settings(), accounts, data_dir=tmp))
            with TestClient(app) as client:
                health = client.get("/health")
                self.assertEqual(health.status_code, 200, health.text)
                body = health.json()
                self.assertEqual(body.get("ok"), "1")
                self.assertEqual(body.get("app"), "Ilaria")
                self.assertTrue(str(body.get("version", "")).startswith("1."))

                username = "smoke_" + uuid.uuid4().hex[:12]
                password = "TmpPass_" + uuid.uuid4().hex[:10]
                registered = client.post(
                    "/api/register",
                    json={
                        "username": username,
                        "password": password,
                        "display_name": "Smoke",
                    },
                )
                self.assertEqual(registered.status_code, 200, registered.text)
                self.assertTrue(registered.json().get("ok"))

                login = client.post(
                    "/api/login",
                    json={"username": username, "password": password},
                )
                self.assertEqual(login.status_code, 200, login.text)
                payload = login.json()
                token = str(payload.get("token") or "")
                cookie = login.cookies.get(COOKIE) or client.cookies.get(COOKIE)
                self.assertTrue(cookie or token, "expected jarvis_sid cookie or token")

                headers = {}
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                chat = client.post(
                    "/api/chat",
                    json={"message": "hola"},
                    headers=headers,
                )
                self.assertEqual(chat.status_code, 200, chat.text)
                reply = chat.json()
                text = str(reply.get("reply") or reply.get("text") or "").strip()
                self.assertTrue(text, f"chat missing reply/text: {reply}")

                alerts = client.get("/api/alerts", params={"after": 0}, headers=headers)
                self.assertEqual(alerts.status_code, 200, alerts.text)
                self.assertIn("items", alerts.json())

                streamed = client.post(
                    "/api/chat/stream",
                    json={"message": "qué hora es", "speak": False},
                    headers=headers,
                )
                self.assertEqual(streamed.status_code, 200, streamed.text)
                raw = streamed.text
                self.assertIn("event: token", raw)
                self.assertIn("event: done", raw)


if __name__ == "__main__":
    unittest.main()
