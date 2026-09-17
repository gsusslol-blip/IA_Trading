"""Process real audio tracks from the terminal (local-first, no streaming downloads).

Modes:
  stage   — copy/normalize a legally owned file into music/input/ for remix_hardtech vocals
  overlay — BPM-aware base+overlay mix via music_remixer (needs librosa + pydub + ffmpeg)
  analyze — loudness/section report via analyze.py on an existing WAV

Examples:
  python -m music.process_track stage path/to/vocal.mp3
  python -m music.process_track overlay base.wav overlay.wav --bpm 150 --out out/mix.wav
  python -m music.process_track analyze music/hardtech_remix_150bpm.wav
  python -m music.process_track pipeline track.mp3 --bpm 150
    (stage → remind / optionally invoke remix_hardtech if --render)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "input"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


def _ensure_audio(path: Path) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No existe: {path}")
    if path.suffix.lower() not in AUDIO_EXTS:
        raise ValueError(f"Extensión no soportada: {path.suffix} (usá {sorted(AUDIO_EXTS)})")
    return path


def stage_input(src: Path, *, clear_others: bool = True) -> Path:
    """Place one owned track into music/input/ for the hardtech vocal pipeline."""
    src = _ensure_audio(src)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    if clear_others:
        for old in INPUT_DIR.iterdir():
            if old.is_file() and old.suffix.lower() in AUDIO_EXTS:
                old.unlink(missing_ok=True)
    dest = INPUT_DIR / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    print(f"[TRACK] staged -> {dest.relative_to(HERE.parent) if HERE.parent in dest.parents else dest}")
    return dest


def run_overlay(
    base: Path,
    overlay: Path,
    output: Path,
    *,
    bpm: float = 150.0,
    fade_ms: int = 4000,
) -> Path:
    try:
        from music.music_remixer import mezclar_remix_hardtech
    except ImportError:
        # Allow `python music/process_track.py` from inside music/
        sys.path.insert(0, str(HERE))
        from music_remixer import mezclar_remix_hardtech  # type: ignore

    return mezclar_remix_hardtech(
        _ensure_audio(base),
        _ensure_audio(overlay),
        Path(output),
        bpm_target=float(bpm),
        overlay_fade_ms=int(fade_ms),
    )


def run_analyze(wav: Path) -> int:
    wav = _ensure_audio(wav)
    script = HERE / "analyze.py"
    return subprocess.call([sys.executable, str(script), str(wav)], cwd=str(HERE))


def run_preview() -> int:
    script = HERE / "preview.py"
    if not script.is_file():
        print("[TRACK] preview.py no encontrado")
        return 1
    return subprocess.call([sys.executable, str(script)], cwd=str(HERE))


def run_hardtech_render(*, fresh: bool = False) -> int:
    script = HERE / "remix_hardtech.py"
    cmd = [sys.executable, str(script)]
    if fresh:
        cmd.append("--fresh")
    print("[TRACK] launching remix_hardtech (Surge/Demucs — puede tardar)...")
    return subprocess.call(cmd, cwd=str(HERE))


def detect_bpm(path: Path) -> float:
    try:
        from music.music_remixer import obtener_bpm
    except ImportError:
        sys.path.insert(0, str(HERE))
        from music_remixer import obtener_bpm  # type: ignore

    bpm = float(obtener_bpm(_ensure_audio(path)))
    print(f"[TRACK] BPM detectado ~ {bpm:.1f}")
    return bpm


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m music.process_track",
        description="Procesá tracks reales desde la terminal (local-first)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_stage = sub.add_parser("stage", help="Copiar track a music/input/ para remix_hardtech")
    p_stage.add_argument("input", type=Path)
    p_stage.add_argument("--keep-others", action="store_true", help="No borrar otros archivos en input/")

    p_bpm = sub.add_parser("bpm", help="Detectar BPM (librosa)")
    p_bpm.add_argument("input", type=Path)

    p_over = sub.add_parser("overlay", help="Mezcla BPM-aware base+overlay")
    p_over.add_argument("base", type=Path)
    p_over.add_argument("overlay", type=Path)
    p_over.add_argument("--out", type=Path, default=HERE / "out" / "track_overlay.wav")
    p_over.add_argument("--bpm", type=float, default=150.0)
    p_over.add_argument("--fade-ms", type=int, default=4000)

    p_an = sub.add_parser("analyze", help="Reporte de loudness/secciones")
    p_an.add_argument("wav", type=Path)

    p_prev = sub.add_parser("preview", help="Generar preview visual del último remix")

    p_pipe = sub.add_parser(
        "pipeline",
        help="Stage + (opcional) render hardtech + analyze/preview",
    )
    p_pipe.add_argument("input", type=Path)
    p_pipe.add_argument("--render", action="store_true", help="Ejecutar remix_hardtech.py")
    p_pipe.add_argument("--fresh", action="store_true", help="Ignorar caches de stems")
    p_pipe.add_argument("--analyze", action="store_true", help="Correr analyze al final")
    p_pipe.add_argument("--preview", action="store_true", help="Correr preview al final")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "stage":
            stage_input(args.input, clear_others=not args.keep_others)
            print("[TRACK] listo. Siguiente: python music/remix_hardtech.py")
            return 0
        if args.cmd == "bpm":
            detect_bpm(args.input)
            return 0
        if args.cmd == "overlay":
            out = run_overlay(args.base, args.overlay, args.out, bpm=args.bpm, fade_ms=args.fade_ms)
            print(f"[TRACK] overlay OK -> {out}")
            return 0
        if args.cmd == "analyze":
            return run_analyze(args.wav)
        if args.cmd == "preview":
            return run_preview()
        if args.cmd == "pipeline":
            stage_input(args.input)
            code = 0
            if args.render:
                code = run_hardtech_render(fresh=args.fresh)
                if code != 0:
                    return code
            else:
                print("[TRACK] staged only (pasá --render para lanzar remix_hardtech)")
            if args.analyze:
                # Default hardtech output name pattern
                import hardtech_arrangement as arr  # type: ignore

                wav = HERE / f"hardtech_remix_{arr.BPM:.0f}bpm.wav"
                if wav.is_file():
                    code = run_analyze(wav) or code
                else:
                    print(f"[TRACK] analyze skip: falta {wav.name}")
            if args.preview:
                code = run_preview() or code
            return code
    except Exception as exc:  # noqa: BLE001
        print(f"[TRACK] error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
