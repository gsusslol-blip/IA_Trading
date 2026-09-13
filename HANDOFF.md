# Handoff — Ilaria (IA_Trading) v1.3.7
# Pegá esto a otra IA. NO reescribir brain/accounts/main/runtime con snippets genéricos.

## Qué es
Asistente local tipo JARVIS → **Ilaria**. Dueño de ESTA PC: `gsuss`. Datos en `data/`. No SaaS.
Español rioplatense en chat; comentarios de código en inglés. Commits solo si el usuario pide.

## Arranque
- Dev: `run.bat` → `.venv` → `python main.py` → `jarvis.runtime.main()`
- Env forzada en run.bat: `OWNER_USERNAME=gsuss`, `HUD_HOST=0.0.0.0`, `HUD_PORT=8787`
- HUD: http://localhost:8787 (no https / no 127.0.0.1 en Brave)
- Exe: `build.bat` → `dist\JARVIS\Ilaria.exe` (cerrar Ilaria antes; usar `free-port.bat`)
- Firewall LAN: `firewall-ilaria.bat` como Admin
- Health: `GET /health` → `{"ok":"1","app":"Ilaria","version":"1.3.7"}`
- Smoke: `.venv\Scripts\python.exe tests/smoke_test.py` (sqlite temporal, no toca `data/`)

# Personalidad filial dulce (owner=papá); packs NO pisan identidad; Ollama gemma2:2b + Whisper CPU
# TTS_VOICE=es-AR-ElenaNeural; APIs reales /api/chat (no /api/v1)

## Ya implementado (no volver a “inventar”)
- Packs dinámicos por usuario (`get_user_pack_prompt` / foco por mensaje o `pack` en chat)
- Diario: `daily_journal` / bitácora inyectada en el system prompt cada mensaje
- Volumen real (pycaw), system_status, clipboard, welcome hablado, packs por hora
- CoT: personality + brain; modelos chicos (gemma2:2b) usan prompt compacto + sticky LOCK; packs no pisan identidad
- Recordatorios proactivos: edge-tts + bus + HUD `audio_url` (poll /api/alerts)
- Aviso horario opcional: `PROACTIVE_HOURLY=1` si Cursor/VS Code/Excel abiertos
- LAN + Android cliente Bearer/token; audio `GET /api/audio/{name}?token=...`
- Tools: TOOL_SCHEMAS + make_executor (NO existe REAL_FUNCTIONS_MAP / /api/v1)
- Sesión persistente 10 años + tono `custom_tone` (enum) aislado del núcleo inmutable
- Wake: Porcupine + PvRecorder; .ppn en `data/wake/` o `data/models/`; sin key → HUD Libre
- VAD: `contains_speech` en `jarvis/stt.py` (RMS+ZCR + Silero ONNX opcional). HUD Libre filtra en el cliente. No PyAudio / no torch.hub
- Spotify: YouTube URL siempre; app Spotify + `SPOTIFY_UI_CONTROL=1` + pyautogui (default 0)
- Vision: `jarvis/vision.py` stub, `VISION_ENABLED=0` por defecto. Luces vía HA_URL / home_assistant
- HA: `control_device` / `home_assistant` con `jarvis/ha_guard.py` (luces on/off; clima 18–26; locks dueño; sin shell_command)
- Escucha continua HUD/Android: solo reacciona a «Ilaria» (+ follow ~22s)
- STT Faster-Whisper CPU; LLM Ollama gemma2:2b
- REST `/api/notes` `/api/workspace` (list/upload/file) — SQLite/files en la PC, no en el celular

## APIs reales
`/api/login` `/api/chat` `{message, speak, pack?}` `/api/profile` `/api/welcome-report` `/api/tts` `/api/stt` `/api/audio/{name}` `/api/alerts` `/api/notes` `/api/workspace` `/api/workspace/file` `/api/workspace/upload`

## Reglas
No reemplazar stack con AccountManager / router suelto / create_daily_note suelto.
No force-push. No commitear `.env` ni `data/`.
No instalar torch/YOLO/PyAudio. Python 3.14 no compila PyAudio.
