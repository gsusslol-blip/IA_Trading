"""LLM provider selection (OpenAI-compatible: Ollama first, then cloud)."""

from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from jarvis.config import Settings, _ollama_reachable

GROQ_MODELS = (
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
)

_SMALL_MARKERS = (":2b", ":3b", ":1b", ":4b", "gemma2:2b", "phi3", "tinyllama", "qwen2:1.5b")


@dataclass(frozen=True)
class LLMEndpoint:
    label: str
    client: OpenAI
    model: str


def groq_model_candidates(settings: Settings) -> list[str]:
    preferred = settings.llm_model.strip()
    models = list(GROQ_MODELS)
    if preferred and preferred not in {"gemma2:2b", "llama3", "llama3:8b"}:
        return [preferred] + [item for item in models if item != preferred]
    return models


def is_missing_model_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "model_not_found" in text
        or "does not exist" in text
        or "not have access" in text
        or "not found" in text
    )


def is_tools_unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "tool" in text and any(
        needle in text for needle in ("not support", "unsupported", "does not support", "no tools")
    )


def is_small_local_model(settings: Settings, model: str | None = None) -> bool:
    name = (model or settings.ollama_model or settings.llm_model or "").strip().lower()
    if settings.llm_provider in {"ollama", "llamacpp"}:
        return any(marker in name for marker in _SMALL_MARKERS) or name in {"llama3", "gemma2"}
    if "gemma2:2b" in name or name.endswith(":2b"):
        return True
    return False


def _ollama_model_name(settings: Settings, model: str | None) -> str:
    if model:
        return model
    if settings.llm_provider in {"ollama", "llamacpp"} and settings.llm_model.strip():
        return settings.llm_model.strip()
    return (settings.ollama_model or "gemma2:2b").strip() or "gemma2:2b"


def _ollama_endpoint(settings: Settings, model: str | None = None) -> LLMEndpoint:
    base = (settings.ollama_base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return LLMEndpoint(
        label="ollama",
        client=OpenAI(api_key="ollama", base_url=base, timeout=120.0),
        model=_ollama_model_name(settings, model),
    )


def looks_like_cloud_model(name: str) -> bool:
    """True when LLM_MODEL points at Groq/OpenAI/Gemini ids, not local Ollama tags."""
    n = (name or "").strip().lower()
    if not n:
        return False
    if "/" in n:
        return True
    if n.startswith(("gpt-", "o1", "o3", "o4", "gemini-", "claude-")):
        return True
    if n.startswith("llama-3") or n.startswith("llama3."):
        return True
    return False


def resolve_llm(settings: Settings, model: str | None = None) -> LLMEndpoint:
    provider = settings.llm_provider
    if provider == "auto":
        preferred = (settings.llm_model or "").strip()
        # Prefer cloud when LLM_MODEL is a cloud id: local 2B skips tools and "talks" instead of acting.
        if preferred and looks_like_cloud_model(preferred) and settings.groq_api_key:
            provider = "groq"
        elif preferred and looks_like_cloud_model(preferred) and settings.openai_api_key:
            provider = "openai"
        elif preferred and looks_like_cloud_model(preferred) and settings.gemini_api_key:
            provider = "gemini"
        elif _ollama_reachable(settings.ollama_base_url):
            provider = "ollama"
        elif settings.groq_api_key:
            provider = "groq"
        elif settings.openai_api_key:
            provider = "openai"
        elif settings.gemini_api_key:
            provider = "gemini"
        else:
            raise RuntimeError(
                "No hay cerebro. Levantá Ollama (gemma2:2b) o pegá GROQ_API_KEY en .env."
            )

    if provider in {"ollama", "llamacpp"}:
        return _ollama_endpoint(settings, model)
    if provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is empty.")
        return LLMEndpoint(
            label="groq",
            client=OpenAI(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            ),
            model=model or groq_model_candidates(settings)[0],
        )
    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is empty.")
        return LLMEndpoint(
            label="openai",
            client=OpenAI(api_key=settings.openai_api_key),
            model=model or settings.llm_model or "gpt-4o-mini",
        )
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is empty.")
        return LLMEndpoint(
            label="gemini",
            client=OpenAI(
                api_key=settings.gemini_api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            model=model or settings.llm_model or "gemini-2.0-flash",
        )
    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider}")
