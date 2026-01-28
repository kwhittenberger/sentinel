"""
Relevance check stage - determines if article is relevant to the tracking system.
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


class RelevanceStage(PipelineStage):
    """Check if article is relevant using keyword matching or AI."""

    slug = "relevance"

    # Keywords that indicate potential relevance
    ENFORCEMENT_KEYWORDS = [
        "ice", "immigration", "customs enforcement", "border patrol", "cbp",
        "deportation", "detainee", "detention", "immigrant", "raid",
        "sanctuary", "enforcement", "undocumented"
    ]

    CRIME_KEYWORDS = [
        "illegal alien", "undocumented immigrant", "deported", "prior deportation",
        "immigration status", "illegal immigrant", "ice detainer",
        "criminal alien", "gang member"
    ]

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Check article relevance.

        Config options:
        - use_ai: Use AI for relevance check (default: False)
        - min_keyword_score: Minimum keyword score (default: 2)
        - prompt_id: Custom prompt for AI check
        """
        title = context.article.get("title", "")
        content = context.article.get("content", "")
        text = f"{title} {content}".lower()

        use_ai = config.get("use_ai", False)
        min_keyword_score = config.get("min_keyword_score", 2)

        # Quick keyword check first
        enforcement_score = sum(1 for kw in self.ENFORCEMENT_KEYWORDS if kw in text)
        crime_score = sum(1 for kw in self.CRIME_KEYWORDS if kw in text)
        total_score = enforcement_score + crime_score

        if total_score < min_keyword_score:
            # Not enough keywords, likely irrelevant
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.REJECT,
                data={
                    "is_relevant": False,
                    "keyword_score": total_score,
                    "enforcement_score": enforcement_score,
                    "crime_score": crime_score,
                    "reason": f"Keyword score too low ({total_score} < {min_keyword_score})"
                }
            )

        # Tentatively set category based on keyword balance
        if enforcement_score > crime_score:
            context.detected_category = "enforcement"
        elif crime_score > enforcement_score:
            context.detected_category = "crime"

        # If AI check is enabled and we have a prompt
        if use_ai and config.get("prompt_id"):
            ai_result = await self._ai_relevance_check(context, config)
            if ai_result:
                return ai_result

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "is_relevant": True,
                "keyword_score": total_score,
                "enforcement_score": enforcement_score,
                "crime_score": crime_score,
                "detected_category": context.detected_category
            }
        )

    async def _ai_relevance_check(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult | None:
        """Run AI-based relevance check."""
        try:
            from backend.services.prompt_manager import get_prompt_manager, PromptType

            prompt_manager = get_prompt_manager()
            prompt = await prompt_manager.get_prompt(
                PromptType.CLASSIFICATION,
                incident_type_id=context.incident_type_id
            )

            if not prompt:
                return None

            title = context.article.get("title", "")
            content = context.article.get("content", "")

            rendered = prompt_manager.render_prompt(
                prompt,
                {"article_text": f"{title}\n\n{content}"}
            )

            # Call LLM
            import anthropic
            import json
            import os

            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            message = client.messages.create(
                model=prompt.model_name,
                max_tokens=prompt.max_tokens,
                system=rendered.system_prompt,
                messages=[{"role": "user", "content": rendered.user_prompt}],
            )

            response_text = message.content[0].text

            # Parse JSON response
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            data = json.loads(response_text)

            if not data.get("is_relevant", False):
                return StageExecutionResult(
                    stage_slug=self.slug,
                    result=StageResult.REJECT,
                    data={
                        "is_relevant": False,
                        "ai_checked": True,
                        "relevance_reason": data.get("relevance_reason", ""),
                        "reason": "AI determined article is not relevant"
                    }
                )

            context.detected_category = data.get("category")

            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "is_relevant": True,
                    "ai_checked": True,
                    "detected_category": context.detected_category,
                    "confidence": data.get("category_confidence", 0.5)
                }
            )

        except Exception as e:
            logger.error(f"AI relevance check failed: {e}")
            return None
