"""HUD, onboarding, owner admin and per-user API."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from jarvis import __version__
from jarvis.accounts import SESSION_MAX_AGE_SECONDS, User
from jarvis.android_ota import advertised as android_update, apk_path
from jarvis.config import STATIC_DIR
from jarvis.lan import phone_base_urls
from jarvis.packs import PACKS, normalize_pack_ids, public_packs, routine_slot, welcome_script
from jarvis.piper_tts import piper_available
from jarvis.state import AppState
from jarvis.stt import transcribe_audio
from jarvis.tts import (
    audio_api_path,
    audio_media_type,
    phrase_cache_count,
    resolve_audio_file,
    speak_to_file,
)

COOKIE = "jarvis_sid"
_HEAVY_WAIT = "Demasiadas operaciones. Esperá un segundo."


def _bind_surface(brain: Any, payload: ChatIn) -> None:
    surface = (payload.client or "hud").strip().lower()
    # Phone clients share phone_hands; HUD stays on PC tools.
    if surface in {"android", "ios", "iphone", "ipad"}:
        brain.actions.client_surface = "ios" if surface in {"ios", "iphone", "ipad"} else "android"
    else:
        brain.actions.client_surface = "hud"
    brain.actions.phone_queue = []
    device = payload.device or {}
    parts = []
    if "battery" in device:
        parts.append(f"battery {device.get('battery')}%")
    if device.get("charging"):
        parts.append("charging")
    if "wifi" in device:
        parts.append("wifi" if device.get("wifi") else "not-wifi")
    if device.get("model"):
        parts.append(str(device.get("model"))[:40])
    if device.get("app_version") or device.get("versionName"):
        parts.append(f"app {device.get('app_version') or device.get('versionName')}")
    if surface in {"ios", "iphone", "ipad"}:
        parts.append("ios")
    brain.actions.device_note = ", ".join(parts)
    if brain.actions.client_surface == "android":
        from jarvis.client_compat import android_upgrade_hint

        brain.actions.android_upgrade_hint = android_upgrade_hint(device)
    else:
        brain.actions.android_upgrade_hint = ""


def _with_android_hint(brain: Any, reply: str) -> str:
    hint = (getattr(brain.actions, "android_upgrade_hint", "") or "").strip()
    if not hint:
        return reply
    brain.actions.android_upgrade_hint = ""
    if hint in reply:
        return reply
    return f"{reply.rstrip()}\n\n{hint}"


def _phone_payload(brain: Any) -> list[dict[str, Any]]:
    items = list(brain.actions.phone_queue)
    brain.actions.phone_queue = []
    return items


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    speak: bool = False
    pack: str = ""
    client: str = "hud"
    device: dict[str, Any] = Field(default_factory=dict)


class RegisterIn(BaseModel):
    username: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    address_as: str = ""
    city: str = ""
    packs: list[str] = Field(default_factory=list)
    groq_key: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    address_as: str = ""
    city: str = ""
    packs: list[str] = Field(default_factory=list)
    groq_key: str = ""
    custom_tone: str = "equilibrado"


class AdminUserIn(BaseModel):
    user_id: int
    disabled: bool | None = None
    delete: bool = False


class AdminMetaIn(BaseModel):
    allow_signups: bool | None = None
    members_pc_hands: bool | None = None


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=128)


class RecoverUsernameIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)


class RecoverIssueIn(BaseModel):
    username: str
    display_name: str = Field(min_length=2, max_length=80)


class RecoverPasswordIn(BaseModel):
    username: str
    recovery_code: str = Field(min_length=8, max_length=64)
    new_password: str = Field(min_length=8, max_length=128)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class NoteRecordIn(BaseModel):
    id: str = ""
    text: str = Field(default="", max_length=4000)
    updated: float = 0
    deleted: bool = False


class NotesSyncIn(BaseModel):
    rev: int = 0
    items: list[NoteRecordIn] = Field(default_factory=list)


class FactsSyncIn(BaseModel):
    facts: dict[str, str] = Field(default_factory=dict)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class RateGate:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.time()
        with self._lock:
            kept = [stamp for stamp in self._hits[key] if now - stamp < window]
            if len(kept) >= limit:
                self._hits[key] = kept
                return False
            kept.append(now)
            self._hits[key] = kept
            return True


def create_hud(state: AppState) -> FastAPI:
    app = FastAPI(title="Ilaria", version=__version__, docs_url=None, redoc_url=None)
    gate = RateGate()

    def heavy(user: User, kind: str, limit: int, window: float) -> None:
        if not gate.allow(f"{kind}:{user.id}", limit, window):
            raise HTTPException(status_code=429, detail=_HEAVY_WAIT)

    def path_http(exc: ValueError) -> HTTPException:
        msg = str(exc)
        code = 403 if "escapes" in msg.lower() else 400
        return HTTPException(status_code=code, detail=msg)

    def session_token(request: Request) -> str | None:
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                return token
        for header in ("X-Ilaria-Token", "X-Jarvis-Token"):
            value = (request.headers.get(header) or "").strip()
            if value:
                return value
        cookie = request.cookies.get(COOKIE)
        return cookie if cookie else None

    def require_user(request: Request) -> User:
        user = state.accounts.user_from_session(session_token(request))
        if user is None:
            raise HTTPException(status_code=401, detail="Inicia sesion.")
        return user

    def require_owner(request: Request) -> User:
        user = require_user(request)
        if not user.is_owner:
            raise HTTPException(status_code=403, detail="Solo el dueno.")
        return user

    def set_session(response: Response, token: str) -> None:
        # 10-year persistent cookie for WebView + browser; Android uses Bearer token too.
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
            secure=False,
        )

    @app.get("/", response_model=None)
    async def root(request: Request) -> RedirectResponse | FileResponse:
        user = state.accounts.user_from_session(session_token(request))
        if user is None:
            return RedirectResponse("/welcome", status_code=302)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "ok": "1",
            "app": "Ilaria",
            "version": __version__,
            "tts": "piper" if piper_available() else "edge",
        }

    @app.get("/api/stack-health")
    async def stack_health(request: Request) -> dict[str, Any]:
        """Lightweight diagnostics for the HUD metrics panel."""
        require_user(request)
        from jarvis.discover import DISCOVER_PORT
        from jarvis.self_healing import get_system_health

        report = await asyncio.to_thread(get_system_health, state.settings)
        ram = report.get("resource_usage") or {}
        from jarvis.tts_warmer import cache_snapshot

        warm = cache_snapshot()
        return {
            "ollama": bool(report.get("ollama_alive")),
            "piper": bool(report.get("piper_ready")),
            "piper_cache_phrases": int(
                warm.get("cached_phrases_count")
                if warm.get("cached_phrases_count") is not None
                else phrase_cache_count()
            ),
            "tts_cache_warm": warm.get("status"),
            "tts_cache_ready": bool(warm.get("ready")),
            "hud": report.get("hud_health") == "OK",
            "hud_port": report.get("hud_port"),
            "udp_discover": bool(report.get("udp_discover_bound")),
            "udp_port": report.get("udp_port") or DISCOVER_PORT,
            "home_assistant": report.get("home_assistant"),
            "ram_load_pct": ram.get("ram_load_pct"),
            "ram_available_gb": ram.get("ram_available_gb"),
            "version": __version__,
        }

    @app.get("/api/android/update")
    async def android_meta() -> dict[str, object]:
        return android_update()

    @app.get("/api/android/apk")
    async def android_apk(request: Request) -> FileResponse:
        if not gate.allow(f"apk:{request.client.host if request.client else 'x'}", 8, 3600):
            raise HTTPException(status_code=429, detail="Demasiadas descargas del APK.")
        path = apk_path()
        if not path.is_file():
            raise HTTPException(status_code=404, detail="No hay APK en dist/Ilaria-android.apk")
        return FileResponse(
            path,
            media_type="application/vnd.android.package-archive",
            filename="Ilaria-android.apk",
        )

    @app.get("/favicon.svg")
    async def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg")

    @app.get("/welcome", response_model=None)
    async def welcome(request: Request) -> RedirectResponse | FileResponse:
        # Persistent cookie: skip login screen when already signed in.
        if state.accounts.user_from_session(session_token(request)) is not None:
            return RedirectResponse("/", status_code=302)
        return FileResponse(STATIC_DIR / "welcome.html")

    @app.get("/settings", response_model=None)
    async def settings_page(request: Request) -> RedirectResponse | FileResponse:
        if state.accounts.user_from_session(session_token(request)) is None:
            return RedirectResponse("/welcome", status_code=302)
        return FileResponse(STATIC_DIR / "settings.html")

    @app.get("/admin", response_model=None)
    async def admin_page(request: Request) -> RedirectResponse | FileResponse:
        user = state.accounts.user_from_session(session_token(request))
        if user is None:
            return RedirectResponse("/welcome", status_code=302)
        if not user.is_owner:
            return RedirectResponse("/", status_code=302)
        return FileResponse(STATIC_DIR / "admin.html")

    @app.get("/api/meta")
    async def meta() -> dict[str, Any]:
        owner = state.accounts.owner()
        locked = not state.accounts.allow_signups
        port = state.settings.hud_port
        from jarvis.pc_updater import load_channel_cache, min_required_android_client, update_url

        channel = load_channel_cache()
        return {
            "version": __version__,
            "allow_signups": state.accounts.allow_signups,
            "has_owner": owner is not None,
            "free": True,
            "locked": locked,
            "owner_hint": owner.username if locked and owner is not None else "",
            "hud_host": state.settings.hud_host,
            "hud_port": port,
            "phone_urls": phone_base_urls(port),
            "lan": state.settings.hud_host in {"0.0.0.0", "::"},
            "update_url_configured": bool(update_url()),
            "min_required_android_client": min_required_android_client(),
            "channel_version": str(channel.get("version") or __version__),
        }

    @app.get("/api/packs")
    async def packs() -> dict[str, Any]:
        return {"packs": public_packs()}

    @app.post("/api/register")
    async def register(payload: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
        ip = request.client.host if request.client else "local"
        if not gate.allow(f"reg:{ip}", 5, 600):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un poco.")
        try:
            user = state.accounts.register(
                username=payload.username,
                password=payload.password,
                display_name=payload.display_name,
                address_as=payload.address_as,
                city=payload.city,
                packs=normalize_pack_ids(payload.packs),
                groq_key=payload.groq_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.brain_for(user, first_time=True)
        token = state.accounts.create_session(user.id)
        set_session(response, token)
        return {"ok": True, "user": user.public(), "token": token}

    @app.post("/api/login")
    async def login(payload: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        ip = request.client.host if request.client else "local"
        key = f"login:{ip}:{payload.username.strip().lower()}"
        if not gate.allow(key, 8, 900):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera 15 minutos.")
        try:
            user = state.accounts.login(payload.username, payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.brain_for(user)
        token = state.accounts.create_session(user.id)
        set_session(response, token)
        return {"ok": True, "user": user.public(), "token": token}

    @app.post("/api/recover/username")
    async def recover_username(payload: RecoverUsernameIn, request: Request) -> dict[str, Any]:
        ip = request.client.host if request.client else "local"
        if not gate.allow(f"rec-user:{ip}", 8, 900):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Esperá un poco.")
        try:
            usernames = state.accounts.lookup_usernames(payload.display_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "usernames": usernames}

    @app.post("/api/recover/issue")
    async def recover_issue(payload: RecoverIssueIn, request: Request) -> dict[str, Any]:
        ip = request.client.host if request.client else "local"
        if not gate.allow(f"rec-issue:{ip}", 5, 900):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Esperá un poco.")
        try:
            _code, path = state.accounts.issue_recovery_code(
                payload.username,
                payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "path": str(path),
            "hint": f"Código guardado en esta PC: {path.name} (carpeta data/recovery).",
        }

    @app.post("/api/recover/password")
    async def recover_password(payload: RecoverPasswordIn, request: Request) -> dict[str, bool]:
        ip = request.client.host if request.client else "local"
        key = f"rec-pass:{ip}:{payload.username.strip().lower()}"
        if not gate.allow(key, 6, 900):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Esperá un poco.")
        try:
            state.accounts.reset_password_with_recovery(
                payload.username,
                payload.recovery_code,
                payload.new_password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        state.accounts.drop_session(session_token(request))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    async def me(request: Request) -> dict[str, Any]:
        user = require_user(request)
        brain = state.brain_for(user)
        return {
            "user": user.public(),
            "status": brain.status,
            "has_llm": state.settings_for(user).has_llm,
            "has_stt": state.settings_for(user).has_stt,
            "tts": "piper" if piper_available() else "edge",
            "version": __version__,
        }

    @app.get("/api/welcome-report")
    async def welcome_report(request: Request) -> dict[str, Any]:
        user = require_user(request)
        settings = state.settings_for(user)
        brain = state.brain_for(user)
        now = datetime.now(ZoneInfo(settings.timezone))
        next_rem = brain.memory.next_reminder_line()
        # Boot must stay fast: no weather / journal / stack probes in the spoken path.
        from jarvis.welcome_reporter import format_welcome_voice, generar_welcome_report_cotidiano

        cotidiano = generar_welcome_report_cotidiano(
            username=user.username,
            display_name=user.address_as.strip() or user.display_name,
            workspace=brain.actions.workspace,
            timezone=settings.timezone,
            stack=None,
        )
        who = user.address_as.strip() or user.display_name or user.username
        voice_base = welcome_script(address=who, hour=now.hour)
        voice = format_welcome_voice(cotidiano, voice_base)
        # Hard guard: never speak more than the greeting sentence.
        voice = (voice.split(".")[0].strip() or f"Hola, {who}") + "."
        audio_url = None
        try:
            path = await speak_to_file(
                settings,
                voice,
                f"tts-{user.id}-welcome-{time.time_ns()}.mp3",
            )
            audio_url = audio_api_path(path.name)
        except Exception:
            audio_url = None
        continue_hint = brain.continue_hint(f"u{user.id}")
        return {
            "status": "online",
            "voice_text": voice,
            "audio_url": audio_url,
            "ui_display": f"{settings.assistant_name} v{__version__}",
            "pack": routine_slot(now.hour),
            "next_reminder": next_rem,
            "last_action": getattr(brain.actions, "last_action_label", "") or "",
            "continue_hint": continue_hint,
            "cotidiano": cotidiano,
            "stack": None,
        }

    @app.get("/api/mission")
    async def mission(request: Request) -> dict[str, Any]:
        user = require_user(request)
        brain = state.brain_for(user)
        settings = state.settings_for(user)
        now = datetime.now(ZoneInfo(settings.timezone))
        return {
            "pack": routine_slot(now.hour),
            "next_reminder": brain.memory.next_reminder_line(),
            "last_action": getattr(brain.actions, "last_action_label", "") or "",
            "continue_hint": brain.continue_hint(f"u{user.id}"),
        }

    @app.post("/api/profile")
    async def profile(payload: ProfileIn, request: Request) -> dict[str, Any]:
        user = require_user(request)
        groq = payload.groq_key.strip() or None
        updated = state.accounts.update_profile(
            user.id,
            display_name=payload.display_name,
            address_as=payload.address_as,
            city=payload.city,
            packs=normalize_pack_ids(payload.packs),
            groq_key=groq,
            custom_tone=payload.custom_tone,
        )
        state.drop_brain(updated.id)
        brain = state.brain_for(updated)
        if payload.city.strip():
            brain.memory.remember("ciudad", payload.city.strip())
        brain.memory.remember("nombre", updated.display_name)
        brain.memory.remember("tono", updated.custom_tone)
        brain.memory.remember("intereses", ", ".join(updated.packs))
        for pid in updated.packs:
            pack = PACKS.get(pid)
            if pack is None:
                continue
            for key, value in pack.facts.items():
                brain.memory.remember(key, value)
        return {"ok": True, "user": updated.public()}

    @app.get("/api/status")
    async def status(request: Request) -> dict[str, str]:
        user = require_user(request)
        data = dict(state.brain_for(user).status)
        data["user"] = user.display_name
        data["role"] = user.role
        data["packs"] = ",".join(user.packs)
        return data

    @app.get("/api/alerts")
    async def alerts(request: Request, after: int = 0) -> dict[str, list[dict[str, object]]]:
        user = require_user(request)
        items = state.brain_for(user).bus.since(after)
        return {
            "items": [
                {
                    "id": item.id,
                    "text": item.text,
                    "audio_url": item.audio_url,
                }
                for item in items
            ]
        }

    @app.post("/api/chat")
    async def chat(payload: ChatIn, request: Request) -> dict[str, Any]:
        user = require_user(request)
        if not gate.allow(f"chat:{user.id}", 30, 60):
            raise HTTPException(status_code=429, detail="Freno un segundo: demasiados mensajes.")
        brain = state.brain_for(user)
        _bind_surface(brain, payload)
        try:
            reply = await asyncio.to_thread(
                brain.reply,
                f"u{user.id}",
                payload.message,
                payload.pack,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        reply = _with_android_hint(brain, reply)
        audio_url = None
        if payload.speak and reply.strip():
            if not gate.allow(f"tts:{user.id}", 20, 60):
                raise HTTPException(status_code=429, detail="Demasiada voz. Esperá un segundo.")
            try:
                path = await speak_to_file(
                    state.settings_for(user),
                    reply,
                    f"tts-{user.id}-{time.time_ns()}.mp3",
                )
                audio_url = audio_api_path(path.name)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"No pude hablar: {exc}") from exc
        return {"reply": reply, "audio_url": audio_url, "author": state.settings.assistant_name, "phone_actions": _phone_payload(brain)}

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatIn, request: Request) -> StreamingResponse:
        """SSE token stream. HUD and Android both POST here."""
        user = require_user(request)
        if not gate.allow(f"chat:{user.id}", 30, 60):
            raise HTTPException(status_code=429, detail="Freno un segundo: demasiados mensajes.")
        brain = state.brain_for(user)
        _bind_surface(brain, payload)
        session_id = f"u{user.id}"
        author = state.settings.assistant_name

        async def events():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
            started = time.perf_counter()

            def produce() -> None:
                try:
                    for token in brain.iter_reply(session_id, payload.message, payload.pack):
                        asyncio.run_coroutine_threadsafe(
                            queue.put(("token", token)),
                            loop,
                        ).result()
                except Exception as exc:  # noqa: BLE001
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("error", str(exc).strip() or exc.__class__.__name__)),
                        loop,
                    ).result()
                finally:
                    asyncio.run_coroutine_threadsafe(queue.put(("end", None)), loop).result()

            worker = threading.Thread(target=produce, name="ilaria-sse", daemon=True)
            worker.start()
            parts: list[str] = []
            early_sentence = ""
            early_audio_url = None
            early_sent = False
            while True:
                kind, value = await queue.get()
                if kind == "token" and value:
                    parts.append(value)
                    yield f"event: token\ndata: {json.dumps({'text': value}, ensure_ascii=False)}\n\n"
                    if payload.speak and not early_sent:
                        from jarvis.tts import first_speakable_sentence

                        sentence = first_speakable_sentence("".join(parts))
                        if sentence:
                            early_sent = True
                            early_sentence = sentence
                            if gate.allow(f"tts:{user.id}", 20, 60):
                                try:
                                    path = await speak_to_file(
                                        state.settings_for(user),
                                        sentence,
                                        f"tts-{user.id}-early-{time.time_ns()}.mp3",
                                    )
                                    early_audio_url = audio_api_path(path.name)
                                    yield (
                                        "event: early_audio\n"
                                        f"data: {json.dumps({'audio_url': early_audio_url, 'text': sentence}, ensure_ascii=False)}\n\n"
                                    )
                                except Exception:  # noqa: BLE001
                                    early_audio_url = None
                elif kind == "error":
                    yield f"event: error\ndata: {json.dumps({'detail': value or 'error'}, ensure_ascii=False)}\n\n"
                    return
                elif kind == "end":
                    break
            reply = _with_android_hint(brain, brain._last_assistant(session_id))
            audio_url = None
            skip_full_tts = False
            # If early TTS already covered a short final reply, skip a second render.
            if (
                early_audio_url
                and early_sentence
                and reply.strip()
                and len(reply.strip()) <= max(len(early_sentence) + 36, 96)
                and reply.strip().startswith(early_sentence[: min(24, len(early_sentence))])
            ):
                audio_url = early_audio_url
                skip_full_tts = True
            elif payload.speak and reply.strip():
                if not gate.allow(f"tts:{user.id}", 20, 60):
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'reply': reply, 'audio_url': early_audio_url, 'author': author, 'tts': 'rate', 'latency_ms': int((time.perf_counter() - started) * 1000), 'phone_actions': _phone_payload(brain)}, ensure_ascii=False)}\n\n"
                    )
                    return
                try:
                    path = await speak_to_file(
                        state.settings_for(user),
                        reply,
                        f"tts-{user.id}-{time.time_ns()}.mp3",
                    )
                    audio_url = audio_api_path(path.name)
                except Exception as exc:  # noqa: BLE001
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'reply': reply, 'audio_url': early_audio_url, 'author': author, 'tts_error': str(exc), 'latency_ms': int((time.perf_counter() - started) * 1000), 'phone_actions': _phone_payload(brain)}, ensure_ascii=False)}\n\n"
                    )
                    return
            yield (
                "event: done\n"
                f"data: {json.dumps({'reply': reply, 'audio_url': audio_url, 'author': author, 'early': bool(early_audio_url), 'skip_full_tts': skip_full_tts, 'latency_ms': int((time.perf_counter() - started) * 1000), 'phone_actions': _phone_payload(brain)}, ensure_ascii=False)}\n\n"
            )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/audio/{name}")
    async def audio(name: str, request: Request, token: str | None = None) -> FileResponse:
        auth = session_token(request) or (token.strip() if token else None)
        user = state.accounts.user_from_session(auth)
        if user is None:
            raise HTTPException(status_code=401, detail="Inicia sesion.")
        try:
            path = resolve_audio_file(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Audio no encontrado.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(path, media_type=audio_media_type(path.name), filename=path.name)

    @app.post("/api/stt")
    async def stt(request: Request, file: UploadFile = File(...)) -> dict[str, str]:
        user = require_user(request)
        if not gate.allow(f"stt:{user.id}", 20, 60):
            raise HTTPException(status_code=429, detail="Demasiados audios. Esperá un segundo.")
        settings = state.settings_for(user)
        if not settings.has_stt:
            raise HTTPException(
                status_code=400,
                detail="Falta Faster-Whisper local o una key para transcribir voz.",
            )
        data = await file.read()
        if len(data) < 400:
            return {"text": ""}
        if len(data) > 6_000_000:
            raise HTTPException(status_code=400, detail="Audio demasiado largo.")
        name = file.filename or "audio.webm"
        if "." not in name:
            name = "audio.webm"
        try:
            text = await asyncio.to_thread(transcribe_audio, settings, data, name)
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).strip() or exc.__class__.__name__
            if "Connection" in detail or "timeout" in detail.lower():
                detail = (
                    "No pude transcribir (STT local o nube). "
                    "Reintentá o escribí el mensaje."
                )
            raise HTTPException(status_code=502, detail=f"No pude transcribir: {detail}") from exc
        return {"text": text}

    @app.post("/api/tts")
    async def tts(payload: SpeakIn, request: Request) -> FileResponse:
        user = require_user(request)
        if not gate.allow(f"tts:{user.id}", 20, 60):
            raise HTTPException(status_code=429, detail="Demasiada voz. Esperá un segundo.")
        try:
            path = await speak_to_file(
                state.settings_for(user),
                payload.text,
                f"tts-{user.id}-{time.time_ns()}.mp3",
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"No pude hablar: {exc}") from exc
        return FileResponse(
            path,
            media_type=audio_media_type(path.name),
            filename=path.name,
        )

    @app.get("/api/admin/users")
    async def admin_users(request: Request) -> dict[str, Any]:
        require_owner(request)
        return {
            "users": [item.public() | {"id": item.id} for item in state.accounts.list_users()],
            "allow_signups": state.accounts.allow_signups,
            "members_pc_hands": state.accounts.members_pc_hands,
        }

    @app.post("/api/admin/users")
    async def admin_users_post(payload: AdminUserIn, request: Request) -> dict[str, Any]:
        require_owner(request)
        try:
            if payload.delete:
                state.accounts.delete_member(payload.user_id)
                state.drop_brain(payload.user_id)
                return {"ok": True}
            if payload.disabled is None:
                raise HTTPException(status_code=400, detail="Nada que cambiar.")
            user = state.accounts.set_disabled(payload.user_id, payload.disabled)
            if payload.disabled:
                state.drop_brain(user.id)
            return {"ok": True, "user": user.public()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/admin/meta")
    async def admin_meta(payload: AdminMetaIn, request: Request) -> dict[str, Any]:
        require_owner(request)
        if payload.allow_signups is not None:
            state.accounts.set_meta("allow_signups", "1" if payload.allow_signups else "0")
        if payload.members_pc_hands is not None:
            state.accounts.set_meta("members_pc_hands", "1" if payload.members_pc_hands else "0")
            for item in state.accounts.list_users():
                if not item.is_owner:
                    state.drop_brain(item.id)
        return {
            "ok": True,
            "allow_signups": state.accounts.allow_signups,
            "members_pc_hands": state.accounts.members_pc_hands,
        }

    @app.post("/api/password")
    async def password(payload: PasswordIn, request: Request) -> dict[str, bool]:
        user = require_user(request)
        try:
            state.accounts.change_password(user.id, payload.current, payload.new)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/admin/password")
    async def admin_password(payload: PasswordIn, request: Request) -> dict[str, bool]:
        owner = require_owner(request)
        try:
            state.accounts.change_password(owner.id, payload.current, payload.new)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.get("/api/notes")
    async def notes_get(request: Request) -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "notes", 60, 60)
        return state.brain_for(user).memory.notes_export()

    @app.post("/api/notes")
    async def notes_post(payload: NoteIn, request: Request) -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "notes-write", 40, 60)
        memory = state.brain_for(user).memory
        memory.add_note(payload.text)
        return memory.notes_export()

    @app.put("/api/notes/sync")
    async def notes_sync(payload: NotesSyncIn, request: Request) -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "notes-write", 40, 60)
        incoming = [item.model_dump() for item in payload.items]
        return state.brain_for(user).memory.merge_notes(incoming, payload.rev)

    @app.put("/api/memory/facts")
    async def memory_facts(payload: FactsSyncIn, request: Request) -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "facts-sync", 40, 60)
        incoming = {str(k): str(v) for k, v in payload.facts.items()}
        facts = state.brain_for(user).memory.merge_facts(incoming)
        return {"ok": True, "facts": facts}

    @app.delete("/api/notes/{note_id}")
    async def notes_delete(note_id: str, request: Request) -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "notes-write", 40, 60)
        memory = state.brain_for(user).memory
        if not memory.delete_note(note_id):
            raise HTTPException(status_code=404, detail="Nota no encontrada.")
        return memory.notes_export()

    @app.get("/api/workspace")
    async def workspace_list(request: Request, path: str = "") -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "workspace", 40, 60)
        actions = state.brain_for(user).actions
        try:
            folder = actions._safe_rel(path or ".")
        except ValueError as exc:
            raise path_http(exc) from exc
        if not folder.exists():
            return {"path": path, "items": []}
        items = []
        for child in sorted(folder.iterdir(), key=lambda p: p.name.lower())[:200]:
            items.append(
                {
                    "name": child.name,
                    "dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0,
                }
            )
        return {"path": path, "items": items}

    @app.get("/api/workspace/file")
    async def workspace_file(request: Request, path: str) -> FileResponse:
        user = require_user(request)
        heavy(user, "workspace", 40, 60)
        actions = state.brain_for(user).actions
        try:
            target = actions._safe_rel(path)
        except ValueError as exc:
            raise path_http(exc) from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        return FileResponse(target, filename=target.name)

    @app.post("/api/workspace/upload")
    async def workspace_upload(
        request: Request,
        file: UploadFile = File(...),
        relative: str = "",
    ) -> dict[str, Any]:
        user = require_user(request)
        heavy(user, "workspace-upload", 10, 60)
        actions = state.brain_for(user).actions
        name = (file.filename or "upload.bin").replace("\\", "/").split("/")[-1]
        rel = (relative.strip().strip("/") + "/" + name).strip("/") if relative.strip() else name
        try:
            dest = actions._safe_rel(rel)
        except ValueError as exc:
            raise path_http(exc) from exc
        data = await file.read()
        if len(data) > 50_000_000:
            raise HTTPException(status_code=400, detail="Archivo demasiado pesado (máx 50 MB).")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {"ok": True, "path": rel, "size": dest.stat().st_size}

    return app
