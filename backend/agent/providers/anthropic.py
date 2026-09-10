"""Anthropic Claude LLM provider implementation using asynchronous HTTP."""
from typing import Any, Dict, List, Optional
import httpx

from backend.agent.providers.base import BaseLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AnthropicLLMProvider(BaseLLMProvider):
    """Native asynchronous provider for Anthropic Claude APIs (Claude 3.5 Sonnet / Haiku)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        model = model_name or settings.ANTHROPIC_MODEL
        super().__init__(model_name=model)
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.base_url = (base_url or settings.ANTHROPIC_BASE_URL).rstrip("/")
        self.timeout = timeout

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        if not self.api_key:
            raise ValueError("Anthropic API key is missing. Set ANTHROPIC_API_KEY in environment or .env.")

        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Separate system messages from user/assistant messages
        system_content = []
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_content.append(content)
            else:
                anthropic_messages.append({"role": role, "content": content})

        if not anthropic_messages:
            anthropic_messages = [{"role": "user", "content": "Please proceed."}]

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 2048,
            "temperature": temperature,
        }
        if system_content:
            payload["system"] = "\n\n".join(system_content)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error("Anthropic API error %s: %s", response.status_code, response.text)
                raise RuntimeError(f"Anthropic API call failed with HTTP {response.status_code}: {response.text}")

            data = response.json()
            content_blocks = data.get("content", [])
            for block in content_blocks:
                if block.get("type") == "text":
                    return block.get("text", "")
            return ""
