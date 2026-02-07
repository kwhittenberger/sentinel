# Lessons Learned — Sentinel

Patterns discovered during the codebase audit (2026-02-07).

---

## Architecture Patterns

1. **Three data models coexist:** `persons` (legacy), `actors` (event-centric), `cases` (legal). All three are in use simultaneously. Any person-related code must check which model is expected in context. `actors` is preferred for new code.

2. **Two extraction pipelines:** Legacy (one-shot via `ingested_articles.extracted_data`) and two-stage (via `article_extractions` + `schema_extraction_results`). Check `ingested_articles.extraction_pipeline` column to determine which was used.

3. **Pipeline stages are pluggable:** 11 stages defined in `pipeline_stages` table, configurable per incident type via `incident_type_pipeline_config`. Don't hardcode pipeline behavior.

4. **Materialized views need manual refresh:** `recidivism_analysis` and `prosecutor_stats` have refresh config in `materialized_view_refresh_config` but no Celery task reads it. They go stale.

## Code Quality Patterns

5. **`datetime.utcnow()` everywhere:** 45+ occurrences. When touching any file that uses it, replace with `datetime.now(timezone.utc)`. Don't fix unrelated files while doing other work.

6. **`api.ts` lacks error handling:** Only 5 of 66 functions check `response.ok`. Any new API function MUST check response status before calling `.json()`.

7. **Only HeatmapLayer has an error boundary.** All other component trees (App, AdminPanel) will crash the entire app on any child error. Use HeatmapLayer's pattern as reference.

8. **JSON extraction from markdown is duplicated 4+ times.** If you need to extract JSON from LLM response, check if a helper exists before writing another copy.

9. **Broad `except Exception` in job_executor.py and settings.py.** When fixing errors in these files, narrow the exception types caught.

## Database Patterns

10. **schema.sql vs migrations can drift.** Tables defined in both places (prompt_executions, task_metrics). Always check migrations for the authoritative column list.

11. **`event_relationships.case_id` has no FK constraint.** Comment says "FK added when cases table exists" but cases table exists since migration 013 and FK was never added.

12. **String-based FK on `relationship_types.name`.** VARCHAR(50) used as FK. Fragile — don't rename relationship types without updating all references.

13. **Circular FK:** `ingested_articles` ↔ `article_extractions`. Must null out `latest_extraction_id` before deleting articles. Migration 022 demonstrates the pattern.
