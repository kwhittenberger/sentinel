"""
Settings service for managing configuration.

Includes an in-memory cache with configurable TTL to avoid repeated
asdict() serialization on every settings access. The cache is keyed by
settings section name and invalidated on writes.
"""

import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings cache — avoids repeated asdict() serialization per request.
# Thread-safe for basic dict operations under CPython's GIL.
# ---------------------------------------------------------------------------

_settings_cache: Dict[str, Tuple[Any, float]] = {}  # {section_key: (value, timestamp)}
SETTINGS_CACHE_TTL: float = float(os.getenv("SETTINGS_CACHE_TTL", "60"))  # seconds


def _get_cached(key: str) -> Tuple[bool, Any]:
    """Return (hit, value). hit=False means cache miss or expired."""
    entry = _settings_cache.get(key)
    if entry is not None:
        value, ts = entry
        if time.monotonic() - ts < SETTINGS_CACHE_TTL:
            return True, value
    return False, None


def _set_cached(key: str, value: Any) -> None:
    """Store a value in the cache with the current timestamp."""
    _settings_cache[key] = (value, time.monotonic())


def _invalidate_cached(key: str) -> None:
    """Remove a single section from the cache."""
    _settings_cache.pop(key, None)


def clear_settings_cache() -> None:
    """Clear the entire settings cache. Useful for testing and admin resets."""
    _settings_cache.clear()
    logger.debug("Settings cache cleared")


from .thresholds import (
    AUTO_APPROVE_CONFIDENCE,
    ENFORCEMENT_AUTO_APPROVE_CONFIDENCE,
    CRIME_AUTO_APPROVE_CONFIDENCE,
    REVIEW_CONFIDENCE,
    AUTO_REJECT_CONFIDENCE,
    FIELD_CONFIDENCE_THRESHOLD,
    MIN_SEVERITY_AUTO_APPROVE,
    MAX_SEVERITY_AUTO_REJECT,
    DUPLICATE_TITLE_SIMILARITY,
    DUPLICATE_CONTENT_SIMILARITY,
    DUPLICATE_ENTITY_DATE_WINDOW,
)


@dataclass
class AutoApprovalSettings:
    """Auto-approval configuration settings."""
    min_confidence_auto_approve: float = AUTO_APPROVE_CONFIDENCE
    min_confidence_review: float = REVIEW_CONFIDENCE
    auto_reject_below: float = AUTO_REJECT_CONFIDENCE
    required_fields: List[str] = field(default_factory=lambda: ['date', 'state', 'incident_type'])
    field_confidence_threshold: float = FIELD_CONFIDENCE_THRESHOLD
    min_severity_auto_approve: int = MIN_SEVERITY_AUTO_APPROVE
    max_severity_auto_reject: int = MAX_SEVERITY_AUTO_REJECT
    enable_auto_approve: bool = True
    enable_auto_reject: bool = True
    # Category-specific thresholds
    enforcement_confidence_threshold: float = ENFORCEMENT_AUTO_APPROVE_CONFIDENCE
    crime_confidence_threshold: float = CRIME_AUTO_APPROVE_CONFIDENCE


@dataclass
class DuplicateDetectionSettings:
    """Duplicate detection configuration settings."""
    title_similarity_threshold: float = DUPLICATE_TITLE_SIMILARITY
    content_similarity_threshold: float = DUPLICATE_CONTENT_SIMILARITY
    entity_match_date_window: int = DUPLICATE_ENTITY_DATE_WINDOW  # days
    shingle_size: int = 3
    enable_url_match: bool = True
    enable_title_match: bool = True
    enable_content_match: bool = True
    enable_entity_match: bool = True


@dataclass
class PipelineSettings:
    """Pipeline behavior configuration settings."""
    enable_llm_extraction: bool = True
    enable_duplicate_detection: bool = True
    enable_auto_approval: bool = True
    batch_size: int = 50
    delay_between_articles_ms: int = 500
    max_article_length: int = 15000
    default_source_tier: int = 3


