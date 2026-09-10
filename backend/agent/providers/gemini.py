"""Google Gemini LLM provider implementation using asynchronous HTTP."""
from typing import Any, Dict, List, Optional
import httpx

from backend.agent.providers.base import BaseLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class GeminiLLMProvider(BaseLLMProvider):
    """Native asynchronous provider for Google Gemini API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        model = model_name or settings.GEMINI_LLM_MODEL
        super().__init__(model_name=model)
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.base_url = (base_url or settings.GEMINI_BASE_URL).rstrip("/")
        self.timeout = timeout

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        if not self.api_key:
            raise ValueError("Gemini API key is missing. Set GEMINI_API_KEY in environment or .env.")

        # Strip 'models/' prefix if present
        model_id = self.model_name.replace("models/", "")
        url = f"{self.base_url}/models/{model_id}:generateContent?key={self.api_key}"

        # Group messages into Gemini format
        contents = []
        system_instruction = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                gemini_role = "user" if role == "user" else "model"
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Please proceed."}]}]

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error("Gemini API error %s: %s", response.status_code, response.text)
                raise RuntimeError(f"Gemini API call failed with HTTP {response.status_code}: {response.text}")

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return ""
            return parts[0].get("text", "")
