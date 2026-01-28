"""
Backend services.
"""

from .llm_extraction import LLMExtractor, extract_incident_from_article, get_extractor
from .extraction_prompts import (
    EXTRACTION_PROMPTS,
    get_extraction_prompt,
    get_system_prompt,
    get_required_fields,
    ENFORCEMENT_REQUIRED_FIELDS,
    CRIME_REQUIRED_FIELDS,
)
from .duplicate_detection import DuplicateDetector, get_detector
from .auto_approval import AutoApprovalService, get_auto_approval_service
from .unified_pipeline import UnifiedPipeline, get_pipeline
from .settings import SettingsService, get_settings_service

__all__ = [
    # LLM Extraction
    "LLMExtractor",
    "extract_incident_from_article",
    "get_extractor",
    "EXTRACTION_PROMPTS",
    "get_extraction_prompt",
    "get_system_prompt",
    "get_required_fields",
    "ENFORCEMENT_REQUIRED_FIELDS",
    "CRIME_REQUIRED_FIELDS",
    # Duplicate Detection
    "DuplicateDetector",
    "get_detector",
    # Auto Approval
    "AutoApprovalService",
    "get_auto_approval_service",
    # Pipeline
    "UnifiedPipeline",
    "get_pipeline",
    # Settings
    "SettingsService",
    "get_settings_service",
]
