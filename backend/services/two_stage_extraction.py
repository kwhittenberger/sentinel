"""
Two-Stage Extraction Service.

Orchestrates a two-stage LLM extraction pipeline:
  Stage 1: Comprehensive entity/event extraction → article_extractions (IR)
  Stage 2: Domain-specific schema extraction → schema_extraction_results

Stage 1 produces a reusable intermediate representation (entities, events,
legal data, quotes, classification hints). Stage 2 schemas receive the IR
plus original article text and produce per-category structured output.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime

from .extraction_prompts import STAGE1_SCHEMA_VERSION, compute_prompt_hash

logger = logging.getLogger(__name__)

# Minimum classification confidence to auto-route to a Stage 2 schema
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.3

# Default timeout (seconds) for individual LLM calls
LLM_CALL_TIMEOUT_SECONDS = 300


class TwoStageExtractionService:
    """Orchestrates two-stage extraction pipeline."""

    # -----------------------------------------------------------------------
    # Stage 1: Comprehensive entity extraction
    # -----------------------------------------------------------------------

    async def run_stage1(
        self,
        article_id: str,
        force: bool = False,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run Stage 1 extraction on an article.

        Args:
            article_id: UUID of the ingested_articles row.
            force: If True, re-run even if a completed extraction exists.

        Returns:
            The article_extractions row as a dict.
        """
        from backend.database import fetch, fetchrow, execute
        from backend.services.llm_provider import get_llm_router

        # Check for existing completed extraction
        if not force:
            existing = await fetchrow(
                """SELECT * FROM article_extractions
                   WHERE article_id = $1::uuid AND status = 'completed'
                   ORDER BY created_at DESC LIMIT 1""",
                article_id,
            )
            if existing:
                return self._serialize(existing)

        # Get article text
        article = await fetchrow(
            "SELECT id, title, content FROM ingested_articles WHERE id = $1::uuid",
            article_id,
        )
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        title = article["title"] or ""
        content = article["content"] or ""
        article_text = f"{title}\n\n{content}".strip()
        if not article_text:
            raise ValueError(f"Article has no text content: {article_id}")

        # Get Stage 1 schema from DB
        stage1_schema = await fetchrow(
            """SELECT * FROM extraction_schemas
               WHERE schema_type = 'stage1' AND is_active = TRUE
               ORDER BY schema_version DESC LIMIT 1"""
        )
        if not stage1_schema:
            raise ValueError("No active Stage 1 schema found")

        system_prompt = stage1_schema["system_prompt"]
        user_prompt_template = stage1_schema["user_prompt_template"]

        # Inject domain relevance criteria into user prompt
        domain_rows = await fetch(
            """SELECT slug, name, relevance_scope
               FROM event_domains
               WHERE is_active = TRUE AND relevance_scope IS NOT NULL
               ORDER BY display_order""",
        )
        if domain_rows:
            criteria_lines = []
            for dr in domain_rows:
                criteria_lines.append(
                    f"- **{dr['name']}** (domain_slug: \"{dr['slug']}\"):\n"
                    f"  {dr['relevance_scope']}"
                )
            domain_criteria_text = "\n".join(criteria_lines)
        else:
            domain_criteria_text = "(No domain relevance criteria configured.)"

        # Substitute template variables: domain criteria (trusted) first,
        # article text (untrusted) second — prevents article text from
        # containing {domain_relevance_criteria} literal.
        user_prompt = user_prompt_template.replace(
            "{domain_relevance_criteria}", domain_criteria_text
        )
        user_prompt = user_prompt.replace("{article_text}", article_text)

        prompt_hash = compute_prompt_hash(system_prompt, user_prompt_template)

        # Create pending extraction row
        extraction_row = await fetchrow(
            """INSERT INTO article_extractions (
                   article_id, extraction_data, status,
                   stage1_schema_version, stage1_prompt_hash
               ) VALUES ($1::uuid, '{}'::jsonb, 'pending', $2, $3)
               RETURNING *""",
            article_id,
            STAGE1_SCHEMA_VERSION,
            prompt_hash,
        )
        extraction_id = str(extraction_row["id"])

        # Call LLM
        try:
            router = get_llm_router()
            effective_model = model_override or stage1_schema.get("model_name", "claude-sonnet-4-5")
            call_kwargs = dict(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model=effective_model,
                max_tokens=stage1_schema.get("max_tokens", 8000),
            )
            if provider_override:
                call_kwargs["provider_name"] = provider_override
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(router.call, **call_kwargs),
                    timeout=LLM_CALL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                from .llm_errors import LLMError, ErrorCategory
                raise LLMError(
                    category=ErrorCategory.TRANSIENT,
                    error_code="timeout",
                    message=f"Stage 1 LLM call timed out after {LLM_CALL_TIMEOUT_SECONDS}s",
                    provider=call_kwargs.get("provider_name", "anthropic"),
                    retryable=True,
                )

            extraction_data = self._parse_json(response.text, stop_reason=response.stop_reason)

            # If truncated, attempt adaptive retry with higher token limit
            truncated = False
            if response.stop_reason in ("max_tokens", "length"):
                original_max = call_kwargs.get("max_tokens", 8000)
                retry_max = min(original_max * 2, 16384)
                logger.warning(
                    "Stage 1 truncated (stop_reason=%s), retrying with max_tokens=%d and focused prompt",
                    response.stop_reason, retry_max,
                )
                focused_suffix = (
                    "\n\nIMPORTANT: Extract ONLY the 10 most significant incidents. "
                    "Prioritize those with named individuals, specific dates, and specific locations."
                )
                retry_kwargs = dict(call_kwargs)
                retry_kwargs["max_tokens"] = retry_max
                retry_kwargs["user_message"] = call_kwargs["user_message"] + focused_suffix
                try:
                    retry_response = await asyncio.wait_for(
                        asyncio.to_thread(router.call, **retry_kwargs),
                        timeout=LLM_CALL_TIMEOUT_SECONDS,
                    )
                    retry_data = self._parse_json(retry_response.text, stop_reason=retry_response.stop_reason)
                    # Use retry result if it has more events or entities
                    retry_events = len(retry_data.get("events", []))
                    orig_events = len(extraction_data.get("events", []))
                    if retry_events >= orig_events:
                        extraction_data = retry_data
                        response = retry_response
                        logger.info("Using retry result (%d events vs %d original)", retry_events, orig_events)
                    else:
                        truncated = True
                        logger.info("Keeping repaired original (%d events vs %d retry)", orig_events, retry_events)
                except Exception as retry_err:
                    logger.warning("Truncation retry failed, using repaired partial data: %s", retry_err)
                    truncated = True

                if truncated:
                    # Still using the repaired partial data from original response
                    pass

            # Compute summary stats
            entities = extraction_data.get("entities", {})
            entity_count = (
                len(entities.get("persons", []))
                + len(entities.get("organizations", []))
                + len(entities.get("locations", []))
            )
            event_count = len(extraction_data.get("events", []))
            overall_confidence = extraction_data.get("extraction_confidence")
            classification_hints = extraction_data.get("classification_hints", [])
            extraction_notes = extraction_data.get("extraction_notes", "")
            if truncated:
                extraction_notes = "[TRUNCATED] " + (extraction_notes or "")

            # Update row with results
            updated = await fetchrow(
                """UPDATE article_extractions SET
                       extraction_data = $2::jsonb,
                       classification_hints = $3::jsonb,
                       entity_count = $4,
                       event_count = $5,
                       overall_confidence = $6,
                       extraction_notes = $7,
                       provider = $8,
                       model = $9,
                       input_tokens = $10,
                       output_tokens = $11,
                       latency_ms = $12,
                       status = 'completed',
                       updated_at = NOW()
                   WHERE id = $1::uuid
                   RETURNING *""",
                extraction_id,
                extraction_data,
                classification_hints,
                entity_count,
                event_count,
                overall_confidence,
                extraction_notes,
                response.provider,
                response.model,
                response.input_tokens,
                response.output_tokens,
                response.latency_ms,
            )

            # Update article's latest_extraction_id
            await execute(
                """UPDATE ingested_articles
                   SET latest_extraction_id = $1::uuid,
                       extraction_pipeline = 'two_stage',
                       updated_at = NOW()
                   WHERE id = $2::uuid""",
                extraction_id,
                article_id,
            )

            return self._serialize(updated)

        except Exception as e:
            logger.exception("Stage 1 extraction failed for article %s", article_id)
            await execute(
                """UPDATE article_extractions SET
                       status = 'failed', error_message = $2, updated_at = NOW()
                   WHERE id = $1::uuid""",
                extraction_id,
                str(e),
            )
            raise

    # -----------------------------------------------------------------------
    # Stage 2: Per-schema extraction
    # -----------------------------------------------------------------------

    async def run_stage2(
        self,
        article_extraction_id: str,
        schema_ids: Optional[List[str]] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run Stage 2 extraction against a completed Stage 1 extraction.

        If schema_ids is None, auto-selects schemas based on classification_hints.

        Args:
            article_extraction_id: UUID of the article_extractions row.
            schema_ids: Optional list of schema UUIDs to run.

        Returns:
            List of schema_extraction_results rows.
        """
        from backend.database import fetch, fetchrow

        # Load Stage 1 extraction
        extraction = await fetchrow(
            "SELECT * FROM article_extractions WHERE id = $1::uuid",
            article_extraction_id,
        )
        if not extraction:
            raise ValueError(f"Article extraction not found: {article_extraction_id}")
        if extraction["status"] != "completed":
            raise ValueError(f"Stage 1 extraction not completed (status: {extraction['status']})")

        article_id = str(extraction["article_id"])
        extraction_data = extraction["extraction_data"]
        if isinstance(extraction_data, str):
            extraction_data = json.loads(extraction_data)
        stage1_json = json.dumps(extraction_data, indent=2)

        # Get article text for Stage 2 (provided alongside IR)
        article = await fetchrow(
            "SELECT title, content FROM ingested_articles WHERE id = $1::uuid",
            article_id,
        )
        article_text = ""
        if article:
            title = article["title"] or ""
            content = article["content"] or ""
            article_text = f"{title}\n\n{content}".strip()

        # Determine which schemas to run
        if schema_ids:
            schemas = await fetch(
                """SELECT es.*, ec.slug as category_slug, ed.slug as domain_slug
                   FROM extraction_schemas es
                   LEFT JOIN event_categories ec ON es.category_id = ec.id
                   LEFT JOIN event_domains ed ON es.domain_id = ed.id
                   WHERE es.id = ANY($1::uuid[]) AND es.schema_type = 'stage2'""",
                schema_ids,
            )
        else:
            schemas = await self._auto_select_schemas(extraction_data)

        if not schemas:
            logger.info("No Stage 2 schemas matched for extraction %s", article_extraction_id)
            return []

        # Run Stage 2 extractions in parallel
        tasks = [
            self._run_single_stage2(
                article_extraction_id=article_extraction_id,
                article_id=article_id,
                schema=s,
                stage1_json=stage1_json,
                article_text=article_text,
                stage1_version=extraction["stage1_schema_version"],
                provider_override=provider_override,
                model_override=model_override,
            )
            for s in schemas
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Stage 2 extraction error: %s", r)
            else:
                output.append(r)
        return output

    async def _run_single_stage2(
        self,
        article_extraction_id: str,
        article_id: str,
        schema,
        stage1_json: str,
        article_text: str,
        stage1_version: int,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a single Stage 2 schema extraction."""
        from backend.database import fetchrow, execute
        from backend.services.llm_provider import get_llm_router

        schema_id = str(schema["id"])

        # Build prompt
        system_prompt = schema["system_prompt"]
        user_prompt = schema["user_prompt_template"]
        user_prompt = user_prompt.replace("{stage1_output}", stage1_json)
        user_prompt = user_prompt.replace("{article_text}", article_text)
        used_original_text = "{article_text}" in schema["user_prompt_template"]

        # Upsert pending row (unique on extraction+schema)
        result_row = await fetchrow(
            """INSERT INTO schema_extraction_results (
                   article_extraction_id, schema_id, article_id,
                   extracted_data, status, stage1_version, used_original_text
               ) VALUES ($1::uuid, $2::uuid, $3::uuid, '{}'::jsonb, 'pending', $4, $5)
               ON CONFLICT (article_extraction_id, schema_id)
               DO UPDATE SET status = 'pending', error_message = NULL, updated_at = NOW()
               RETURNING *""",
            article_extraction_id,
            schema_id,
            article_id,
            stage1_version,
            used_original_text,
        )
        result_id = str(result_row["id"])

        try:
            router = get_llm_router()
            effective_model = model_override or schema.get("model_name", "claude-sonnet-4-5")
            call_kwargs = dict(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model=effective_model,
                max_tokens=schema.get("max_tokens", 4000),
            )
            if provider_override:
                call_kwargs["provider_name"] = provider_override
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(router.call, **call_kwargs),
                    timeout=LLM_CALL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                from .llm_errors import LLMError, ErrorCategory
                raise LLMError(
                    category=ErrorCategory.TRANSIENT,
                    error_code="timeout",
                    message=f"Stage 2 LLM call timed out after {LLM_CALL_TIMEOUT_SECONDS}s",
                    provider=call_kwargs.get("provider_name", "anthropic"),
                    retryable=True,
                )

            extracted_data = self._parse_json(response.text, stop_reason=response.stop_reason)

            # Validate and preserve source spans
            from backend.utils.span_validation import validate_spans as _validate_spans
            raw_spans = extracted_data.pop("source_spans", None)
            validated_spans = _validate_spans(raw_spans, article_text)

            # Validate against schema fields
            from backend.services.generic_extraction import get_generic_extraction_service
            svc = get_generic_extraction_service()
            schema_dict = svc._serialize_schema(schema)
            validated = svc._validate_extraction(extracted_data, schema_dict)
            if validated_spans:
                validated["source_spans"] = validated_spans
            confidence = svc._calculate_confidence(validated, schema_dict)

            # Check for validation errors
            validation_errors = []
            required = schema_dict.get("required_fields", [])
            for field in required:
                if validated.get(field) is None:
                    validation_errors.append({"field": field, "error": "required field missing"})

            updated = await fetchrow(
                """UPDATE schema_extraction_results SET
                       extracted_data = $2::jsonb,
                       confidence = $3,
                       validation_errors = $4::jsonb,
                       provider = $5,
                       model = $6,
                       input_tokens = $7,
                       output_tokens = $8,
                       latency_ms = $9,
                       status = 'completed',
                       updated_at = NOW()
                   WHERE id = $1::uuid
                   RETURNING *""",
                result_id,
                validated,
                confidence,
                validation_errors,
                response.provider,
                response.model,
                response.input_tokens,
                response.output_tokens,
                response.latency_ms,
            )
            result = self._serialize(updated)
            # Enrich with domain metadata for downstream selection/merge
            result["schema_name"] = schema.get("name", "")
            result["domain_slug"] = schema.get("domain_slug", "")
            result["category_slug"] = schema.get("category_slug", "")
            return result

        except Exception as e:
            logger.exception("Stage 2 extraction failed for schema %s", schema_id)
            await execute(
                """UPDATE schema_extraction_results SET
                       status = 'failed', error_message = $2, updated_at = NOW()
                   WHERE id = $1::uuid""",
                result_id,
                str(e),
            )
            raise

    async def _auto_select_schemas(self, extraction_data: Dict[str, Any]) -> list:
        """Select Stage 2 schemas based on classification_hints and domain relevance."""
        from backend.database import fetch

        hints = extraction_data.get("classification_hints", [])
        if not hints:
            return []

        # Filter hints above threshold
        qualified = [
            h for h in hints
            if h.get("confidence", 0) >= CLASSIFICATION_CONFIDENCE_THRESHOLD
        ]
        if not qualified:
            return []

        # --- Domain relevance gate ---
        # Build set of relevant domains from domain_relevance assessment.
        # If domain_relevance is absent (v1 extractions), skip the gate.
        domain_relevance = extraction_data.get("domain_relevance", [])
        if domain_relevance:
            relevant_domains = {
                dr["domain_slug"].replace("-", "_").lower()
                for dr in domain_relevance
                if dr.get("is_relevant") and dr.get("confidence", 0) >= 0.5
            }
            if not relevant_domains:
                logger.info(
                    "Domain relevance gate: no domains relevant — article is off-topic"
                )
                return []
            # Filter qualified hints to only relevant domains
            qualified = [
                h for h in qualified
                if h.get("domain_slug", "").replace("-", "_").lower()
                in relevant_domains
            ]
            if not qualified:
                logger.info(
                    "Domain relevance gate: no classification hints match relevant domains"
                )
                return []
        else:
            relevant_domains = None  # Legacy v1 extraction, skip gate

        # Build domain/category pairs
        pairs = [(h["domain_slug"], h["category_slug"]) for h in qualified]

        # Query matching stage2 schemas
        # We need to match on domain slug + category slug
        all_schemas = await fetch(
            """SELECT es.*, ec.slug as category_slug, ed.slug as domain_slug
               FROM extraction_schemas es
               JOIN event_categories ec ON es.category_id = ec.id
               JOIN event_domains ed ON es.domain_id = ed.id
               WHERE es.schema_type = 'stage2' AND es.is_active = TRUE"""
        )

        def normalize(slug: str) -> str:
            return slug.replace("-", "_").lower()

        normalized_pairs = [(normalize(d), normalize(c)) for d, c in pairs]

        # Collect all hint domain slugs (including domain extracted from combined slugs)
        hint_domains: set[str] = set()
        for nd, _nc in normalized_pairs:
            hint_domains.add(nd)

        matched = []
        matched_ids: set[str] = set()
        for schema in all_schemas:
            sid = str(schema["id"]) if "id" in schema else f"{schema['domain_slug']}/{schema['category_slug']}"
            sd = normalize(schema["domain_slug"])
            sc = normalize(schema["category_slug"])
            for nd, nc in normalized_pairs:
                # Exact match
                if sd == nd and sc == nc:
                    if sid not in matched_ids:
                        matched.append(schema)
                        matched_ids.add(sid)
                    break
                # LLM combined domain+category into domain_slug
                # e.g. hint "immigration_enforcement" matches domain="immigration" category="enforcement"
                combined = f"{sd}_{sc}"
                if combined == nd:
                    if sid not in matched_ids:
                        matched.append(schema)
                        matched_ids.add(sid)
                    break
                # Domain-only match: hint domain matches schema domain
                # (LLM may invent categories, but domain is usually correct)
                if sd == nd and sid not in matched_ids:
                    matched.append(schema)
                    matched_ids.add(sid)
                    break
                # Domain extracted from combined hint slug
                # e.g. hint "civil_rights_bystander_detention" — check if it starts with domain
                if nd.startswith(sd + "_") and sid not in matched_ids:
                    matched.append(schema)
                    matched_ids.add(sid)
                    break

        return matched

    # -----------------------------------------------------------------------
    # Full pipeline
    # -----------------------------------------------------------------------

    async def run_full_pipeline(
        self,
        article_id: str,
        force_stage1: bool = False,
        schema_ids: Optional[List[str]] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the complete two-stage pipeline: Stage 1 → Stage 2.

        Args:
            article_id: UUID of the article.
            force_stage1: Re-run Stage 1 even if cached.
            schema_ids: Optional schemas to run (auto-selects if None).
            provider_override: Override the LLM provider for all stages.
            model_override: Override the LLM model for all stages.

        Returns:
            Dict with stage1 result and stage2_results list.
        """
        stage1 = await self.run_stage1(
            article_id, force=force_stage1,
            provider_override=provider_override,
            model_override=model_override,
        )
        stage2_results = await self.run_stage2(
            stage1["id"], schema_ids=schema_ids,
            provider_override=provider_override,
            model_override=model_override,
        )
        return {
            "stage1": stage1,
            "stage2_results": stage2_results,
        }

    # -----------------------------------------------------------------------
    # Re-extraction
    # -----------------------------------------------------------------------

    async def reextract_stage2(
        self,
        article_extraction_id: str,
        schema_id: str,
    ) -> Dict[str, Any]:
        """
        Re-run a single Stage 2 extraction (supersedes previous result).
        """
        from backend.database import fetchrow, execute

        # Mark old result as superseded
        await execute(
            """UPDATE schema_extraction_results
               SET status = 'superseded', updated_at = NOW()
               WHERE article_extraction_id = $1::uuid AND schema_id = $2::uuid
                 AND status = 'completed'""",
            article_extraction_id,
            schema_id,
        )

        results = await self.run_stage2(article_extraction_id, schema_ids=[schema_id])
        if results:
            return results[0]
        raise ValueError("Stage 2 re-extraction produced no results")

    # -----------------------------------------------------------------------
    # Status / query
    # -----------------------------------------------------------------------

    async def get_extraction_status(self, article_id: str) -> Dict[str, Any]:
        """Get the extraction pipeline status for an article."""
        from backend.database import fetch, fetchrow

        article = await fetchrow(
            """SELECT id, title, extraction_pipeline, latest_extraction_id
               FROM ingested_articles WHERE id = $1::uuid""",
            article_id,
        )
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        # Get all Stage 1 extractions
        extractions = await fetch(
            """SELECT id, status, entity_count, event_count, overall_confidence,
                      classification_hints, created_at
               FROM article_extractions
               WHERE article_id = $1::uuid
               ORDER BY created_at DESC""",
            article_id,
        )

        # Get Stage 2 results for the latest extraction
        stage2_results = []
        if article["latest_extraction_id"]:
            stage2_results = await fetch(
                """SELECT ser.*, es.name as schema_name,
                          ed.slug as domain_slug, ec.slug as category_slug
                   FROM schema_extraction_results ser
                   JOIN extraction_schemas es ON ser.schema_id = es.id
                   LEFT JOIN event_domains ed ON es.domain_id = ed.id
                   LEFT JOIN event_categories ec ON es.category_id = ec.id
                   WHERE ser.article_extraction_id = $1::uuid
                   ORDER BY ser.created_at DESC""",
                str(article["latest_extraction_id"]),
            )

        return {
            "article_id": str(article["id"]),
            "article_title": article["title"],
            "extraction_pipeline": article["extraction_pipeline"],
            "latest_extraction_id": str(article["latest_extraction_id"]) if article["latest_extraction_id"] else None,
            "stage1_extractions": [self._serialize(e) for e in extractions],
            "stage2_results": [self._serialize(r) for r in stage2_results],
        }

    async def get_extraction_detail(self, extraction_id: str) -> Dict[str, Any]:
        """Get full Stage 1 extraction with linked Stage 2 results."""
        from backend.database import fetch, fetchrow

        extraction = await fetchrow(
            "SELECT * FROM article_extractions WHERE id = $1::uuid",
            extraction_id,
        )
        if not extraction:
            raise ValueError(f"Extraction not found: {extraction_id}")

        stage2 = await fetch(
            """SELECT ser.*, es.name as schema_name,
                      ed.slug as domain_slug, ec.slug as category_slug
               FROM schema_extraction_results ser
               JOIN extraction_schemas es ON ser.schema_id = es.id
               LEFT JOIN event_domains ed ON es.domain_id = ed.id
               LEFT JOIN event_categories ec ON es.category_id = ec.id
               WHERE ser.article_extraction_id = $1::uuid
               ORDER BY ser.created_at DESC""",
            extraction_id,
        )

        result = self._serialize(extraction)
        result["stage2_results"] = [self._serialize(r) for r in stage2]
        return result

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _parse_json(self, text: str, stop_reason: Optional[str] = None) -> Dict[str, Any]:
        """Parse LLM JSON response, handling markdown code blocks and truncation."""
        from .llm_errors import LLMError, ErrorCategory

        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # If truncated due to max_tokens, attempt JSON repair
            if stop_reason == "max_tokens" or stop_reason == "length":
                logger.warning("LLM response truncated (stop_reason=%s), attempting JSON repair", stop_reason)
                repaired = self._repair_truncated_json(cleaned)
                if repaired is not None:
                    return repaired
            logger.warning("Failed to parse LLM JSON: %s", cleaned[:200])
            raise LLMError(
                category=ErrorCategory.PARTIAL,
                error_code="json_parse_error",
                message=f"Failed to parse LLM response as JSON: {e}",
                provider="unknown",
                retryable=True,
                original=e,
            ) from e

    def _repair_truncated_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Attempt to repair truncated JSON by closing open structures.

        Tracks open braces, brackets, and strings, then appends the necessary
        closing characters to produce valid JSON. Falls back to truncating at
        the last comma and retrying recursively (once).
        """
        # Strategy 1: close open structures
        repaired = self._close_json_structures(text)
        if repaired is not None:
            try:
                result = json.loads(repaired)
                if isinstance(result, dict):
                    logger.info("JSON repair succeeded by closing open structures")
                    return result
            except json.JSONDecodeError:
                pass

        # Strategy 2: truncate to last comma and retry
        last_comma = text.rfind(',')
        if last_comma > 0:
            truncated = text[:last_comma]
            repaired = self._close_json_structures(truncated)
            if repaired is not None:
                try:
                    result = json.loads(repaired)
                    if isinstance(result, dict):
                        logger.info("JSON repair succeeded after truncating to last comma")
                        return result
                except json.JSONDecodeError:
                    pass

        logger.warning("JSON repair failed")
        return None

    def _close_json_structures(self, text: str) -> Optional[str]:
        """Close unclosed JSON structures (braces, brackets, strings)."""
        in_string = False
        escape_next = False
        stack: list[str] = []  # tracks opening chars: { or [

        for ch in text:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ('{', '['):
                stack.append(ch)
            elif ch == '}' and stack and stack[-1] == '{':
                stack.pop()
            elif ch == ']' and stack and stack[-1] == '[':
                stack.pop()

        # If we're inside a string, close it
        suffix = ''
        if in_string:
            suffix += '"'

        # Close structures in reverse order
        for opener in reversed(stack):
            if opener == '{':
                suffix += '}'
            elif opener == '[':
                suffix += ']'

        return text + suffix if stack or in_string else text

    def _serialize(self, row) -> Dict[str, Any]:
        """Serialize a database row to a JSON-safe dict."""
        if not row:
            return {}
        d = dict(row)
        for k, v in d.items():
            if hasattr(v, "hex"):
                d[k] = str(v)
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
        return d


# Singleton
_instance: Optional[TwoStageExtractionService] = None


def get_two_stage_service() -> TwoStageExtractionService:
    global _instance
    if _instance is None:
        _instance = TwoStageExtractionService()
    return _instance
