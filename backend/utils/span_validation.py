"""
Validate LLM-reported source spans against actual article text.

Each span claims that article_text[start:end] == text.  We verify this
with whitespace-normalized, case-insensitive comparison and silently
drop any span that doesn't match.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Collapse whitespace and lowercase for fuzzy comparison."""
    return _WS_RE.sub(" ", s).strip().lower()


def validate_spans(
    source_spans: dict[str, Any] | None,
    article_text: str,
) -> dict[str, Any]:
    """Return only those spans whose text matches article_text[start:end].

    Args:
        source_spans: Dict mapping field names to {start, end, text} dicts.
        article_text: The original article content.

    Returns:
        A new dict containing only validated spans.
    """
    if not source_spans or not article_text:
        return {}

    validated: dict[str, Any] = {}
    for key, span in source_spans.items():
        if not isinstance(span, dict):
            continue
        start = span.get("start")
        end = span.get("end")
        claimed = span.get("text")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(claimed, str):
            continue
        if start < 0 or end > len(article_text) or start >= end:
            continue

        actual = article_text[start:end]
        if _normalize(actual) == _normalize(claimed):
            validated[key] = span
        else:
            logger.debug(
                "Dropping invalid span for %s: expected %r, got %r",
                key, claimed, actual,
            )

    if source_spans and validated:
        logger.info(
            "Source span validation: %d/%d spans validated",
            len(validated), len(source_spans),
        )
    return validated
