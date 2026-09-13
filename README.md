# Ilaria 1.4 — asistente local (self-hosted)

Doble clic en `run.bat`. Celular: `dist\Ilaria-android.apk`.

El primer arranque descarga Piper + voz CPU si faltan (`tools/ensure_piper.ps1`). Hace falta [Ollama](https://ollama.com) y `ollama pull gemma2:2b` para el cerebro local. HUD: `http://localhost:8787/` (no https ni `127.0.0.1` en Brave). Celular: misma Wi-Fi, IP LAN que imprime al arrancar, APK en `dist\Ilaria-android.apk`.

## Esta máquina

Dueño local vía `.local-owner.bat` (no se publica). En un clone público, `OWNER_USERNAME` vacío: el primero que se registra es dueño de *su* copia.

## Portable (opcional)

`build.bat` vuelve a generar `dist\JARVIS` (WebView2). No copies tu `.env` con keys. El empaquetado viejo (v1.3.4) ya no está en `dist`.

No es consejo médico ni financiero.
