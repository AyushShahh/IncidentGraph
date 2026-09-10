"""Base abstract interface for pluggable LLM providers."""
from abc import ABC, abstractmethod
import json
import re
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

from backend.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Abstract interface defining uniform LLM generation operations across all providers."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Generate a completion given a list of messages.

        Args:
            messages: List of dicts with 'role' ('system', 'user', 'assistant') and 'content'.
            temperature: Sampling temperature (0.0 - 1.0).
            max_tokens: Optional maximum tokens to generate.
            json_mode: Hint to provider to enforce valid JSON output where supported.

        Returns:
            String response content.
        """
        pass

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> T:
        """Generate and parse structured JSON into a Pydantic model.

        Strips markdown code fences (e.g. ```json ... ```) and handles common LLM formatting artifacts.
        """
        raw_text = await self.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )

        cleaned = raw_text.strip()
        # Strip markdown code blocks if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
            return response_model.model_validate(data)
        except Exception as exc:
            logger.error("Failed parsing structured LLM response into %s: %s\nRaw output: %s", response_model.__name__, exc, raw_text)
            raise ValueError(f"Could not parse LLM response into {response_model.__name__}: {exc}") from exc
