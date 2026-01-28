"""
Configurable pipeline orchestrator for processing articles through multiple stages.
Supports type-aware processing with configurable stages per incident type.
"""

import logging
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List, Type
from uuid import UUID
from enum import Enum

logger = logging.getLogger(__name__)


class StageResult(str, Enum):
    """Possible results from a pipeline stage."""
    CONTINUE = "continue"  # Continue to next stage
    SKIP = "skip"  # Skip remaining stages (e.g., duplicate found)
    REJECT = "reject"  # Reject the article
    ERROR = "error"  # Stage encountered an error


@dataclass
class PipelineContext:
    """Context passed through pipeline stages."""
    article_id: Optional[UUID] = None
    article: Dict = field(default_factory=dict)
    incident_type_id: Optional[UUID] = None
    detected_category: Optional[str] = None

    # Extraction results
    extraction_result: Optional[Dict] = None
    extracted_data: Optional[Dict] = None

    # Entity resolution
    detected_actors: List[Dict] = field(default_factory=list)
    detected_relations: List[Dict] = field(default_factory=list)

    # Validation
    validation_errors: List[str] = field(default_factory=list)

    # Stage results
    stage_results: Dict[str, "StageExecutionResult"] = field(default_factory=dict)

    # Final decision
    final_decision: Optional[str] = None
    decision_reason: Optional[str] = None


@dataclass
class StageExecutionResult:
    """Result of executing a single stage."""
    stage_slug: str
    result: StageResult
    data: Dict = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class PipelineResult:
    """Final result of pipeline execution."""
    success: bool
    article_id: Optional[str] = None
    stages_completed: List[str] = field(default_factory=list)
    final_decision: Optional[str] = None
    decision_reason: Optional[str] = None
    context: Optional[PipelineContext] = None
    error: Optional[str] = None
    total_duration_ms: int = 0


