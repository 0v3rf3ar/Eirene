"""Provider catalogue and factory."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.config import Config
from ..core.errors import ProviderError
from .anthropic_compat import AnthropicCompatible
from .base import Provider
from .gemini import Gemini
from .ollama import Ollama
from .openai_compat import OpenAICompatible
from .omniroute import OmniRoute
from .codex_subscription import CodexSubscription
from .claude_code import ClaudeCode
from .chatgpt_plan import ChatGPTPlan


@dataclass
class Spec:
    """Static facts about one provider."""

    key: str
    label: str
    protocol: str
    base_url: str = ""
    needs_key: bool = True
    needs_base_url: bool = False
    supports_tools: bool = True
    key_hint: str = ""
    models: list[str] = field(default_factory=list)
    note: str = ""
    optional_key: bool = False


SPECS: dict[str, Spec] = {
    "chatgpt-plan": Spec(
        "chatgpt-plan", "ChatGPT subscription", "chatgpt-responses",
        "https://api.openai.com/v1", needs_key=False,
        note="uses your authorized ChatGPT plan; Eirene runs the workspace tools"),
    "claude-code": Spec(
        "claude-code", "Claude (headless)", "claude-code-cli",
        needs_key=False, supports_tools=False,
        models=["sonnet", "opus", "haiku"],
        note="uses Claude Code tools and your Claude subscription limits"),
    "chatgpt-subscription": Spec(
        "chatgpt-subscription", "Codex (headless)", "codex-app-server",
        needs_key=False, supports_tools=False,
        note="uses Codex tools and your ChatGPT subscription limits"),
    "chatgpt": Spec(
        "chatgpt", "OpenAI API", "openai", "https://api.openai.com/v1",
        key_hint="starts with 'sk-'",
        models=["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o",
                "gpt-4o-mini", "o3", "o4-mini"]),
    "anthropic": Spec(
        "anthropic", "Anthropic (Claude)", "anthropic", "https://api.anthropic.com/v1",
        key_hint="starts with 'sk-ant-'",
        models=["claude-opus-4-1-20250805", "claude-sonnet-4-5-20250929",
                "claude-haiku-4-5-20251001", "claude-3-7-sonnet-latest"]),
    "ollama": Spec(
        "ollama", "Ollama (API)", "ollama", "https://ollama.com",
        key_hint="from ollama.com/settings/keys",
        models=["gpt-oss:120b", "gpt-oss:20b", "deepseek-v3.1:671b",
                "qwen3-coder:480b", "kimi-k2:1t", "glm-4.6", "minimax-m2"]),
    "ollama-local": Spec(
        "ollama-local", "Ollama (local)", "ollama", "http://localhost:11434",
        needs_key=False),
    "gemini": Spec(
        "gemini", "Gemini", "gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        key_hint="Google AI Studio key",
        models=["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                "gemini-2.0-flash"]),
    "groq": Spec(
        "groq", "Groq", "openai", "https://api.groq.com/openai/v1",
        key_hint="from console.groq.com/keys",
        models=["openai/gpt-oss-120b", "openai/gpt-oss-20b",
                "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]),
    "omniroute": Spec(
        "omniroute", "OmniRoute", "openai", "http://localhost:20128/v1",
        needs_key=False, needs_base_url=True, optional_key=True,
        key_hint="from OmniRoute Dashboard → Endpoints; leave empty if auth is disabled",
        models=["auto/coding", "auto"],
        note="routing, providers, combos, and compression are configured in the OmniRoute dashboard"),
    "deepseek": Spec(
        "deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1",
        key_hint="starts with 'sk-'",
        models=["deepseek-chat", "deepseek-reasoner"]),
    "kimi": Spec(
        "kimi", "Kimi (Moonshot)", "openai", "https://api.moonshot.ai/v1",
        key_hint="starts with 'sk-'",
        models=["kimi-k2-turbo-preview", "kimi-k2-0905-preview", "kimi-latest",
                "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"]),
    "perplexity": Spec(
        "perplexity", "Perplexity", "openai", "https://api.perplexity.ai",
        key_hint="starts with 'pplx-'", supports_tools=False,
        note="search only; no tool calling, so it cannot edit files or run commands",
        models=["sonar", "sonar-pro", "sonar-reasoning", "sonar-reasoning-pro",
                "sonar-deep-research"]),
    "custom-openai": Spec(
        "custom-openai", "Custom OpenAI-compatible", "openai",
        needs_base_url=True, key_hint="whatever your endpoint expects",
        note="base URL must end at /v1"),
    "custom-anthropic": Spec(
        "custom-anthropic", "Custom Anthropic-compatible", "anthropic",
        needs_base_url=True, key_hint="whatever your endpoint expects",
        note="base URL must end at /v1"),
}

ORDER = list(SPECS)


def available(key: str) -> bool:
    if key != "omniroute":
        return True
    from ..core.plugins import discover
    return any(plugin.name == "omniroute" for plugin in discover())


def spec(key: str) -> Spec:
    found = SPECS.get(key.strip().lower())
    if not found:
        raise ProviderError(f"unknown provider '{key}'")
    return found


def resolve_alias(name: str) -> str:
    """Map friendly names to keys."""
    text = name.strip().lower().replace("_", "-")
    aliases = {"openai": "chatgpt", "gpt": "chatgpt", "claude": "anthropic",
               "claude-subscription": "claude-code", "claude-cli": "claude-code",
               "subscription": "chatgpt-subscription", "codex": "chatgpt-subscription",
               "chatgpt-direct": "chatgpt-plan", "chatgpt-oauth": "chatgpt-plan",
               "moonshot": "kimi", "google": "gemini", "pplx": "perplexity",
               "custom": "custom-openai", "openai-compatible": "custom-openai",
               "anthropic-compatible": "custom-anthropic",
               "ollama-api": "ollama", "ollama-cloud": "ollama",
               "local-ollama": "ollama-local"}
    if text in SPECS:
        return text
    if text in aliases:
        return aliases[text]
    matches = [key for key in SPECS if key.startswith(text)]
    if len(matches) == 1:
        return matches[0]
    raise ProviderError(f"unknown provider '{name}'")


def build(key: str, config: Config, *, api_key: str | None = None,
          base_url: str | None = None) -> Provider:
    """Instantiate a provider from config."""
    info = spec(key)
    token = api_key if api_key is not None else config.api_key(key)
    url = (base_url or config.base_url(key) or info.base_url).rstrip("/")
    timeout = float(config.get("request_timeout", 300) or 300)

    if info.protocol == "chatgpt-responses":
        return ChatGPTPlan(timeout=timeout,
                           reasoning_efforts=config.provider_config(key).get("reasoning_efforts"))
    if info.protocol == "codex-app-server":
        return CodexSubscription(timeout=timeout)
    if info.protocol == "claude-code-cli":
        return ClaudeCode(timeout=timeout)

    if info.needs_key and not token:
        raise ProviderError(f"{info.label} has no API key; run /connect")
    if not url:
        raise ProviderError(f"{info.label} has no base URL; run /connect")

    if info.protocol == "anthropic":
        return AnthropicCompatible(token, url, name=key, static_models=info.models,
                                   timeout=timeout)
    if info.protocol == "gemini":
        return Gemini(token, url, static_models=info.models, timeout=timeout)
    if info.protocol == "ollama":
        think = None
        if key == "ollama-local":
            think = bool(config.provider_config(key).get("think", True))
        return Ollama(token, url, name=key, static_models=info.models,
                      timeout=max(timeout, 600.0), think=think)
    if key == "omniroute":
        return OmniRoute(token, url, timeout=timeout)
    return OpenAICompatible(token, url, name=key, supports_tools=info.supports_tools,
                            static_models=info.models, timeout=timeout)


def default_model(key: str) -> str:
    info = spec(key)
    return info.models[0] if info.models else ""


def validate_key(key: str, raw: str) -> str:
    """Clean and sanity-check a pasted key."""
    if raw is None:
        raise ProviderError("no key given")
    cleaned = "".join(raw.split())
    if not cleaned:
        raise ProviderError("key is empty")
    if len(cleaned) < 8:
        raise ProviderError("key is too short to be valid")
    if len(cleaned) > 512:
        raise ProviderError("key is unusually long; check what you pasted")
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise ProviderError("key contains control characters")
    return cleaned


def validate_base_url(raw: str) -> str:
    """Clean and sanity-check a base URL."""
    cleaned = (raw or "").strip().rstrip("/")
    if not cleaned:
        raise ProviderError("base URL is empty")
    if not cleaned.startswith(("http://", "https://")):
        raise ProviderError("base URL must start with http:// or https://")
    if " " in cleaned:
        raise ProviderError("base URL contains a space")
    if len(cleaned) > 300:
        raise ProviderError("base URL is too long")
    return cleaned
