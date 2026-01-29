"""
Enrichment pipeline stage - fills missing incident fields from related data.

Runs after cross_reference (order 110). Uses cross-incident merge and
optionally targeted LLM re-extraction to fill NULL fields.
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


class EnrichmentStage(PipelineStage):
    """Fill missing incident fields from related incidents and articles."""

    slug = "enrichment"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Attempt to enrich extracted data using cross-references.

        Uses context.detected_relations from CrossReferenceStage to find
        related incidents that may have data we're missing.

        Config options:
        - strategy: 'cross_incident', 'llm_reextract', 'both' (default: 'cross_incident')
        - auto_apply: Apply high-confidence enrichments (default: False)
        - min_confidence: Minimum confidence to suggest (default: 0.6)
        - max_llm_calls: Limit LLM calls per pipeline run (default: 5)
        """
        if not context.extracted_data:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No extracted data"}
            )

        strategy = config.get("strategy", "cross_incident")
        min_confidence = config.get("min_confidence", 0.6)
        max_llm_calls = config.get("max_llm_calls", 5)

        # Collect suggestions from related incidents found by CrossReferenceStage
        enrichment_suggestions = []
        data = context.extracted_data

        # Identify missing fields in current extraction
        missing_fields = []
        field_checks = {
            "city": data.get("city") or (data.get("incident", {}) or {}).get("location", {}).get("city"),
            "description": data.get("description") or (data.get("incident", {}) or {}).get("summary"),
            "victim_name": data.get("victim_name"),
            "outcome_category": data.get("outcome_category") or (data.get("incident", {}) or {}).get("outcome", {}).get("category"),
        }

        for field_name, value in field_checks.items():
            if not value:
                missing_fields.append(field_name)

        if not missing_fields:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No missing fields to enrich"}
            )

        # Check related incidents from cross-reference stage
        related_incidents = [
            r for r in context.detected_relations
            if r.get("type") == "suggested_relation"
        ]

        if related_incidents and strategy in ("cross_incident", "both"):
            from backend.database import fetch

            for relation in related_incidents[:10]:
                related_id = relation.get("incident_id")
                if not related_id:
                    continue

                try:
                    import uuid
                    rows = await fetch("""
                        SELECT city, description, victim_name, outcome_category, outcome_detail,
                               latitude, longitude
                        FROM incidents WHERE id = $1
                    """, uuid.UUID(related_id))

                    if not rows:
                        continue

                    related = dict(rows[0])
                    match_score = relation.get("match_score", 0.5)

                    for field_name in missing_fields:
                        column_map = {
                            "city": "city",
                            "description": "description",
                            "victim_name": "victim_name",
                            "outcome_category": "outcome_category",
                        }
                        col = column_map.get(field_name)
                        if col and related.get(col):
                            confidence = min(0.9, match_score)
                            if confidence >= min_confidence:
                                enrichment_suggestions.append({
                                    "field": field_name,
                                    "value": str(related[col]),
                                    "source_type": "cross_incident",
                                    "source_incident_id": related_id,
                                    "confidence": confidence,
                                    "reason": relation.get("reason", "Related incident"),
                                })

                except Exception as e:
                    logger.warning(f"Error checking related incident {related_id}: {e}")

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "missing_fields": missing_fields,
                "suggestions": enrichment_suggestions,
                "suggestion_count": len(enrichment_suggestions),
                "related_checked": len(related_incidents),
            }
        )
