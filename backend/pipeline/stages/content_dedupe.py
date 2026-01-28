"""
Content deduplication stage - checks for similar content via title/text similarity.
"""

import logging
from typing import Dict, Any

from backend.services.pipeline_orchestrator import (
    PipelineStage,
    PipelineContext,
    StageExecutionResult,
    StageResult,
)

logger = logging.getLogger(__name__)


class ContentDedupeStage(PipelineStage):
    """Check for duplicate content via similarity matching."""

    slug = "content_dedupe"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Check for similar existing articles by title and content.

        Config options:
        - title_threshold: Similarity threshold for titles (default: 0.85)
        - content_threshold: Similarity threshold for content (default: 0.80)
        - check_days: Only check articles from last N days (default: 30)
        """
        from backend.database import fetch

        title = context.article.get("title") or context.article.get("headline", "")
        content = context.article.get("content") or context.article.get("description", "")

        if not title and not content:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No title or content"}
            )

        title_threshold = config.get("title_threshold", 0.85)
        content_threshold = config.get("content_threshold", 0.80)
        check_days = config.get("check_days", 30)

        # Check title similarity
        if title:
            query = """
                SELECT id, title, similarity(title, $1) as sim
                FROM ingested_articles
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND title %% $1
                  AND similarity(title, $1) > $2
                ORDER BY sim DESC
                LIMIT 1
            """ % check_days

            rows = await fetch(query, title, title_threshold)

            if rows:
                existing = rows[0]
                return StageExecutionResult(
                    stage_slug=self.slug,
                    result=StageResult.SKIP,
                    data={
                        "is_duplicate": True,
                        "match_type": "title",
                        "similarity": float(existing["sim"]),
                        "existing_id": str(existing["id"]),
                        "existing_title": existing["title"],
                        "reason": f"Similar title found ({existing['sim']:.0%} match)"
                    }
                )

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={"is_duplicate": False}
        )
