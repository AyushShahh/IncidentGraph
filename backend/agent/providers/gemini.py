"""Google Gemini / Vertex AI LLM provider implementation.

Supports:
1. Google GenAI SDK with Vertex AI (vertexai=True) - Enabled by default.
2. Direct asynchronous HTTP for Gemini Developer API when Vertex AI is disabled.
"""
import asyncio
from typing import Any, Dict, List, Optional
import httpx

from backend.agent.providers.base import BaseLLMProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class GeminiLLMProvider(BaseLLMProvider):
    """Asynchronous provider for Google Gemini with Vertex AI support."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        use_vertex_ai: Optional[bool] = None,
        project: Optional[str] = None,
        location: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        model = model_name or (
            settings.LLM_MODEL
            if settings.LLM_PROVIDER in ("gemini", "google") and settings.LLM_MODEL
            else settings.GEMINI_LLM_MODEL
        )
        super().__init__(model_name=model)
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.base_url = (base_url or settings.GEMINI_BASE_URL).rstrip("/")
        self.use_vertex_ai = settings.GEMINI_USE_VERTEX_AI if use_vertex_ai is None else use_vertex_ai
        self.project = project or settings.GOOGLE_CLOUD_PROJECT
        self.location = location or settings.GOOGLE_CLOUD_LOCATION
        self.timeout = timeout
        self._genai_client = None

        if self.use_vertex_ai:
            logger.info(
                "Initializing GeminiLLMProvider in Vertex AI mode (project=%s, location=%s, model=%s)",
                self.project,
                self.location,
                self.model_name,
            )
            try:
                from google import genai
                client_kwargs: Dict[str, Any] = {"vertexai": True}
                if self.project:
                    client_kwargs["project"] = self.project
                if self.location:
                    client_kwargs["location"] = self.location
                if self.api_key:
                    client_kwargs["api_key"] = self.api_key

                self._genai_client = genai.Client(**client_kwargs)
            except Exception as exc:
                logger.warning(
                    "Failed to initialize google.genai.Client for Vertex AI (%s). Will attempt lazy init on generate.",
                    exc,
                )

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Generate response using either Vertex AI SDK or direct HTTP."""
        if self.use_vertex_ai:
            return await self._generate_vertex_ai(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        else:
            return await self._generate_http(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )

    async def _generate_vertex_ai(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Execute call via google-genai SDK in Vertex AI mode."""
        from google import genai
        from google.genai import types

        if self._genai_client is None:
            client_kwargs: Dict[str, Any] = {"vertexai": True}
            if self.project:
                client_kwargs["project"] = self.project
            if self.location:
                client_kwargs["location"] = self.location
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            self._genai_client = genai.Client(**client_kwargs)

        system_instruction = None
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            else:
                gemini_role = "user" if role == "user" else "model"
                contents.append(types.Content(role=gemini_role, parts=[types.Part.from_text(text=content)]))

        if not contents:
            contents = [types.Content(role="user", parts=[types.Part.from_text(text="Please proceed.")])]

        config_kwargs: Dict[str, Any] = {
            "temperature": temperature,
        }
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        config = types.GenerateContentConfig(**config_kwargs)

        # Normalize model identifier (strip 'models/' if provided)
        model_id = self.model_name.replace("models/", "")

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._genai_client.models.generate_content(
                model=model_id,
                contents=contents,
                config=config,
            ),
        )

        return getattr(response, "text", "") or ""

    async def _generate_http(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Execute call via direct asynchronous HTTP against Gemini Developer API."""
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
