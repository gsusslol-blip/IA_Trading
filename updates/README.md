# Actualizaciones incrementales de la PC (Ilaria) — GitHub Releases como CDN

## Manifiesto (`version.json`)

```json
{
  "version": "1.5.1",
  "release_date": "2026-09-13T20:00:00Z",
  "changelog": ["…"],
  "download_url": "https://github.com/DUEÑO/REPO/releases/download/pc-v1.5.1/ilaria-pc-1.5.1.zip",
  "zip_url": "https://github.com/DUEÑO/REPO/releases/download/pc-v1.5.1/ilaria-pc-1.5.1.zip",
  "sha256": "…",
  "min_version": "1.4.0",
  "min_required_android_client": "1.5.4"
}
```

`pc_updater.py` acepta `download_url` o `zip_url`.

## Publicar

```bat
.venv\Scripts\python.exe tools\release_pipeline.py --version 1.5.1 --repo DUEÑO/REPO --changelog "fix X" --min-android 1.5.4
.venv\Scripts\python.exe tools\publish_pc_update.py --version 1.5.1 --repo DUEÑO/REPO
```

O tag + Actions: `git tag pc-v1.5.1 && git push origin pc-v1.5.1`

## Clientes PC (`.env`)

```
ILARIA_UPDATE_URL=https://github.com/DUEÑO/REPO/releases/latest/download/version.json
ILARIA_AUTO_UPDATE=1
ILARIA_PASSIVE_HEAL=1
```

## Play Store / app vieja

Si `device.app_version` < `min_required_android_client`, el chat agrega el aviso de actualizar la app.
