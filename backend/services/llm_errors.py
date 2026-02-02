"""
LLM Error Classification.

Classifies raw SDK exceptions from Anthropic and OpenAI (Ollama) into
actionable categories so callers can decide whether to retry, skip,
or abort an entire batch.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"    # Rate limit, timeout, server error — retry later
    PERMANENT = "permanent"    # Credits exhausted, auth failed — stop immediately
    PARTIAL = "partial"        # Bad LLM output (JSON parse) — retry once


@dataclass
class LLMError(Exception):
    """Classified LLM error with retry semantics."""
    category: ErrorCategory
    error_code: str
    message: str
    provider: str
    retryable: bool = True
    status_code: Optional[int] = None
    original: Optional[Exception] = field(default=None, repr=False)

    def __str__(self):
        return f"[{self.provider}:{self.category.value}] {self.error_code}: {self.message}"


def classify_anthropic_error(exc: Exception) -> LLMError:
    """Classify an Anthropic SDK exception into an LLMError."""
    import anthropic

    provider = "anthropic"

    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code="authentication_error",
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=401,
            original=exc,
        )

    if isinstance(exc, anthropic.PermissionDeniedError):
        # Includes credit_balance_too_low (403)
        error_code = _extract_anthropic_error_type(exc) or "permission_denied"
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code=error_code,
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=403,
            original=exc,
        )

    if isinstance(exc, anthropic.BadRequestError):
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code="bad_request",
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=400,
            original=exc,
        )

    if isinstance(exc, anthropic.RateLimitError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="rate_limit",
            message=str(exc),
            provider=provider,
            retryable=True,
            status_code=429,
            original=exc,
        )

    if isinstance(exc, anthropic.InternalServerError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="server_error",
            message=str(exc),
            provider=provider,
            retryable=True,
            status_code=getattr(exc, "status_code", 500),
            original=exc,
        )

    if isinstance(exc, anthropic.APITimeoutError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="timeout",
            message=str(exc),
            provider=provider,
            retryable=True,
            original=exc,
        )

    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="connection_error",
            message=str(exc),
            provider=provider,
            retryable=True,
            original=exc,
        )

    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", None)
        if status and status >= 500:
            return LLMError(
                category=ErrorCategory.TRANSIENT,
                error_code=f"server_error_{status}",
                message=str(exc),
                provider=provider,
                retryable=True,
                status_code=status,
                original=exc,
            )
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code=f"api_error_{status}",
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=status,
            original=exc,
        )

    # Fallback for unknown anthropic errors
    return LLMError(
        category=ErrorCategory.TRANSIENT,
        error_code="unknown",
        message=str(exc),
        provider=provider,
        retryable=True,
        original=exc,
    )


def classify_ollama_error(exc: Exception) -> LLMError:
    """Classify an OpenAI SDK exception (used by Ollama) into an LLMError."""
    import openai

    provider = "ollama"

    if isinstance(exc, openai.AuthenticationError):
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code="authentication_error",
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=401,
            original=exc,
        )

    if isinstance(exc, openai.BadRequestError):
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code="bad_request",
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=400,
            original=exc,
        )

    if isinstance(exc, openai.RateLimitError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="rate_limit",
            message=str(exc),
            provider=provider,
            retryable=True,
            status_code=429,
            original=exc,
        )

    if isinstance(exc, openai.InternalServerError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="server_error",
            message=str(exc),
            provider=provider,
            retryable=True,
            status_code=getattr(exc, "status_code", 500),
            original=exc,
        )

    if isinstance(exc, openai.APITimeoutError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="timeout",
            message=str(exc),
            provider=provider,
            retryable=True,
            original=exc,
        )

    if isinstance(exc, openai.APIConnectionError):
        return LLMError(
            category=ErrorCategory.TRANSIENT,
            error_code="connection_error",
            message=str(exc),
            provider=provider,
            retryable=True,
            original=exc,
        )

    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", None)
        if status and status >= 500:
            return LLMError(
                category=ErrorCategory.TRANSIENT,
                error_code=f"server_error_{status}",
                message=str(exc),
                provider=provider,
                retryable=True,
                status_code=status,
                original=exc,
            )
        return LLMError(
            category=ErrorCategory.PERMANENT,
            error_code=f"api_error_{status}",
            message=str(exc),
            provider=provider,
            retryable=False,
            status_code=status,
            original=exc,
        )

    # Fallback: treat unknown errors as transient
    return LLMError(
        category=ErrorCategory.TRANSIENT,
        error_code="unknown",
        message=str(exc),
        provider=provider,
        retryable=True,
        original=exc,
    )


def _extract_anthropic_error_type(exc) -> Optional[str]:
    """Extract the error type string from an Anthropic API error body."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", {})
        if isinstance(error, dict):
            return error.get("type")
    return None
