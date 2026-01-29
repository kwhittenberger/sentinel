"""
Extraction stage - extracts structured incident data from article using LLM.
"""

import json
import logging
from typing import Dict, Any

from backend.services.pipeline_orchestrator import (
    PipelineStage,
    PipelineContext,
    StageExecutionResult,
    StageResult,
)

logger = logging.getLogger(__name__)


class ExtractionStage(PipelineStage):
    """Extract structured incident data using LLM."""

    slug = "extraction"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Extract incident data from article text.

        Config options:
        - max_tokens: Max tokens for LLM response (default: 2000)
        - model: Model to use (default: from prompt config)
        - skip_if_extracted: Skip if already has extraction (default: True)
        """
        from backend.services.prompt_manager import (
            get_prompt_manager,
            PromptType,
            ExecutionResult
        )
        from backend.services.llm_provider import get_llm_router
        from backend.services.settings import get_settings_service

        # Check if already extracted
        if config.get("skip_if_extracted", True) and context.article.get("extracted_data"):
            context.extraction_result = context.article["extracted_data"]
            context.extracted_data = context.article["extracted_data"]
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "skipped": True,
                    "reason": "Already has extracted data",
                    "extracted_data": context.extracted_data
                }
            )

        # Get prompt
        prompt_manager = get_prompt_manager()
        prompt = await prompt_manager.get_prompt(
            PromptType.EXTRACTION,
            incident_type_id=context.incident_type_id
        )

        if not prompt:
            # Fall back to legacy extraction
            return await self._legacy_extraction(context, config)

        # Prepare article text
        title = context.article.get("title", "")
        content = context.article.get("content", "")
        article_text = f"{title}\n\n{content}"

        # Truncate if too long
        if len(article_text) > 15000:
            article_text = article_text[:15000] + "\n\n[Article truncated due to length]"

        # Render prompt
        rendered = prompt_manager.render_prompt(
            prompt,
            {"article_text": article_text}
        )

        # Get schema from type or use default
        output_schema = prompt.output_schema
        if not output_schema and context.incident_type_id:
            from backend.services.incident_type_service import get_incident_type_service
            type_service = get_incident_type_service()
            output_schema = await type_service.get_extraction_schema(context.incident_type_id)

        # Call LLM via router
        router = get_llm_router()
        if not router.has_available_provider():
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.ERROR,
                error="No LLM providers available"
            )

        settings = get_settings_service()
        llm_settings = settings._settings.llm
        stage_cfg = llm_settings.get_stage_config("pipeline_extraction")

        try:
            user_content = rendered.user_prompt
            if output_schema:
                user_content += f"\n\nRespond with JSON matching this schema:\n{json.dumps(output_schema, indent=2)}"

            llm_response = router.call(
                system_prompt=rendered.system_prompt,
                user_message=user_content,
                model=config.get("model", prompt.model_name),
                max_tokens=config.get("max_tokens", prompt.max_tokens),
                provider_name=stage_cfg.provider,
                fallback_provider=llm_settings.fallback_provider,
                fallback_model=llm_settings.fallback_model,
            )

            latency_ms = llm_response.latency_ms
            response_text = llm_response.text

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

            # Record execution
            await prompt_manager.record_execution(
                prompt.id,
                ExecutionResult(
                    success=True,
                    input_tokens=llm_response.input_tokens,
                    output_tokens=llm_response.output_tokens,
                    latency_ms=latency_ms,
                    confidence_score=data.get("incident", {}).get("overall_confidence"),
                    result_data=data
                ),
                article_id=context.article_id
            )

            # Update context
            context.extraction_result = data
            if data.get("is_relevant") and "incident" in data:
                context.extracted_data = data["incident"]

                # Update category if detected
                if data.get("category"):
                    context.detected_category = data["category"]

            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "success": True,
                    "is_relevant": data.get("is_relevant", False),
                    "category": data.get("category"),
                    "confidence": data.get("incident", {}).get("overall_confidence"),
                    "extracted_data": context.extracted_data,
                    "latency_ms": latency_ms
                }
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.ERROR,
                error=f"JSON parse error: {e}"
            )
        except Exception as e:
            logger.exception(f"Extraction error: {e}")
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.ERROR,
                error=str(e)
            )

    async def _legacy_extraction(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """Fall back to legacy extraction if no prompt configured."""
        from backend.services.llm_extraction import get_extractor

        extractor = get_extractor()

        if not extractor.is_available():
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.ERROR,
                error="LLM extraction not available"
            )

        title = context.article.get("title", "")
        content = context.article.get("content", "")
        full_text = f"{title}\n\n{content}" if title else content

        result = extractor.extract(
            full_text,
            category=context.detected_category,
            max_tokens=config.get("max_tokens", 2000)
        )

        if not result.get("success"):
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.ERROR,
                error=result.get("error", "Extraction failed")
            )

        context.extraction_result = result
        context.extracted_data = result.get("extracted_data")

        if result.get("category"):
            context.detected_category = result["category"]

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "success": True,
                "is_relevant": result.get("is_relevant", False),
                "category": result.get("category"),
                "confidence": result.get("confidence"),
                "extracted_data": context.extracted_data,
                "source": "legacy"
            }
        )
