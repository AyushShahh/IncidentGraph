"""OpenAI LLM provider implementation using asynchronous HTTP."""
from typing import Any, Dict, List, Optional
import httpx

from backend.agent.providers.base import BaseLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class OpenAILLMProvider(BaseLLMProvider):
    """Native asynchronous provider for OpenAI APIs (GPT-4o, GPT-4o-mini)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        model = model_name or settings.OPENAI_MODEL or settings.LLM_MODEL
        super().__init__(model_name=model)
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.timeout = timeout

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        if not self.api_key:
            raise ValueError("OpenAI API key is missing. Set OPENAI_API_KEY in environment or .env.")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error("OpenAI API error %s: %s", response.status_code, response.text)
                raise RuntimeError(f"OpenAI API call failed with HTTP {response.status_code}: {response.text}")

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")
