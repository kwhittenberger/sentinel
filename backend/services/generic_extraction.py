"""
Generic Extraction Service.

Schema-driven LLM extraction supporting multiple domains.
Uses extraction_schemas to determine prompts, field definitions,
validation rules, and confidence thresholds per domain/category.
"""

import json
import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)


class GenericExtractionService:
    """LLM extraction service with domain-specific schemas."""

    # --- Schema CRUD ---

    async def list_schemas(
        self,
        domain_id: Optional[str] = None,
        category_id: Optional[str] = None,
        is_active: Optional[bool] = True,
        page: int = 1,
        page_size: int = 50,
        schema_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        from backend.database import fetch, fetchrow

        conditions = []
        params: list = []
        idx = 1

        if domain_id:
            conditions.append(f"es.domain_id = ${idx}::uuid")
            params.append(domain_id)
            idx += 1
        if category_id:
            conditions.append(f"es.category_id = ${idx}::uuid")
            params.append(category_id)
            idx += 1
        if is_active is not None:
            conditions.append(f"es.is_active = ${idx}")
            params.append(is_active)
            idx += 1
        if schema_type:
            conditions.append(f"es.schema_type = ${idx}")
            params.append(schema_type)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        count_row = await fetchrow(
            f"SELECT COUNT(*) as total FROM extraction_schemas es {where}", *params
        )
        total = count_row["total"] if count_row else 0

        rows = await fetch(
            f"""SELECT es.*,
                       ed.name as domain_name, ed.slug as domain_slug,
                       ec.name as category_name, ec.slug as category_slug
                FROM extraction_schemas es
                LEFT JOIN event_domains ed ON es.domain_id = ed.id
                LEFT JOIN event_categories ec ON es.category_id = ec.id
                {where}
                ORDER BY es.name
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params,
            page_size,
            offset,
        )

        return {
            "schemas": [self._serialize_schema(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_schema(self, schema_id: str) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        row = await fetchrow(
            """SELECT es.*,
                      ed.name as domain_name, ed.slug as domain_slug,
                      ec.name as category_name, ec.slug as category_slug
               FROM extraction_schemas es
               LEFT JOIN event_domains ed ON es.domain_id = ed.id
               LEFT JOIN event_categories ec ON es.category_id = ec.id
               WHERE es.id = $1::uuid""",
            schema_id,
        )
        return self._serialize_schema(row) if row else None

    async def get_production_schema(
        self,
        domain_id: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        if category_id:
            row = await fetchrow(
                """SELECT * FROM extraction_schemas
                   WHERE category_id = $1::uuid AND is_production = TRUE AND is_active = TRUE
                   ORDER BY schema_version DESC LIMIT 1""",
                category_id,
            )
        elif domain_id:
            row = await fetchrow(
                """SELECT * FROM extraction_schemas
                   WHERE domain_id = $1::uuid AND category_id IS NULL
                     AND is_production = TRUE AND is_active = TRUE
                   ORDER BY schema_version DESC LIMIT 1""",
                domain_id,
            )
        else:
            return None
        return self._serialize_schema(row) if row else None

    async def create_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        from backend.database import fetchrow

        row = await fetchrow(
            """INSERT INTO extraction_schemas (
                   domain_id, category_id, name, description,
                   system_prompt, user_prompt_template, model_name,
                   temperature, max_tokens,
                   required_fields, optional_fields, field_definitions,
                   validation_rules, confidence_thresholds,
                   min_quality_threshold, git_commit_sha, previous_version_id
               ) VALUES (
                   $1::uuid, $2::uuid, $3, $4,
                   $5, $6, $7,
                   $8, $9,
                   $10::jsonb, $11::jsonb, $12::jsonb,
                   $13::jsonb, $14::jsonb,
                   $15, $16, $17::uuid
               ) RETURNING *""",
            data.get("domain_id"),
            data.get("category_id"),
            data["name"],
            data.get("description"),
            data["system_prompt"],
            data["user_prompt_template"],
            data.get("model_name", "claude-sonnet-4-5"),
            data.get("temperature", 0.7),
            data.get("max_tokens", 4000),
            json.dumps(data.get("required_fields", [])),
            json.dumps(data.get("optional_fields", [])),
            json.dumps(data.get("field_definitions", {})),
            json.dumps(data.get("validation_rules", {})),
            json.dumps(data.get("confidence_thresholds", {})),
            data.get("min_quality_threshold", 0.80),
            data.get("git_commit_sha"),
            data.get("previous_version_id"),
        )
        return self._serialize_schema(row)

    async def update_schema(self, schema_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        sets = []
        params: list = []
        idx = 1

        updatable = [
            "name", "description", "system_prompt", "user_prompt_template",
            "model_name", "temperature", "max_tokens", "min_quality_threshold",
            "git_commit_sha", "is_active",
        ]
        for field in updatable:
            if field in data:
                sets.append(f"{field} = ${idx}")
                params.append(data[field])
                idx += 1

        json_fields = [
            "required_fields", "optional_fields", "field_definitions",
            "validation_rules", "confidence_thresholds",
        ]
        for field in json_fields:
            if field in data:
                sets.append(f"{field} = ${idx}::jsonb")
                params.append(json.dumps(data[field]))
                idx += 1

        if not sets:
            return await self.get_schema(schema_id)

        sets.append("updated_at = NOW()")
        params.append(schema_id)

        row = await fetchrow(
            f"""UPDATE extraction_schemas SET {', '.join(sets)}
                WHERE id = ${idx}::uuid RETURNING *""",
            *params,
        )
        return self._serialize_schema(row) if row else None

    # --- Extraction ---

    async def extract_from_article(
        self,
        article_text: str,
        schema_id: Optional[str] = None,
        domain_id: Optional[str] = None,
        category_id: Optional[str] = None,
        stage1_output: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract structured data using the appropriate schema.

        Args:
            article_text: Raw article text.
            schema_id: Specific schema to use.
            domain_id: Domain to find production schema for.
            category_id: Category to find production schema for.
            stage1_output: Optional Stage 1 IR JSON string for two-stage extraction.
                           When provided, the user_prompt_template is rendered with both
                           {stage1_output} and {article_text} placeholders.
        """
        from backend.services.llm_provider import get_llm_router

        if schema_id:
            schema = await self.get_schema(schema_id)
        else:
            schema = await self.get_production_schema(domain_id, category_id)

        if not schema:
            raise ValueError("No extraction schema found for the specified domain/category")

        system_prompt = schema["system_prompt"]
        user_prompt = schema["user_prompt_template"].replace("{article_text}", article_text)
        if stage1_output is not None:
            user_prompt = user_prompt.replace("{stage1_output}", stage1_output)

        router = get_llm_router()
        response = await router.call(
            system_prompt=system_prompt,
            user_message=user_prompt,
            model=schema.get("model_name", "claude-sonnet-4-5"),
            max_tokens=schema.get("max_tokens", 4000),
        )

        extracted_data = self._parse_llm_response(response.text)
        validated_data = self._validate_extraction(extracted_data, schema)
        confidence = self._calculate_confidence(validated_data, schema)

        return {
            "success": True,
            "schema_id": schema["id"],
            "schema_name": schema["name"],
            "extracted_data": validated_data,
            "confidence": confidence,
            "provider": response.provider,
            "model": response.model,
            "usage": {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
            },
        }

    # --- Validation ---

    def _validate_extraction(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        """Validate extracted data against schema field definitions."""
        field_defs = schema.get("field_definitions", {})
        validated = {}

        for field, value in data.items():
            if field in field_defs:
                fd = field_defs[field]
                ftype = fd.get("type", "string")
                if ftype == "string" and value is not None and not isinstance(value, str):
                    value = str(value)
                elif ftype in ("number", "integer") and value is not None:
                    try:
                        value = float(value) if ftype == "number" else int(value)
                    except (ValueError, TypeError):
                        value = None
                elif ftype == "boolean" and value is not None:
                    value = bool(value)
            validated[field] = value

        return validated

    def _calculate_confidence(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
        llm_confidence: Optional[float] = None,
    ) -> float:
        """
        Calculate extraction confidence score using weighted field scoring,
        optional LLM confidence blending, and cross-field validation penalties.
        """
        required_fields = schema.get("required_fields", [])
        if not required_fields:
            return 0.5

        critical_fields = {
            "date", "event_date", "prosecutor_name", "defendant_name",
            "victim_name", "state", "incident_type", "charges",
        }
        total_weight = 0.0
        filled_weight = 0.0
        for field in required_fields:
            weight = 2.0 if field in critical_fields else 1.0
            total_weight += weight
            if data.get(field) is not None:
                filled_weight += weight

        field_completeness = filled_weight / total_weight if total_weight > 0 else 0

        optional_fields = schema.get("optional_fields", [])
        if optional_fields:
            filled_optional = sum(1 for f in optional_fields if data.get(f) is not None)
            optional_bonus = (filled_optional / len(optional_fields)) * 0.15
            field_completeness = min(1.0, field_completeness + optional_bonus)

        if llm_confidence is not None and 0 <= llm_confidence <= 1:
            blended = (llm_confidence * 0.6) + (field_completeness * 0.4)
        else:
            blended = field_completeness

        penalties = self._cross_field_validation(data, schema)
        blended = max(0.0, blended - penalties)

        return round(blended, 2)

    def _cross_field_validation(self, data: Dict[str, Any], schema: Dict[str, Any]) -> float:
        """Apply domain-specific cross-field validation rules. Returns penalty 0.0-0.3."""
        penalty = 0.0

        if "sentencing_date" in data and "filing_date" in data:
            if data["sentencing_date"] and data["filing_date"]:
                if data["sentencing_date"] < data["filing_date"]:
                    penalty += 0.1

        if "disposition" in data and "charges" in data:
            if data.get("disposition") == "convicted" and not data.get("charges"):
                penalty += 0.1

        return min(penalty, 0.3)

    # --- Quality Samples ---

    async def record_quality_sample(
        self,
        schema_id: str,
        article_id: str,
        extracted_data: Dict[str, Any],
        confidence: float,
    ) -> Dict[str, Any]:
        from backend.database import fetchrow

        row = await fetchrow(
            """INSERT INTO extraction_quality_samples
                   (schema_id, article_id, extracted_data, confidence)
               VALUES ($1::uuid, $2::uuid, $3::jsonb, $4)
               RETURNING *""",
            schema_id,
            article_id,
            json.dumps(extracted_data),
            confidence,
        )
        return self._serialize_quality_sample(row)

    async def review_quality_sample(
        self,
        sample_id: str,
        review_passed: bool,
        corrections: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        row = await fetchrow(
            """UPDATE extraction_quality_samples SET
                   human_reviewed = TRUE,
                   review_passed = $2,
                   review_corrections = $3::jsonb,
                   reviewed_at = NOW()
               WHERE id = $1::uuid RETURNING *""",
            sample_id,
            review_passed,
            json.dumps(corrections) if corrections else None,
        )
        return self._serialize_quality_sample(row) if row else None

    async def get_production_quality(
        self, schema_id: str, sample_size: int = 100
    ) -> Dict[str, Any]:
        from backend.database import fetch

        samples = await fetch(
            """SELECT * FROM extraction_quality_samples
               WHERE schema_id = $1::uuid AND human_reviewed = TRUE
               ORDER BY reviewed_at DESC LIMIT $2""",
            schema_id,
            sample_size,
        )

        if not samples:
            return {"schema_id": schema_id, "sample_count": 0, "error": "No reviewed samples"}

        passed = sum(1 for s in samples if s["review_passed"])
        total = len(samples)
        accuracy = passed / total

        recent = samples[:20]
        recent_acc = sum(1 for s in recent if s["review_passed"]) / len(recent) if recent else 0
        degraded = recent_acc < accuracy * 0.85

        return {
            "schema_id": schema_id,
            "sample_count": total,
            "passed": passed,
            "failed": total - passed,
            "overall_accuracy": round(accuracy, 3),
            "recent_accuracy": round(recent_acc, 3),
            "quality_degraded": degraded,
            "recommendation": "ROLLBACK" if degraded else "OK",
        }

    # --- Helpers ---

    def _parse_llm_response(self, text: str) -> Dict[str, Any]:
        """Parse LLM JSON response, handling markdown code blocks."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # drop ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON: %s", cleaned[:200])
            return {}

    def _serialize_schema(self, row) -> Dict[str, Any]:
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

    def _serialize_quality_sample(self, row) -> Dict[str, Any]:
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


_instance: Optional[GenericExtractionService] = None


def get_generic_extraction_service() -> GenericExtractionService:
    global _instance
    if _instance is None:
        _instance = GenericExtractionService()
    return _instance
