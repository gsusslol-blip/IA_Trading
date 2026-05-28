# config/

Secretos y parámetros estáticos.

- **`.env`** — copiá desde `../.env.example` (tokens Telegram, MT5, riesgo). También se acepta `.env` en la raíz del repo.
- **`settings.json`** — opcional; plantilla en `settings.json.example`.

`local_env.load_env_file()` carga en orden: `ENV_FILE` → `config/.env` → `.env` en la raíz.
