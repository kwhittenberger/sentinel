"""
Extraction route module.
Extracted from main.py — pipeline stages/execute, enrichment, extraction schemas,
and two-stage extraction endpoints.
"""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException, Body
from typing import Optional, List

from backend.routes._shared import USE_DATABASE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Extraction"])


# =====================
# Pipeline Stages
# =====================

@router.get("/api/admin/pipeline/stages")
async def get_pipeline_stages():
    """Get all available pipeline stages."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service

    type_service = get_incident_type_service()
    stages = await type_service.get_pipeline_stages()

    return [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "description": s.description,
            "default_order": s.default_order,
            "is_active": s.is_active,
        }
        for s in stages
    ]


@router.post("/api/admin/pipeline/execute")
async def execute_pipeline(data: dict = Body(...)):
    """Execute the configurable pipeline on an article."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.pipeline_orchestrator import get_pipeline_orchestrator
    import uuid as uuid_mod

    orchestrator = get_pipeline_orchestrator()

    incident_type_id = uuid_mod.UUID(data["incident_type_id"]) if data.get("incident_type_id") else None
    skip_stages = data.get("skip_stages", [])

    result = await orchestrator.execute(
        article=data["article"],
        incident_type_id=incident_type_id,
        skip_stages=skip_stages,
    )

    return {
        "success": result.success,
        "article_id": result.article_id,
        "stages_completed": result.stages_completed,
        "final_decision": result.final_decision,
        "decision_reason": result.decision_reason,
        "total_duration_ms": result.total_duration_ms,
        "error": result.error,
        "context": {
            "detected_category": result.context.detected_category if result.context else None,
            "detected_actors": result.context.detected_actors if result.context else [],
            "detected_relations": result.context.detected_relations if result.context else [],
            "validation_errors": result.context.validation_errors if result.context else [],
        } if result.context else None,
    }


# =====================
# Enrichment Endpoints
# =====================

@router.get("/api/admin/enrichment/stats")
async def get_enrichment_stats():
    """Get missing field counts and enrichment summary."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.enrichment_service import get_enrichment_service
    service = get_enrichment_service()
    return await service.get_enrichment_stats()


@router.get("/api/admin/enrichment/candidates")
async def get_enrichment_candidates(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    target_fields: Optional[str] = Query(None, description="Comma-separated field names"),
):
    """Preview which incidents can be enriched."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.enrichment_service import get_enrichment_service

    fields = target_fields.split(",") if target_fields else None
    service = get_enrichment_service()
    candidates = await service.find_enrichment_candidates(limit=limit, offset=offset, target_fields=fields)
    total_count = await service.count_enrichment_candidates(target_fields=fields)

    # Serialize for JSON
    for c in candidates:
        c["id"] = str(c["id"])
        if c.get("date"):
            c["date"] = c["date"].isoformat()
        for num_field in ("latitude", "longitude"):
            if c.get(num_field) is not None:
                c[num_field] = float(c[num_field])

    return {"candidates": candidates, "total": len(candidates), "total_count": total_count}


@router.post("/api/admin/enrichment/run")
async def run_enrichment(
    strategy: str = Body("cross_incident", embed=True),
    limit: int = Body(100, embed=True),
    target_fields: Optional[List[str]] = Body(None, embed=True),
    auto_apply: Optional[bool] = Body(None, embed=True),
    min_confidence: float = Body(0.7, embed=True),
):
    """Start an enrichment job."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    if strategy not in ("cross_incident", "llm_reextract", "full"):
        raise HTTPException(status_code=400, detail=f"Invalid strategy: {strategy}")

    from backend.database import execute

    params = {
        "strategy": strategy,
        "limit": limit,
        "min_confidence": min_confidence,
    }
    if target_fields:
        params["target_fields"] = target_fields
    if auto_apply is not None:
        params["auto_apply"] = auto_apply

    job_id = uuid.uuid4()
    await execute("""
        INSERT INTO background_jobs (id, job_type, status, params, created_at)
        VALUES ($1, 'cross_reference_enrich', 'pending', $2, $3)
    """, job_id, params, datetime.now(timezone.utc))

    return {"success": True, "job_id": str(job_id)}


@router.get("/api/admin/enrichment/runs")
async def get_enrichment_runs(
    limit: int = Query(20, ge=1, le=100),
):
    """Get enrichment run history."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.enrichment_service import get_enrichment_service
    service = get_enrichment_service()
    runs = await service.get_run_history(limit=limit)
    return {"runs": runs, "total": len(runs)}


