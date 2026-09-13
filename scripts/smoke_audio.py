"""Smoke-test chat+audio URLs the way the Android client consumes them."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from jarvis.accounts import AccountStore
from jarvis.bootstrap import ensure_owner, should_lock_owner
from jarvis.config import DATA_DIR, load_settings
from jarvis.hud import create_hud
from jarvis.state import AppState
from jarvis.tts import resolve_audio_file


def main() -> int:
    settings = load_settings()
    accounts = AccountStore()
    if should_lock_owner():
        print(ensure_owner(accounts))
    app = create_hud(AppState(settings, accounts))
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200, health.text
    print("health", health.json())

    owner = accounts.owner()
    assert owner is not None, "No owner — set OWNER_USERNAME=gsuss and restart once."
    creds = DATA_DIR / "OWNER_CREDENTIALS.txt"
    password = ""
    if creds.exists():
        for line in creds.read_text(encoding="utf-8").splitlines():
            if "contrasena:" in line.lower() or "contraseña:" in line.lower() or line.lower().startswith("password"):
                # bootstrap note format: "contrasena: xxx"
                parts = line.split(":", 1)
                if len(parts) == 2 and "ya tenias" not in parts[1].lower():
                    password = parts[1].strip()
    # Prefer env override for CI-like smoke
    import os

    password = os.getenv("ILARIA_SMOKE_PASSWORD", "").strip() or password
    if not password or password.startswith("("):
        # Login may fail without known password; create a throwaway session as owner via store
        token = accounts.create_session(owner.id)
        print("session via store (no clear password in OWNER_CREDENTIALS)")
    else:
        login = client.post("/api/login", json={"username": owner.username, "password": password})
        if login.status_code != 200:
            token = accounts.create_session(owner.id)
            print("login failed, using store session:", login.text[:200])
        else:
            token = login.json()["token"]
            print("login ok", owner.username)

    headers = {"Authorization": f"Bearer {token}", "X-Ilaria-Token": token}

    welcome = client.get("/api/welcome-report", headers=headers)
    assert welcome.status_code == 200, welcome.text
    w = welcome.json()
    print("welcome keys", sorted(w.keys()))
    assert w.get("voice_text"), "missing voice_text"
    audio_url = w.get("audio_url")
    assert audio_url and audio_url.startswith("/api/audio/"), audio_url
    name = audio_url.rsplit("/", 1)[-1]
    path = resolve_audio_file(name)
    assert path.is_file() and path.stat().st_size > 200, path
    print("welcome mp3", path.name, path.stat().st_size, "bytes")

    # Android MediaPlayer style: query token, no Authorization header
    audio = client.get(f"/api/audio/{name}", params={"token": token})
    assert audio.status_code == 200, audio.text
    assert audio.headers.get("content-type", "").startswith("audio/mpeg")
    body = audio.content
    assert len(body) > 200 and body[:3] == b"ID3" or body[:2] == b"\xff\xfb" or len(body) > 500
    print("GET ?token= ok", len(body), "bytes")

    # Bearer also works
    audio2 = client.get(f"/api/audio/{name}", headers=headers)
    assert audio2.status_code == 200
    print("GET Bearer ok")

    # Reject garbage / traversal
    bad = client.get("/api/audio/../secret.mp3", params={"token": token})
    assert bad.status_code in {400, 404, 422}
    print("traversal blocked", bad.status_code)

    expired = client.get(f"/api/audio/{name}", params={"token": "deadbeef"})
    assert expired.status_code == 401
    print("bad token -> 401")

    print("SMOKE_AUDIO_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
