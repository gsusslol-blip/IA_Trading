# Ilaria 1.5 — asistente local-first (F.R.I.D.A.Y.)

Repo: [gsusslol-blip/Ilaria](https://github.com/gsusslol-blip/Ilaria)  
Release CDN: [latest](https://github.com/gsusslol-blip/Ilaria/releases/latest)

## Arranque (PC)

1. Doble clic en `run.bat` (o acceso **Ilaria** del escritorio).
2. [Ollama](https://ollama.com) + `ollama pull gemma2:2b`.
3. HUD: `http://localhost:8787/` (Brave: sin `https`, sin `127.0.0.1`).
4. Celular: misma Wi‑Fi → `dist\Ilaria-android.apk`.

El primer arranque puede bajar Piper (`tools/ensure_piper.ps1`).

## Updates del código PC (sin re-bajar modelos)

En `.env`:

```
ILARIA_UPDATE_URL=https://github.com/gsusslol-blip/Ilaria/releases/latest/download/version.json
ILARIA_AUTO_UPDATE=1
ILARIA_PASSIVE_HEAL=1
```

Al arrancar, si hay release más nueva, descarga el ZIP liviano de `jarvis/` (SHA256), hace backup en `data/updates/` y aplica allowlist. No toca Ollama, Piper ni `data/`.

Publicar: `git tag pc-vX.Y.Z && git push origin pc-vX.Y.Z` (Action `PC update release`).

## Dueño local

`.local-owner.bat` (no se publica). En un clone, el primero que se registra es dueño de *su* PC.

## Portable

`build.bat` → `dist\JARVIS` (WebView2). No copies `.env` con keys.

No es consejo médico ni financiero.
