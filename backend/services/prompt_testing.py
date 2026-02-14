"""
Prompt Testing Service.

Automated testing and validation for LLM extraction prompts.
Supports golden dataset test suites, per-case metrics (precision/recall/F1),
deploy-to-production workflow, rollback, and production quality monitoring.
"""

import asyncio
import json
import logging
import math
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
            data["expected_extraction"],
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
        self,
        schema_id: str,
        dataset_id: str,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        comparison_id: Optional[str] = None,
        iteration_number: Optional[int] = None,
        config_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute the full test suite for an extraction schema against a golden dataset.
        Optionally override the provider/model for A/B comparison testing.
        When called as part of a comparison, comparison_id/iteration_number/config_label
        are set to link the run back to the parent comparison.
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

        # Resolve effective provider/model
        effective_provider = provider_name or "anthropic"
        effective_model = model_name or schema.get("model_name", "claude-sonnet-4-20250514")

        # Create test run record with provider info and optional comparison link
        run_row = await fetchrow(
            """INSERT INTO prompt_test_runs
                   (schema_id, dataset_id, total_cases, status, provider_name, model_name,
                    comparison_id, iteration_number, config_label)
               VALUES ($1::uuid, $2::uuid, $3, 'running', $4, $5,
                       $6::uuid, $7, $8) RETURNING *""",
            schema_id,
            dataset_id,
            len(test_cases),
            effective_provider,
            effective_model,
            comparison_id,
            iteration_number,
            config_label,
        )
        test_run_id = str(run_row["id"])

        results: List[TestCaseResult] = []
        total_input_tokens = 0
        total_output_tokens = 0
        router = get_llm_router()

        for tc in test_cases:
            tc = dict(tc)
            result = await self._test_single_case(
                schema, tc, router,
                provider_name=effective_provider,
                model_name=effective_model,
            )
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
            [asdict(r) for r in results],
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
        self,
        schema: Dict[str, Any],
        test_case: Dict[str, Any],
        router,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> TestCaseResult:
        """Test extraction on a single test case, optionally overriding provider/model."""
        system_prompt = schema["system_prompt"]
        user_prompt = schema["user_prompt_template"].replace(
            "{article_text}", test_case["article_text"]
        )

        effective_model = model_name or schema.get("model_name", "claude-sonnet-4-20250514")
        effective_provider = provider_name or "anthropic"

        try:
            response = router.call(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model=effective_model,
                max_tokens=schema.get("max_tokens", 4000),
                provider_name=effective_provider,
                fallback_provider=None,  # No fallback during comparison tests
            )
            extracted_data = self._parse_llm_response(response.text)
        except Exception as e:
            logger.error("LLM call failed for test case %s (%s/%s): %s",
                         test_case["id"], effective_provider, effective_model, e)
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

    # --- Model Comparisons ---

    async def create_comparison(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new model comparison record."""
        from backend.database import fetchrow

        iterations = data.get("iterations_per_config", 3)
        total = iterations * 2  # A + B

        row = await fetchrow(
            """INSERT INTO prompt_test_comparisons
                   (schema_id, dataset_id,
                    config_a_provider, config_a_model,
                    config_b_provider, config_b_model,
                    iterations_per_config, total_iterations)
               VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8) RETURNING *""",
            data["schema_id"],
            data["dataset_id"],
            data["config_a_provider"],
            data["config_a_model"],
            data["config_b_provider"],
            data["config_b_model"],
            iterations,
            total,
        )
        return self._serialize(row)

    async def run_comparison(self, comparison_id: str) -> None:
        """
        Core executor for a model comparison.
        Loops through iterations, running Config A + Config B concurrently,
        updates progress, and computes summary stats on completion.
        """
        from backend.database import fetchrow, execute

        comp = await fetchrow(
            "SELECT * FROM prompt_test_comparisons WHERE id = $1::uuid",
            comparison_id,
        )
        if not comp:
            return
        comp = dict(comp)

        await execute(
            """UPDATE prompt_test_comparisons
               SET status = 'running', started_at = NOW(), message = 'Running iterations...'
               WHERE id = $1::uuid""",
            comparison_id,
        )

        iterations = comp["iterations_per_config"]
        a_run_ids: List[str] = []
        b_run_ids: List[str] = []

        try:
            for i in range(1, iterations + 1):
                # Run Config A and Config B concurrently for this iteration
                result_a, result_b = await asyncio.gather(
                    self._run_comparison_iteration(comp, "A", i, comparison_id),
                    self._run_comparison_iteration(comp, "B", i, comparison_id),
                )
                a_run_ids.append(result_a["id"])
                b_run_ids.append(result_b["id"])

                # Update progress (2 runs per iteration)
                progress = i * 2
                await execute(
                    """UPDATE prompt_test_comparisons
                       SET progress = $2, message = $3
                       WHERE id = $1::uuid""",
                    comparison_id,
                    progress,
                    f"Completed iteration {i}/{iterations}",
                )

            # Compute summary statistics
            await self._compute_comparison_summary(
                comparison_id, a_run_ids, b_run_ids, comp
            )

            await execute(
                """UPDATE prompt_test_comparisons
                   SET status = 'completed', completed_at = NOW(),
                       message = 'Comparison complete'
                   WHERE id = $1::uuid""",
                comparison_id,
            )
        except Exception as e:
            logger.error("Comparison %s failed: %s", comparison_id, e)
            await execute(
                """UPDATE prompt_test_comparisons
                   SET status = 'failed', completed_at = NOW(),
                       error = $2, message = 'Comparison failed'
                   WHERE id = $1::uuid""",
                comparison_id,
                str(e),
            )

    async def _run_comparison_iteration(
        self,
        comp: Dict[str, Any],
        label: str,
        iter_num: int,
        comparison_id: str,
    ) -> Dict[str, Any]:
        """Run a single iteration for one config (A or B) within a comparison."""
        provider = comp[f"config_{label.lower()}_provider"]
        model = comp[f"config_{label.lower()}_model"]

        return await self.run_test_suite(
            schema_id=str(comp["schema_id"]),
            dataset_id=str(comp["dataset_id"]),
            provider_name=provider,
            model_name=model,
            comparison_id=comparison_id,
            iteration_number=iter_num,
            config_label=label,
        )

    async def _compute_comparison_summary(
        self,
        comparison_id: str,
        a_ids: List[str],
        b_ids: List[str],
        comp: Dict[str, Any],
    ) -> None:
        """Compute aggregate statistics across all runs for each config."""
        from backend.database import fetch, execute

        def _stats_for_values(values: List[float]) -> Dict[str, float]:
            if not values:
                return {"mean": 0, "std": 0, "min": 0, "max": 0}
            n = len(values)
            mean = sum(values) / n
            variance = sum((x - mean) ** 2 for x in values) / n if n > 1 else 0
            return {
                "mean": round(mean, 4),
                "std": round(math.sqrt(variance), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }

        def _build_config_stats(
            runs: list, provider: str, model: str
        ) -> Dict[str, Any]:
            precisions = [float(r["precision"] or 0) for r in runs]
            recalls = [float(r["recall"] or 0) for r in runs]
            f1s = [float(r["f1_score"] or 0) for r in runs]
            durations = []
            for r in runs:
                if r["started_at"] and r["completed_at"]:
                    started = r["started_at"]
                    completed = r["completed_at"]
                    if isinstance(started, str):
                        started = datetime.fromisoformat(started)
                    if isinstance(completed, str):
                        completed = datetime.fromisoformat(completed)
                    ms = (completed - started).total_seconds() * 1000
                    durations.append(ms)

            total_passed = sum(1 for r in runs if r["status"] == "passed")
            total_tokens = sum(
                int(r.get("total_input_tokens") or 0) + int(r.get("total_output_tokens") or 0)
                for r in runs
            )

            return {
                "label": f"{provider} / {model}",
                "precision": _stats_for_values(precisions),
                "recall": _stats_for_values(recalls),
                "f1_score": _stats_for_values(f1s),
                "duration_ms": _stats_for_values(durations),
                "passed_rate": round(total_passed / len(runs), 3) if runs else 0,
                "total_tokens": total_tokens,
            }

        # Fetch all runs for each config
        a_runs = await fetch(
            """SELECT * FROM prompt_test_runs
               WHERE comparison_id = $1::uuid AND config_label = 'A'
               ORDER BY iteration_number""",
            comparison_id,
        )
        b_runs = await fetch(
            """SELECT * FROM prompt_test_runs
               WHERE comparison_id = $1::uuid AND config_label = 'B'
               ORDER BY iteration_number""",
            comparison_id,
        )

        a_stats = _build_config_stats(
            [dict(r) for r in a_runs],
            comp["config_a_provider"], comp["config_a_model"],
        )
        b_stats = _build_config_stats(
            [dict(r) for r in b_runs],
            comp["config_b_provider"], comp["config_b_model"],
        )

        a_f1_mean = a_stats["f1_score"]["mean"]
        b_f1_mean = b_stats["f1_score"]["mean"]
        f1_delta = round(abs(a_f1_mean - b_f1_mean), 4)
        winner = "config_a" if a_f1_mean >= b_f1_mean else "config_b"

        # Simple significance check: non-overlapping confidence intervals (mean ± 2*std)
        a_lower = a_f1_mean - 2 * a_stats["f1_score"]["std"]
        b_upper = b_f1_mean + 2 * b_stats["f1_score"]["std"]
        b_lower = b_f1_mean - 2 * b_stats["f1_score"]["std"]
        a_upper = a_f1_mean + 2 * a_stats["f1_score"]["std"]
        statistically_significant = (a_lower > b_upper) or (b_lower > a_upper)

        summary = {
            "config_a": a_stats,
            "config_b": b_stats,
            "winner": winner,
            "f1_delta": f1_delta,
            "statistically_significant": statistically_significant,
        }

        await execute(
            """UPDATE prompt_test_comparisons
               SET summary_stats = $2::jsonb
               WHERE id = $1::uuid""",
            comparison_id,
            summary,
        )

    async def list_comparisons(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List comparisons with schema/dataset names."""
        from backend.database import fetch

        rows = await fetch(
            """SELECT c.*, es.name as schema_name, ptd.name as dataset_name
               FROM prompt_test_comparisons c
               LEFT JOIN extraction_schemas es ON c.schema_id = es.id
               LEFT JOIN prompt_test_datasets ptd ON c.dataset_id = ptd.id
               ORDER BY c.created_at DESC
               LIMIT $1""",
            limit,
        )
        return [self._serialize(r) for r in rows]

    async def get_comparison(self, comparison_id: str) -> Optional[Dict[str, Any]]:
        """Get a single comparison with schema/dataset names."""
        from backend.database import fetchrow

        row = await fetchrow(
            """SELECT c.*, es.name as schema_name, ptd.name as dataset_name
               FROM prompt_test_comparisons c
               LEFT JOIN extraction_schemas es ON c.schema_id = es.id
               LEFT JOIN prompt_test_datasets ptd ON c.dataset_id = ptd.id
               WHERE c.id = $1::uuid""",
            comparison_id,
        )
        return self._serialize(row) if row else None

    async def get_comparison_runs(
        self, comparison_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get all runs for a comparison, grouped by config label."""
        from backend.database import fetch

        rows = await fetch(
            """SELECT tr.*, es.name as schema_name, ptd.name as dataset_name
               FROM prompt_test_runs tr
               LEFT JOIN extraction_schemas es ON tr.schema_id = es.id
               LEFT JOIN prompt_test_datasets ptd ON tr.dataset_id = ptd.id
               WHERE tr.comparison_id = $1::uuid
               ORDER BY tr.config_label, tr.iteration_number""",
            comparison_id,
        )
        config_a = []
        config_b = []
        for r in rows:
            serialized = self._serialize(r)
            if serialized.get("config_label") == "A":
                config_a.append(serialized)
            else:
                config_b.append(serialized)
        return {"config_a": config_a, "config_b": config_b}

    # --- Calibration Mode ---

    async def create_calibration_comparison(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a comparison in calibration mode (no dataset required)."""
        from backend.database import fetchrow

        article_count = data.get("article_count", 20)
        filters = data.get("article_filters", {})

        row = await fetchrow(
            """INSERT INTO prompt_test_comparisons
                   (schema_id, dataset_id,
                    config_a_provider, config_a_model,
                    config_b_provider, config_b_model,
                    iterations_per_config, total_iterations,
                    mode, article_count, article_filters, total_articles)
               VALUES ($1::uuid, NULL, $2, $3, $4, $5, 1, 0,
                       'calibration', $6, $7::jsonb, 0) RETURNING *""",
            data["schema_id"],
            data["config_a_provider"],
            data["config_a_model"],
            data["config_b_provider"],
            data["config_b_model"],
            article_count,
            filters,
        )
        return self._serialize(row)

    async def run_calibration(self, comparison_id: str) -> None:
        """
        Fetch articles matching filters, run both configs per article,
        store results in comparison_articles, update progress.
        """
        from backend.database import fetch, fetchrow, execute

        comp = await fetchrow(
            "SELECT * FROM prompt_test_comparisons WHERE id = $1::uuid",
            comparison_id,
        )
        if not comp:
            return
        comp = dict(comp)

        await execute(
            """UPDATE prompt_test_comparisons
               SET status = 'running', started_at = NOW(), message = 'Fetching articles...'
               WHERE id = $1::uuid""",
            comparison_id,
        )

        try:
            # Fetch schema for prompt templates
            schema = await fetchrow(
                "SELECT * FROM extraction_schemas WHERE id = $1::uuid",
                str(comp["schema_id"]),
            )
            if not schema:
                raise ValueError("Schema not found")
            schema = dict(schema)

            # Build article query from filters
            filters = comp.get("article_filters") or {}
            if isinstance(filters, str):
                filters = json.loads(filters)
            article_count = comp.get("article_count") or 20

            conditions = []
            params: list = []
            idx = 1

            status_filter = filters.get("status")
            if status_filter:
                conditions.append(f"status = ${idx}")
                params.append(status_filter)
                idx += 1

            min_date = filters.get("min_date")
            if min_date:
                conditions.append(f"published_date >= ${idx}::date")
                params.append(min_date)
                idx += 1

            max_date = filters.get("max_date")
            if max_date:
                conditions.append(f"published_date <= ${idx}::date")
                params.append(max_date)
                idx += 1

            # Require content to be present
            conditions.append("content IS NOT NULL")
            conditions.append("content != ''")

            where = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE content IS NOT NULL AND content != ''"

            params.append(article_count)
            articles = await fetch(
                f"""SELECT id, title, content, source_url, published_date
                    FROM ingested_articles
                    {where}
                    ORDER BY fetched_at DESC
                    LIMIT ${idx}""",
                *params,
            )

            if not articles:
                raise ValueError("No articles matched the filters")

            total = len(articles)
            await execute(
                """UPDATE prompt_test_comparisons
                   SET total_articles = $2, total_iterations = $2,
                       message = $3
                   WHERE id = $1::uuid""",
                comparison_id,
                total,
                f"Processing 0/{total} articles...",
            )

            from backend.services.llm_provider import get_llm_router
            router = get_llm_router()

            for i, article in enumerate(articles):
                article = dict(article)

                # Run both configs concurrently
                result_a, result_b = await asyncio.gather(
                    self._run_single_extraction(
                        schema, article, router,
                        comp["config_a_provider"], comp["config_a_model"],
                    ),
                    self._run_single_extraction(
                        schema, article, router,
                        comp["config_b_provider"], comp["config_b_model"],
                    ),
                )

                # Insert comparison_article row
                await execute(
                    """INSERT INTO comparison_articles
                           (comparison_id, article_id,
                            article_title, article_content, article_source_url, article_published_date,
                            config_a_extraction, config_a_confidence, config_a_duration_ms, config_a_error,
                            config_b_extraction, config_b_confidence, config_b_duration_ms, config_b_error)
                       VALUES ($1::uuid, $2::uuid,
                               $3, $4, $5, $6,
                               $7::jsonb, $8, $9, $10,
                               $11::jsonb, $12, $13, $14)""",
                    comparison_id,
                    str(article["id"]),
                    article.get("title"),
                    article.get("content"),
                    article.get("source_url"),
                    article.get("published_date"),
                    result_a["extraction"] if result_a["extraction"] else None,
                    result_a.get("confidence"),
                    result_a.get("duration_ms"),
                    result_a.get("error"),
                    result_b["extraction"] if result_b["extraction"] else None,
                    result_b.get("confidence"),
                    result_b.get("duration_ms"),
                    result_b.get("error"),
                )

                # Update progress
                progress = i + 1
                await execute(
                    """UPDATE prompt_test_comparisons
                       SET progress = $2, message = $3
                       WHERE id = $1::uuid""",
                    comparison_id,
                    progress,
                    f"Processing {progress}/{total} articles...",
                )

            await execute(
                """UPDATE prompt_test_comparisons
                   SET status = 'completed', completed_at = NOW(),
                       message = 'Calibration complete'
                   WHERE id = $1::uuid""",
                comparison_id,
            )
        except Exception as e:
            logger.error("Calibration %s failed: %s", comparison_id, e)
            await execute(
                """UPDATE prompt_test_comparisons
                   SET status = 'failed', completed_at = NOW(),
                       error = $2, message = 'Calibration failed'
                   WHERE id = $1::uuid""",
                comparison_id,
                str(e),
            )

    async def _run_single_extraction(
        self,
        schema: Dict[str, Any],
        article: Dict[str, Any],
        router,
        provider: str,
        model: str,
    ) -> Dict[str, Any]:
        """
        Build prompt from schema template + article content, call LLM,
        parse response, return {extraction, confidence, duration_ms, error}.
        """
        system_prompt = schema["system_prompt"]
        content = article.get("content") or ""
        user_prompt = schema["user_prompt_template"].replace(
            "{article_text}", content
        )

        start_ms = time.monotonic_ns() // 1_000_000
        try:
            response = router.call(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model=model,
                max_tokens=schema.get("max_tokens", 4000),
                provider_name=provider,
                fallback_provider=None,
            )
            duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms
            extraction = self._parse_llm_response(response.text)
            confidence = extraction.get("overall_confidence") or extraction.get("confidence")
            if isinstance(confidence, (int, float)):
                confidence = round(confidence / 100, 2) if confidence > 1 else round(confidence, 2)
            else:
                confidence = None
            return {
                "extraction": extraction,
                "confidence": confidence,
                "duration_ms": duration_ms,
                "error": None,
            }
        except Exception as e:
            duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms
            logger.error("Calibration extraction failed (%s/%s): %s", provider, model, e)
            return {
                "extraction": None,
                "confidence": None,
                "duration_ms": duration_ms,
                "error": str(e),
            }

    async def list_calibration_articles(
        self, comparison_id: str
    ) -> List[Dict[str, Any]]:
        """List all articles for a calibration comparison."""
        from backend.database import fetch

        rows = await fetch(
            """SELECT * FROM comparison_articles
               WHERE comparison_id = $1::uuid
               ORDER BY created_at""",
            comparison_id,
        )
        return [self._serialize(r) for r in rows]

    async def review_calibration_article(
        self,
        article_id: str,
        chosen_config: Optional[str],
        golden_extraction: Optional[Dict[str, Any]],
        notes: Optional[str],
    ) -> Dict[str, Any]:
        """Submit a review for one calibration article."""
        from backend.database import fetchrow, execute

        row = await fetchrow(
            "SELECT * FROM comparison_articles WHERE id = $1::uuid",
            article_id,
        )
        if not row:
            raise ValueError("Calibration article not found")

        was_already_reviewed = row["review_status"] == "reviewed"

        await execute(
            """UPDATE comparison_articles SET
                   review_status = 'reviewed',
                   chosen_config = $2,
                   golden_extraction = $3::jsonb,
                   reviewer_notes = $4,
                   reviewed_at = NOW()
               WHERE id = $1::uuid""",
            article_id,
            chosen_config,
            golden_extraction if golden_extraction else None,
            notes,
        )

        # Increment parent reviewed_count only for newly reviewed articles
        if not was_already_reviewed:
            await execute(
                """UPDATE prompt_test_comparisons
                   SET reviewed_count = reviewed_count + 1
                   WHERE id = $1::uuid""",
                str(row["comparison_id"]),
            )

        updated = await fetchrow(
            "SELECT * FROM comparison_articles WHERE id = $1::uuid",
            article_id,
        )
        return self._serialize(updated)

    async def save_calibration_as_dataset(
        self,
        comparison_id: str,
        name: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a prompt_test_dataset + insert prompt_test_cases
        from reviewed calibration articles, set output_dataset_id.
        """
        from backend.database import fetch, fetchrow, execute

        comp = await fetchrow(
            "SELECT * FROM prompt_test_comparisons WHERE id = $1::uuid",
            comparison_id,
        )
        if not comp:
            raise ValueError("Comparison not found")

        # Get reviewed articles with golden extractions
        reviewed = await fetch(
            """SELECT * FROM comparison_articles
               WHERE comparison_id = $1::uuid
                 AND review_status = 'reviewed'
                 AND golden_extraction IS NOT NULL
               ORDER BY created_at""",
            comparison_id,
        )

        if not reviewed:
            raise ValueError("No reviewed articles with golden extractions to save")

        # Create dataset
        dataset = await fetchrow(
            """INSERT INTO prompt_test_datasets (name, description, domain_id, category_id)
               VALUES ($1, $2, NULL, NULL) RETURNING *""",
            name,
            description,
        )
        dataset_id = str(dataset["id"])

        # Insert test cases from reviewed articles
        for article in reviewed:
            article = dict(article)
            golden = article["golden_extraction"]
            if isinstance(golden, str):
                golden = json.loads(golden)

            await execute(
                """INSERT INTO prompt_test_cases
                       (dataset_id, article_text, expected_extraction, importance, notes)
                   VALUES ($1::uuid, $2, $3::jsonb, 'medium', $4)""",
                dataset_id,
                article.get("article_content") or "",
                golden,
                article.get("reviewer_notes"),
            )

        # Link dataset to comparison
        await execute(
            """UPDATE prompt_test_comparisons
               SET output_dataset_id = $2::uuid
               WHERE id = $1::uuid""",
            comparison_id,
            dataset_id,
        )

        return self._serialize(dataset)

    # --- Pipeline Comparisons ---

    async def create_pipeline_comparison(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a comparison in pipeline mode (no schema, runs full two-stage pipeline)."""
        from backend.database import fetchrow

        article_count = data.get("article_count", 20)
        filters = data.get("article_filters", {})

        row = await fetchrow(
            """INSERT INTO prompt_test_comparisons
                   (schema_id, dataset_id,
                    config_a_provider, config_a_model,
                    config_b_provider, config_b_model,
                    iterations_per_config, total_iterations,
                    mode, article_count, article_filters, total_articles,
                    comparison_type)
               VALUES (NULL, NULL, $1, $2, $3, $4, 1, 0,
                       'calibration', $5, $6::jsonb, 0, 'pipeline') RETURNING *""",
            data["config_a_provider"],
            data["config_a_model"],
            data["config_b_provider"],
            data["config_b_model"],
            article_count,
            filters,
        )
        return self._serialize(row)

    async def run_pipeline_calibration(self, comparison_id: str) -> None:
        """
        Fetch articles matching filters, run the full two-stage pipeline
        with both configs per article, store results in comparison_articles.
        """
        from backend.database import fetch, fetchrow, execute
        from backend.services.two_stage_extraction import get_two_stage_service

        comp = await fetchrow(
            "SELECT * FROM prompt_test_comparisons WHERE id = $1::uuid",
            comparison_id,
        )
        if not comp:
            return
        comp = dict(comp)

        # Support reuse_comparison_id filter: pull article IDs from an existing comparison
        filters_raw = comp.get("article_filters") or {}
        if isinstance(filters_raw, str):
            filters_raw = json.loads(filters_raw)
        reuse_id = filters_raw.get("reuse_comparison_id")
        if reuse_id:
            existing_articles = await fetch(
                "SELECT article_id FROM comparison_articles WHERE comparison_id = $1::uuid",
                reuse_id,
            )
            if existing_articles:
                filters_raw["article_ids"] = [str(r["article_id"]) for r in existing_articles]
                # Remove reuse key so it doesn't interfere downstream
                del filters_raw["reuse_comparison_id"]
                comp["article_filters"] = filters_raw

        await execute(
            """UPDATE prompt_test_comparisons
               SET status = 'running', started_at = NOW(), message = 'Fetching articles...'
               WHERE id = $1::uuid""",
            comparison_id,
        )

        try:
            # Build article query from filters
            filters = comp.get("article_filters") or {}
            if isinstance(filters, str):
                filters = json.loads(filters)
            article_count = comp.get("article_count") or 20

            conditions = []
            params: list = []
            idx = 1

            article_ids = filters.get("article_ids")
            if article_ids:
                conditions.append(f"id = ANY(${idx}::uuid[])")
                params.append(article_ids)
                idx += 1

            status_filter = filters.get("status")
            if status_filter:
                conditions.append(f"status = ${idx}")
                params.append(status_filter)
                idx += 1

            min_date = filters.get("min_date")
            if min_date:
                conditions.append(f"published_date >= ${idx}::date")
                params.append(min_date)
                idx += 1

            max_date = filters.get("max_date")
            if max_date:
                conditions.append(f"published_date <= ${idx}::date")
                params.append(max_date)
                idx += 1

            conditions.append("content IS NOT NULL")
            conditions.append("content != ''")

            where = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE content IS NOT NULL AND content != ''"

            params.append(article_count)
            articles = await fetch(
                f"""SELECT id, title, content, source_url, published_date
                    FROM ingested_articles
                    {where}
                    ORDER BY fetched_at DESC
                    LIMIT ${idx}""",
                *params,
            )

            if not articles:
                raise ValueError("No articles matched the filters")

            total = len(articles)
            await execute(
                """UPDATE prompt_test_comparisons
                   SET total_articles = $2, total_iterations = $2,
                       message = $3
                   WHERE id = $1::uuid""",
                comparison_id,
                total,
                f"Processing 0/{total} articles...",
            )

            two_stage = get_two_stage_service()

            for i, article in enumerate(articles):
                article = dict(article)
                article_id = str(article["id"])

                # Run full pipeline with both configs concurrently
                result_a, result_b = await asyncio.gather(
                    self._run_pipeline_config(
                        two_stage, article_id,
                        comp["config_a_provider"], comp["config_a_model"],
                    ),
                    self._run_pipeline_config(
                        two_stage, article_id,
                        comp["config_b_provider"], comp["config_b_model"],
                    ),
                    return_exceptions=True,
                )

                # Handle exceptions from gather
                if isinstance(result_a, Exception):
                    logger.error("Pipeline config A failed for article %s: %s", article_id, result_a)
                    result_a = {"stage1": None, "stage2_results": [], "error": str(result_a),
                                "total_tokens": 0, "total_latency_ms": 0}
                if isinstance(result_b, Exception):
                    logger.error("Pipeline config B failed for article %s: %s", article_id, result_b)
                    result_b = {"stage1": None, "stage2_results": [], "error": str(result_b),
                                "total_tokens": 0, "total_latency_ms": 0}

                # Select best Stage 2 result using domain-priority + entity merge
                from backend.services.stage2_selector import select_and_merge_stage2
                merged_a = select_and_merge_stage2(result_a.get("stage2_results", []))
                merged_b = select_and_merge_stage2(result_b.get("stage2_results", []))
                best_a = merged_a
                best_b = merged_b

                await execute(
                    """INSERT INTO comparison_articles
                           (comparison_id, article_id,
                            article_title, article_content, article_source_url, article_published_date,
                            config_a_extraction, config_a_confidence, config_a_duration_ms, config_a_error,
                            config_b_extraction, config_b_confidence, config_b_duration_ms, config_b_error,
                            config_a_stage1, config_b_stage1,
                            config_a_stage2_results, config_b_stage2_results,
                            config_a_total_tokens, config_b_total_tokens,
                            config_a_total_latency_ms, config_b_total_latency_ms,
                            config_a_merge_info, config_b_merge_info)
                       VALUES ($1::uuid, $2::uuid,
                               $3, $4, $5, $6,
                               $7::jsonb, $8, $9, $10,
                               $11::jsonb, $12, $13, $14,
                               $15::jsonb, $16::jsonb,
                               $17::jsonb, $18::jsonb,
                               $19, $20, $21, $22,
                               $23::jsonb, $24::jsonb)""",
                    comparison_id,
                    article_id,
                    article.get("title"),
                    article.get("content"),
                    article.get("source_url"),
                    article.get("published_date"),
                    # Flat extraction: merged Stage 2 result
                    best_a["extracted_data"] if best_a else None,
                    best_a.get("confidence") if best_a else None,
                    result_a.get("total_latency_ms"),
                    result_a.get("error"),
                    best_b["extracted_data"] if best_b else None,
                    best_b.get("confidence") if best_b else None,
                    result_b.get("total_latency_ms"),
                    result_b.get("error"),
                    # Pipeline-specific columns
                    result_a.get("stage1") or None,
                    result_b.get("stage1") or None,
                    result_a.get("stage2_results", []),
                    result_b.get("stage2_results", []),
                    result_a.get("total_tokens"),
                    result_b.get("total_tokens"),
                    result_a.get("total_latency_ms"),
                    result_b.get("total_latency_ms"),
                    # Merge info
                    best_a.get("merge_info") if best_a else None,
                    best_b.get("merge_info") if best_b else None,
                )

                progress = i + 1
                await execute(
                    """UPDATE prompt_test_comparisons
                       SET progress = $2, message = $3
                       WHERE id = $1::uuid""",
                    comparison_id,
                    progress,
                    f"Processing {progress}/{total} articles...",
                )

            await execute(
                """UPDATE prompt_test_comparisons
                   SET status = 'completed', completed_at = NOW(),
                       message = 'Pipeline calibration complete'
                   WHERE id = $1::uuid""",
                comparison_id,
            )
        except Exception as e:
            logger.error("Pipeline calibration %s failed: %s", comparison_id, e)
            await execute(
                """UPDATE prompt_test_comparisons
                   SET status = 'failed', completed_at = NOW(),
                       error = $2, message = 'Pipeline calibration failed'
                   WHERE id = $1::uuid""",
                comparison_id,
                str(e),
            )

    async def _run_pipeline_config(
        self,
        two_stage_service,
        article_id: str,
        provider: str,
        model: str,
    ) -> Dict[str, Any]:
        """Run the full two-stage pipeline for one config, return structured results."""
        start_ms = time.monotonic_ns() // 1_000_000
        result = await two_stage_service.run_full_pipeline(
            article_id,
            force_stage1=True,
            provider_override=provider,
            model_override=model,
        )
        total_latency = (time.monotonic_ns() // 1_000_000) - start_ms

        # Compute total tokens across stages
        stage1 = result.get("stage1", {})
        total_tokens = (stage1.get("input_tokens") or 0) + (stage1.get("output_tokens") or 0)
        for s2 in result.get("stage2_results", []):
            total_tokens += (s2.get("input_tokens") or 0) + (s2.get("output_tokens") or 0)

        return {
            "stage1": stage1,
            "stage2_results": result.get("stage2_results", []),
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency,
            "error": None,
        }

    def _pick_best_stage2(self, stage2_results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Pick the Stage 2 result with the highest confidence."""
        if not stage2_results:
            return None
        best = None
        best_conf = -1.0
        for r in stage2_results:
            conf = r.get("confidence") or 0
            if isinstance(conf, (int, float)) and conf > best_conf:
                best_conf = conf
                best = r
        return best

    # --- Prompt Improvement Generation ---

    async def generate_prompt_improvement(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze per-field preferences between two config extractions and generate
        targeted prompt improvement suggestions using the LLM.
        """
        from backend.services.llm_provider import get_llm_router

        article_content = data.get("article_content", "")
        config_a_extraction = data.get("config_a_extraction", {})
        config_b_extraction = data.get("config_b_extraction", {})
        overall_preferred = data.get("overall_preferred_config", "A")
        field_preferences = data.get("field_preferences", {})
        current_system_prompt = data.get("current_system_prompt")
        current_user_prompt_template = data.get("current_user_prompt_template")

        # Identify fields where the non-overall config was preferred
        divergent_fields = {}
        for field_name, pref in field_preferences.items():
            if pref != overall_preferred:
                divergent_fields[field_name] = {
                    "preferred_config": pref,
                    "preferred_value": (config_b_extraction if pref == "B" else config_a_extraction).get(field_name),
                    "other_value": (config_a_extraction if pref == "B" else config_b_extraction).get(field_name),
                }

        if not divergent_fields:
            return {
                "analysis": "No divergent field preferences found. All fields were preferred from the same config.",
                "suggested_prompt_additions": [],
                "suggested_field_instructions": {},
            }

        # Build the analysis prompt
        divergent_summary = "\n".join(
            f"- Field '{f}': Preferred Config {d['preferred_config']} value = {json.dumps(d['preferred_value'])}; "
            f"Config {overall_preferred} value = {json.dumps(d['other_value'])}"
            for f, d in divergent_fields.items()
        )

        system_prompt = (
            "You are an expert at analyzing LLM extraction quality and improving prompts. "
            "You will be given an article, two extraction outputs (Config A and Config B), "
            "and information about which config did better for specific fields. "
            "Your job is to analyze why one config extracted certain fields better and suggest "
            "specific prompt improvements to capture those better extraction patterns."
        )

        system_prompt_section = f"## Current System Prompt\n{current_system_prompt}" if current_system_prompt else ""
        user_prompt_section = f"## Current User Prompt Template\n{current_user_prompt_template}" if current_user_prompt_template else ""

        user_prompt = f"""## Article Content (truncated to 3000 chars)
{article_content[:3000]}

## Config A Extraction
{json.dumps(config_a_extraction, indent=2)}

## Config B Extraction
{json.dumps(config_b_extraction, indent=2)}

## Overall Preferred Config: {overall_preferred}

## Fields Where the Other Config Was Preferred
{divergent_summary}

{system_prompt_section}
{user_prompt_section}

## Task
Analyze why Config {('B' if overall_preferred == 'A' else 'A')} extracted the divergent fields better, and suggest specific prompt additions or modifications.

Respond with valid JSON matching this schema:
{{
  "analysis": "A 2-3 sentence analysis of why the non-preferred config extracted certain fields better",
  "suggested_prompt_additions": [
    {{
      "target": "system_prompt" | "user_prompt_template",
      "addition": "The specific text to add or modify in the prompt",
      "rationale": "Why this change would improve extraction of these fields"
    }}
  ],
  "suggested_field_instructions": {{
    "field_name": "Specific extraction instruction for this field"
  }}
}}"""

        try:
            router = get_llm_router()
            response = router.call(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                provider_name="anthropic",
                fallback_provider=None,
            )
            result = self._parse_llm_response(response.text)
            # Ensure required keys exist
            if "analysis" not in result:
                result["analysis"] = "Analysis unavailable"
            if "suggested_prompt_additions" not in result:
                result["suggested_prompt_additions"] = []
            if "suggested_field_instructions" not in result:
                result["suggested_field_instructions"] = {}
            return result
        except Exception as e:
            logger.error("Prompt improvement generation failed: %s", e)
            return {
                "analysis": f"Failed to generate improvement: {str(e)}",
                "suggested_prompt_additions": [],
                "suggested_field_instructions": {},
            }

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
