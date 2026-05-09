"""
Utilidades livianas compartidas (sin depender de MT5).

Rotación de CSV de auditoría por tamaño — mantiene ``pd.read_csv`` / guards de slippage rápidos.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def rotar_log_por_tamaño(csv_path: str | Path, max_mb: float = 5.0, *, label: str = "") -> bool:
    """
    Si ``csv_path`` supera ``max_mb`` MiB, lo renombra a ``<path>.old`` (reemplaza un ``.old`` previo).

    Con ``max_mb`` <= 0 no hace nada. Retorna ``True`` si rotó.
    Errores: mensaje a stderr, no levanta.
    """
    try:
        lim = float(max_mb)
    except (TypeError, ValueError):
        return False
    if lim <= 0:
        return False

    p = Path(csv_path)
    if not p.is_file():
        return False

    try:
        size_mb = p.stat().st_size / (1024.0 * 1024.0)
    except OSError as e:
        print(f"[LOG_ROT] no se pudo medir {p}: {e}", file=sys.stderr)
        return False

    if size_mb <= lim:
        return False

    old_path = p.with_name(p.name + ".old")
    pre = f"{label} " if label else ""
    try:
        if old_path.is_file():
            old_path.unlink()
        p.rename(old_path)
        print(
            f"[LOG_ROT] {pre}{p.name} rotado (~{size_mb:.2f} MiB > {lim:g} MiB) → {old_path.name}",
            file=sys.stderr,
        )
        return True
    except OSError as e:
        print(f"[LOG_ROT] error rotando {p}: {e}", file=sys.stderr)
        return False


def execution_quality_max_mb_from_env() -> float:
    """Primera clave no vacía entre ``IA_LOG_MAX_MB`` y ``IA_EXEC_LOG_MAX_MB``; default 5; ``0`` = sin rotación."""
    for key in ("IA_LOG_MAX_MB", "IA_EXEC_LOG_MAX_MB"):
        raw = os.environ.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s == "":
            continue
        try:
            return float(s)
        except ValueError:
            continue
    return 5.0
