"""Provider factory for instantiating pluggable LLM backends."""
from typing import Dict, Optional

from backend.agent.providers.base import BaseLLMProvider
from backend.agent.providers.openai import OpenAILLMProvider
from backend.agent.providers.anthropic import AnthropicLLMProvider
from backend.agent.providers.gemini import GeminiLLMProvider
from backend.agent.providers.groq import GroqLLMProvider
from backend.agent.providers.ollama import OllamaLLMProvider
from backend.agent.providers.vllm import VLLMLLMProvider
from backend.agent.providers.llamacpp import LlamaCppLLMProvider
from backend.agent.providers.mock import MockLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_cached_providers: Dict[str, BaseLLMProvider] = {}


def get_llm_provider(provider_type: Optional[str] = None) -> BaseLLMProvider:
    """Instantiate or retrieve a cached LLM provider based on configuration.

    Supports: 'openai', 'anthropic', 'gemini', 'groq', 'ollama', 'vllm', 'llamacpp', 'mock'.
    """
    provider_name = (provider_type or settings.LLM_PROVIDER).strip().lower()

    if provider_name in _cached_providers:
        return _cached_providers[provider_name]

    logger.info("Instantiating LLM provider '%s'...", provider_name)

    if provider_name in ("openai", "gpt"):
        provider = OpenAILLMProvider()
    elif provider_name in ("anthropic", "claude"):
        provider = AnthropicLLMProvider()
    elif provider_name in ("gemini", "google"):
        provider = GeminiLLMProvider()
    elif provider_name == "groq":
        provider = GroqLLMProvider()
    elif provider_name == "ollama":
        provider = OllamaLLMProvider()
    elif provider_name == "vllm":
        provider = VLLMLLMProvider()
    elif provider_name in ("llamacpp", "llama.cpp"):
        provider = LlamaCppLLMProvider()
    elif provider_name in ("mock", "test"):
        provider = MockLLMProvider()
    else:
        logger.warning("Unrecognized LLM provider '%s', falling back to Mock provider.", provider_name)
        provider = MockLLMProvider()

    _cached_providers[provider_name] = provider
    return provider


def set_llm_provider(provider: BaseLLMProvider, provider_name: str = "custom") -> None:
    """Override the active provider for testing or specialized agent tasks."""
    _cached_providers[provider_name.lower()] = provider
    _cached_providers[settings.LLM_PROVIDER.lower()] = provider


def set_global_provider_override(provider: Optional[BaseLLMProvider]) -> None:
    """Set or clear a global override provider for testing."""
    if provider is None:
        _cached_providers.clear()
    else:
        _cached_providers[settings.LLM_PROVIDER.lower()] = provider
        _cached_providers["mock"] = provider
        _cached_providers["custom"] = provider

