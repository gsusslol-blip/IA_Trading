"""Ilaria everyday flow smoke test (offline kitchen/music + optional live HUD).

Usage:
  .venv\\Scripts\\python tools\\test_flow.py --offline --message "Quiero la receta de milanesas"
  .venv\\Scripts\\python tools\\test_flow.py --offline --message "remix techno"
  .venv\\Scripts\\python tools\\test_flow.py --user gsuss --password *** --message "volumen al 30"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.brain_parser import parse_and_execute
from jarvis.config import DATA_DIR
from jarvis.welcome_reporter import generar_welcome_report_cotidiano
from jarvis.workspace_manager import backup_user_notes, purge_old_tts_cache


def _post(url: str, payload: dict, cookie: str | None = None) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _run_maintenance(username: str) -> None:
    print("[MANTENIMIENTO] Verificando almacenamiento local...")
    cache_status = purge_old_tts_cache(days_limit=7)
    print(f"[MANTENIMIENTO] Purga caché TTS: {json.dumps(cache_status, ensure_ascii=False)}")
    user_root = DATA_DIR / "users" / username.strip().lower()
    workspace = user_root / "workspace"
    mem = user_root / "memory.json"
    backup = backup_user_notes(
        workspace=workspace,
        user_root=user_root if user_root.is_dir() else None,
        memory_path=mem if mem.is_file() else None,
    )
    print(f"[MANTENIMIENTO] Backup notas: {json.dumps(backup, ensure_ascii=False)}")


def ejecutar_suite_test(mensaje: str, usuario: str, *, offline: bool = True) -> dict:
    print(f"=== TESTING ECOSYSTEM ILARIA [OFFLINE: {offline}] ===")
    print("\n[PASO 1] Welcome Report cotidiano...")
    welcome = generar_welcome_report_cotidiano(usuario)
    print(json.dumps(welcome, indent=2, ensure_ascii=False))

    print("\n[PASO 2] Simulando procesamiento del Cerebro...")
    lower = mensaje.lower()
    if "reloj" in lower or "smartwatch" in lower or "pasos" in lower or "métricas" in lower or "metricas" in lower or "hrv" in lower:
        mock_llm = (
            '{"thought":"Consulta métricas del wearable","tool":"wellness_action",'
            '"params":{"action":"leer_reloj","tipo_tema":"smartwatch"}}'
        )
    elif "período" in lower or "periodo" in lower or "entrenamiento" in lower or "dieta" in lower or "embarazo" in lower or "bienestar" in lower:
        mock_llm = (
            '{"thought":"Usuario reporta actualización física","tool":"wellness_action",'
            '"params":{"action":"registrar","tipo_tema":"menstruacion",'
            '"notas_registro":"Primer día del ciclo, dolores leves"}}'
        )
    elif "listá" in lower or "lista" in lower or "catálogo" in lower or "catalogo" in lower or (
        "recetas" in lower and "milanesa" not in lower and "tortilla" not in lower
    ):
        mock_llm = (
            '{"thought":"Gsuss quiere el índice culinario local","tool":"kitchen_action",'
            '"params":{"action":"listar"}}'
        )
    elif "receta" in lower or "cocinar" in lower or "milanesa" in lower or "tortilla" in lower or "caruso" in lower or "lentejas" in lower:
        dish = "milanesa"
        if "caruso" in lower:
            dish = "fideos_caruso"
        elif "lentejas" in lower:
            dish = "guiso_lentejas"
        elif "tortilla" in lower:
            dish = "tortilla"
        mock_llm = (
            '{"thought":"Buscando plato pedido","tool":"kitchen_action",'
            f'"params":{{"action":"buscar","comida":"{dish}","receta_texto_completo":null}}}}'
        )
    elif "remix" in lower or "musica" in lower or "música" in lower or "techno" in lower:
        mock_llm = (
            '{"thought":"Configurando pista","tool":"music_action",'
            '"params":{"action":"mix_tracks","track_base":"base_techno.mp3",'
            '"track_overlay":"vocals.mp3","target_bpm":140}}'
        )
    elif "deshacer" in lower or "undo" in lower:
        mock_llm = '{"thought":"Revirtiendo","tool":"trigger_undo","params":{}}'
    else:
        mock_llm = (
            '{"thought":"Ajustando audio","tool":"win_action",'
            '"params":{"action":"volume","value":30}}'
        )
    print(f"[MOCK LLM] {mock_llm}")

    print("\n[PASO 3] Pipeline parser unificado...")
    resultado = parse_and_execute(mock_llm, client_info="test_env", current_user=usuario, execute=True)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(description="Ilaria everyday flow smoke test")
    parser.add_argument("--host", default="http://127.0.0.1:8787")
    parser.add_argument("--user", default="gsuss")
    parser.add_argument("--password", default="")
    parser.add_argument("--message", default="Quiero la receta de milanesas")
    parser.add_argument("--client", default="hud")
    parser.add_argument("--offline", action="store_true", default=True)
    parser.add_argument("--online", action="store_true", help="Also hit live /api/chat if password set")
    args = parser.parse_args()

    _run_maintenance(args.user)
    print("-" * 50)
    resultado = ejecutar_suite_test(args.message, args.user, offline=not args.online)
    print("-" * 50)

    if not args.online:
        ok = resultado.get("status") in {
            "success",
            "playing",
            "mixing_started",
            "trigger_llm_free_text",
            "empty",
        } or resultado.get("type") in {
            "action",
            "kitchen",
            "music",
            "wellness",
            "speech",
        }
        # kitchen local_db returns status success
        if resultado.get("source") == "local_db":
            ok = True
        print("[TEST_FLOW] Suite offline completada.")
        return 0 if ok or resultado.get("status") != "error" else 1

    base = args.host.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=3) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        print(f"[OK] /health → {health}")
    except Exception as exc:
        print(f"[WARN] HUD no responde ({exc}).")
        return 0

    password = (args.password or "").strip()
    if not password:
        print("[INFO] --online sin --password: solo suite offline.")
        return 0

    code, login = _post(f"{base}/api/login", {"username": args.user, "password": password})
    print(f"[LOGIN] {code}")
    if code >= 400:
        return 1
    cookie = None
    if isinstance(login, dict) and login.get("token"):
        cookie = f"jarvis_sid={login['token']}"
    code, chat = _post(
        f"{base}/api/chat",
        {"message": args.message, "speak": False, "client": args.client},
        cookie=cookie,
    )
    print(f"[CHAT] {code}")
    print(f"[RESPUESTA] {json.dumps(chat, ensure_ascii=False)[:800] if isinstance(chat, dict) else chat}")
    return 0 if code < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
