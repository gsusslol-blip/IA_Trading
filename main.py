"""Launch Ilaria (dev and standalone exe)."""

from __future__ import annotations

import multiprocessing
import sys
import traceback
from pathlib import Path


def _attach_log() -> None:
    if not getattr(sys, "frozen", False):
        return
    folder = Path(sys.executable).resolve().parent / "data"
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / "jarvis.log", "a", encoding="utf-8")
    sys.stdout = handle
    sys.stderr = handle


def _alert(title: str, message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        print(message)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _attach_log()
    try:
        try:
            from jarvis.pc_updater import maybe_update_on_boot

            maybe_update_on_boot()
        except Exception as upd_exc:  # noqa: BLE001 — never block boot
            print(f"[updater] ignored: {upd_exc}")
        from jarvis.runtime import main

        main()
    except SystemExit:
        raise
    except Exception:
        text = traceback.format_exc()
        print(text)
        _alert("Ilaria", "No pude arrancar. Mira data\\jarvis.log junto al .exe")
        raise
