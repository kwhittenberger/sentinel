"""
Per-batch Circuit Breaker.

Monitors errors during a batch extraction run and trips when it detects
a systemic failure (permanent error or repeated identical transient errors),
preventing wasted API calls.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .llm_errors import LLMError, ErrorCategory

logger = logging.getLogger(__name__)

# Number of consecutive identical transient errors before tripping
TRANSIENT_TRIP_THRESHOLD = 3


@dataclass
class FailureRecord:
    error_code: str
    category: str
    message: str
    article_id: str
    timestamp: str


@dataclass
class BatchCircuitBreaker:
    """Circuit breaker scoped to a single batch extraction run."""

    tripped: bool = False
    trip_reason: Optional[str] = None
    trip_error_code: Optional[str] = None
    failure_log: list[FailureRecord] = field(default_factory=list)
    _consecutive_code: Optional[str] = field(default=None, repr=False)
    _consecutive_count: int = field(default=0, repr=False)

    def record_error(self, error: LLMError, article_id: str) -> bool:
        """
        Record an error and check if the breaker should trip.

        Returns True if the breaker just tripped (caller should stop).
        """
        self.failure_log.append(FailureRecord(
            error_code=error.error_code,
            category=error.category.value,
            message=str(error.message)[:200],
            article_id=article_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

        # Permanent errors trip immediately
        if error.category == ErrorCategory.PERMANENT:
            self.tripped = True
            self.trip_reason = f"Permanent error: {error.error_code}"
            self.trip_error_code = error.error_code
            logger.warning(
                "Circuit breaker tripped (permanent): %s — %s",
                error.error_code, str(error.message)[:100],
            )
            return True

        # Track consecutive identical transient errors
        if error.error_code == self._consecutive_code:
            self._consecutive_count += 1
        else:
            self._consecutive_code = error.error_code
            self._consecutive_count = 1

        if self._consecutive_count >= TRANSIENT_TRIP_THRESHOLD:
            self.tripped = True
            self.trip_reason = (
                f"{self._consecutive_count} consecutive '{error.error_code}' errors"
            )
            self.trip_error_code = error.error_code
            logger.warning(
                "Circuit breaker tripped (transient): %d consecutive %s errors",
                self._consecutive_count, error.error_code,
            )
            return True

        return False

    def record_success(self):
        """Reset consecutive error counter on success."""
        self._consecutive_code = None
        self._consecutive_count = 0

    def summary(self) -> dict:
        """Return a JSON-serializable summary for API responses."""
        return {
            "tripped": self.tripped,
            "trip_reason": self.trip_reason,
            "trip_error_code": self.trip_error_code,
            "total_failures": len(self.failure_log),
            "failure_log": [
                {
                    "error_code": f.error_code,
                    "category": f.category,
                    "message": f.message,
                    "article_id": f.article_id,
                    "timestamp": f.timestamp,
                }
                for f in self.failure_log
            ],
        }
