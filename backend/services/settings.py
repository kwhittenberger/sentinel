"""
Settings service for managing configuration.
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


@dataclass
class AutoApprovalSettings:
    """Auto-approval configuration settings."""
    min_confidence_auto_approve: float = 0.85
    min_confidence_review: float = 0.5
    auto_reject_below: float = 0.3
    required_fields: List[str] = field(default_factory=lambda: ['date', 'state', 'incident_type'])
    field_confidence_threshold: float = 0.7
    min_severity_auto_approve: int = 5
    max_severity_auto_reject: int = 2
    enable_auto_approve: bool = True
    enable_auto_reject: bool = True
    # Category-specific thresholds
    enforcement_confidence_threshold: float = 0.90  # Higher scrutiny for enforcement
    crime_confidence_threshold: float = 0.85


@dataclass
class DuplicateDetectionSettings:
    """Duplicate detection configuration settings."""
    title_similarity_threshold: float = 0.75
    content_similarity_threshold: float = 0.85
    entity_match_date_window: int = 30  # days
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
class AllSettings:
    """All application settings combined."""
    auto_approval: AutoApprovalSettings = field(default_factory=AutoApprovalSettings)
    duplicate_detection: DuplicateDetectionSettings = field(default_factory=DuplicateDetectionSettings)
    pipeline: PipelineSettings = field(default_factory=PipelineSettings)


class SettingsService:
    """Service for managing application settings."""

    def __init__(self):
        self._settings = AllSettings()

    def get_all(self) -> dict:
        """Get all settings as a dict."""
        return {
            'auto_approval': asdict(self._settings.auto_approval),
            'duplicate_detection': asdict(self._settings.duplicate_detection),
            'pipeline': asdict(self._settings.pipeline),
        }

    def get_auto_approval(self) -> dict:
        """Get auto-approval settings."""
        return asdict(self._settings.auto_approval)

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

        return self.get_auto_approval()

    def get_duplicate_detection(self) -> dict:
        """Get duplicate detection settings."""
        return asdict(self._settings.duplicate_detection)

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

        return self.get_duplicate_detection()

    def get_pipeline(self) -> dict:
        """Get pipeline settings."""
        return asdict(self._settings.pipeline)

    def update_pipeline(self, config: dict) -> dict:
        """Update pipeline settings."""
        for key, value in config.items():
            if hasattr(self._settings.pipeline, key):
                setattr(self._settings.pipeline, key, value)
                logger.info(f"Updated pipeline.{key} = {value}")

        return self.get_pipeline()


# Singleton instance
_settings_service: Optional[SettingsService] = None


def get_settings_service() -> SettingsService:
    """Get the singleton settings service instance."""
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service
