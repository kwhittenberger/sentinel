"""
Pipeline module for article processing stages.
"""

from backend.pipeline.stages import (
    URLDedupeStage,
    ContentDedupeStage,
    RelevanceStage,
    ClassificationStage,
    ExtractionStage,
    EntityResolutionStage,
    ValidationStage,
    AutoApprovalStage,
    PatternDetectionStage,
    CrossReferenceStage,
)

__all__ = [
    "URLDedupeStage",
    "ContentDedupeStage",
    "RelevanceStage",
    "ClassificationStage",
    "ExtractionStage",
    "EntityResolutionStage",
    "ValidationStage",
    "AutoApprovalStage",
    "PatternDetectionStage",
    "CrossReferenceStage",
]
