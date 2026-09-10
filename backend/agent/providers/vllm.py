"""vLLM local high-throughput serving provider implementation."""
from typing import Any, Dict, List, Optional
import httpx

from backend.agent.providers.base import BaseLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class VLLMLLMProvider(BaseLLMProvider):
    """Asynchronous provider for high-throughput vLLM OpenAI-compatible serving endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        model = model_name or settings.VLLM_MODEL
        super().__init__(model_name=model)
        self.base_url = (base_url or settings.VLLM_BASE_URL).rstrip("/")
        self.timeout = timeout

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error("vLLM API error %s: %s", response.status_code, response.text)
                raise RuntimeError(f"vLLM API call failed with HTTP {response.status_code}: {response.text}")

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")
