"""
Prompt Testing Service.

Automated testing and validation for LLM extraction prompts.
Supports golden dataset test suites, per-case metrics (precision/recall/F1),
deploy-to-production workflow, rollback, and production quality monitoring.
"""

import json
import logging
import time
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class TestCaseResult:
    """Result of testing extraction on a single test case."""
    test_case_id: str
    passed: bool
    extracted_data: Dict[str, Any]
    expected_data: Dict[str, Any]
    field_matches: Dict[str, bool]
    precision: float
    recall: float
    f1_score: float
    errors: List[str] = field(default_factory=list)


class PromptTestingService:
    """Service for testing and validating extraction prompts."""

    # --- Test Datasets ---

    async def list_datasets(
        self,
        domain_id: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from backend.database import fetch

        conditions = []
        params: list = []
        idx = 1

        if domain_id:
            conditions.append(f"d.domain_id = ${idx}::uuid")
            params.append(domain_id)
            idx += 1
        if category_id:
            conditions.append(f"d.category_id = ${idx}::uuid")
            params.append(category_id)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = await fetch(
            f"""SELECT d.*,
                       COUNT(tc.id) as case_count,
                       ed.name as domain_name,
                       ec.name as category_name
                FROM prompt_test_datasets d
                LEFT JOIN prompt_test_cases tc ON tc.dataset_id = d.id
                LEFT JOIN event_domains ed ON d.domain_id = ed.id
                LEFT JOIN event_categories ec ON d.category_id = ec.id
                {where}
                GROUP BY d.id, ed.name, ec.name
                ORDER BY d.name""",
            *params,
        )
        return [self._serialize(r) for r in rows]

    async def create_dataset(self, data: Dict[str, Any]) -> Dict[str, Any]:
        from backend.database import fetchrow

        row = await fetchrow(
            """INSERT INTO prompt_test_datasets (name, description, domain_id, category_id)
               VALUES ($1, $2, $3::uuid, $4::uuid) RETURNING *""",
            data["name"],
            data.get("description"),
            data.get("domain_id"),
            data.get("category_id"),
        )
        return self._serialize(row)

    async def get_dataset(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        row = await fetchrow(
            "SELECT * FROM prompt_test_datasets WHERE id = $1::uuid", dataset_id
        )
        return self._serialize(row) if row else None

    # --- Test Cases ---

    async def list_test_cases(self, dataset_id: str) -> List[Dict[str, Any]]:
        from backend.database import fetch

        rows = await fetch(
            """SELECT * FROM prompt_test_cases
               WHERE dataset_id = $1::uuid ORDER BY importance DESC, created_at""",
            dataset_id,
        )
        return [self._serialize(r) for r in rows]

    async def create_test_case(self, data: Dict[str, Any]) -> Dict[str, Any]:
        from backend.database import fetchrow

        row = await fetchrow(
            """INSERT INTO prompt_test_cases
                   (dataset_id, article_text, expected_extraction, importance, notes)
               VALUES ($1::uuid, $2, $3::jsonb, $4, $5) RETURNING *""",
            data["dataset_id"],
            data["article_text"],
            json.dumps(data["expected_extraction"]),
            data.get("importance", "medium"),
            data.get("notes"),
        )
        return self._serialize(row)

    # --- Test Runs ---

    async def list_test_runs(
        self,
        schema_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from backend.database import fetch

        conditions = []
        params: list = []
        idx = 1

        if schema_id:
            conditions.append(f"tr.schema_id = ${idx}::uuid")
            params.append(schema_id)
            idx += 1
        if dataset_id:
            conditions.append(f"tr.dataset_id = ${idx}::uuid")
            params.append(dataset_id)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = await fetch(
            f"""SELECT tr.*, es.name as schema_name, ptd.name as dataset_name
                FROM prompt_test_runs tr
                LEFT JOIN extraction_schemas es ON tr.schema_id = es.id
                LEFT JOIN prompt_test_datasets ptd ON tr.dataset_id = ptd.id
                {where}
                ORDER BY tr.started_at DESC LIMIT 50""",
            *params,
        )
        return [self._serialize(r) for r in rows]

    async def get_test_run(self, test_run_id: str) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        row = await fetchrow(
            """SELECT tr.*, es.name as schema_name, ptd.name as dataset_name
               FROM prompt_test_runs tr
               LEFT JOIN extraction_schemas es ON tr.schema_id = es.id
               LEFT JOIN prompt_test_datasets ptd ON tr.dataset_id = ptd.id
               WHERE tr.id = $1::uuid""",
            test_run_id,
        )
        return self._serialize(row) if row else None

    async def run_test_suite(
        self, schema_id: str, dataset_id: str
    ) -> Dict[str, Any]:
        """
        Execute the full test suite for an extraction schema against a golden dataset.
        Returns the test_run record with aggregate metrics.
        """
        from backend.database import fetch, fetchrow, execute
        from backend.services.llm_provider import get_llm_router

        schema = await fetchrow(
            "SELECT * FROM extraction_schemas WHERE id = $1::uuid", schema_id
        )
        test_cases = await fetch(
            "SELECT * FROM prompt_test_cases WHERE dataset_id = $1::uuid", dataset_id
        )

        if not schema:
            raise ValueError("Schema not found")
        if not test_cases:
            raise ValueError("No test cases in dataset")

        schema = dict(schema)

        # Create test run record
        run_row = await fetchrow(
            """INSERT INTO prompt_test_runs (schema_id, dataset_id, total_cases, status)
               VALUES ($1::uuid, $2::uuid, $3, 'running') RETURNING *""",
            schema_id,
            dataset_id,
            len(test_cases),
        )
        test_run_id = str(run_row["id"])

        results: List[TestCaseResult] = []
        total_input_tokens = 0
        total_output_tokens = 0
        router = get_llm_router()

        for tc in test_cases:
            tc = dict(tc)
            result = await self._test_single_case(schema, tc, router)
            results.append(result)

        passed_cases = sum(1 for r in results if r.passed)
        failed_cases = len(results) - passed_cases

        avg_precision = sum(r.precision for r in results) / len(results) if results else 0
        avg_recall = sum(r.recall for r in results) / len(results) if results else 0
        avg_f1 = sum(r.f1_score for r in results) / len(results) if results else 0

        min_threshold = float(schema.get("min_quality_threshold", 0.80))
        status = "passed" if avg_f1 >= min_threshold else "failed"

        await execute(
            """UPDATE prompt_test_runs SET
                   completed_at = NOW(),
                   status = $2,
                   passed_cases = $3,
                   failed_cases = $4,
                   precision = $5,
                   recall = $6,
                   f1_score = $7,
                   total_input_tokens = $8,
                   total_output_tokens = $9,
                   results = $10::jsonb
               WHERE id = $1::uuid""",
            test_run_id,
            status,
            passed_cases,
            failed_cases,
            avg_precision,
            avg_recall,
            avg_f1,
            total_input_tokens,
            total_output_tokens,
            json.dumps([asdict(r) for r in results]),
        )

        # Update schema quality metrics
        await execute(
            """UPDATE extraction_schemas SET
                   quality_metrics = jsonb_build_object(
                       'precision', $2,
                       'recall', $3,
                       'f1_score', $4,
                       'last_tested', NOW()::text,
                       'test_run_id', $5
                   ),
                   updated_at = NOW()
               WHERE id = $1::uuid""",
            schema_id,
            avg_precision,
            avg_recall,
            avg_f1,
            test_run_id,
        )

        return await self.get_test_run(test_run_id)

    async def _test_single_case(
        self, schema: Dict[str, Any], test_case: Dict[str, Any], router
    ) -> TestCaseResult:
        """Test extraction on a single test case."""
        system_prompt = schema["system_prompt"]
        user_prompt = schema["user_prompt_template"].replace(
            "{article_text}", test_case["article_text"]
        )

        try:
            response = await router.call(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model=schema.get("model_name", "claude-sonnet-4-5"),
                max_tokens=schema.get("max_tokens", 4000),
            )
            extracted_data = self._parse_llm_response(response.text)
        except Exception as e:
            logger.error("LLM call failed for test case %s: %s", test_case["id"], e)
            extracted_data = {}

        expected_data = test_case["expected_extraction"]
        if isinstance(expected_data, str):
            expected_data = json.loads(expected_data)

        required_fields = schema.get("required_fields", [])
        if isinstance(required_fields, str):
            required_fields = json.loads(required_fields)
        optional_fields = schema.get("optional_fields", [])
        if isinstance(optional_fields, str):
            optional_fields = json.loads(optional_fields)

        all_fields = set(required_fields + optional_fields)

        field_matches = {}
        for f in all_fields:
            expected_val = expected_data.get(f)
            extracted_val = extracted_data.get(f)
            field_matches[f] = self._values_match(expected_val, extracted_val)

        true_positives = sum(1 for f in required_fields if field_matches.get(f, False))
        false_negatives = sum(1 for f in required_fields if not field_matches.get(f, False))
        false_positives = sum(1 for f in extracted_data if f not in expected_data)

        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives) > 0
            else 0.0
        )
        recall = (
            true_positives / (true_positives + false_negatives)
            if (true_positives + false_negatives) > 0
            else 0.0
        )
        f1_score = (
            2 * (precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        min_threshold = float(schema.get("min_quality_threshold", 0.80))
        passed = f1_score >= min_threshold

        errors = []
        for f in required_fields:
            if not field_matches.get(f, False):
                errors.append(
                    f"Required field '{f}' mismatch: "
                    f"expected={expected_data.get(f)}, got={extracted_data.get(f)}"
                )

        return TestCaseResult(
            test_case_id=str(test_case["id"]),
            passed=passed,
            extracted_data=extracted_data,
            expected_data=expected_data,
            field_matches=field_matches,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1_score, 4),
            errors=errors,
        )

    def _values_match(self, expected, actual, tolerance: float = 0.1) -> bool:
        """Compare expected and actual values with fuzzy matching."""
        if expected == actual:
            return True
        if expected is None or actual is None:
            return False

        if isinstance(expected, str) and isinstance(actual, str):
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, expected.lower(), actual.lower()).ratio()
            return similarity >= 0.85

        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            return abs(expected - actual) <= tolerance

        if isinstance(expected, list) and isinstance(actual, list):
            if len(expected) != len(actual):
                return False
            return set(str(x) for x in expected) == set(str(x) for x in actual)

        return False

    # --- Deploy / Rollback ---

    async def deploy_to_production(
        self,
        schema_id: str,
        test_run_id: str,
        require_passing_tests: bool = True,
    ) -> Dict[str, Any]:
        """Deploy extraction schema to production after validation."""
        from backend.database import fetchrow, execute

        test_run = await fetchrow(
            "SELECT * FROM prompt_test_runs WHERE id = $1::uuid", test_run_id
        )
        if not test_run:
            raise ValueError("Test run not found")

        if require_passing_tests and test_run["status"] != "passed":
            raise ValueError(
                f"Test run failed: F1={float(test_run['f1_score'] or 0):.3f}, "
                f"passed {test_run['passed_cases']}/{test_run['total_cases']} cases"
            )

        schema = await fetchrow(
            "SELECT * FROM extraction_schemas WHERE id = $1::uuid", schema_id
        )
        if not schema:
            raise ValueError("Schema not found")

        min_threshold = float(schema["min_quality_threshold"])
        f1 = float(test_run["f1_score"] or 0)
        if f1 < min_threshold:
            raise ValueError(f"F1 score {f1:.3f} below threshold {min_threshold}")

        # Deactivate current production version for this domain/category
        await execute(
            """UPDATE extraction_schemas SET is_production = FALSE, updated_at = NOW()
               WHERE domain_id IS NOT DISTINCT FROM $1
                 AND category_id IS NOT DISTINCT FROM $2
                 AND is_production = TRUE AND is_active = TRUE
                 AND id != $3::uuid""",
            schema["domain_id"],
            schema["category_id"],
            schema_id,
        )

        # Activate new production version
        await execute(
            """UPDATE extraction_schemas SET
                   is_production = TRUE, deployed_at = NOW(), updated_at = NOW()
               WHERE id = $1::uuid""",
            schema_id,
        )

        return {"success": True, "schema_id": schema_id, "deployed": True}

    async def rollback_to_previous(
        self, schema_id: str, reason: str
    ) -> Dict[str, Any]:
        """Rollback to previous schema version."""
        from backend.database import fetchrow, execute

        schema = await fetchrow(
            "SELECT * FROM extraction_schemas WHERE id = $1::uuid", schema_id
        )
        if not schema:
            raise ValueError("Schema not found")
        if not schema["previous_version_id"]:
            raise ValueError("No previous version to rollback to")

        prev_id = str(schema["previous_version_id"])

        await execute(
            """UPDATE extraction_schemas SET
                   is_production = FALSE, rollback_reason = $2, updated_at = NOW()
               WHERE id = $1::uuid""",
            schema_id,
            reason,
        )

        await execute(
            """UPDATE extraction_schemas SET
                   is_production = TRUE, deployed_at = NOW(), updated_at = NOW()
               WHERE id = $1::uuid""",
            prev_id,
        )

        return {"success": True, "rolled_back_from": schema_id, "restored_version": prev_id}

    # --- Helpers ---

    def _parse_llm_response(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response: %s", cleaned[:200])
            return {}

    def _serialize(self, row) -> Dict[str, Any]:
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


_instance: Optional[PromptTestingService] = None


def get_prompt_testing_service() -> PromptTestingService:
    global _instance
    if _instance is None:
        _instance = PromptTestingService()
    return _instance
