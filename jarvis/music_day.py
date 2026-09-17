"""Everyday music dispatcher: play_standard → play_music; mix_tracks → remixer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ejecutar_comando_musical(
    action_type: str,
    params: dict[str, Any],
    *,
    actions: Any,
) -> str:
    """Route everyday music intents through existing Actions / mix_tracks bridge."""
    kind = (action_type or "").strip().lower()
    params = params or {}

    if kind in {"play_standard", "play", "play_music"}:
        track = str(params.get("track_name") or params.get("query") or params.get("track") or "").strip()
        platform = str(params.get("platform") or "youtube").strip()
        if not track:
            return json.dumps({"status": "error", "message": "Falta track_name / query."}, ensure_ascii=False)
        result = actions.play_music(track, platform=platform)
        return json.dumps(
            {"status": "playing", "track": track, "mode": "standard", "platform": platform, "result": result},
            ensure_ascii=False,
        )

    if kind in {"mix_tracks", "mix", "hardtech"}:
        from jarvis.music_bridge import run_hardtech_remix

        base = str(params.get("track_base") or params.get("base_file") or "").strip()
        overlay = str(params.get("track_overlay") or params.get("overlay_file") or "").strip()
        bpm = params.get("target_bpm", params.get("bpm_target", 142))
        try:
            bpm_f = float(bpm)
        except (TypeError, ValueError):
            bpm_f = 142.0
        out = str(params.get("output_file") or "remix_generado.mp3")
        if not base or not overlay:
            # Auto-pick first two audio files in workspace when names omitted
            picked = _pick_workspace_audio(Path(actions.workspace))
            if len(picked) >= 2:
                base = base or picked[0]
                overlay = overlay or picked[1]
            else:
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Necesito track_base y track_overlay en el workspace (mp3/wav).",
                        "available": picked,
                    },
                    ensure_ascii=False,
                )
        result = run_hardtech_remix(
            track_base=base,
            track_overlay=overlay,
            output=out,
            bpm_target=bpm_f,
            workspace=actions.workspace,
        )
        return json.dumps(
            {
                "status": "mixing_started",
                "output": out,
                "bpm": bpm_f,
                "base": Path(base).name,
                "overlay": Path(overlay).name,
                "result": result,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {"status": "error", "message": f"action_type desconocido: {action_type}"},
        ensure_ascii=False,
    )


def _pick_workspace_audio(workspace: Path) -> list[str]:
    root = Path(workspace)
    if not root.is_dir():
        return []
    exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}
    names = sorted(
        p.name
        for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("remix_")
    )
    return names[:8]
