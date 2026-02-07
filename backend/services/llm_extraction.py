"""
LLM-based extraction service using Anthropic Claude.
Supports category-aware extraction for enforcement vs crime incidents.
Now integrates with PromptManager for database-backed prompts when available.
"""

import json
import logging
from typing import Optional, Literal
from uuid import UUID

from backend.utils.llm_parsing import parse_llm_json

from .extraction_prompts import (
    EXTRACTION_SCHEMA,
    UNIVERSAL_EXTRACTION_SCHEMA,
    UNIVERSAL_SYSTEM_PROMPT,
    TRIAGE_SCHEMA,
    TRIAGE_SYSTEM_PROMPT,
    get_extraction_prompt,
    get_system_prompt,
    get_triage_prompt,
    get_universal_extraction_prompt,
    get_required_fields,
    IncidentCategory,
)
from .prompt_manager import ExecutionResult

logger = logging.getLogger(__name__)

# Import PromptManager for database-backed prompts (optional)
try:
    from .prompt_manager import get_prompt_manager, PromptManager
    PROMPT_MANAGER_AVAILABLE = True
except ImportError:
    PROMPT_MANAGER_AVAILABLE = False
    PromptManager = None


class LLMExtractor:
    """Extracts incident data from article text using LLM providers."""

    def __init__(self, use_db_prompts: bool = True):
        self.use_db_prompts = use_db_prompts and PROMPT_MANAGER_AVAILABLE
        self._prompt_manager: Optional[PromptManager] = None
        self._db_pool = None

        from .llm_provider import get_llm_router
        self._router = get_llm_router()

        if not self._router.has_available_provider():
            logger.warning("No LLM providers available - extraction disabled")

    def set_db_pool(self, pool):
        """Set database pool for PromptManager integration."""
        self._db_pool = pool
        if self.use_db_prompts and PROMPT_MANAGER_AVAILABLE:
            self._prompt_manager = get_prompt_manager(pool)

    def is_available(self) -> bool:
        """Check if extraction is available."""
        return self._router.has_available_provider()

    def _get_stage_config(self, stage_key: str):
        """Get LLM stage config from settings."""
        from .settings import get_settings_service
        settings = get_settings_service()
        llm_settings = settings._settings.llm
        return llm_settings.get_stage_config(stage_key), llm_settings

    def triage(self, title: str, article_text: str) -> dict:
        """
        Quick triage to determine if article is worth full extraction.
        Uses a smaller context and faster model for efficiency.

        Args:
            title: Article title
            article_text: Article content

        Returns:
            dict with recommendation (extract/reject/review) and reasoning
        """
        if not self._router.has_available_provider():
            return {
                "success": False,
                "error": "LLM not available",
                "recommendation": "review"
            }

        prompt = get_triage_prompt(title, article_text)
        stage_cfg, llm_settings = self._get_stage_config("triage")

        try:
            response = self._router.call(
                system_prompt=TRIAGE_SYSTEM_PROMPT,
                user_message=prompt,
                model=stage_cfg.model,
                max_tokens=stage_cfg.max_tokens,
                provider_name=stage_cfg.provider,
                fallback_provider=llm_settings.fallback_provider,
                fallback_model=llm_settings.fallback_model,
            )

            data = parse_llm_json(response.text)

            return {
                "success": True,
                "is_specific_incident": data.get("is_specific_incident", False),
                "reason": data.get("reason", ""),
                "incident_type": data.get("incident_type", "none"),
                "has_named_individuals": data.get("has_named_individuals", False),
                "has_specific_date_or_timeframe": data.get("has_specific_date_or_timeframe", False),
                "has_specific_location": data.get("has_specific_location", False),
                "recommendation": data.get("recommendation", "review"),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse triage response: {e}")
            return {"success": False, "error": str(e), "recommendation": "review"}
        except Exception as e:
            logger.exception(f"Triage error: {e}")
            return {"success": False, "error": str(e), "recommendation": "review"}

    async def extract_universal_async(self, article_text: str, max_tokens: int = 4000) -> dict:
        """Async version of extract_universal with tracking support."""
        result = self.extract_universal(article_text, max_tokens)

        # Track usage if prompt manager available
        if self._prompt_manager and result.get('_api_usage'):
            try:
                from uuid import UUID
                import asyncio

                # Get the universal extraction prompt
                prompt = await self._prompt_manager.get_prompt(
                    prompt_type='extraction',
                    slug='universal_extraction'
                )

                if prompt:
                    usage = result.get('_api_usage', {})
                    execution_result = ExecutionResult(
                        success=result.get('success', False),
                        confidence_score=result.get('confidence', 0.0),
                        input_tokens=usage.get('input_tokens'),
                        output_tokens=usage.get('output_tokens'),
                        latency_ms=usage.get('latency_ms'),
                        result_data=result.get('incident') or result.get('actors'),
                    )
                    await self._prompt_manager.record_execution(
                        prompt_id=prompt.id,
                        result=execution_result,
                    )
            except Exception as e:
                logger.warning(f"Failed to record universal extraction: {e}")

        # Remove internal tracking data before returning
        result.pop('_api_usage', None)
        return result

    def extract_universal(self, article_text: str, max_tokens: int = 4000) -> dict:
        """
        Universal extraction that captures ALL entities regardless of category.

        This extracts:
        - All actors (people, agencies, organizations) with their roles
        - All events (protests, hearings, prior incidents)
        - Incident details with multiple possible categories
        - Policy context

        Args:
            article_text: The article content to analyze
            max_tokens: Maximum tokens for response

        Returns:
            dict with universal extraction schema results
        """
        if not self._router.has_available_provider():
            return {
                "success": False,
                "error": "LLM extraction not available - no providers configured",
            }

        # Truncate very long articles
        if len(article_text) > 20000:
            article_text = article_text[:20000] + "\n\n[Article truncated due to length]"

        prompt = get_universal_extraction_prompt(article_text)
        prompt += f"\n\nRespond with JSON matching this schema:\n{json.dumps(UNIVERSAL_EXTRACTION_SCHEMA, indent=2)}"

        stage_cfg, llm_settings = self._get_stage_config("extraction_universal")

        try:
            response = self._router.call(
                system_prompt=UNIVERSAL_SYSTEM_PROMPT,
                user_message=prompt,
                model=stage_cfg.model,
                max_tokens=stage_cfg.max_tokens if max_tokens == 4000 else max_tokens,
                provider_name=stage_cfg.provider,
                fallback_provider=llm_settings.fallback_provider,
                fallback_model=llm_settings.fallback_model,
            )

            data = parse_llm_json(response.text)

            result = {
                "success": True,
                "is_relevant": data.get("is_relevant", False),
                "relevance_reason": data.get("relevance_reason", ""),
                "extraction_type": "universal",
            }

            if data.get("is_relevant"):
                result["incident"] = data.get("incident", {})
                result["actors"] = data.get("actors", [])
                result["events"] = data.get("events", [])
                result["policy_context"] = data.get("policy_context", {})
                result["sources_cited"] = data.get("sources_cited", [])
                result["extraction_notes"] = data.get("extraction_notes", "")

                # Calculate overall confidence
                incident = result.get("incident", {})
                result["confidence"] = incident.get("overall_confidence", 0.5)

                # Determine categories from incident
                result["categories"] = incident.get("categories", [])

            # Track provider info for usage recording
            result["_api_usage"] = {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
                "provider": response.provider,
                "model": response.model,
            }

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse universal extraction response: {e}")
            return {"success": False, "error": f"Failed to parse response: {e}"}
        except Exception as e:
            logger.exception(f"Unexpected error during universal extraction: {e}")
            return {"success": False, "error": f"Unexpected error: {e}"}

    async def _get_prompt_from_db(
        self,
        prompt_type: str,
        incident_type_id: Optional[UUID] = None
    ) -> Optional[dict]:
        """Get prompt from database if available."""
        if not self._prompt_manager or not self._db_pool:
            return None

        try:
            prompt = await self._prompt_manager.get_prompt(
                prompt_type=prompt_type,
                incident_type_id=incident_type_id
            )
            return prompt
        except Exception as e:
            logger.warning(f"Failed to get prompt from database: {e}")
            return None

    async def extract_async(
        self,
        article_text: str,
        document_type: str = "news_article",
        category: Optional[IncidentCategory] = None,
        incident_type_id: Optional[UUID] = None,
        max_tokens: int = 2000,
    ) -> dict:
        """
        Async version of extract that can use database-backed prompts.

        Args:
            article_text: The article content to analyze
            document_type: Type of document
            category: Optional category hint
            incident_type_id: Optional incident type ID for type-specific prompts
            max_tokens: Maximum tokens for response

        Returns:
            Extraction result dict
        """
        if not self._router.has_available_provider():
            return {
                "success": False,
                "error": "LLM extraction not available - no providers configured",
            }

        # Truncate very long articles
        if len(article_text) > 15000:
            article_text = article_text[:15000] + "\n\n[Article truncated due to length]"

        # Try to get prompt from database
        db_prompt = await self._get_prompt_from_db('extraction', incident_type_id)

        if db_prompt and self._prompt_manager:
            # Use database-backed prompt
            rendered = self._prompt_manager.render_prompt(
                db_prompt,
                {
                    "document_type": document_type,
                    "article_text": article_text,
                    "category": category,
                }
            )
            system_prompt = rendered["system"]
            user_prompt = rendered["user"]
            model = db_prompt.get("model_name", "claude-sonnet-4-20250514")
            db_max_tokens = db_prompt.get("max_tokens", max_tokens)
        else:
            # Fall back to static prompts
            user_prompt = get_extraction_prompt(document_type, article_text, category)
            user_prompt += f"\n\nRespond with JSON matching this schema:\n{json.dumps(EXTRACTION_SCHEMA, indent=2)}"
            system_prompt = get_system_prompt(category)
            model = "claude-sonnet-4-20250514"
            db_max_tokens = max_tokens

        stage_cfg, llm_settings = self._get_stage_config("extraction_async")

        try:
            llm_response = self._router.call(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model=model if db_prompt else stage_cfg.model,
                max_tokens=db_max_tokens if db_prompt else stage_cfg.max_tokens,
                provider_name=stage_cfg.provider,
                fallback_provider=llm_settings.fallback_provider,
                fallback_model=llm_settings.fallback_model,
            )

            # Parse response
            data = parse_llm_json(llm_response.text)

            result = {
                "success": True,
                "is_relevant": data.get("is_relevant", False),
                "relevance_reason": data.get("relevance_reason", ""),
                "prompt_source": "database" if db_prompt else "static",
            }

            if data.get("is_relevant") and "incident" in data:
                incident = data["incident"]
                result["extracted_data"] = incident
                result["confidence"] = incident.get("overall_confidence", 0.5)

                extracted_category = data.get("category") or category
                result["category"] = extracted_category

                confidence_fields = ["date", "state", "city", "incident_type", "victim_name", "offender_name"]
                result["field_confidence"] = {
                    field: incident.get(f"{field}_confidence", 0.0)
                    for field in confidence_fields
                    if f"{field}_confidence" in incident
                }

                if extracted_category:
                    required = get_required_fields(extracted_category)
                    result["required_fields_met"] = all(
                        incident.get(field) is not None
                        for field in required
                    )
                    result["required_fields"] = required
                    result["missing_fields"] = [
                        field for field in required
                        if incident.get(field) is None
                    ]

            # Record execution if using database prompts
            if db_prompt and self._prompt_manager:
                try:
                    execution_result = ExecutionResult(
                        success=result.get("success", False),
                        confidence_score=result.get("confidence", 0.0),
                        input_tokens=llm_response.input_tokens,
                        output_tokens=llm_response.output_tokens,
                        result_data=result.get("extracted_data"),
                    )
                    await self._prompt_manager.record_execution(
                        prompt_id=UUID(db_prompt["id"]),
                        result=execution_result,
                    )
                except Exception as e:
                    logger.warning(f"Failed to record prompt execution: {e}")

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return {"success": False, "error": f"Failed to parse response: {e}"}
        except Exception as e:
            logger.exception(f"Unexpected error during extraction: {e}")
            return {"success": False, "error": f"Unexpected error: {e}"}

    def extract(
        self,
        article_text: str,
        document_type: str = "news_article",
        category: Optional[IncidentCategory] = None,
        max_tokens: int = 2000,
    ) -> dict:
        """
        Extract incident data from article text.

        Args:
            article_text: The article content to analyze
            document_type: Type of document (news_article, ice_release, court_document)
            category: Optional category hint (enforcement or crime) for targeted extraction
            max_tokens: Maximum tokens for response

        Returns:
            dict with:
                - success: bool
                - is_relevant: bool
                - relevance_reason: str
                - category: str (enforcement or crime)
                - extracted_data: dict (if relevant)
                - confidence: float
                - required_fields_met: bool
                - error: str (if failed)
        """
        if not self._router.has_available_provider():
            return {
                "success": False,
                "error": "LLM extraction not available - no providers configured",
            }

        # Truncate very long articles
        if len(article_text) > 15000:
            article_text = article_text[:15000] + "\n\n[Article truncated due to length]"

        # Get category-aware prompts
        prompt = get_extraction_prompt(document_type, article_text, category)
        system_prompt = get_system_prompt(category)

        stage_cfg, llm_settings = self._get_stage_config("extraction")

        try:
            llm_response = self._router.call(
                system_prompt=system_prompt,
                user_message=prompt + f"\n\nRespond with JSON matching this schema:\n{json.dumps(EXTRACTION_SCHEMA, indent=2)}",
                model=stage_cfg.model,
                max_tokens=max_tokens if max_tokens != 2000 else stage_cfg.max_tokens,
                provider_name=stage_cfg.provider,
                fallback_provider=llm_settings.fallback_provider,
                fallback_model=llm_settings.fallback_model,
            )

            # Parse response
            data = parse_llm_json(llm_response.text)

            result = {
                "success": True,
                "is_relevant": data.get("is_relevant", False),
                "relevance_reason": data.get("relevance_reason", ""),
            }

            if data.get("is_relevant") and "incident" in data:
                incident = data["incident"]
                result["extracted_data"] = incident
                result["confidence"] = incident.get("overall_confidence", 0.5)

                # Determine category from extraction or use provided hint
                extracted_category = data.get("category") or category
                result["category"] = extracted_category

                # Calculate field-level confidence
                confidence_fields = ["date", "state", "city", "incident_type", "victim_name", "offender_name"]
                result["field_confidence"] = {
                    field: incident.get(f"{field}_confidence", 0.0)
                    for field in confidence_fields
                    if f"{field}_confidence" in incident
                }

                # Check if required fields for category are met
                if extracted_category:
                    required = get_required_fields(extracted_category)
                    result["required_fields_met"] = all(
                        incident.get(field) is not None
                        for field in required
                    )
                    result["required_fields"] = required
                    result["missing_fields"] = [
                        field for field in required
                        if incident.get(field) is None
                    ]

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return {
                "success": False,
                "error": f"Failed to parse response: {e}",
            }
        except Exception as e:
            logger.exception(f"Unexpected error during extraction: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


# Singleton instance
_extractor: Optional[LLMExtractor] = None


def get_extractor() -> LLMExtractor:
    """Get the singleton LLM extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = LLMExtractor()
    return _extractor


def extract_incident_from_article(
    article_text: str,
    document_type: str = "news_article",
) -> dict:
    """
    Convenience function to extract incident from article.

    Args:
        article_text: The article content
        document_type: Type of document

    Returns:
        Extraction result dict
    """
    extractor = get_extractor()
    return extractor.extract(article_text, document_type)


def should_auto_approve(extraction_result: dict, threshold: float = 0.8) -> bool:
    """
    Determine if an extraction should be auto-approved.

    Args:
        extraction_result: Result from extract()
        threshold: Confidence threshold for auto-approval

    Returns:
        bool indicating if should auto-approve
    """
    if not extraction_result.get("success"):
        return False

    if not extraction_result.get("is_relevant"):
        return False

    confidence = extraction_result.get("confidence", 0.0)
    if confidence < threshold:
        return False

    # Check required fields have high confidence
    field_confidence = extraction_result.get("field_confidence", {})
    required_fields = ["date", "state", "incident_type"]

    for field in required_fields:
        if field_confidence.get(field, 0.0) < threshold:
            return False

    return True
