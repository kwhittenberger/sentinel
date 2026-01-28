"""
Pipeline stages for article processing.
"""

from backend.pipeline.stages.url_dedupe import URLDedupeStage
from backend.pipeline.stages.content_dedupe import ContentDedupeStage
from backend.pipeline.stages.relevance import RelevanceStage
from backend.pipeline.stages.classification import ClassificationStage
from backend.pipeline.stages.extraction import ExtractionStage
from backend.pipeline.stages.entity_resolution import EntityResolutionStage
from backend.pipeline.stages.validation import ValidationStage
from backend.pipeline.stages.auto_approval import AutoApprovalStage
from backend.pipeline.stages.pattern_detection import PatternDetectionStage
from backend.pipeline.stages.cross_reference import CrossReferenceStage

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
