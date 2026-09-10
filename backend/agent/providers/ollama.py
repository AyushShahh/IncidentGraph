"""Ollama local LLM provider implementation using asynchronous HTTP."""
from typing import Any, Dict, List, Optional
import httpx

from backend.agent.providers.base import BaseLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class OllamaLLMProvider(BaseLLMProvider):
    """Local inference provider for Ollama (e.g. Qwen2.5-Coder, Llama 3.1)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        model = model_name or settings.OLLAMA_LLM_MODEL
        super().__init__(model_name=model)
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error("Ollama API error %s: %s", response.status_code, response.text)
                raise RuntimeError(f"Ollama API call failed with HTTP {response.status_code}: {response.text}")

            data = response.json()
            return data.get("message", {}).get("content", "")
