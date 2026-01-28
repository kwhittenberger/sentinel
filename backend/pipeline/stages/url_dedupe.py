"""
URL deduplication stage - checks for duplicate URLs.
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


class URLDedupeStage(PipelineStage):
    """Check for duplicate URLs in the database."""

    slug = "url_dedupe"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Check if the article URL already exists.

        Config options:
        - check_archived: Also check archived articles (default: True)
        """
        from backend.database import fetch

        url = context.article.get("url") or context.article.get("source_url")

        if not url:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No URL provided"}
            )

        check_archived = config.get("check_archived", True)

        # Check ingested_articles
        query = """
            SELECT id, title, curation_status
            FROM ingested_articles
            WHERE url = $1
        """
        if not check_archived:
            query += " AND curation_status != 'archived'"

        rows = await fetch(query, url)

        if rows:
            existing = rows[0]
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.SKIP,
                data={
                    "is_duplicate": True,
                    "existing_id": str(existing["id"]),
                    "existing_title": existing["title"],
                    "existing_status": existing["curation_status"],
                    "reason": f"URL already exists (ID: {existing['id']})"
                }
            )

        # Also check approved incidents
        query = """
            SELECT i.id, i.description
            FROM incidents i
            JOIN incident_sources s ON i.id = s.incident_id
            WHERE s.url = $1
        """
        rows = await fetch(query, url)

        if rows:
            existing = rows[0]
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.SKIP,
                data={
                    "is_duplicate": True,
                    "existing_incident_id": str(existing["id"]),
                    "reason": f"URL already linked to incident {existing['id']}"
                }
            )

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={"is_duplicate": False}
        )
