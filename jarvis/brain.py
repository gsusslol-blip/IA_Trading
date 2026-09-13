"""Conversation loop with tool use and local-first reasoning."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pathlib import Path

from jarvis.actions import Actions
from jarvis.bus import EventBus
from jarvis.config import Settings
from jarvis.llm import (
    LLMEndpoint,
    groq_model_candidates,
    is_missing_model_error,
    is_small_local_model,
    is_tools_unsupported,
    resolve_llm,
)
from jarvis.memory import Memory
from jarvis.personality import (
    build_system_prompt,
    guard_filial_reply,
    messages_with_lock,
)
from jarvis.security import redact_secrets, secret_values
from jarvis.tools import TOOL_SCHEMAS, make_executor, schemas_for

MAX_HISTORY = 24
MAX_TOOL_ROUNDS = 6
# gpt-oss uses inner reasoning; keep headroom on the first/tool passes.
REASONING_MAX_TOKENS = 2500
SYNTHESIS_MAX_TOKENS = 1500
REASONING_TEMPERATURE = 0.2
SMALL_MAX_TOKENS = 220
SMALL_TEMPERATURE = 0.65


class Brain:
    def __init__(
        self,
        settings: Settings,
        memory: Memory | None = None,
        bus: EventBus | None = None,
        workspace: Path | None = None,
        profile_style: str = "",
        enabled_packs: list[str] | None = None,
        custom_tone: str = "equilibrado",
        city: str = "",
        allowed_tools: set[str] | None = None,
        is_owner: bool = False,
    ) -> None:
        self.settings = settings
        self.memory = memory or Memory()
        self.bus = bus or EventBus()
        self.profile_style = profile_style
        self.enabled_packs = list(enabled_packs or [])
        self.custom_tone = custom_tone
        self.city = city
        self.is_owner = is_owner
        self.allowed_tools = allowed_tools
        self.actions = Actions(settings, self.bus, workspace, is_owner=is_owner)
        self._endpoint: LLMEndpoint | None = None
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        raw_execute = make_executor(settings, self.memory, self.actions)

        def execute(name: str, arguments_json: str) -> str:
            if self.allowed_tools is not None and name not in self.allowed_tools:
                return "Permiso denegado: esa accion es solo del dueno."
            result = raw_execute(name, arguments_json)
            return redact_secrets(result, extra=secret_values(self.settings))

        self.execute = execute

    def _chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        if self.endpoint.label == "groq":
            last: BaseException | None = None
            for model in groq_model_candidates(self.settings):
                try:
                    self._endpoint = resolve_llm(self.settings, model=model)
                    return self.endpoint.client.chat.completions.create(
                        model=self.endpoint.model,
                        messages=messages,
                        **kwargs,
                    )
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    if not is_missing_model_error(exc):
                        raise
                    self._endpoint = None
            if last is not None:
                raise last
        return self.endpoint.client.chat.completions.create(
            model=self.endpoint.model,
            messages=messages,
            **kwargs,
        )

    def _finish(self, text: str) -> str:
        clean = redact_secrets(text or "", extra=secret_values(self.settings))
        return guard_filial_reply(
            clean,
            is_owner=self.is_owner,
            address_as=self.settings.user_name,
        )

    @property
    def endpoint(self) -> LLMEndpoint:
        if self._endpoint is None:
            self._endpoint = resolve_llm(self.settings)
        return self._endpoint

    @property
    def status(self) -> dict[str, str]:
        llm = "local"
        if self.settings.has_llm:
            try:
                llm = f"{self.endpoint.label}:{self.endpoint.model}"
            except RuntimeError:
                llm = "setup"
        return {
            "name": self.settings.assistant_name,
            "llm": llm,
            "net": "online",
            "hands": "full" if self.is_owner else "limited",
            "mail": "on" if self.settings.has_smtp else "off",
            "ha": "on" if self.settings.has_ha else "off",
            "stt": "ready" if self.settings.has_stt else "text-only",
            "telegram": "ready" if self.settings.has_telegram else "off",
        }

    def due_alerts(self) -> list[str]:
        now = datetime.now(ZoneInfo(self.settings.timezone))
        return self.memory.due_reminders(now)

    def _local_answer(self, text: str) -> str:
        from jarvis.local import local_reply

        return local_reply(
            text,
            self.execute,
            self.memory,
            self.settings,
            self.allowed_tools,
            surface=getattr(self.actions, "client_surface", "hud"),
        )

    def _store(self, session_id: str, answer: str) -> str:
        clean = redact_secrets(answer, extra=secret_values(self.settings))
        self._history[session_id].append({"role": "assistant", "content": clean})
        return clean

    def _last_assistant(self, session_id: str) -> str:
        history = self._history[session_id]
        if history and history[-1].get("role") == "assistant":
            content = history[-1].get("content")
            if isinstance(content, str) and content.strip():
                return content
        return ""

    def _iter_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        stream = self._chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            piece = getattr(delta, "content", None) or ""
            if piece:
                yield redact_secrets(piece, extra=secret_values(self.settings))

    def reply(self, session_id: str, user_text: str, focus_pack: str = "") -> str:
        pieces: list[str] = []
        for part in self.iter_reply(session_id, user_text, focus_pack):
            pieces.append(part)
        stored = self._last_assistant(session_id)
        if stored:
            return stored
        return "".join(pieces) or "No capté nada. Repetilo, por favor."

    def iter_reply(self, session_id: str, user_text: str, focus_pack: str = "") -> Iterator[str]:
        """Yield reply chunks. History stores the post-filter final text, not LOCK."""
        text = redact_secrets(user_text.strip(), extra=secret_values(self.settings))
        if not text:
            yield "No capté nada. Repetilo, por favor."
            return

        history = self._history[session_id]
        history.append({"role": "user", "content": text})

        from jarvis.local import try_local_command

        commanded = try_local_command(
            text,
            self.execute,
            self.memory,
            self.settings,
            self.allowed_tools,
            surface=getattr(self.actions, "client_surface", "hud"),
        )
        if commanded:
            answer = self._finish(commanded)
            self._store(session_id, answer)
            yield answer
            return

        if not self.settings.has_llm:
            answer = self._finish(self._local_answer(text))
            self._store(session_id, answer)
            yield answer
            return

        small = is_small_local_model(self.settings, self.endpoint.model)
        cap = 10 if small else MAX_HISTORY
        history[:] = history[-cap:]

        system = build_system_prompt(
            self.settings,
            self.memory,
            self.actions,
            self.profile_style,
            self.is_owner,
            focus_pack=focus_pack,
            user_message=text,
            enabled_packs=self.enabled_packs,
            custom_tone=self.custom_tone,
            city=self.city,
            compact=small,
            client_surface=getattr(self.actions, "client_surface", "hud"),
            device_note=getattr(self.actions, "device_note", ""),
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *history,
        ]
        if small:
            messages = messages_with_lock(messages, is_owner=self.is_owner)
        tools = schemas_for(self.allowed_tools) if self.allowed_tools is not None else TOOL_SCHEMAS
        max_tokens = SMALL_MAX_TOKENS if small else REASONING_MAX_TOKENS
        temperature = SMALL_TEMPERATURE if small else REASONING_TEMPERATURE

        try:
            if small:
                raw_parts: list[str] = []
                for piece in self._iter_tokens(
                    messages, temperature=temperature, max_tokens=max_tokens
                ):
                    raw_parts.append(piece)
                    yield piece
                answer = self._finish("".join(raw_parts))
                if not answer:
                    answer = "Sistemas en línea, pero no armé una respuesta. Probá de nuevo."
                    yield answer
                self._store(session_id, answer)
                return

            for _ in range(MAX_TOOL_ROUNDS):
                try:
                    response = self._chat(
                        messages,
                        tools=tools,
                        tool_choice="auto",
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as exc:  # noqa: BLE001
                    if is_tools_unsupported(exc):
                        raw_parts = []
                        for piece in self._iter_tokens(
                            messages, temperature=temperature, max_tokens=max_tokens
                        ):
                            raw_parts.append(piece)
                            yield piece
                        answer = self._finish("".join(raw_parts))
                        if not answer:
                            answer = "Sistemas en línea, pero no armé una respuesta. Probá de nuevo."
                            yield answer
                        self._store(session_id, answer)
                        return
                    raise
                choice = response.choices[0].message
                tool_calls = choice.tool_calls or []
                if tool_calls and _broken_tool_json(tool_calls):
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "La llamada a herramienta no era JSON válido. "
                                "Reintentá la tool con arguments como objeto JSON plano."
                            ),
                        }
                    )
                    continue
                if not tool_calls:
                    raw = choice.content or ""
                    if raw:
                        yield redact_secrets(raw, extra=secret_values(self.settings))
                    answer = self._finish(raw)
                    if not answer:
                        answer = "Sistemas en línea, pero no armé una respuesta. Probá de nuevo."
                        yield answer
                    self._store(session_id, answer)
                    return

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": choice.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments or "{}",
                            },
                        }
                        for call in tool_calls
                    ],
                }
                messages.append(assistant_msg)
                history.append(assistant_msg)

                for call in tool_calls:
                    result = self.execute(call.function.name, call.function.arguments or "{}")
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result[:12000],
                    }
                    messages.append(tool_msg)
                    history.append(tool_msg)

            raw_parts = []
            for piece in self._iter_tokens(
                messages,
                temperature=temperature,
                max_tokens=SYNTHESIS_MAX_TOKENS,
            ):
                raw_parts.append(piece)
                yield piece
            answer = self._finish("".join(raw_parts))
            if not answer:
                answer = "No pude cerrar la respuesta después de usar las herramientas."
                yield answer
            self._store(session_id, answer)
        except Exception as exc:  # noqa: BLE001
            if is_missing_model_error(exc) or _is_soft_llm_failure(exc):
                answer = self._finish(self._local_answer(text))
                self._store(session_id, answer)
                yield answer
                return
            detail = redact_secrets(
                str(exc).strip() or exc.__class__.__name__,
                extra=secret_values(self.settings),
            )
            if self.is_owner:
                who = (self.settings.user_name or "").strip() or "pá"
                answer = f"{who}, se me trabó el cerebro local: {detail}"
            else:
                answer = f"Detecté una anomalía en el enlace cognitivo: {detail}"
            self._store(session_id, answer)
            yield answer


def _broken_tool_json(tool_calls: list[Any]) -> bool:
    for call in tool_calls:
        raw = getattr(getattr(call, "function", None), "arguments", None) or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return True
        if not isinstance(parsed, dict):
            return True
    return False


def _is_soft_llm_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    needles = (
        "rate limit",
        "429",
        "503",
        "502",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "overloaded",
    )
    return any(item in text for item in needles)
