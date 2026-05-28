"""
Mantenimiento de datos (sábado): purga CSV/Optuna > N días y compacta SQLite.

Variables:
  IA_DATA_MAINTENANCE_ENABLE=1
  IA_DATA_RETENTION_DAYS=90
  IA_SAT_MAINTENANCE_UTC_WEEKDAY=5
  IA_SAT_MAINTENANCE_UTC_HOUR=1
  IA_OPTUNA_PURGE_FAIL_TRIALS=1
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def maintenance_enabled() -> bool:
    return os.environ.get("IA_DATA_MAINTENANCE_ENABLE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _retention_days() -> int:
    try:
        return max(7, int(os.environ.get("IA_DATA_RETENTION_DAYS", "90").strip() or "90"))
    except ValueError:
        return 90


def _state_path() -> Path:
    from ia_paths import resolve_data_path

    return resolve_data_path("IA_SAT_MAINTENANCE_STATE", "logs/ia_saturday_maintenance_state.json")


def _load_state() -> dict:
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(**fields) -> None:
    data = _load_state()
    data.update(fields)
    data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def debe_ejecutar_mantenimiento_sabado(now: datetime | None = None) -> bool:
    """True una vez por día calendario UTC en la franja de sábado configurada."""
    if not maintenance_enabled():
        return False
    now = now or _utc_now()
    wd = int(os.environ.get("IA_SAT_MAINTENANCE_UTC_WEEKDAY", "5").strip() or "5")
    hour = int(os.environ.get("IA_SAT_MAINTENANCE_UTC_HOUR", "1").strip() or "1")
    if int(now.weekday()) != wd:
        return False
    if int(now.hour) != hour:
        return False
    key = now.strftime("%Y-%m-%d")
    if _load_state().get("last_run_key") == key:
        return False
    return True


def purgar_datos_obsoletos_sabado_autonomo() -> dict[str, int | bool]:
    """
    Purga audit CSV, trials Optuna fallidos/antiguos y compacta SQLite.
    Devuelve resumen ``{csv_rows, optuna_deleted, vacuum}``.
    """
    from ia_paths import resolve_data_path

    print("[maintenance] Protocolo de mantenimiento de datos (sabado)...", flush=True)
    cutoff = _utc_now() - timedelta(days=_retention_days())
    cutoff_ts = cutoff.timestamp()
    stats: dict[str, int | bool] = {"csv_rows": 0, "optuna_deleted": 0, "vacuum": False}

    csv_path = resolve_data_path("IA_ML_AUDIT_CSV", "logs/trade_audit_ml.csv")
    if csv_path.is_file():
        try:
            import pandas as pd

            df = pd.read_csv(csv_path)
            n_before = len(df)
            col = None
            for c in ("time_open_utc", "hora_utc", "time_close_utc"):
                if c in df.columns:
                    col = c
                    break
            if col:
                if col == "hora_utc":
                    ts = pd.to_numeric(df[col], errors="coerce")
                    mask = ts >= cutoff_ts
                else:
                    dt = pd.to_datetime(df[col], utc=True, errors="coerce")
                    mask = dt >= cutoff
                df = df.loc[mask]
            df.to_csv(csv_path, index=False)
            stats["csv_rows"] = n_before - len(df)
            print(f"[maintenance] CSV audit: eliminadas {stats['csv_rows']} filas antiguas.", flush=True)
        except ImportError:
            print("[maintenance] pandas no instalado; omitiendo purga CSV.", file=sys.stderr)
        except Exception as e:
            print(f"[maintenance] CSV: {e}", file=sys.stderr)

    db_path = resolve_data_path("IA_OPTUNA_DB_FILE", "logs/ia_optuna_trials.db")
    if db_path.is_file():
        try:
            con = sqlite3.connect(str(db_path))
            cur = con.cursor()
            deleted = 0
            if os.environ.get("IA_OPTUNA_PURGE_FAIL_TRIALS", "1").strip().lower() in (
                "1",
                "true",
                "yes",
            ):
                cur.execute("DELETE FROM trials WHERE state = 'FAIL'")
                deleted += int(cur.rowcount or 0)
            try:
                cur.execute(
                    "DELETE FROM trials WHERE datetime_start IS NOT NULL AND datetime_start < ?",
                    (cutoff_ts,),
                )
                deleted += int(cur.rowcount or 0)
            except sqlite3.OperationalError:
                pass
            con.commit()
            cur.execute("VACUUM")
            con.close()
            stats["optuna_deleted"] = deleted
            stats["vacuum"] = True
            print(
                f"[maintenance] Optuna DB: {deleted} trial(s) purgados; VACUUM OK.",
                flush=True,
            )
        except Exception as e:
            print(f"[maintenance] SQLite: {e}", file=sys.stderr)

    try:
        from ia_memory_gc import liberar_memoria_ciclo

        liberar_memoria_ciclo()
    except Exception:
        pass

    _save_state(last_run_key=_utc_now().strftime("%Y-%m-%d"))
    return stats


def ejecutar_mantenimiento_sabado_si_toca() -> bool:
    """
    Ejecuta purga si toca la ventana de sábado. True si corrió en esta llamada.
    """
    if not debe_ejecutar_mantenimiento_sabado():
        return False
    purgar_datos_obsoletos_sabado_autonomo()
    return True


def main() -> int:
    from local_env import load_env_file

    load_env_file()
    if ejecutar_mantenimiento_sabado_si_toca() or maintenance_enabled():
        purgar_datos_obsoletos_sabado_autonomo()
        return 0
    print("No toca mantenimiento (IA_DATA_MAINTENANCE_ENABLE o ventana horaria).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
