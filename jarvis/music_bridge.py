"""Bridge from ILARIA tools to music/music_remixer.py (BPM overlay remix)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from jarvis.config import ROOT
from jarvis.security import safe_under

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def run_hardtech_remix(
    *,
    track_base: str | Path,
    track_overlay: str | Path,
    output: str | Path,
    bpm_target: float = 140.0,
    workspace: Path | None = None,
) -> str:
    """Run music_remixer with sandboxed workspace paths. Returns status for the LLM."""
    script = ROOT / "music" / "music_remixer.py"
    if not script.is_file():
        return "Motor Hardtech no disponible (falta music/music_remixer.py)."

    if workspace is None:
        return "Sin workspace de usuario."

    try:
        base = safe_under(workspace, Path(track_base).name)
        overlay = safe_under(workspace, Path(track_overlay).name)
        out_name = Path(output).name or "remix_generado.mp3"
        if not out_name.lower().endswith((".mp3", ".wav", ".flac", ".ogg")):
            out_name = out_name + ".mp3"
        out = safe_under(workspace, out_name)
    except ValueError as exc:
        return f"Ruta inválida: {exc}"

    if not base.is_file():
        return f"No encuentro el track base en el workspace: {base.name}"
    if not overlay.is_file():
        return f"No encuentro el overlay en el workspace: {overlay.name}"

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(script),
        str(base),
        str(overlay),
        str(out),
        "--bpm",
        str(float(bpm_target)),
    ]
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": 600,
        "cwd": str(ROOT),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        completed = subprocess.run(cmd, **kwargs)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired:
        return "El remix tardó demasiado (timeout 10 min)."
    except OSError as exc:
        return f"No pude lanzar el remixer: {exc}"

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()[:400]
        return f"Remix falló: {err or completed.returncode}"
    return f"Remix listo en {out.name} ({bpm_target:.0f} BPM)."
