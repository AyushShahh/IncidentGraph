"""Unit tests for Stage 4 LLM provider abstraction layer."""
import pytest
from pydantic import BaseModel

from backend.agent.providers.base import BaseLLMProvider
from backend.agent.providers.factory import get_llm_provider, set_llm_provider
from backend.agent.providers.mock import MockLLMProvider
from backend.agent.providers.openai import OpenAILLMProvider
from backend.agent.providers.anthropic import AnthropicLLMProvider
from backend.agent.providers.gemini import GeminiLLMProvider
from backend.agent.providers.groq import GroqLLMProvider
from backend.agent.providers.ollama import OllamaLLMProvider
from backend.agent.providers.vllm import VLLMLLMProvider
from backend.agent.providers.llamacpp import LlamaCppLLMProvider


class SampleModel(BaseModel):
    name: str
    score: float


@pytest.mark.asyncio
async def test_mock_provider_queue_and_structured():
    """Verify MockLLMProvider structured generation and markdown code fence stripping."""
    mock_p = MockLLMProvider()
    mock_p.queue_response('```json\n{"name": "test_bug", "score": 0.95}\n```')

    res: SampleModel = await mock_p.generate_structured(
        messages=[{"role": "user", "content": "hello"}],
        response_model=SampleModel,
    )

    assert res.name == "test_bug"
    assert res.score == 0.95
    assert len(mock_p.recorded_calls) == 1


@pytest.mark.asyncio
async def test_mock_provider_custom_handler():
    """Verify MockLLMProvider custom callback mechanism."""
    mock_p = MockLLMProvider()
    mock_p.set_handler(lambda msgs: '{"name": "from_handler", "score": 1.0}')

    res: SampleModel = await mock_p.generate_structured(
        messages=[{"role": "user", "content": "analyze"}],
        response_model=SampleModel,
    )
    assert res.name == "from_handler"
    assert res.score == 1.0


def test_provider_factory_instantiation():
    """Verify provider factory correctly instantiates all supported providers."""
    p_mock = get_llm_provider("mock")
    assert isinstance(p_mock, MockLLMProvider)

    p_openai = get_llm_provider("openai")
    assert isinstance(p_openai, OpenAILLMProvider)

    p_anthropic = get_llm_provider("anthropic")
    assert isinstance(p_anthropic, AnthropicLLMProvider)

    p_gemini = get_llm_provider("gemini")
    assert isinstance(p_gemini, GeminiLLMProvider)

    p_groq = get_llm_provider("groq")
    assert isinstance(p_groq, GroqLLMProvider)

    p_ollama = get_llm_provider("ollama")
    assert isinstance(p_ollama, OllamaLLMProvider)

    p_vllm = get_llm_provider("vllm")
    assert isinstance(p_vllm, VLLMLLMProvider)

    p_llamacpp = get_llm_provider("llamacpp")
    assert isinstance(p_llamacpp, LlamaCppLLMProvider)


def test_set_llm_provider_override():
    """Verify set_llm_provider overrides provider globally."""
    custom = MockLLMProvider(model_name="custom-mock")
    set_llm_provider(custom, "custom")
    assert get_llm_provider("custom") is custom
