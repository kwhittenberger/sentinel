"""
Unified pipeline service for processing articles.
Orchestrates: duplicate detection -> LLM extraction -> auto-approval.
Ported from crime-tracker project.

Now supports optional integration with PipelineOrchestrator for
configurable, database-backed pipeline stages.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from uuid import UUID

from .duplicate_detection import get_detector, DuplicateDetector
from .auto_approval import get_auto_approval_service, AutoApprovalService, ApprovalDecision
from .llm_extraction import get_extractor, LLMExtractor
from ..utils.state_normalizer import normalize_state

logger = logging.getLogger(__name__)

# Optional import of PipelineOrchestrator
try:
    from .pipeline_orchestrator import get_pipeline_orchestrator, PipelineOrchestrator
    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    ORCHESTRATOR_AVAILABLE = False
    PipelineOrchestrator = None


@dataclass
class PipelineResult:
    """Result of pipeline processing."""
    success: bool
    article_id: str
    steps_completed: List[str] = field(default_factory=list)
    duplicate_result: Optional[Dict[str, Any]] = None
    extraction_result: Optional[Dict[str, Any]] = None
    approval_result: Optional[Dict[str, Any]] = None
    final_decision: Optional[str] = None
    error: Optional[str] = None


@dataclass
class BatchResult:
    """Result of batch pipeline processing."""
    processed: int = 0
    auto_approved: int = 0
    auto_rejected: int = 0
    needs_review: int = 0
    duplicates: int = 0
    errors: int = 0
    results: List[PipelineResult] = field(default_factory=list)


class UnifiedPipeline:
    """Orchestrates the full article processing pipeline."""

    def __init__(
        self,
        detector: DuplicateDetector = None,
        extractor: LLMExtractor = None,
        approver: AutoApprovalService = None,
        use_orchestrator: bool = False
    ):
        self.detector = detector or get_detector()
        self.extractor = extractor or get_extractor()
        self.approver = approver or get_auto_approval_service()
        self.use_orchestrator = use_orchestrator and ORCHESTRATOR_AVAILABLE
        self._db_pool = None
        self._orchestrator: Optional[PipelineOrchestrator] = None

    def set_db_pool(self, pool):
        """Set database pool for orchestrator and services."""
        self._db_pool = pool
        if self.use_orchestrator and ORCHESTRATOR_AVAILABLE:
            self._orchestrator = get_pipeline_orchestrator(pool)
        # Pass pool to services for database integration
        if hasattr(self.extractor, 'set_db_pool'):
            self.extractor.set_db_pool(pool)
        if hasattr(self.approver, 'set_db_pool'):
            self.approver.set_db_pool(pool)

    async def process_with_orchestrator(
        self,
        article: dict,
        incident_type_id: Optional[UUID] = None,
    ) -> PipelineResult:
        """
        Process article using the configurable PipelineOrchestrator.

        This uses the database-backed stage configuration for the incident type.
        """
        if not self._orchestrator:
            return PipelineResult(
                success=False,
                article_id=str(article.get('id', 'unknown')),
                error="Pipeline orchestrator not available"
            )

        try:
            orch_result = await self._orchestrator.execute(article, incident_type_id)

            return PipelineResult(
                success=orch_result.success,
                article_id=str(article.get('id', 'unknown')),
                steps_completed=orch_result.stages_completed,
                final_decision=orch_result.final_decision,
                error=orch_result.error,
                extraction_result=orch_result.context.get('extraction_result') if orch_result.context else None,
                approval_result={
                    'decision': orch_result.final_decision,
                    'reason': orch_result.decision_reason,
                } if orch_result.final_decision else None,
            )
        except Exception as e:
            logger.exception(f"Error in orchestrator pipeline: {e}")
            return PipelineResult(
                success=False,
                article_id=str(article.get('id', 'unknown')),
                error=str(e)
            )

    async def process_single(
        self,
        article: dict,
        existing_articles: List[dict] = None,
        skip_duplicate_check: bool = False,
        skip_extraction: bool = False,
        skip_approval: bool = False,
        incident_type_id: Optional[UUID] = None,
        use_orchestrator: bool = None,
        extraction_pipeline: Optional[str] = None,
    ) -> PipelineResult:
        """
        Process a single article through the pipeline.

        Args:
            article: Article to process
            existing_articles: List of existing articles for duplicate check
            skip_duplicate_check: Skip duplicate detection
            skip_extraction: Skip LLM extraction
            skip_approval: Skip auto-approval evaluation
            incident_type_id: Optional incident type ID for type-specific processing
            use_orchestrator: Override instance setting for orchestrator use
            extraction_pipeline: 'legacy' or 'two_stage' (overrides article's setting)

        Returns:
            PipelineResult with all step results
        """
        # Determine if we should use orchestrator
        should_use_orchestrator = use_orchestrator if use_orchestrator is not None else self.use_orchestrator

        # Use orchestrator if available and requested
        if should_use_orchestrator and self._orchestrator and incident_type_id:
            return await self.process_with_orchestrator(article, incident_type_id)

        # Check for two-stage pipeline
        pipeline_mode = extraction_pipeline or article.get('extraction_pipeline', 'legacy')
        if pipeline_mode == 'two_stage' and not skip_extraction:
            return await self._process_two_stage(article, existing_articles, skip_duplicate_check, skip_approval)

        result = PipelineResult(
            success=True,
            article_id=str(article.get('id', 'unknown'))
        )

        try:
            # Step 1: Duplicate Detection
            if not skip_duplicate_check and existing_articles:
                dup_result = self.detector.check_duplicate(article, existing_articles)
                if dup_result:
                    result.duplicate_result = dup_result
                    result.final_decision = 'duplicate'
                    result.steps_completed.append('duplicate_detection')
                    return result
                result.steps_completed.append('duplicate_detection')

            # Step 2: LLM Extraction
            extraction_data = article.get('extracted_data')
            if not skip_extraction and not extraction_data and self.extractor.is_available():
                content = article.get('content') or article.get('description', '')
                title = article.get('title') or article.get('headline', '')
                full_text = f"{title}\n\n{content}" if title else content

                if full_text.strip():
                    ext_result = self.extractor.extract(full_text)
                    result.extraction_result = ext_result
                    if ext_result.get('success') and ext_result.get('extracted_data'):
                        extraction_data = ext_result['extracted_data']
                        # Normalize state field
                        if 'state' in extraction_data:
                            extraction_data['state'] = normalize_state(extraction_data['state'])
                        article['extracted_data'] = extraction_data
                result.steps_completed.append('llm_extraction')

            # Step 3: Auto-Approval Evaluation
            if not skip_approval:
                approval = self.approver.evaluate(article, extraction_data)
                result.approval_result = {
                    'decision': approval.decision,
                    'confidence': approval.confidence,
                    'reason': approval.reason,
                    'details': approval.details
                }
                result.final_decision = approval.decision
                result.steps_completed.append('auto_approval')

            return result

        except Exception as e:
            logger.exception(f"Error processing article {result.article_id}: {e}")
            result.success = False
            result.error = str(e)
            return result

    async def _process_two_stage(
        self,
        article: dict,
        existing_articles: List[dict] = None,
        skip_duplicate_check: bool = False,
        skip_approval: bool = False,
    ) -> PipelineResult:
        """Process article using the two-stage extraction pipeline."""
        from .two_stage_extraction import get_two_stage_service

        result = PipelineResult(
            success=True,
            article_id=str(article.get('id', 'unknown'))
        )

        try:
            # Step 1: Duplicate Detection (same as legacy)
            if not skip_duplicate_check and existing_articles:
                dup_result = self.detector.check_duplicate(article, existing_articles)
                if dup_result:
                    result.duplicate_result = dup_result
                    result.final_decision = 'duplicate'
                    result.steps_completed.append('duplicate_detection')
                    return result
                result.steps_completed.append('duplicate_detection')

            # Step 2: Two-stage extraction
            article_id = str(article.get('id', ''))
            if article_id:
                service = get_two_stage_service()
                pipeline_result = await service.run_full_pipeline(article_id)
                result.extraction_result = {
                    'success': True,
                    'pipeline': 'two_stage',
                    'stage1': {
                        'id': pipeline_result['stage1']['id'],
                        'entity_count': pipeline_result['stage1'].get('entity_count'),
                        'event_count': pipeline_result['stage1'].get('event_count'),
                        'confidence': pipeline_result['stage1'].get('overall_confidence'),
                    },
                    'stage2_count': len(pipeline_result.get('stage2_results', [])),
                }
                result.steps_completed.append('two_stage_extraction')

                # Select and merge best stage2 result into article extracted_data
                from .stage2_selector import select_and_merge_stage2
                merged = select_and_merge_stage2(pipeline_result.get('stage2_results', []))
                if merged and merged.get('extracted_data'):
                    article['extracted_data'] = merged['extracted_data']
                    # Persist merge_info inside extracted_data so schema
                    # identity survives to approval/incident-creation time
                    if merged.get('merge_info'):
                        article['extracted_data']['merge_info'] = merged['merge_info']
                    result.extraction_result['merge_info'] = merged.get('merge_info')

            # Step 3: Auto-Approval (uses merged Stage 2 extraction)
            if not skip_approval:
                extraction_data = article.get('extracted_data')
                approval = self.approver.evaluate(article, extraction_data)
                result.approval_result = {
                    'decision': approval.decision,
                    'confidence': approval.confidence,
                    'reason': approval.reason,
                    'details': approval.details
                }
                result.final_decision = approval.decision
                result.steps_completed.append('auto_approval')

            return result

        except Exception as e:
            logger.exception("Error in two-stage pipeline for article %s: %s", result.article_id, e)
            result.success = False
            result.error = str(e)
            return result

    async def process_batch(
        self,
        articles: List[dict],
        existing_articles: List[dict] = None,
        delay_ms: int = 500
    ) -> BatchResult:
        """
        Process a batch of articles through the pipeline.

        Args:
            articles: List of articles to process
            existing_articles: List of existing articles for duplicate check
            delay_ms: Delay between articles (to avoid API throttling)

        Returns:
            BatchResult with aggregate statistics
        """
        import asyncio

        batch_result = BatchResult()

        for article in articles:
            result = await self.process_single(article, existing_articles)
            batch_result.results.append(result)
            batch_result.processed += 1

            if result.error:
                batch_result.errors += 1
            elif result.final_decision == 'duplicate':
                batch_result.duplicates += 1
            elif result.final_decision == 'auto_approve':
                batch_result.auto_approved += 1
            elif result.final_decision == 'auto_reject':
                batch_result.auto_rejected += 1
            elif result.final_decision == 'needs_review':
                batch_result.needs_review += 1

            # Delay between articles
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

        return batch_result

    def get_stats(self) -> dict:
        """Get pipeline statistics and configuration."""
        return {
            'duplicate_detection': self.detector.get_config(),
            'auto_approval': self.approver.get_config(),
            'llm_extraction': {
                'available': self.extractor.is_available(),
            }
        }


# Singleton instance
_pipeline: Optional[UnifiedPipeline] = None


def get_pipeline() -> UnifiedPipeline:
    """Get the singleton pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = UnifiedPipeline()
    return _pipeline