@router.get("/api/admin/enrichment/log/{incident_id}")
async def get_enrichment_log(incident_id: str, limit: int = Query(50, ge=1, le=200)):
    """Get enrichment audit log for an incident."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        iid = uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident ID format")

    from backend.services.enrichment_service import get_enrichment_service
    service = get_enrichment_service()
    entries = await service.get_incident_enrichment_log(iid, limit=limit)
    return {"entries": entries, "total": len(entries)}


@router.post("/api/admin/enrichment/revert/{log_id}")
async def revert_enrichment(log_id: str):
    """Revert a specific enrichment change."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        lid = uuid.UUID(log_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid log ID format")

    from backend.services.enrichment_service import get_enrichment_service
    service = get_enrichment_service()
    success = await service.revert_enrichment(lid)

    if not success:
        raise HTTPException(status_code=404, detail="Enrichment log entry not found or not applied")

    return {"success": True, "message": "Enrichment reverted"}


# =====================
# Extraction Schemas
# =====================

@router.get("/api/admin/extraction-schemas")
async def list_extraction_schemas(
    domain_id: Optional[str] = None,
    category_id: Optional[str] = None,
    is_active: Optional[bool] = True,
    schema_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.list_schemas(domain_id, category_id, is_active, page, page_size, schema_type=schema_type)


@router.get("/api/admin/extraction-schemas/{schema_id}")
async def get_extraction_schema(schema_id: str):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    result = await service.get_schema(schema_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schema not found")
    return result


@router.post("/api/admin/extraction-schemas")
async def create_extraction_schema(data: dict = Body(...)):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.create_schema(data)


@router.put("/api/admin/extraction-schemas/{schema_id}")
async def update_extraction_schema(schema_id: str, data: dict = Body(...)):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    result = await service.update_schema(schema_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Schema not found")
    return result


@router.post("/api/admin/extraction-schemas/{schema_id}/extract")
async def run_extraction(schema_id: str, data: dict = Body(...)):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.extract_from_article(
        article_text=data["article_text"],
        schema_id=schema_id,
    )


@router.get("/api/admin/extraction-schemas/{schema_id}/quality")
async def get_extraction_quality(schema_id: str, sample_size: int = 100):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.get_production_quality(schema_id, sample_size)


@router.post("/api/admin/extraction-schemas/{schema_id}/deploy")
async def deploy_schema(schema_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        return await service.deploy_to_production(
            schema_id, data["test_run_id"], data.get("require_passing_tests", True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/extraction-schemas/{schema_id}/rollback")
async def rollback_schema(schema_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        return await service.rollback_to_previous(schema_id, data["reason"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================
# Two-Stage Extraction
# =====================

@router.post("/api/admin/two-stage/extract-stage1")
async def two_stage_extract_stage1(data: dict = Body(...)):
    """Run Stage 1 comprehensive extraction on an article."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.run_stage1(
            article_id=data["article_id"],
            force=data.get("force", False),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/two-stage/extract-stage2")
async def two_stage_extract_stage2(data: dict = Body(...)):
    """Run Stage 2 schema extractions against a Stage 1 result."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return {
            "results": await service.run_stage2(
                article_extraction_id=data["article_extraction_id"],
                schema_ids=data.get("schema_ids"),
            )
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/two-stage/extract-full")
async def two_stage_extract_full(data: dict = Body(...)):
    """Run full two-stage pipeline (Stage 1 + Stage 2) on an article."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.run_full_pipeline(
            article_id=data["article_id"],
            force_stage1=data.get("force_stage1", False),
            schema_ids=data.get("schema_ids"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/two-stage/reextract")
async def two_stage_reextract(data: dict = Body(...)):
    """Re-run a single Stage 2 extraction without re-running Stage 1."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.reextract_stage2(
            article_extraction_id=data["article_extraction_id"],
            schema_id=data["schema_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/admin/two-stage/status/{article_id}")
async def two_stage_status(article_id: str):
    """Get extraction pipeline status for an article."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.get_extraction_status(article_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/admin/two-stage/extractions/{extraction_id}")
async def two_stage_extraction_detail(extraction_id: str):
    """Get full Stage 1 extraction with linked Stage 2 results."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.get_extraction_detail(extraction_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/admin/two-stage/batch-extract")
async def two_stage_batch_extract(data: dict = Body(...)):
    """Run two-stage pipeline with merge on a batch of pending articles.

    Body: { "limit": 50, "include_previously_failed": false }

    Includes circuit breaker: stops on permanent errors (credits exhausted,
    auth failure) and on 3 consecutive identical transient errors.
    """
    import asyncio
    import json
    import uuid as uuid_mod
    from datetime import datetime as dt, timezone
    from backend.services.two_stage_extraction import get_two_stage_service
    from backend.services.stage2_selector import select_and_merge_stage2, resolve_category_from_merge_info
    from backend.services.llm_errors import LLMError
    from backend.services.circuit_breaker import BatchCircuitBreaker
    from backend.services.auto_approval import get_auto_approval_service
    from backend.services.incident_creation_service import get_incident_creation_service

    limit = min(data.get("limit", 50), 200)
    include_previously_failed = data.get("include_previously_failed", False)
    provider_override = data.get("provider_override")
    model_override = data.get("model_override")
    service = get_two_stage_service()
    approval_service = get_auto_approval_service()
    incident_service = get_incident_creation_service()

    from backend.database import get_pool
    pool = await get_pool()

    # Fetch pending articles, excluding permanently-failed and 3x-failed
    if include_previously_failed:
        rows = await pool.fetch("""
            SELECT id, title, content, source_url, published_date
            FROM ingested_articles
            WHERE status = 'pending' AND content IS NOT NULL AND length(content) > 50
            ORDER BY published_date DESC NULLS LAST
            LIMIT $1
        """, limit)
    else:
        rows = await pool.fetch("""
            SELECT id, title, content, source_url, published_date
            FROM ingested_articles
            WHERE status = 'pending' AND content IS NOT NULL AND length(content) > 50
              AND (extraction_error_category IS NULL OR extraction_error_category != 'permanent')
              AND COALESCE(extraction_error_count, 0) < 3
            ORDER BY published_date DESC NULLS LAST
            LIMIT $1
        """, limit)

    results = []
    extracted = 0
    errors = 0
    skipped = 0
    auto_approved = 0
    auto_rejected = 0
    needs_review = 0
    breaker = BatchCircuitBreaker()
    approval_service.set_db_pool(pool)
    await approval_service.load_category_configs_from_db()

    for row in rows:
        article_id = str(row['id'])
        title = row['title'] or '(untitled)'

        # Check circuit breaker before each article
        if breaker.tripped:
            skipped += 1
            results.append({
                "id": article_id,
                "title": title[:80],
                "status": "skipped",
                "reason": "circuit_breaker_tripped",
            })
            continue

        try:
            # Run two-stage extraction
            pipeline_result = await service.run_full_pipeline(
                article_id,
                provider_override=provider_override,
                model_override=model_override,
            )

            # Merge stage2 results using domain-priority selector
            stage2_results = pipeline_result.get('stage2_results', [])
            merged = select_and_merge_stage2(stage2_results)

            merged_data = merged.get('extracted_data', {}) if merged else {}
            merge_info = merged.get('merge_info') if merged else None

            # Ensure merged_data is a dict, not a string (stage2 may return either)
            if isinstance(merged_data, str):
                merged_data = json.loads(merged_data)

            # Use the LLM's self-reported confidence from inside extracted_data,
            # NOT the schema-completeness score from select_and_merge_stage2.
            # The schema completeness is already stored on schema_extraction_results.
            confidence = float(merged_data.get('overall_confidence',
                              merged_data.get('confidence', 0)))

            # Round-trip through json.dumps(default=str) to handle non-serializable
            # types (UUID, datetime), then loads() back to a dict.  Pass the dict
            # to asyncpg — asyncpg's jsonb codec will call json.dumps once.
            # Passing a pre-serialized string would cause double-serialization.
            clean_data = json.loads(json.dumps(merged_data, default=str))

            # Persist merge_info so schema identity survives to approval time
            if merge_info:
                clean_data["merge_info"] = json.loads(json.dumps(merge_info, default=str))

            # Update ingested_articles with merged extraction + clear errors
            await pool.execute("""
                UPDATE ingested_articles
                SET extracted_data = $2::jsonb,
                    extraction_confidence = $3,
                    extracted_at = NOW(),
                    status = 'in_review',
                    extraction_pipeline = 'two_stage',
                    extraction_error_count = 0,
                    last_extraction_error = NULL,
                    last_extraction_error_at = NULL,
                    extraction_error_category = NULL,
                    updated_at = NOW()
                WHERE id = $1
            """, row['id'], clean_data, confidence)

            breaker.record_success()
            extracted += 1

            # --- Auto-approval evaluation ---
            article_dict = {
                "id": article_id,
                "title": row["title"],
                "content": row["content"],
                "source_url": row["source_url"],
                "published_date": str(row["published_date"]) if row.get("published_date") else None,
            }

            # Determine category from merge_info (schema-aware) or extracted_data fallback
            row_category = resolve_category_from_merge_info(merge_info, merged_data)

            decision = await approval_service.evaluate_async(
                article_dict, merged_data, category=row_category
            )

            result_item = {
                "id": article_id,
                "title": title[:80],
                "status": "extracted",
                "confidence": confidence,
                "stage2_count": len(stage2_results),
                "merged_schemas": len(merge_info.get('sources', [])) if merge_info else 0,
                "primary_domain": merge_info.get('sources', [{}])[0].get('domain_slug', '') if merge_info and merge_info.get('sources') else '',
                "approval_decision": decision.decision,
                "approval_reason": decision.reason,
                "incident_id": None,
            }

            if decision.decision == "auto_approve":
                try:
                    inc_result = await incident_service.create_incident_from_extraction(
                        extracted_data=merged_data,
                        article=article_dict,
                        category=row_category,
                        merge_info=merge_info,
                    )
                    incident_id = inc_result["incident_id"]
                    await pool.execute("""
                        UPDATE ingested_articles
                        SET status = 'approved', incident_id = $1, reviewed_at = $2
                        WHERE id = $3
                    """, uuid_mod.UUID(incident_id), dt.now(timezone.utc), row['id'])
                    result_item["status"] = "auto_approved"
                    result_item["incident_id"] = incident_id
                    auto_approved += 1
                except Exception as e:
                    logger.error("Auto-approve failed for article %s, leaving in_review: %s", article_id, e)
                    needs_review += 1
                    result_item["approval_decision"] = "needs_review"
                    result_item["approval_reason"] = f"Auto-approve failed: {e}"
            elif decision.decision == "auto_reject":
                await pool.execute("""
                    UPDATE ingested_articles
                    SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
                    WHERE id = $3
                """, decision.reason[:500], dt.now(timezone.utc), row['id'])
                result_item["status"] = "auto_rejected"
                auto_rejected += 1
            else:
                needs_review += 1

            results.append(result_item)

            # Rate limit: 2s between articles to avoid API throttling
            await asyncio.sleep(2)

        except LLMError as e:
            errors += 1

            # Record error on the article
            await pool.execute("""
                UPDATE ingested_articles
                SET extraction_error_count = COALESCE(extraction_error_count, 0) + 1,
                    last_extraction_error = $2,
                    last_extraction_error_at = NOW(),
                    extraction_error_category = $3,
                    extraction_pipeline = 'two_stage',
                    updated_at = NOW()
                WHERE id = $1
            """, row['id'], str(e)[:500], e.category.value)

            # Feed to circuit breaker
            just_tripped = breaker.record_error(e, article_id)

            results.append({
                "id": article_id,
                "title": title[:80],
                "status": "error",
                "error": str(e)[:200],
                "error_category": e.category.value,
                "error_code": e.error_code,
            })
            logger.error("LLM error extracting article %s: %s", article_id, e)

            if just_tripped:
                logger.warning("Circuit breaker tripped — skipping remaining articles")
            else:
                await asyncio.sleep(1)

        except Exception as e:
            errors += 1
            # Non-LLM error — record but don't trip breaker
            await pool.execute("""
                UPDATE ingested_articles
                SET extraction_error_count = COALESCE(extraction_error_count, 0) + 1,
                    last_extraction_error = $2,
                    last_extraction_error_at = NOW(),
                    extraction_pipeline = 'two_stage',
                    updated_at = NOW()
                WHERE id = $1
            """, row['id'], str(e)[:500])
            results.append({
                "id": article_id,
                "title": title[:80],
                "status": "error",
                "error": str(e)[:200],
            })
            logger.exception("Error extracting article %s: %s", article_id, e)
            await asyncio.sleep(1)

    return {
        "success": True,
        "total_pending": await pool.fetchval("SELECT count(*) FROM ingested_articles WHERE status = 'pending'"),
        "processed": len(rows),
        "extracted": extracted,
        "auto_approved": auto_approved,
        "auto_rejected": auto_rejected,
        "needs_review": needs_review,
        "errors": errors,
        "skipped": skipped,
        "circuit_breaker": breaker.summary(),
        "items": results,
    }