class PipelineStage(ABC):
    """
    Abstract base class for pipeline stages.

    Each stage must implement:
    - slug: Unique identifier for the stage
    - execute: Process the context and return a result
    """

    slug: str = ""

    @abstractmethod
    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Execute this pipeline stage.

        Args:
            context: Pipeline context with article and accumulated data
            config: Stage-specific configuration

        Returns:
            StageExecutionResult indicating whether to continue, skip, or reject
        """
        pass


class PipelineOrchestrator:
    """
    Configurable, type-aware pipeline execution.

    Features:
    - Dynamic stage loading
    - Per-type pipeline configuration
    - Stage execution tracking
    - Error handling and recovery
    """

    def __init__(self):
        self._stage_registry: Dict[str, Type[PipelineStage]] = {}
        self._register_default_stages()

    def _register_default_stages(self):
        """Register built-in pipeline stages."""
        # Import stages from the pipeline module
        try:
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

            self.register_stage(URLDedupeStage)
            self.register_stage(ContentDedupeStage)
            self.register_stage(RelevanceStage)
            self.register_stage(ClassificationStage)
            self.register_stage(ExtractionStage)
            self.register_stage(EntityResolutionStage)
            self.register_stage(ValidationStage)
            self.register_stage(AutoApprovalStage)
            self.register_stage(PatternDetectionStage)
            self.register_stage(CrossReferenceStage)

        except ImportError as e:
            logger.warning(f"Could not load pipeline stages: {e}")
            # Register placeholder stages that just continue
            pass

    def register_stage(self, stage_class: Type[PipelineStage]):
        """Register a pipeline stage class."""
        if not hasattr(stage_class, 'slug') or not stage_class.slug:
            raise ValueError(f"Stage {stage_class.__name__} must have a slug")

        self._stage_registry[stage_class.slug] = stage_class
        logger.debug(f"Registered pipeline stage: {stage_class.slug}")

    def get_stage(self, slug: str) -> Optional[PipelineStage]:
        """Get an instance of a registered stage."""
        stage_class = self._stage_registry.get(slug)
        if stage_class:
            return stage_class()
        return None

    async def execute(
        self,
        article: Dict,
        incident_type_id: Optional[UUID] = None,
        skip_stages: Optional[List[str]] = None
    ) -> PipelineResult:
        """
        Execute the pipeline for an article.

        Args:
            article: Article data to process
            incident_type_id: Optional type ID for type-specific pipeline config
            skip_stages: Optional list of stage slugs to skip

        Returns:
            PipelineResult with execution details
        """
        from backend.services.incident_type_service import get_incident_type_service
        import time

        start_time = time.time()
        skip_stages = skip_stages or []

        # Initialize context
        context = PipelineContext(
            article_id=article.get("id"),
            article=article,
            incident_type_id=incident_type_id
        )

        result = PipelineResult(
            success=True,
            article_id=str(article.get("id")) if article.get("id") else None,
            context=context
        )

        try:
            # Get pipeline configuration
            pipeline_config = await self._get_pipeline_config(incident_type_id)

            # Execute stages in order
            for stage_config in pipeline_config:
                stage_slug = stage_config["slug"]

                # Skip if disabled or in skip list
                if not stage_config.get("enabled", True):
                    continue
                if stage_slug in skip_stages:
                    continue

                # Get stage instance
                stage = self.get_stage(stage_slug)
                if not stage:
                    logger.warning(f"Stage not found: {stage_slug}")
                    continue

                # Execute stage
                stage_start = time.time()
                try:
                    stage_result = await stage.execute(
                        context,
                        stage_config.get("config", {})
                    )

                    stage_result.duration_ms = int((time.time() - stage_start) * 1000)
                    context.stage_results[stage_slug] = stage_result
                    result.stages_completed.append(stage_slug)

                    # Handle stage result
                    if stage_result.result == StageResult.SKIP:
                        logger.debug(f"Stage {stage_slug} returned SKIP")
                        break
                    elif stage_result.result == StageResult.REJECT:
                        context.final_decision = "rejected"
                        context.decision_reason = stage_result.data.get("reason", f"Rejected by {stage_slug}")
                        break
                    elif stage_result.result == StageResult.ERROR:
                        logger.error(f"Stage {stage_slug} error: {stage_result.error}")
                        # Continue to next stage on error by default
                        continue

                except Exception as e:
                    logger.exception(f"Error in stage {stage_slug}: {e}")
                    context.stage_results[stage_slug] = StageExecutionResult(
                        stage_slug=stage_slug,
                        result=StageResult.ERROR,
                        error=str(e)
                    )
                    # Continue to next stage

            # Set final result
            result.final_decision = context.final_decision
            result.decision_reason = context.decision_reason
            result.total_duration_ms = int((time.time() - start_time) * 1000)

        except Exception as e:
            logger.exception(f"Pipeline execution error: {e}")
            result.success = False
            result.error = str(e)

        return result

    async def _get_pipeline_config(
        self,
        incident_type_id: Optional[UUID]
    ) -> List[Dict]:
        """
        Get pipeline configuration for an incident type.

        Returns stages in execution order with their configs.
        """
        from backend.database import fetch

        if incident_type_id:
            # Get type-specific config
            query = """
                SELECT ps.slug, ps.handler_class, itpc.enabled,
                       COALESCE(itpc.execution_order, ps.default_order) as execution_order,
                       itpc.stage_config as config, itpc.prompt_id
                FROM pipeline_stages ps
                LEFT JOIN incident_type_pipeline_config itpc
                    ON ps.id = itpc.pipeline_stage_id
                    AND itpc.incident_type_id = $1
                WHERE ps.is_active = TRUE
                ORDER BY execution_order
            """
            rows = await fetch(query, incident_type_id)
        else:
            # Get default config
            query = """
                SELECT slug, handler_class, TRUE as enabled,
                       default_order as execution_order, '{}' as config, NULL as prompt_id
                FROM pipeline_stages
                WHERE is_active = TRUE
                ORDER BY default_order
            """
            rows = await fetch(query)

        return [
            {
                "slug": row["slug"],
                "handler_class": row["handler_class"],
                "enabled": row.get("enabled", True),
                "execution_order": row["execution_order"],
                "config": row.get("config") or {},
                "prompt_id": row.get("prompt_id")
            }
            for row in rows
        ]

    async def process_batch(
        self,
        articles: List[Dict],
        incident_type_id: Optional[UUID] = None,
        delay_ms: int = 500,
        max_concurrent: int = 1
    ) -> Dict:
        """
        Process multiple articles through the pipeline.

        Args:
            articles: List of articles to process
            incident_type_id: Optional type ID for all articles
            delay_ms: Delay between articles
            max_concurrent: Max concurrent processing (1 = sequential)

        Returns:
            Batch processing statistics
        """
        stats = {
            "processed": 0,
            "approved": 0,
            "rejected": 0,
            "skipped": 0,
            "errors": 0,
            "results": []
        }

        if max_concurrent == 1:
            # Sequential processing
            for article in articles:
                result = await self.execute(article, incident_type_id)
                stats["results"].append(result)
                stats["processed"] += 1

                if result.error:
                    stats["errors"] += 1
                elif result.final_decision == "approved" or result.final_decision == "auto_approve":
                    stats["approved"] += 1
                elif result.final_decision == "rejected" or result.final_decision == "auto_reject":
                    stats["rejected"] += 1
                elif result.final_decision == "duplicate":
                    stats["skipped"] += 1

                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000)
        else:
            # Concurrent processing with semaphore
            semaphore = asyncio.Semaphore(max_concurrent)

            async def process_with_semaphore(article):
                async with semaphore:
                    return await self.execute(article, incident_type_id)

            tasks = [process_with_semaphore(article) for article in articles]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    stats["errors"] += 1
                    stats["processed"] += 1
                else:
                    stats["results"].append(result)
                    stats["processed"] += 1

                    if result.error:
                        stats["errors"] += 1
                    elif result.final_decision in ("approved", "auto_approve"):
                        stats["approved"] += 1
                    elif result.final_decision in ("rejected", "auto_reject"):
                        stats["rejected"] += 1
                    elif result.final_decision == "duplicate":
                        stats["skipped"] += 1

        return stats


# Singleton instance
_orchestrator: Optional[PipelineOrchestrator] = None


def get_pipeline_orchestrator() -> PipelineOrchestrator:
    """Get the singleton PipelineOrchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
    return _orchestrator
