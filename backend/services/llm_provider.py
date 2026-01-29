"""
Multi-LLM provider abstraction.

Routes LLM calls to Anthropic Claude or local Ollama (via OpenAI-compatible API),
with per-stage configuration and automatic fallback.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: str
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


class AnthropicProvider:
    """Wraps the Anthropic SDK for Claude calls."""

    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or ANTHROPIC_API_KEY
        self._client = None

    @property
    def client(self):
        if self._client is None and self._api_key:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key)

    def call(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2000,
    ) -> LLMResponse:
        if not self.client:
            raise RuntimeError("Anthropic API key not configured")

        start = time.time()
        message = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        latency_ms = int((time.time() - start) * 1000)

        return LLMResponse(
            text=message.content[0].text,
            provider="anthropic",
            model=model,
            input_tokens=getattr(message.usage, "input_tokens", None),
            output_tokens=getattr(message.usage, "output_tokens", None),
            latency_ms=latency_ms,
        )


class OllamaProvider:
    """Wraps Ollama via its OpenAI-compatible API."""

    name = "ollama"

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url or OLLAMA_BASE_URL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self._base_url,
                api_key="ollama",  # Ollama doesn't need a real key
            )
        return self._client

    def is_available(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return model IDs available on the Ollama server."""
        try:
            response = self.client.models.list()
            return [m.id for m in response.data]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []

    def call(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "llama3.1",
        max_tokens: int = 2000,
    ) -> LLMResponse:
        start = time.time()
        response = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        latency_ms = int((time.time() - start) * 1000)

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            text=choice.message.content,
            provider="ollama",
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            latency_ms=latency_ms,
        )


class LLMRouter:
    """Routes LLM calls to providers with automatic fallback."""

    def __init__(self):
        self._anthropic = AnthropicProvider()
        self._ollama = OllamaProvider()
        self._providers = {
            "anthropic": self._anthropic,
            "ollama": self._ollama,
        }

    @property
    def anthropic(self) -> AnthropicProvider:
        return self._anthropic

    @property
    def ollama(self) -> OllamaProvider:
        return self._ollama

    def get_provider(self, name: str):
        return self._providers.get(name)

    def has_available_provider(self) -> bool:
        return any(p.is_available() for p in self._providers.values())

    def provider_status(self) -> dict:
        """Return availability status for each provider."""
        return {
            name: provider.is_available()
            for name, provider in self._providers.items()
        }

    def call(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2000,
        provider_name: str = "anthropic",
        fallback_provider: Optional[str] = "anthropic",
        fallback_model: Optional[str] = None,
    ) -> LLMResponse:
        """
        Route an LLM call to the specified provider with optional fallback.

        Args:
            system_prompt: System prompt text
            user_message: User message text
            model: Model name for the primary provider
            max_tokens: Max tokens for the response
            provider_name: Primary provider to use
            fallback_provider: Provider to fall back to on failure (None to disable)
            fallback_model: Model to use with fallback provider (defaults to Claude Sonnet)
        """
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_name}")

        # Try primary provider
        try:
            return provider.call(system_prompt, user_message, model, max_tokens)
        except Exception as e:
            logger.warning(
                f"Provider '{provider_name}' failed (model={model}): {e}"
            )

            # Try fallback if configured and different from primary
            if (
                fallback_provider
                and fallback_provider != provider_name
                and fallback_provider in self._providers
            ):
                fb = self._providers[fallback_provider]
                fb_model = fallback_model or "claude-sonnet-4-20250514"
                logger.info(
                    f"Falling back to '{fallback_provider}' (model={fb_model})"
                )
                try:
                    return fb.call(system_prompt, user_message, fb_model, max_tokens)
                except Exception as fb_err:
                    logger.error(f"Fallback provider '{fallback_provider}' also failed: {fb_err}")
                    raise fb_err from e

            # No fallback available — re-raise original
            raise


# Singleton
_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get the singleton LLM router instance."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