@dataclass
class EventClusteringSettings:
    """Event clustering configuration settings."""
    # Geographic settings
    max_distance_km: float = 50.0  # Max km between incidents to cluster
    require_coordinates: bool = False  # If false, falls back to city/state matching

    # Temporal settings
    max_time_window_days: int = 7  # Max days apart for incidents

    # Matching criteria
    require_same_incident_type: bool = True  # Must be same type (shooting, protest, etc.)
    require_same_category: bool = True  # Must be same category (enforcement/crime)

    # Cluster settings
    min_cluster_size: int = 2  # Minimum incidents to form an event
    min_confidence_threshold: float = 0.6  # Minimum confidence to suggest

    # AI-assisted settings (for future)
    enable_ai_similarity: bool = False  # Use LLM to compare descriptions
    ai_similarity_threshold: float = 0.7  # Min similarity score from AI
    enable_actor_matching: bool = True  # Consider shared actors


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM call site (stage)."""
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 2000
    enabled: bool = True


@dataclass
class LLMSettings:
    """LLM provider routing settings."""
    # Global defaults
    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-20250514"
    fallback_provider: str = "anthropic"
    fallback_model: str = "claude-sonnet-4-20250514"
    ollama_base_url: str = "http://localhost:11434/v1"

    # Per-stage overrides (None means use global defaults)
    triage: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=500))
    extraction_universal: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=4000))
    extraction_async: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=2000))
    extraction: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=2000))
    pipeline_extraction: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=2000))
    relevance_ai: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=500))
    enrichment_reextract: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(max_tokens=1000))

    def get_stage_config(self, stage_key: str) -> LLMProviderConfig:
        """Get effective config for a stage, falling back to global defaults."""
        stage_cfg = getattr(self, stage_key, None)
        if stage_cfg is None:
            return LLMProviderConfig(
                provider=self.default_provider,
                model=self.default_model,
            )
        # Fill in global defaults for any stage fields still at class defaults
        return LLMProviderConfig(
            provider=stage_cfg.provider if stage_cfg.provider != "anthropic" or self.default_provider == "anthropic" else self.default_provider,
            model=stage_cfg.model if stage_cfg.model != "claude-sonnet-4-20250514" or self.default_model == "claude-sonnet-4-20250514" else self.default_model,
            max_tokens=stage_cfg.max_tokens,
            enabled=stage_cfg.enabled,
        )


# Stage keys for iteration
LLM_STAGE_KEYS = [
    "triage",
    "extraction_universal",
    "extraction_async",
    "extraction",
    "pipeline_extraction",
    "relevance_ai",
    "enrichment_reextract",
]


@dataclass
class AllSettings:
    """All application settings combined."""
    auto_approval: AutoApprovalSettings = field(default_factory=AutoApprovalSettings)
    duplicate_detection: DuplicateDetectionSettings = field(default_factory=DuplicateDetectionSettings)
    pipeline: PipelineSettings = field(default_factory=PipelineSettings)
    event_clustering: EventClusteringSettings = field(default_factory=EventClusteringSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)


class SettingsService:
    """Service for managing application settings."""

    def __init__(self):
        self._settings = AllSettings()

    def get_all(self) -> dict:
        """Get all settings as a dict."""
        hit, cached = _get_cached("all")
        if hit:
            return cached
        result = {
            'auto_approval': self.get_auto_approval(),
            'duplicate_detection': self.get_duplicate_detection(),
            'pipeline': self.get_pipeline(),
            'event_clustering': self.get_event_clustering(),
            'llm': self.get_llm(),
        }
        _set_cached("all", result)
        return result

    def get_auto_approval(self) -> dict:
        """Get auto-approval settings."""
        hit, cached = _get_cached("auto_approval")
        if hit:
            return cached
        result = asdict(self._settings.auto_approval)
        _set_cached("auto_approval", result)
        return result

    def update_auto_approval(self, config: dict) -> dict:
        """Update auto-approval settings."""
        for key, value in config.items():
            if hasattr(self._settings.auto_approval, key):
                setattr(self._settings.auto_approval, key, value)
                logger.info(f"Updated auto_approval.{key} = {value}")

        # Also update the singleton auto-approval service config
        from .auto_approval import get_auto_approval_service
        service = get_auto_approval_service()
        service.update_config(config)

        _invalidate_cached("auto_approval")
        _invalidate_cached("all")
        return self.get_auto_approval()

    def get_duplicate_detection(self) -> dict:
        """Get duplicate detection settings."""
        hit, cached = _get_cached("duplicate_detection")
        if hit:
            return cached
        result = asdict(self._settings.duplicate_detection)
        _set_cached("duplicate_detection", result)
        return result

    def update_duplicate_detection(self, config: dict) -> dict:
        """Update duplicate detection settings."""
        for key, value in config.items():
            if hasattr(self._settings.duplicate_detection, key):
                setattr(self._settings.duplicate_detection, key, value)
                logger.info(f"Updated duplicate_detection.{key} = {value}")

        # Also update the singleton detector config
        from .duplicate_detection import get_detector
        detector = get_detector()
        for key, value in config.items():
            if hasattr(detector.config, key):
                setattr(detector.config, key, value)

        _invalidate_cached("duplicate_detection")
        _invalidate_cached("all")
        return self.get_duplicate_detection()

    def get_pipeline(self) -> dict:
        """Get pipeline settings."""
        hit, cached = _get_cached("pipeline")
        if hit:
            return cached
        result = asdict(self._settings.pipeline)
        _set_cached("pipeline", result)
        return result

    def update_pipeline(self, config: dict) -> dict:
        """Update pipeline settings."""
        for key, value in config.items():
            if hasattr(self._settings.pipeline, key):
                setattr(self._settings.pipeline, key, value)
                logger.info(f"Updated pipeline.{key} = {value}")

        _invalidate_cached("pipeline")
        _invalidate_cached("all")
        return self.get_pipeline()

    def get_event_clustering(self) -> dict:
        """Get event clustering settings."""
        hit, cached = _get_cached("event_clustering")
        if hit:
            return cached
        result = asdict(self._settings.event_clustering)
        _set_cached("event_clustering", result)
        return result

    def update_event_clustering(self, config: dict) -> dict:
        """Update event clustering settings."""
        for key, value in config.items():
            if hasattr(self._settings.event_clustering, key):
                setattr(self._settings.event_clustering, key, value)
                logger.info(f"Updated event_clustering.{key} = {value}")

        _invalidate_cached("event_clustering")
        _invalidate_cached("all")
        return self.get_event_clustering()

    def get_llm(self) -> dict:
        """Get LLM provider settings."""
        hit, cached = _get_cached("llm")
        if hit:
            return cached
        result = asdict(self._settings.llm)
        _set_cached("llm", result)
        return result

    def update_llm(self, config: dict) -> dict:
        """Update LLM provider settings."""
        llm = self._settings.llm

        # Update top-level fields
        for key in ("default_provider", "default_model", "fallback_provider",
                     "fallback_model", "ollama_base_url"):
            if key in config:
                setattr(llm, key, config[key])
                logger.info(f"Updated llm.{key} = {config[key]}")

        # Update per-stage configs
        for stage_key in LLM_STAGE_KEYS:
            if stage_key in config and isinstance(config[stage_key], dict):
                stage_cfg = getattr(llm, stage_key)
                for field_name, value in config[stage_key].items():
                    if hasattr(stage_cfg, field_name):
                        setattr(stage_cfg, field_name, value)
                        logger.info(f"Updated llm.{stage_key}.{field_name} = {value}")

        # Propagate Ollama URL change to the router if it's already initialized
        try:
            from .llm_provider import get_llm_router
            router = get_llm_router()
            if llm.ollama_base_url != router.ollama._base_url:
                router.ollama._base_url = llm.ollama_base_url
                router.ollama._client = None  # Force re-create on next call
                logger.info(f"Updated Ollama base URL to {llm.ollama_base_url}")
        except (ImportError, AttributeError):
            # ImportError: llm_provider not available yet
            # AttributeError: router or ollama provider not initialized
            pass

        _invalidate_cached("llm")
        _invalidate_cached("all")
        return self.get_llm()


# Singleton instance
_settings_service: Optional[SettingsService] = None


def get_settings_service() -> SettingsService:
    """Get the singleton settings service instance."""
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service
