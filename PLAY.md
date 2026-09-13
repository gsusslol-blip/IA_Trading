# Play Store y portable

Hay **dos entregas**. No es la misma binario.

## 1. Portable Windows (revisar ahora)

1. Doble clic en `run.bat`
2. Se abre **una ventana propia** (Edge WebView2), no Brave
3. URL de respaldo: **http://localhost:8787/welcome**

Brave suele romper `http://127.0.0.1` porque lo “mejora” a HTTPS. Por eso no entraba.

Si igual querés Brave: `abrir-brave.bat` (con Ilaria ya abierta) o desactivá **Siempre usar HTTPS** en `brave://settings/security`.

Para distribuir el portable: `build.bat` → carpeta `dist\JARVIS`.

## 2. App de Play Store (Android) — modo LAN (híbrido)

El teléfono **no** es un SaaS aparte: habla con Ilaria en **tu PC** (mismo Wi-Fi).

1. En la PC: `HUD_HOST=0.0.0.0` en `.env`, abrí `run.bat` / `Ilaria.exe`
2. Anotá la URL que imprime (ej. `http://192.168.1.45:8787`)
3. Firewall de Windows: permitir puerto **8787** en red privada si el celular no conecta
4. Android Studio → carpeta `android` → en la app pegá esa URL e iniciá sesión con **gsuss**
5. Notas / diario / herramientas de PC se ejecutan en el disco de la PC (`data/`)

Google no publica un `.exe` de Python. Hace falta el proyecto en `android/`.

1. Instalá [Android Studio](https://developer.android.com/studio)
2. File → Open → carpeta `android`
3. Dejá que Gradle sincronice (si pide wrapper, Generate)
4. Build → Generate Signed App Bundle
5. Cuenta de desarrollador de Play (~25 USD, una vez)
6. Subí el `.aab` + esta política de privacidad **hosteada en https** (`docs/privacy.html`)

Play puede rechazar nombres de marca. El de la app es **Ilaria**.

Esto no lo puedo publicar yo: hace falta **tu** Play Console.
