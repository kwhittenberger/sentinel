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

# New extensible system services
from .prompt_manager import PromptManager, get_prompt_manager, PromptType, PromptStatus
from .incident_type_service import IncidentTypeService, get_incident_type_service, IncidentCategory, FieldType
from .event_service import EventService, get_event_service
from .actor_service import ActorService, get_actor_service, ActorType, ActorRole
from .pipeline_orchestrator import PipelineOrchestrator, get_pipeline_orchestrator, PipelineStage, PipelineContext

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
    # Prompt Management
    "PromptManager",
    "get_prompt_manager",
    "PromptType",
    "PromptStatus",
    # Incident Types
    "IncidentTypeService",
    "get_incident_type_service",
    "IncidentCategory",
    "FieldType",
    # Events
    "EventService",
    "get_event_service",
    # Actors
    "ActorService",
    "get_actor_service",
    "ActorType",
    "ActorRole",
    # Pipeline Orchestrator
    "PipelineOrchestrator",
    "get_pipeline_orchestrator",
    "PipelineStage",
    "PipelineContext",
]
