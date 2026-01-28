"""
LLM-based extraction service using Anthropic Claude.
Supports category-aware extraction for enforcement vs crime incidents.
Now integrates with PromptManager for database-backed prompts when available.
"""

import json
import logging
import os
from typing import Optional, Literal
from uuid import UUID

import anthropic

from .extraction_prompts import (
    EXTRACTION_SCHEMA,
    get_extraction_prompt,
    get_system_prompt,
    get_required_fields,
    IncidentCategory,
)

logger = logging.getLogger(__name__)

# Get API key from environment
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Import PromptManager for database-backed prompts (optional)
try:
    from .prompt_manager import get_prompt_manager, PromptManager
    PROMPT_MANAGER_AVAILABLE = True
except ImportError:
    PROMPT_MANAGER_AVAILABLE = False
    PromptManager = None


class LLMExtractor:
    """Extracts incident data from article text using Claude."""

    def __init__(self, api_key: Optional[str] = None, use_db_prompts: bool = True):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.use_db_prompts = use_db_prompts and PROMPT_MANAGER_AVAILABLE
        self._prompt_manager: Optional[PromptManager] = None
        self._db_pool = None

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set - LLM extraction disabled")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)

    def set_db_pool(self, pool):
        """Set database pool for PromptManager integration."""
        self._db_pool = pool
        if self.use_db_prompts and PROMPT_MANAGER_AVAILABLE:
            self._prompt_manager = get_prompt_manager(pool)

    def is_available(self) -> bool:
        """Check if extraction is available."""
        return self.client is not None

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
        if not self.client:
            return {
                "success": False,
                "error": "LLM extraction not available - ANTHROPIC_API_KEY not set",
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

        try:
            message = self.client.messages.create(
                model=model,
                max_tokens=db_max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Parse response
            response_text = message.content[0].text

            # Extract JSON from response
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            data = json.loads(response_text)

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
                    await self._prompt_manager.record_execution(
                        prompt_id=UUID(db_prompt["id"]),
                        result={
                            "success": result.get("success", False),
                            "confidence": result.get("confidence", 0.0),
                            "input_tokens": message.usage.input_tokens if hasattr(message.usage, 'input_tokens') else None,
                            "output_tokens": message.usage.output_tokens if hasattr(message.usage, 'output_tokens') else None,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to record prompt execution: {e}")

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return {"success": False, "error": f"Failed to parse response: {e}"}
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return {"success": False, "error": f"API error: {e}"}
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
        if not self.client:
            return {
                "success": False,
                "error": "LLM extraction not available - ANTHROPIC_API_KEY not set",
            }

        # Truncate very long articles
        if len(article_text) > 15000:
            article_text = article_text[:15000] + "\n\n[Article truncated due to length]"

        # Get category-aware prompts
        prompt = get_extraction_prompt(document_type, article_text, category)
        system_prompt = get_system_prompt(category)

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": prompt + f"\n\nRespond with JSON matching this schema:\n{json.dumps(EXTRACTION_SCHEMA, indent=2)}"
                    }
                ],
            )

            # Parse response
            response_text = message.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            data = json.loads(response_text)

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
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return {
                "success": False,
                "error": f"API error: {e}",
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
