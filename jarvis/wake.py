"""Always-on wake-word listener (Picovoice Porcupine + PvRecorder)."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

from jarvis.config import DATA_DIR, ROOT
from jarvis.state import AppState
from jarvis.stt import contains_speech, record_command_wav, transcribe_audio
from jarvis.tts import audio_api_path, speak_to_file

_WAKE_LOCK = threading.Lock()
_STARTED = False

_HUD_LIBRE_HINT = (
    "Fallback: botón Libre del HUD — decí «Ilaria» por el micrófono "
    "(el HUD filtra VAD del lado cliente). Guía: data/wake/README.txt"
)


def wake_enabled() -> bool:
    raw = os.getenv("WAKE_ENABLED", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(_access_key())


def start_wake_listener(state: AppState) -> None:
    """Spawn a daemon thread; no-op if disabled, missing key, or deps unavailable."""
    global _STARTED
    if _STARTED:
        return
    if not wake_enabled():
        print(f"[-] Wake PC off (falta PICOVOICE_ACCESS_KEY / PICOVOICE_API_KEY). {_HUD_LIBRE_HINT}")
        return
    try:
        import pvporcupine  # noqa: F401
        from pvrecorder import PvRecorder  # noqa: F401
    except ImportError as exc:
        print(f"[-] Wake word skipped (pip install pvporcupine pvrecorder): {exc}")
        print(f"    {_HUD_LIBRE_HINT}")
        return
    _STARTED = True
    thread = threading.Thread(
        target=_listen_loop,
        args=(state,),
        name="ilaria-wake",
        daemon=True,
    )
    thread.start()
    print("[+] Wake word: escuchando en segundo plano.")


def _access_key() -> str:
    return (
        os.getenv("PICOVOICE_ACCESS_KEY", "").strip()
        or os.getenv("PICOVOICE_API_KEY", "").strip()
    )


def _keyword_paths() -> list[str]:
    """Custom .ppn files (e.g. Ilaria from Picovoice Console)."""
    raw = os.getenv("WAKE_PPN_PATH", "").strip()
    paths: list[str] = []
    if raw:
        for part in raw.split(";"):
            p = Path(part.strip())
            if not p.is_absolute():
                p = ROOT / p
            if p.is_file():
                paths.append(str(p))
            else:
                print(f"[-] Wake .ppn no encontrado: {p}")
    for default in (
        DATA_DIR / "wake" / "ilaria_windows.ppn",
        DATA_DIR / "models" / "ilaria_windows.ppn",
    ):
        resolved = str(default)
        if default.is_file() and resolved not in paths:
            paths.append(resolved)
    return paths


def _builtin_keywords() -> list[str]:
    """Last resort only when a Picovoice key exists but no custom .ppn."""
    raw = os.getenv("WAKE_KEYWORDS", "computer,jarvis").strip()
    allowed = {
        "alexa",
        "americano",
        "blueberry",
        "bumblebee",
        "computer",
        "grapefruit",
        "grasshopper",
        "hey google",
        "hey siri",
        "jarvis",
        "ok google",
        "picovoice",
        "porcupine",
        "terminator",
    }
    out: list[str] = []
    for item in raw.split(","):
        key = item.strip().lower()
        if key in allowed and key not in out:
            out.append(key)
    return out or ["computer"]


def _create_porcupine():
    import pvporcupine

    key = _access_key()
    paths = _keyword_paths()
    if paths:
        print(f"[+] Wake: usando .ppn custom ({paths[0]})")
        return pvporcupine.create(access_key=key, keyword_paths=paths)
    builtins = _builtin_keywords()
    print(
        "[+] Wake: sin data/wake/ilaria_windows.ppn ni data/models/ilaria_windows.ppn — "
        f"last resort built-in {builtins}. Para «Ilaria» entrená el .ppn "
        f"(data/wake/README.txt). {_HUD_LIBRE_HINT}"
    )
    return pvporcupine.create(access_key=key, keywords=builtins)


def _listen_loop(state: AppState) -> None:
    from pvrecorder import PvRecorder

    porcupine = None
    recorder = None
    try:
        porcupine = _create_porcupine()
        recorder = PvRecorder(device_index=-1, frame_length=porcupine.frame_length)
        recorder.start()
        print(
            f"[+] Mic wake listo @ {porcupine.sample_rate} Hz "
            f"(device={recorder.selected_device}). Esperando keyword…"
        )
        while True:
            pcm = recorder.read()
            index = porcupine.process(pcm)
            if index < 0:
                continue
            if not _WAKE_LOCK.acquire(blocking=False):
                continue
            try:
                print("[!] Wake word detectada — grabando comando…")
                recorder.stop()
                _handle_wake(state, porcupine.sample_rate, porcupine.frame_length)
            except Exception as exc:  # noqa: BLE001
                print(f"[-] Wake handler error: {exc}")
            finally:
                try:
                    if not recorder.is_recording:
                        recorder.start()
                except Exception:
                    pass
                _WAKE_LOCK.release()
    except Exception as exc:  # noqa: BLE001
        print(f"[-] Wake word runtime error: {exc}")
        print(f"    {_HUD_LIBRE_HINT}")
    finally:
        try:
            if recorder is not None:
                if recorder.is_recording:
                    recorder.stop()
                recorder.delete()
        except Exception:
            pass
        try:
            if porcupine is not None:
                porcupine.delete()
        except Exception:
            pass


def _handle_wake(state: AppState, sample_rate: int, frame_length: int) -> None:
    owner = state.accounts.owner()
    if owner is None:
        print("[-] Wake: no hay owner registrado.")
        return
    seconds = float(os.getenv("WAKE_LISTEN_SECONDS", "8").strip() or "8")
    seconds = max(3.0, min(12.0, seconds))
    brain = state.brain_for(owner)
    settings = brain.settings
    if not settings.has_stt:
        print("[-] Wake: falta GROQ_API_KEY / OPENAI_API_KEY para Whisper.")
        return
    brain.bus.push("Te escucho…", audio_url=None)
    try:
        wav = record_command_wav(
            sample_rate=sample_rate,
            frame_length=frame_length,
            max_seconds=seconds,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[-] Wake STT record error: {exc}")
        wav = b""
    if len(wav) < 800 or not contains_speech(wav):
        print("[-] Wake: VAD descartó el clip (sin voz) antes de Whisper.")
        reply = "No te escuché bien, pá. Decilo otra vez después de llamarme."
        _announce(brain, reply)
        return
    try:
        text = transcribe_audio(settings, wav, "wake.wav")
    except Exception as exc:  # noqa: BLE001
        print(f"[-] Wake STT error: {exc}")
        text = ""
    if not text.strip():
        reply = "No te escuché bien, pá. Decilo otra vez después de llamarme."
        _announce(brain, reply)
        return
    print(f"[+] Wake STT: {text}")
    brain.bus.push(f"(vos) {text}", audio_url=None)
    answer = brain.reply(f"wake-{owner.id}", text)
    _announce(brain, answer)


def _announce(brain, text: str) -> None:
    audio_url = None
    path = None
    try:
        path = asyncio.run(
            speak_to_file(brain.settings, text, f"tts-wake-{time.time_ns()}.mp3")
        )
        audio_url = audio_api_path(path.name)
    except Exception as exc:  # noqa: BLE001
        print(f"[-] Wake TTS: {exc}")
    brain.bus.push(text, audio_url=audio_url)
    if path is not None and path.is_file():
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            pass
