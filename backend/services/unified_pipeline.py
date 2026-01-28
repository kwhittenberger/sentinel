"""
Unified pipeline service for processing articles.
Orchestrates: duplicate detection -> LLM extraction -> auto-approval.
Ported from crime-tracker project.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from .duplicate_detection import get_detector, DuplicateDetector
from .auto_approval import get_auto_approval_service, AutoApprovalService, ApprovalDecision
from .llm_extraction import get_extractor, LLMExtractor

logger = logging.getLogger(__name__)


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
        approver: AutoApprovalService = None
    ):
        self.detector = detector or get_detector()
        self.extractor = extractor or get_extractor()
        self.approver = approver or get_auto_approval_service()

    async def process_single(
        self,
        article: dict,
        existing_articles: List[dict] = None,
        skip_duplicate_check: bool = False,
        skip_extraction: bool = False,
        skip_approval: bool = False
    ) -> PipelineResult:
        """
        Process a single article through the pipeline.

        Args:
            article: Article to process
            existing_articles: List of existing articles for duplicate check
            skip_duplicate_check: Skip duplicate detection
            skip_extraction: Skip LLM extraction
            skip_approval: Skip auto-approval evaluation

        Returns:
            PipelineResult with all step results
        """
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
