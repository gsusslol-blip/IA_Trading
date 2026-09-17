"""BPM-aware hardtech overlay remix (librosa + pydub). Separate from remix_hardtech.py synth engine.

Requires optional deps: librosa, pydub, and ffmpeg on PATH for mp3 export.

Example:
  python -m music.music_remixer tracks/base.mp3 tracks/overlay.mp3 out/remix.mp3 --bpm 142
"""

from __future__ import annotations

import argparse
from pathlib import Path


def obtener_bpm(archivo_path: str | Path, *, duration: float = 60.0) -> float:
    """Detect approximate BPM from the first ``duration`` seconds."""
    import librosa
    import numpy as np

    path = Path(archivo_path)
    y, sr = librosa.load(str(path), sr=None, mono=True, duration=float(duration))
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    arr = np.asarray(tempo).reshape(-1)
    return float(arr[0]) if arr.size else 120.0


def mezclar_remix_hardtech(
    track_base_path: str | Path,
    track_overlay_path: str | Path,
    output_path: str | Path,
    bpm_target: float = 142.0,
    *,
    overlay_fade_ms: int = 4000,
    overlay_db: float = -3.5,
    headroom_db: float = 0.5,
    bitrate: str = "320k",
) -> Path:
    """Time-scale to bpm_target, fade-in overlay, overlay at reduced gain, normalize peaks."""
    from pydub import AudioSegment

    base_path = Path(track_base_path)
    overlay_path = Path(track_overlay_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[HARDTECH] Post-proceso a {bpm_target} BPM (fade {overlay_fade_ms} ms)...")
    bpm_base = max(obtener_bpm(base_path), 1.0)
    bpm_overlay = max(obtener_bpm(overlay_path), 1.0)

    sound_base = AudioSegment.from_file(str(base_path))
    sound_overlay = AudioSegment.from_file(str(overlay_path))

    factor_base = float(bpm_target) / bpm_base
    factor_overlay = float(bpm_target) / bpm_overlay

    sound_base_rescaled = sound_base._spawn(
        sound_base.raw_data,
        overrides={"frame_rate": int(sound_base.frame_rate * factor_base)},
    ).set_frame_rate(sound_base.frame_rate)

    sound_overlay_rescaled = sound_overlay._spawn(
        sound_overlay.raw_data,
        overrides={"frame_rate": int(sound_overlay.frame_rate * factor_overlay)},
    ).set_frame_rate(sound_overlay.frame_rate)

    overlay_ready = sound_overlay_rescaled.fade_in(max(0, int(overlay_fade_ms))) + float(overlay_db)
    remix_final = sound_base_rescaled.overlay(overlay_ready, position=0)
    # Peak normalize with headroom to avoid digital clipping on the kick.
    remix_final = remix_final.normalize(headroom=float(headroom_db))

    fmt = out.suffix.lstrip(".").lower() or "mp3"
    export_kw: dict[str, object] = {"format": fmt}
    if fmt == "mp3":
        export_kw["bitrate"] = bitrate
    remix_final.export(str(out), **export_kw)
    print(
        f"[HARDTECH] Master listo: {out} "
        f"(base {bpm_base:.1f} / overlay {bpm_overlay:.1f} → {bpm_target:.0f} BPM)"
    )
    return out


# Aliases matching the design doc naming
get_exact_bpm = obtener_bpm
generate_pro_hardtech_mix = mezclar_remix_hardtech


def main() -> None:
    parser = argparse.ArgumentParser(description="Hardtech BPM overlay remixer (pro mix)")
    parser.add_argument("base", type=Path, help="Base kick/track file")
    parser.add_argument("overlay", type=Path, help="Overlay / vocals file")
    parser.add_argument("output", type=Path, help="Output path (.mp3/.wav)")
    parser.add_argument("--bpm", type=float, default=142.0, help="Target BPM (default 142)")
    parser.add_argument("--fade-ms", type=int, default=4000, help="Overlay fade-in milliseconds")
    args = parser.parse_args()
    mezclar_remix_hardtech(
        args.base,
        args.overlay,
        args.output,
        bpm_target=args.bpm,
        overlay_fade_ms=args.fade_ms,
    )


if __name__ == "__main__":
    main()
