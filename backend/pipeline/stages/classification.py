"""
Classification stage - classifies article into incident type.
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


class ClassificationStage(PipelineStage):
    """Classify article into a specific incident type."""

    slug = "classification"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Classify the article into an incident type.

        Config options:
        - default_category: Default category if unknown (default: None)
        - use_ai: Use AI for classification (default: True if not already classified)
        """
        from backend.services.incident_type_service import get_incident_type_service

        type_service = get_incident_type_service()

        # If already classified by previous stage, look up the type
        if context.detected_category:
            incident_type = await type_service.get_type_by_slug(context.detected_category)
            if incident_type:
                context.incident_type_id = incident_type.id
                return StageExecutionResult(
                    stage_slug=self.slug,
                    result=StageResult.CONTINUE,
                    data={
                        "incident_type_id": str(incident_type.id),
                        "category": context.detected_category,
                        "source": "previous_stage"
                    }
                )

        # Try to classify based on content analysis
        title = context.article.get("title", "")
        content = context.article.get("content", "")
        text = f"{title} {content}".lower()

        # Simple rule-based classification
        enforcement_indicators = [
            "ice agent", "cbp officer", "border patrol", "immigration officer",
            "protester", "journalist", "bystander", "detained", "custody death",
            "use of force", "raid", "workplace enforcement"
        ]

        crime_indicators = [
            "charged with", "arrested for", "convicted of", "murder", "assault",
            "robbery", "rape", "sexual assault", "prior deportation", "reentry",
            "criminal history", "gang", "cartel", "drug trafficking"
        ]

        enforcement_count = sum(1 for ind in enforcement_indicators if ind in text)
        crime_count = sum(1 for ind in crime_indicators if ind in text)

        if enforcement_count > crime_count:
            category = "enforcement"
        elif crime_count > enforcement_count:
            category = "crime"
        else:
            category = config.get("default_category")

        if category:
            incident_type = await type_service.get_type_by_slug(category)
            if incident_type:
                context.detected_category = category
                context.incident_type_id = incident_type.id
                return StageExecutionResult(
                    stage_slug=self.slug,
                    result=StageResult.CONTINUE,
                    data={
                        "incident_type_id": str(incident_type.id),
                        "category": category,
                        "enforcement_indicators": enforcement_count,
                        "crime_indicators": crime_count,
                        "source": "rule_based"
                    }
                )

        # Could not classify
        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "incident_type_id": None,
                "category": None,
                "enforcement_indicators": enforcement_count,
                "crime_indicators": crime_count,
                "source": "unclassified"
            }
        )
