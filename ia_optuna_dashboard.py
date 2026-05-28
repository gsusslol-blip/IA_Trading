"""
Arranca Optuna Dashboard contra la base SQLite del proyecto (consola separada del bot).

Uso:
  python ia_optuna_dashboard.py
  python ia_optuna_dashboard.py --port 8080
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from local_env import load_env_file


def main() -> int:
    load_env_file()
    from ia_optuna_storage import dashboard_port, ensure_optuna_db_dir, optuna_storage_url

    ap = argparse.ArgumentParser(description="Optuna Dashboard IA_Trading")
    ap.add_argument("--port", type=int, default=0, help="Puerto HTTP (default IA_OPTUNA_DASHBOARD_PORT)")
    args = ap.parse_args()

    storage = optuna_storage_url()
    if not storage:
        print("[dashboard] IA_OPTUNA_STORAGE_ENABLE=0; activa SQLite para usar el panel.", file=sys.stderr)
        return 1

    db = ensure_optuna_db_dir()
    if not db.is_file():
        print(
            f"[dashboard] No existe {db}. Ejecuta antes: python ia_auto_optimizer.py --force",
            file=sys.stderr,
        )
        return 1

    port = args.port if args.port > 0 else dashboard_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"[dashboard] {storage}")
    print(f"[dashboard] Abre: {url}")

    try:
        subprocess.run(
            ["optuna-dashboard", storage, "--port", str(port)],
            check=True,
        )
    except FileNotFoundError:
        print("[dashboard] Instala: pip install optuna-dashboard>=0.20.0", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"[dashboard] Error: {e}", file=sys.stderr)
        return int(e.returncode or 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
