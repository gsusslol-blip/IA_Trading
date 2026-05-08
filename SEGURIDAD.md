# Guardar el proyecto en modo seguro

## Qué ya está protegido

- **`.env`** está en **`.gitignore`**: tokens de Telegram, API keys y rutas sensibles **no** deben subirse a Git.
- Existe **`.env.example`**: plantilla **sin secretos** para copiar y completar en otro PC.
- Si usás **OneDrive**, los archivos ya se sincronizan en la nube de tu cuenta; igual conviene no copiar `.env` a chats públicos.

## Si instalás Git más adelante

```powershell
cd ruta\IA_Trading
git init
git add .
git status
```

Revisá que **`git status` no liste `.env`**. Luego:

```powershell
git commit -m "Guardar estado del proyecto IA_Trading"
```

Subí el repo solo a un remoto **privado** si hay código sensible.

## Tokens Telegram

Si alguna vez filtraste el token del bot en un chat o repo: en **@BotFather** revocá el token y generá uno nuevo; actualizá `.env`.

## Resumen

| Archivo        | ¿Versionar?      |
|----------------|------------------|
| `.env`         | **No**           |
| `.env.example` | **Sí** (plantilla) |
| `SCRIPTS.md`, código `.py` | Sí, si querés historial |
