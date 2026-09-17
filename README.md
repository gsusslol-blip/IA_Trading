# Ilaria 1.5 — asistente local-first (estilo F.R.I.D.A.Y.)

Repo: [gsusslol-blip/Ilaria](https://github.com/gsusslol-blip/Ilaria) · Releases: [latest](https://github.com/gsusslol-blip/Ilaria/releases/latest)

Ilaria corre en **tu PC**: privacidad, baja latencia, sin suscripción obligatoria.  
El HUD, el celular (misma Wi‑Fi) y las tools (volumen, recetas, bitácora, undo…) viven en este repo.  
El “cerebro” y la voz pesada se instalan una vez en la máquina.

---

## Arranque en 3 pasos (experiencia F.R.I.D.A.Y.)

### Paso 1 — Cerebro local (Ollama)

1. Instalá [Ollama](https://ollama.com) en Windows.
2. En una terminal:

```bat
ollama pull gemma2:2b
```

(Modelo por defecto en `.env.example`. Si tenés más VRAM: `llama3.1` u otro y cambiá `OLLAMA_MODEL`.)

`run.bat` chequea si Ollama está activo e intenta levantarlo si hace falta.

### Paso 2 — Voz (Piper + Faster-Whisper)

No hace falta armar rutas a mano en la mayoría de PCs:

| Pieza | Qué hace | Cómo llega |
|---|---|---|
| **Piper** | Habla offline (español AR) | `run.bat` → `tools/ensure_piper.ps1` baja `bin/piper/` + `data/tts/es_AR-daniela-high.onnx` |
| **Faster-Whisper** | Escucha offline (CPU) | `pip` en el `.venv`; el modelo `base`/`small` se descarga la primera vez que usás el mic |

Opcional (override en `.env`):

```
PIPER_EXE=
PIPER_MODEL=
FASTER_WHISPER_MODEL=small
WHISPER_DEVICE=cpu
TTS_CACHE_DIR=data/assets/tts_cache
```

Si preferís un ZIP con motores ya armados, podés publicarlo en **GitHub Releases** y documentar el enlace acá; el layout esperado sigue siendo `bin/piper/` + `data/tts/`.

### Paso 3 — Python + un clic

1. Instalá [Python 3.11+](https://www.python.org/downloads/) (marcá “Add to PATH”).
2. En la carpeta del repo:

```bat
copy .env.example .env
run.bat
```

Eso crea `.venv`, instala `requirements.txt`, asegura Piper y abre el HUD:

**http://localhost:8787/**

- Brave: usá `localhost`, no `https`, no `127.0.0.1`.
- Primer registro en esa PC = dueño de *esa* instalación.

---

## Qué trae el repositorio (listo)

- HUD web + APIs FastAPI (`:8787`)
- Autodescubrimiento LAN **UDP 8788** (el celular encuentra la PC)
- Undo táctico (~30 s), bitácora `diario_YYYY-MM-DD.txt`, cocina local, métricas de stack
- Android: `dist\Ilaria-android.apk` + OTA `/api/android/update`
- iOS: proyecto en `ios/` ([ios/README.md](ios/README.md))
- Updates de código PC livianos (sin re-bajar modelos) vía Releases

## Qué NO va en GitHub (y por qué)

| Extra | Motivo | Quién lo instala |
|---|---|---|
| Modelos Ollama | GB de peso | `ollama pull …` |
| Piper ONNX + binario | Cientos de MB | `ensure_piper.ps1` o ZIP de Releases |
| Pesos Faster-Whisper | Caché local | primera vez que hablás al mic |

Opcional: `GROQ_API_KEY` en `.env` como fallback si Ollama está caído (`LLM_PROVIDER=auto`).

---

## Celular (misma Wi‑Fi)

1. PC con `run.bat` (HUD escuchando en la LAN: `HUD_HOST=0.0.0.0`).
2. **Android:** instalá el APK; la app busca sola la PC (UDP 8788).
3. **iOS:** abrí `ios/` en Xcode; URL de la PC o modo solo.

Firewall una vez (Admin): `firewall-ilaria.bat` (TCP 8787 + UDP 8788).

---

## Updates del código PC (sin re-bajar modelos)

En `.env`:

```
ILARIA_UPDATE_URL=https://github.com/gsusslol-blip/Ilaria/releases/latest/download/version.json
ILARIA_AUTO_UPDATE=1
```

Al arrancar, si hay release nueva, aplica ZIP liviano de `jarvis/` (backup en `data/updates/`). No toca Ollama, Piper ni `data/`.

---

## Dueño local / portable

- `.local-owner.bat` (no se publica) fija dueño en *tu* copia.
- `build.bat` → `dist\JARVIS` (WebView2). No copies `.env` con secrets.

No es consejo médico ni financiero.
