"""Piper CLI on CPU — offline WAV, portable relative paths, no VRAM."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from jarvis.config import DATA_DIR, search_roots

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DEFAULT_MODEL = "es_AR-daniela-high.onnx"
_FALLBACK_MODELS = ("es_AR-daniela-high.onnx", "es_MX-ald-medium.onnx")
_EXE_NAMES = ("piper.exe", "piper")
_session_lock = threading.Lock()
_session: _PiperSession | None = None


def _existing_file(path: Path) -> Path | None:
    try:
        if path.is_file():
            return path.resolve()
    except OSError:
        return None
    return None


def _resolve_file(raw: str | Path) -> Path | None:
    path = Path(raw)
    found = _existing_file(path)
    if found is not None:
        return found
    if path.is_absolute():
        return None
    for root in search_roots():
        found = _existing_file(root / path)
        if found is not None:
            return found
    return None


def _voice_dirs() -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()
    for folder in [DATA_DIR / "tts", *[root / "data" / "tts" for root in search_roots()]]:
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        dirs.append(folder)
    return dirs


def piper_exe() -> Path | None:
    env = (os.getenv("PIPER_EXE") or "").strip()
    if env:
        found = _resolve_file(env)
        if found is not None:
            return found
    for root in search_roots():
        folder = root / "bin" / "piper"
        for name in _EXE_NAMES:
            found = _existing_file(folder / name)
            if found is not None:
                return found
    return None


def piper_model() -> Path | None:
    env = (os.getenv("PIPER_MODEL") or "").strip()
    if env:
        found = _resolve_file(env)
        if found is not None:
            return found
    for folder in _voice_dirs():
        for name in _FALLBACK_MODELS:
            found = _existing_file(folder / name)
            if found is not None:
                return found
    for folder in _voice_dirs():
        if not folder.is_dir():
            continue
        onnx = sorted(p for p in folder.glob("*.onnx") if p.is_file())
        if onnx:
            return onnx[0].resolve()
    return None


def piper_available() -> bool:
    exe = piper_exe()
    model = piper_model()
    if exe is None or model is None:
        return False
    return Path(str(model) + ".json").is_file()


def _synth_flags() -> list[str]:
    """Slightly slower, more variation, space between sentences — less ticker-robot."""
    return [
        "--length_scale",
        "1.05",
        "--noise_scale",
        "0.76",
        "--noise_w",
        "0.92",
        "--sentence_silence",
        "0.34",
    ]


class _PiperSession:
    def __init__(self, exe: Path, model: Path) -> None:
        self.exe = exe
        self.model = model
        self.work = DATA_DIR / "piper-work"
        self.work.mkdir(parents=True, exist_ok=True)
        self.proc: subprocess.Popen[bytes] | None = None
        self._spawn()

    def _spawn(self) -> None:
        self.close()
        cmd = [
            str(self.exe),
            "--model",
            str(self.model),
            "--output_dir",
            str(self.work),
            *_synth_flags(),
            "--quiet",
        ]
        espeak = self.exe.parent / "espeak-ng-data"
        if espeak.is_dir():
            cmd.extend(["--espeak_data", str(espeak)])
        kwargs: dict[str, object] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(self.exe.parent),
        }
        if os.name == "nt":
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        self.proc = subprocess.Popen(cmd, **kwargs)

    def close(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.kill()
        except OSError:
            pass

    def say(self, text: str, dest: Path) -> Path:
        line = " ".join(text.split())
        if not line:
            raise ValueError("Nothing to speak.")
        proc = self.proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            self._spawn()
            proc = self.proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("Piper process failed to start.")
        before = {p.name for p in self.work.glob("*.wav")}
        proc.stdin.write((line + "\n").encode("utf-8"))
        proc.stdin.flush()
        deadline = time.time() + 40
        newest: Path | None = None
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("Piper process exited.")
            created = [p for p in self.work.glob("*.wav") if p.name not in before]
            if created:
                candidate = max(created, key=lambda p: p.stat().st_mtime)
                size = candidate.stat().st_size
                if size > 44:
                    time.sleep(0.04)
                    if candidate.stat().st_size == size:
                        newest = candidate
                        break
            time.sleep(0.03)
        if newest is None:
            raise RuntimeError("Piper did not write audio.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        shutil.move(str(newest), str(dest))
        for leftover in self.work.glob("*.wav"):
            try:
                leftover.unlink()
            except OSError:
                pass
        return dest


def _session_for(exe: Path, model: Path) -> _PiperSession:
    global _session
    if (
        _session is None
        or _session.exe != exe
        or _session.model != model
        or _session.proc is None
        or _session.proc.poll() is not None
    ):
        if _session is not None:
            _session.close()
        _session = _PiperSession(exe, model)
    return _session


def _close_session() -> None:
    global _session
    with _session_lock:
        _drop_session()


def _drop_session() -> None:
    global _session
    if _session is not None:
        _session.close()
        _session = None


atexit.register(_close_session)


def reset_piper_session() -> None:
    """Drop persistent Piper worker so the next speak respawns cleanly."""
    with _session_lock:
        _drop_session()


def synthesize_wav(text: str, dest: Path) -> Path:
    exe = piper_exe()
    model = piper_model()
    if exe is None or model is None:
        raise RuntimeError("Piper binary or ONNX voice missing (bin/piper + data/tts).")
    try:
        with _session_lock:
            session = _session_for(exe, model)
            return session.say(text, dest)
    except Exception:
        with _session_lock:
            _drop_session()
        return _oneshot(exe, model, text, dest)


def _oneshot(exe: Path, model: Path, text: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    cmd = [
        str(exe),
        "--model",
        str(model),
        "--output_file",
        str(dest),
        *_synth_flags(),
        "--quiet",
    ]
    kwargs: dict[str, object] = {
        "input": (text.strip() + "\n").encode("utf-8"),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "cwd": str(exe.parent),
        "timeout": 40,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    completed = subprocess.run(cmd, **kwargs)
    if completed.returncode != 0 or not dest.is_file():
        err = (completed.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise RuntimeError(err or f"Piper exit {completed.returncode}")
    return dest
