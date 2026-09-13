"""Speech-to-text via Groq/OpenAI Whisper + post-wake mic capture (PvRecorder)."""

from __future__ import annotations

import io
import math
import struct
import time
import wave
from io import BytesIO

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from jarvis.config import DATA_DIR, Settings
from jarvis.vad import wav_contains_speech


def contains_speech(wav_bytes: bytes, filename: str = "audio.wav") -> bool:
    """
    Local VAD before Whisper: RMS + zero-crossing, plus Silero ONNX if importable.
    HUD Libre still filters client-side (RMS + wake regex in jarvis/static/index.html).
    No PyAudio. No torch.hub.
    """
    return wav_contains_speech(wav_bytes, filename)


def transcribe_audio(settings: Settings, data: bytes, filename: str = "audio.webm") -> str:
    if len(data) < 400:
        return ""
    if not contains_speech(data, filename):
        return ""
    provider = (getattr(settings, "stt_provider", "auto") or "auto").strip().lower()
    if provider in {"faster-whisper", "local", "auto"}:
        try:
            from jarvis.whisper_local import transcribe_local, whisper_available

            if whisper_available():
                return transcribe_local(settings, data, filename)
            if provider in {"faster-whisper", "local"}:
                raise RuntimeError("Faster-Whisper no está instalado. pip install faster-whisper")
        except RuntimeError:
            raise
        except Exception:
            if provider in {"faster-whisper", "local"}:
                raise
    if settings.groq_api_key:
        client = OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=90.0,
            max_retries=0,
        )
        model = "whisper-large-v3"
    elif settings.openai_api_key:
        client = OpenAI(api_key=settings.openai_api_key, timeout=90.0, max_retries=0)
        model = "whisper-1"
    else:
        raise RuntimeError(
            "Voz local: instalá faster-whisper, o pegá GROQ_API_KEY para transcribir."
        )

    suffix = ".webm"
    lower = filename.lower()
    for ext in (".webm", ".wav", ".mp3", ".ogg", ".mp4", ".m4a"):
        if lower.endswith(ext):
            suffix = ext
            break

    last_error: Exception | None = None
    for attempt in range(3):
        buffer = BytesIO(data)
        buffer.name = f"speech{suffix}"
        try:
            result = client.audio.transcriptions.create(
                model=model,
                file=buffer,
                language="es",
            )
            return (result.text or "").strip()
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
        except RateLimitError as exc:
            last_error = exc
            time.sleep(1.2 * (attempt + 1))
        except APIStatusError as exc:
            last_error = exc
            if exc.status_code and exc.status_code < 500:
                raise
            time.sleep(0.8 * (attempt + 1))
    if last_error is not None:
        raise last_error
    return ""


def _frame_energy_rms(chunk: list[int]) -> float:
    if not chunk:
        return 0.0
    acc = 0.0
    for sample in chunk:
        acc += float(sample) * float(sample)
    return math.sqrt(acc / len(chunk))


def _frame_zcr(chunk: list[int]) -> float:
    if len(chunk) < 2:
        return 0.0
    crosses = 0
    prev = chunk[0]
    for sample in chunk[1:]:
        if (prev >= 0) != (sample >= 0) and (prev != 0 or sample != 0):
            crosses += 1
        prev = sample
    return crosses / (len(chunk) - 1)


def record_command_wav(
    *,
    sample_rate: int = 16000,
    frame_length: int = 512,
    max_seconds: float = 8.0,
    silence_seconds: float = 1.2,
    energy_threshold: int = 450,
) -> bytes:
    """
    Record after a wake word using PvRecorder (not PyAudio).
    RMS + zero-crossing VAD: keep listening until silence or max_seconds.
    Returns WAV bytes ready for Whisper.
    """
    from pvrecorder import PvRecorder

    max_seconds = max(3.0, min(12.0, float(max_seconds)))
    silence_seconds = max(0.4, min(3.0, float(silence_seconds)))
    frames_needed = int((sample_rate / frame_length) * max_seconds)
    silence_needed = max(1, int((sample_rate / frame_length) * silence_seconds))

    recorder = PvRecorder(device_index=-1, frame_length=frame_length)
    pcm_all: list[int] = []
    silent_streak = 0
    heard_voice = False
    try:
        recorder.start()
        print("[!] Grabando comando del usuario…")
        for _ in range(max(1, frames_needed)):
            chunk = recorder.read()
            pcm_all.extend(chunk)
            rms = _frame_energy_rms(chunk)
            zcr = _frame_zcr(chunk)
            voiced = rms >= float(energy_threshold) and 0.015 <= zcr <= 0.40
            if voiced:
                heard_voice = True
                silent_streak = 0
            elif heard_voice:
                silent_streak += 1
                if silent_streak >= silence_needed:
                    break
    finally:
        try:
            if recorder.is_recording:
                recorder.stop()
            recorder.delete()
        except Exception:
            pass

    if not pcm_all:
        return b""

    try:
        dump = DATA_DIR / "temp_command.wav"
        dump.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dump), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"{len(pcm_all)}h", *pcm_all))
    except Exception:
        pass

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"{len(pcm_all)}h", *pcm_all))
    return buffer.getvalue()


def record_and_transcribe(
    settings: Settings,
    *,
    sample_rate: int = 16000,
    frame_length: int = 512,
    max_seconds: float = 8.0,
) -> str:
    """Capture mic after wake and send WAV to Groq/OpenAI Whisper."""
    wav = record_command_wav(
        sample_rate=sample_rate,
        frame_length=frame_length,
        max_seconds=max_seconds,
    )
    if len(wav) < 800:
        return ""
    if not contains_speech(wav, "wake.wav"):
        print("[-] Wake: VAD descartó el clip (sin voz).")
        return ""
    return transcribe_audio(settings, wav, "wake.wav")
