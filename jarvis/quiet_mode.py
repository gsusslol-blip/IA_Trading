"""Deterministic Quiet-Mode from Windows focus / fullscreen (no LLM).

When active: suppress beeps and proactive TTS; HUD stays text-only for alerts.
User-initiated chat/wake speech is NOT suppressed (caller decides).

Env:
  QUIET_MODE_ENABLED=1|0   (default 1 on Windows)
  QUIET_FORCE=1            force quiet (tests / manual)
  QUIET_EXTRA_EXES=foo.exe,bar.exe
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

# Hard quiet when these own the foreground (games/media launchers & players).
_QUIET_FOCUS_EXES = frozenset(
    {
        "steam.exe",
        "steamwebhelper.exe",
        "gameoverlayui.exe",
        "epicgameslauncher.exe",
        "origin.exe",
        "eadesktop.exe",
        "battle.net.exe",
        "vlc.exe",
        "mpv.exe",
        "mpc-hc.exe",
        "mpc-hc64.exe",
        "potplayer.exe",
        "potplayer64.exe",
        "wmplayer.exe",
        "spotify.exe",
        "plex.exe",
        "kodi.exe",
    }
)

# Only quiet when this process is also fullscreen / near-fullscreen.
_SOFT_FULLSCREEN_EXES = frozenset(
    {
        "cursor.exe",
        "code.exe",
        "devenv.exe",
        "chrome.exe",
        "msedge.exe",
        "brave.exe",
        "firefox.exe",
    }
)

_lock = Lock()
_cache: QuietState | None = None
_cache_at = 0.0
_CACHE_TTL_S = 1.25


@dataclass(frozen=True)
class QuietState:
    active: bool
    reason: str
    process: str = ""
    title: str = ""
    fullscreen: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def quiet_mode_enabled() -> bool:
    raw = os.getenv("QUIET_MODE_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def evaluate_quiet(
    *,
    process: str = "",
    title: str = "",
    fullscreen: bool = False,
    force: bool | None = None,
) -> QuietState:
    """Pure policy — unit-testable without Win32."""
    if not quiet_mode_enabled():
        return QuietState(active=False, reason="disabled")

    if force is None:
        force = os.getenv("QUIET_FORCE", "0").strip().lower() in {"1", "true", "yes", "on"}
    if force:
        return QuietState(
            active=True,
            reason="force",
            process=process,
            title=title,
            fullscreen=fullscreen,
        )

    exe = (process or "").strip().lower()
    if "\\" in exe or "/" in exe:
        exe = exe.replace("\\", "/").rsplit("/", 1)[-1]

    extra = {
        p.strip().lower()
        for p in (os.getenv("QUIET_EXTRA_EXES") or "").replace(";", ",").split(",")
        if p.strip()
    }
    quiet_exes = _QUIET_FOCUS_EXES | extra

    if fullscreen and exe in _SOFT_FULLSCREEN_EXES:
        return QuietState(
            active=True,
            reason=f"fullscreen:{exe or 'unknown'}",
            process=exe,
            title=title,
            fullscreen=True,
        )
    if fullscreen and exe and exe not in {"explorer.exe", "shellhost.exe", "searchhost.exe"}:
        # Any other app covering the monitor (games .exe, video, etc.)
        return QuietState(
            active=True,
            reason=f"fullscreen:{exe}",
            process=exe,
            title=title,
            fullscreen=True,
        )
    if exe in quiet_exes:
        return QuietState(
            active=True,
            reason=f"focus:{exe}",
            process=exe,
            title=title,
            fullscreen=fullscreen,
        )
    return QuietState(
        active=False,
        reason="off",
        process=exe,
        title=title,
        fullscreen=fullscreen,
    )


def probe_foreground() -> tuple[str, str, bool]:
    """Return (process_basename, window_title, is_fullscreen). Non-Windows → empty."""
    if sys.platform != "win32":
        return "", "", False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", "", False

        # Title
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(max(length, 1))
        user32.GetWindowTextW(hwnd, buf, length)
        title = (buf.value or "").strip()

        # Process
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = ""
        if pid.value:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if handle:
                try:
                    size = wintypes.DWORD(512)
                    path_buf = ctypes.create_unicode_buffer(512)
                    # QueryFullProcessImageNameW
                    if kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                        process = path_buf.value or ""
                finally:
                    kernel32.CloseHandle(handle)
        exe = process.replace("\\", "/").rsplit("/", 1)[-1] if process else ""

        fullscreen = _is_fullscreen(hwnd, user32)
        return exe.lower(), title, fullscreen
    except Exception:
        return "", "", False


def _is_fullscreen(hwnd: int, user32: Any) -> bool:
    """True for exclusive / borderless fullscreen (not a normal maximized app).

    Maximized windows sit on the *work* area (taskbar free). Exclusive
    fullscreen usually matches the raw monitor rect edge-to-edge.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        if win_w < 400 or win_h < 300:
            return False

        MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return False
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return False
        mon = info.rcMonitor
        work = info.rcWork
        mon_w = mon.right - mon.left
        mon_h = mon.bottom - mon.top
        if mon_w <= 0 or mon_h <= 0:
            return False

        def _edges_match(target: RECT, slack: int = 3) -> bool:
            return (
                abs(rect.left - target.left) <= slack
                and abs(rect.top - target.top) <= slack
                and abs(rect.right - target.right) <= slack
                and abs(rect.bottom - target.bottom) <= slack
            )

        # Exclusive / borderless: matches the full monitor (covers taskbar).
        if _edges_match(mon, slack=4):
            return True
        # Some games report 1px off; also accept ≥99% of monitor with near origin.
        area_ratio = (win_w * win_h) / float(mon_w * mon_h)
        if area_ratio >= 0.99 and abs(rect.left - mon.left) <= 4 and abs(rect.top - mon.top) <= 4:
            # Reject plain maximized (fits work area, leaves taskbar).
            if _edges_match(work, slack=6):
                return False
            work_h = work.bottom - work.top
            if win_h <= work_h + 2 and rect.bottom <= work.bottom + 2:
                return False
            return True
        return False
    except Exception:
        return False


def snapshot(*, bypass_cache: bool = False) -> QuietState:
    """Cached live evaluation for the local PC."""
    global _cache, _cache_at
    now = time.monotonic()
    with _lock:
        if not bypass_cache and _cache is not None and (now - _cache_at) < _CACHE_TTL_S:
            return _cache
    process, title, fullscreen = probe_foreground()
    state = evaluate_quiet(process=process, title=title, fullscreen=fullscreen)
    with _lock:
        _cache = state
        _cache_at = time.monotonic()
    return state


def is_quiet(*, bypass_cache: bool = False) -> bool:
    return snapshot(bypass_cache=bypass_cache).active


def clear_cache() -> None:
    global _cache, _cache_at
    with _lock:
        _cache = None
        _cache_at = 0.0
