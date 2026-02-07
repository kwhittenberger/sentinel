"""
Curation queue and pipeline management routes.

Extracted from main.py — admin status, legacy pipeline triggers,
tiered queue management, batch processing, article approval/rejection,
and pipeline reset utilities.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException, Body, Depends

from backend.routes._shared import (
    USE_DATABASE,
    INCIDENT_FILES,
    INCIDENTS_DIR,
    clear_incidents_cache,
    load_incidents,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Curation"])


# =====================
# Admin API Endpoints
# =====================

@router.get("/api/admin/status")
def get_admin_status():
    """Get current data status for admin panel."""
    from data_pipeline.pipeline import DataPipeline, run_pipeline
    from data_pipeline.config import SOURCES

    clear_incidents_cache()
    incidents = load_incidents()

    # Count by tier
    by_tier = {}
    for inc in incidents:
        t = inc.get('tier', 0)
        by_tier[t] = by_tier.get(t, 0) + 1

    # Count by source file
    by_source = {}
    for inc in incidents:
        source = inc.get('source_file', 'unknown')
        by_source[source] = by_source.get(source, 0) + 1

    # Get available sources from pipeline config
    available_sources = []
    for name, config in SOURCES.items():
        available_sources.append({
            "name": name,
            "enabled": config.enabled,
            "tier": config.tier,
            "description": config.name,  # Use source name as description
        })

    # Get data file info
    data_files = []
    for filename, tier in INCIDENT_FILES:
        filepath = INCIDENTS_DIR / filename
        if filepath.exists():
            stat = filepath.stat()
            data_files.append({
                "filename": filename,
                "tier": tier,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

    return {
        "total_incidents": len(incidents),
        "by_tier": by_tier,
        "by_source": by_source,
        "available_sources": available_sources,
        "data_files": data_files,
    }


@router.post("/api/admin/pipeline/fetch")
def admin_fetch(
    source: Optional[str] = Query(None, description="Source name to fetch, or all if not specified"),
    force_refresh: bool = Query(False, description="Force refresh cached data"),
):
    """Fetch data from sources."""
    from data_pipeline.pipeline import DataPipeline
    from data_pipeline.config import SOURCES

    try:
        pipeline = DataPipeline()

        if source:
            if source not in [s for s in SOURCES.keys()]:
                return {"success": False, "error": f"Unknown source: {source}"}
            count = pipeline.fetch_source(source, force_refresh=force_refresh)
            result = {"fetched": {source: count}}
        else:
            count = pipeline.fetch_all(force_refresh=force_refresh)
            result = {"fetched": {"all": count}}

        # Clear cache
        clear_incidents_cache()

        return {
            "success": True,
            "operation": "fetch",
            **result,
        }
    except Exception as e:
        logger.exception("Fetch failed")
        return {"success": False, "error": str(e)}


@router.post("/api/admin/pipeline/process")
def admin_process():
    """Process existing data (validate, normalize, dedupe, geocode)."""
    from data_pipeline.pipeline import DataPipeline

    try:
        pipeline = DataPipeline()

        # Load existing data from files
        for filename, tier in INCIDENT_FILES:
            filepath = INCIDENTS_DIR / filename
            if filepath.exists():
                pipeline.import_json(str(filepath), tier=tier)

        # Process
        stats = pipeline.process()

        # Save back
        pipeline.save(merge_existing=False)

        # Clear cache
        clear_incidents_cache()

        return {
            "success": True,
            "operation": "process",
            "stats": stats,
        }
    except Exception as e:
        logger.exception("Process failed")
        return {"success": False, "error": str(e)}


@router.post("/api/admin/pipeline/run")
def admin_run_pipeline(
    force_refresh: bool = Query(False, description="Force refresh cached data"),
):
    """Run full pipeline (fetch + process + save)."""
    from data_pipeline.pipeline import run_pipeline

    try:
        result = run_pipeline(force_refresh=force_refresh)

        # Clear cache
        clear_incidents_cache()

        return {
            "success": True,
            "operation": "run",
            **result,
        }
    except Exception as e:
        logger.exception("Pipeline run failed")
        return {"success": False, "error": str(e)}


# =====================
# Curation Queue Endpoints
# =====================

@router.get("/api/admin/queue")
async def get_curation_queue(
    status: Optional[str] = Query("pending", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get articles in the curation queue."""
    if not USE_DATABASE:
        return {"items": [], "total": 0}

    from backend.database import fetch

    query = """
        SELECT
            id, source_url, title, content, source_name, published_date,
            fetched_at, status, extracted_data,
            relevance_score, extraction_confidence
        FROM ingested_articles
        WHERE status = $1
        ORDER BY fetched_at DESC
        LIMIT $2
    """
    rows = await fetch(query, status or "pending", limit)

    import json as json_module
    items = []
    for row in rows:
        extracted_data_raw = row.get("extracted_data") or {}
        # Handle both string and dict formats (for backwards compatibility)
        if isinstance(extracted_data_raw, str):
            try:
                extracted_data_raw = json_module.loads(extracted_data_raw)
            except:
                extracted_data_raw = {}
        # Extract nested extracted_data if present
        extracted_data = extracted_data_raw.get("extracted_data") if isinstance(extracted_data_raw, dict) and "extracted_data" in extracted_data_raw else extracted_data_raw

        items.append({
            "id": str(row["id"]),
            "url": row.get("source_url"),
            "title": row.get("title"),
            "content": row.get("content"),
            "source_name": row.get("source_name"),
            "source_url": row.get("source_url"),
            "published_date": str(row["published_date"]) if row.get("published_date") else None,
            "fetched_at": str(row["fetched_at"]) if row.get("fetched_at") else None,
            "curation_status": row.get("status"),
            "relevance_score": float(row["relevance_score"]) if row.get("relevance_score") else None,
            "extraction_confidence": float(row["extraction_confidence"]) if row.get("extraction_confidence") else None,
            "extracted_data": extracted_data,
        })

    # Get total count
    count_query = "SELECT COUNT(*) as count FROM ingested_articles WHERE status = $1"
    count_rows = await fetch(count_query, status or "pending")
    total = count_rows[0]["count"] if count_rows else 0

    return {"items": items, "total": total}


@router.get("/api/admin/articles/audit")
async def get_article_audit(
    status: Optional[str] = Query(None, description="Filter by status"),
    format: Optional[str] = Query(None, description="Filter by extraction format"),
    issues_only: bool = Query(False, description="Show only articles with issues"),
    limit: int = Query(200, ge=1, le=500),
):
    """Get article audit data with extraction quality analysis."""
    if not USE_DATABASE:
        return {"articles": [], "stats": {}}

    from backend.database import fetch

    # Build WHERE clause
    where_clauses = []
    params = []
    param_idx = 1

    if status:
        where_clauses.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1

    if format == 'llm':
        where_clauses.append(f"extracted_data::text LIKE '%overall_confidence%'")
    elif format == 'keyword_only':
        where_clauses.append(f"extracted_data::text LIKE '%matchedKeywords%'")
    elif format == 'none':
        where_clauses.append(f"extracted_data IS NULL")

    if issues_only:
        where_clauses.append(
            "(status = 'approved' AND incident_id IS NULL) OR "
            "(status = 'approved' AND extracted_data::text LIKE '%matchedKeywords%')"
        )

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    # Fetch articles
    query = f"""
        SELECT
            id, title, source_name, source_url, status,
            extraction_confidence, extracted_data, incident_id,
            published_date, created_at, content
        FROM ingested_articles
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ${param_idx}
    """
    params.append(limit)

    rows = await fetch(query, *params)

    # Required fields by category
    REQUIRED_FIELDS = {
        'enforcement': ['date', 'state', 'incident_type', 'victim_category', 'outcome_category'],
        'crime': ['date', 'state', 'incident_type', 'immigration_status']
    }

    articles = []
    for row in rows:
        extracted_data = row.get("extracted_data") or {}

        # Determine extraction format
        if not extracted_data:
            extraction_format = 'none'
        elif 'matchedKeywords' in str(extracted_data):
            extraction_format = 'keyword_only'
        elif 'overall_confidence' in str(extracted_data) or 'incident' in str(extracted_data):
            extraction_format = 'llm'
        else:
            extraction_format = 'unknown'

        # Check for required fields
        category = extracted_data.get('category', 'crime')
        required = REQUIRED_FIELDS.get(category, ['date', 'state', 'incident_type'])
        missing_fields = [f for f in required if not extracted_data.get(f)]
        has_required_fields = len(missing_fields) == 0

        articles.append({
            "id": str(row["id"]),
            "title": row.get("title"),
            "source_name": row.get("source_name"),
            "source_url": row.get("source_url"),
            "status": row.get("status"),
            "extraction_confidence": float(row["extraction_confidence"]) if row.get("extraction_confidence") else None,
            "extraction_format": extraction_format,
            "incident_id": str(row["incident_id"]) if row.get("incident_id") else None,
            "has_required_fields": has_required_fields,
            "missing_fields": missing_fields,
            "published_date": str(row["published_date"]) if row.get("published_date") else None,
            "created_at": str(row["created_at"]) if row.get("created_at") else None,
            "extracted_data": extracted_data,
            "content": row.get("content"),
        })

    # Calculate stats
    stats_query = """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'pending') as pending,
            COUNT(*) FILTER (WHERE status = 'approved') as approved,
            COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
            COUNT(*) FILTER (WHERE status = 'approved' AND incident_id IS NULL) as approved_without_incident,
            COUNT(*) FILTER (WHERE status = 'approved' AND extracted_data::text LIKE '%matchedKeywords%') as approved_keyword_only
        FROM ingested_articles
    """
    stats_rows = await fetch(stats_query)
    stats_row = stats_rows[0] if stats_rows else {}

    stats = {
        "total": stats_row.get("total", 0),
        "by_status": {
            "pending": stats_row.get("pending", 0),
            "approved": stats_row.get("approved", 0),
            "rejected": stats_row.get("rejected", 0),
        },
        "by_format": {
            "llm": sum(1 for a in articles if a["extraction_format"] == "llm"),
            "keyword_only": sum(1 for a in articles if a["extraction_format"] == "keyword_only"),
            "none": sum(1 for a in articles if a["extraction_format"] == "none"),
        },
        "approved_without_incident": stats_row.get("approved_without_incident", 0),
        "approved_keyword_only": stats_row.get("approved_keyword_only", 0),
    }

    return {"articles": articles, "stats": stats}


@router.post("/api/admin/queue/submit")
async def submit_article_for_curation(
    url: str = Body(..., embed=True),
    title: Optional[str] = Body(None, embed=True),
    content: str = Body(..., embed=True),
    source_name: Optional[str] = Body(None, embed=True),
    run_extraction: bool = Body(True, embed=True),
):
    """Submit an article for curation (and optionally run LLM extraction)."""
    import uuid
    from datetime import datetime

    if not USE_DATABASE:
        return {"success": False, "error": "Database not enabled"}

    from backend.database import execute, fetch

    article_id = str(uuid.uuid4())

    # Run LLM extraction if requested
    extraction_result = None
    extraction_confidence = None
    relevance_score = None

    if run_extraction:
        from backend.services import get_extractor
        extractor = get_extractor()
        if extractor.is_available():
            full_text = f"{title}\n\n{content}" if title else content
            extraction_result = extractor.extract(full_text)
            extraction_confidence = extraction_result.get("confidence")
            if extraction_result.get("is_relevant"):
                relevance_score = 1.0
            elif extraction_result.get("is_relevant") is False:
                relevance_score = 0.0

    # Insert into database - pass dict directly for JSONB column (asyncpg handles encoding)
    query = """
        INSERT INTO ingested_articles (
            id, source_url, title, content, source_name, fetched_at,
            status, extracted_data, extraction_confidence, relevance_score
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
    """
    await execute(
        query,
        uuid.UUID(article_id), url, title, content, source_name,
        datetime.utcnow(), "pending",
        extraction_result,  # Pass dict directly, asyncpg JSON codec handles it
        extraction_confidence, relevance_score
    )

    return {
        "success": True,
        "article_id": article_id,
        "extraction_result": extraction_result,
    }


# =====================
# Tiered Queue & Batch Processing Endpoints
# (Must be defined BEFORE parameterized /{article_id} routes)
# =====================

@router.get("/api/admin/queue/tiered")
async def get_tiered_queue(category: Optional[str] = Query(None)):
    """Get queue items grouped by confidence tier."""
    if not USE_DATABASE:
        return {"high": [], "medium": [], "low": []}

    from backend.database import fetch

    query = """
        SELECT id, title, source_name, extraction_confidence, published_date, fetched_at
        FROM ingested_articles
        WHERE status IN ('pending', 'in_review')
        ORDER BY extraction_confidence DESC NULLS LAST
        LIMIT 200
    """
    rows = await fetch(query)

    tiers = {"high": [], "medium": [], "low": []}

    for row in rows:
        item = {
            "id": str(row["id"]),
            "title": row.get("title"),
            "source_name": row.get("source_name"),
            "extraction_confidence": float(row["extraction_confidence"]) if row.get("extraction_confidence") else None,
            "published_date": str(row["published_date"]) if row.get("published_date") else None,
            "fetched_at": str(row["fetched_at"]) if row.get("fetched_at") else None,
        }

        confidence = item["extraction_confidence"] or 0
        if confidence >= 0.85:
            tiers["high"].append(item)
        elif confidence >= 0.50:
            tiers["medium"].append(item)
        else:
            tiers["low"].append(item)

    return tiers


@router.post("/api/admin/queue/bulk-approve")
async def bulk_approve(
    tier: str = Body(..., embed=True),
    category: Optional[str] = Body(None, embed=True),
    limit: int = Body(50, embed=True),
):
    """Bulk approve articles in a confidence tier."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch, execute
    import uuid
    from datetime import datetime

    # Map tier to confidence threshold (use <= for upper bound to include 1.0)
    tier_filters = {
        "high": "extraction_confidence >= 0.85",
        "medium": "extraction_confidence >= 0.50 AND extraction_confidence < 0.85",
        "low": "extraction_confidence < 0.50 OR extraction_confidence IS NULL",
    }

    if tier not in tier_filters:
        raise HTTPException(status_code=400, detail="Invalid tier. Must be: high, medium, low")

    # Get articles in tier
    query = f"""
        SELECT id, title, extracted_data, source_url, extraction_confidence
        FROM ingested_articles
        WHERE status IN ('pending', 'in_review')
          AND ({tier_filters[tier]})
        ORDER BY extraction_confidence DESC
        LIMIT $1
    """
    rows = await fetch(query, limit)

    from backend.services.incident_creation_service import get_incident_creation_service
    svc = get_incident_creation_service()

    approved_count = 0
    errors = 0
    error_details = []
    incident_ids = []

    for row in rows:
        article_id = row["id"]
        extracted_data = row.get("extracted_data") or {}
        # Handle cases where extracted_data is stored as a JSON string
        if isinstance(extracted_data, str):
            import json as _json
            try:
                extracted_data = _json.loads(extracted_data)
            except (ValueError, TypeError):
                extracted_data = {}

        # Extract merge_info (persisted in extracted_data by the extraction pipeline)
        from backend.services.stage2_selector import resolve_category_from_merge_info
        row_merge_info = extracted_data.pop("merge_info", None)
        row_category = resolve_category_from_merge_info(row_merge_info, extracted_data, default=category or "crime")

        try:
            # Dedup check before creating incident
            from backend.services.duplicate_detection import find_duplicate_incident
            source_url = row.get("source_url")
            dup = await find_duplicate_incident(extracted_data, source_url=source_url)
            if dup:
                dup_id = dup.get("matched_id", "?")
                dup_reason = dup.get("reason", "duplicate")
                await execute("""
                    UPDATE ingested_articles
                    SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
                    WHERE id = $3
                """, f"Duplicate of {dup_id}: {dup_reason}"[:400], datetime.utcnow(), article_id)
                error_details.append(f"{row.get('title', article_id)}: duplicate of {dup_id}")
                errors += 1
                continue

            result = await svc.create_incident_from_extraction(
                extracted_data=extracted_data,
                article=dict(row),
                category=row_category,
                merge_info=row_merge_info,
            )
            incident_id = result["incident_id"]

            # Update article status
            await execute("""
                UPDATE ingested_articles
                SET status = 'approved', incident_id = $1, reviewed_at = $2
                WHERE id = $3
            """, uuid.UUID(incident_id), datetime.utcnow(), article_id)

            approved_count += 1
            incident_ids.append(incident_id)
        except Exception as e:
            logger.error(f"Bulk approve failed for article {article_id}: {e}")
            # Mark as error so it doesn't keep appearing in queue
            await execute("""
                UPDATE ingested_articles
                SET status = 'error', rejection_reason = $1, reviewed_at = $2
                WHERE id = $3
            """, f"Bulk approve error: {str(e)[:400]}", datetime.utcnow(), article_id)
            error_details.append(f"{row.get('title', article_id)}: {str(e)[:200]}")
            errors += 1

    return {
        "success": True,
        "approved_count": approved_count,
        "errors": errors,
        "error_details": error_details,
        "incident_ids": incident_ids,
    }


@router.post("/api/admin/queue/bulk-reject")
async def bulk_reject(
    tier: str = Body(..., embed=True),
    reason: str = Body(..., embed=True),
    category: Optional[str] = Body(None, embed=True),
    limit: int = Body(50, embed=True),
):
    """Bulk reject articles in a confidence tier."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch, execute
    from datetime import datetime

    tier_filters = {
        "high": "extraction_confidence >= 0.85",
        "medium": "extraction_confidence >= 0.50 AND extraction_confidence < 0.85",
        "low": "extraction_confidence < 0.50 OR extraction_confidence IS NULL",
    }

    if tier not in tier_filters:
        raise HTTPException(status_code=400, detail="Invalid tier. Must be: high, medium, low")

    result = await execute(f"""
        UPDATE ingested_articles
        SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
        WHERE id IN (
            SELECT id FROM ingested_articles
            WHERE status IN ('pending', 'in_review')
              AND ({tier_filters[tier]})
            LIMIT $3
        )
    """, reason, datetime.utcnow(), limit)

    # Parse result to get count
    rejected_count = 0
    if "UPDATE" in result:
        try:
            rejected_count = int(result.split()[1])
        except:
            pass

    return {"success": True, "rejected_count": rejected_count}


@router.post("/api/admin/queue/auto-approve")
async def auto_approve_extracted(data: dict = Body(...)):
    """Evaluate extracted-but-pending articles against approval thresholds.

    Creates incidents for articles that pass, marks rejects, leaves
    borderline articles for manual review. Can be called independently
    after extraction or as part of the pipeline.

    Body: { "limit": 50 }
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    import uuid as uuid_mod
    import json as _json
    from datetime import datetime
    from backend.database import get_pool
    from backend.services.auto_approval import get_auto_approval_service
    from backend.services.incident_creation_service import get_incident_creation_service

    limit = min(data.get("limit", 50), 200)
    pool = await get_pool()

    approval_service = get_auto_approval_service()
    incident_service = get_incident_creation_service()
    approval_service.set_db_pool(pool)
    await approval_service.load_category_configs_from_db()

    # Fetch articles that have been extracted but not yet approved/rejected
    rows = await pool.fetch("""
        SELECT id, title, content, source_url, published_date,
               extracted_data, extraction_confidence
        FROM ingested_articles
        WHERE status IN ('pending', 'in_review')
          AND extracted_data IS NOT NULL
          AND extraction_confidence IS NOT NULL
        ORDER BY extraction_confidence DESC
        LIMIT $1
    """, limit)

    auto_approved = 0
    auto_rejected = 0
    needs_review = 0
    errors = 0
    items = []

    for row in rows:
        article_id = str(row["id"])
        title = (row.get("title") or "(untitled)")[:80]

        extracted_data = row.get("extracted_data") or {}
        if isinstance(extracted_data, str):
            try:
                extracted_data = _json.loads(extracted_data)
            except (ValueError, TypeError):
                extracted_data = {}

        # Extract merge_info (persisted in extracted_data by the extraction pipeline)
        from backend.services.stage2_selector import resolve_category_from_merge_info
        row_merge_info = extracted_data.pop("merge_info", None)
        row_category = resolve_category_from_merge_info(row_merge_info, extracted_data)

        article_dict = {
            "id": article_id,
            "title": row.get("title"),
            "content": row.get("content"),
            "source_url": row.get("source_url"),
            "published_date": str(row["published_date"]) if row.get("published_date") else None,
        }

        try:
            decision = await approval_service.evaluate_async(
                article_dict, extracted_data, category=row_category
            )

            item = {
                "id": article_id,
                "title": title,
                "confidence": float(row["extraction_confidence"]) if row.get("extraction_confidence") else None,
                "decision": decision.decision,
                "reason": decision.reason,
            }

            if decision.decision == "auto_approve":
                try:
                    inc_result = await incident_service.create_incident_from_extraction(
                        extracted_data=extracted_data,
                        article=article_dict,
                        category=row_category,
                        merge_info=row_merge_info,
                    )
                    incident_id = inc_result["incident_id"]
                    await pool.execute("""
                        UPDATE ingested_articles
                        SET status = 'approved', incident_id = $1, reviewed_at = $2
                        WHERE id = $3
                    """, uuid_mod.UUID(incident_id), datetime.utcnow(), row["id"])
                    item["status"] = "auto_approved"
                    item["incident_id"] = incident_id
                    auto_approved += 1
                except Exception as e:
                    logger.error("Auto-approve incident creation failed for %s: %s", article_id, e)
                    await pool.execute("""
                        UPDATE ingested_articles
                        SET status = 'error', rejection_reason = $1, reviewed_at = $2
                        WHERE id = $3
                    """, f"Auto-approve error: {str(e)[:400]}", datetime.utcnow(), row["id"])
                    item["status"] = "error"
                    item["error"] = str(e)[:200]
                    errors += 1

            elif decision.decision == "auto_reject":
                await pool.execute("""
                    UPDATE ingested_articles
                    SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
                    WHERE id = $3
                """, decision.reason[:500], datetime.utcnow(), row["id"])
                item["status"] = "auto_rejected"
                auto_rejected += 1

            else:
                # needs_review — mark as in_review if still pending
                await pool.execute("""
                    UPDATE ingested_articles
                    SET status = 'in_review'
                    WHERE id = $1 AND status = 'pending'
                """, row["id"])
                item["status"] = "needs_review"
                needs_review += 1

            items.append(item)

        except Exception as e:
            logger.error("Auto-approve evaluation failed for %s: %s", article_id, e)
            errors += 1
            items.append({
                "id": article_id,
                "title": title,
                "status": "error",
                "error": str(e)[:200],
            })

    return {
        "success": True,
        "processed": len(rows),
        "auto_approved": auto_approved,
        "auto_rejected": auto_rejected,
        "needs_review": needs_review,
        "errors": errors,
        "items": items,
    }


@router.get("/api/admin/queue/extraction-status")
async def get_queue_extraction_status():
    """
    Get breakdown of queue by extraction status and pipeline stage.
    """
    from backend.database import fetch

    # Get stage-based counts for clearer pipeline view
    stage_rows = await fetch("""
        SELECT
            CASE
                -- Not yet extracted (keyword matching only or nothing)
                WHEN extracted_data IS NULL THEN 'need_extraction'
                WHEN extracted_data->>'matchedKeywords' IS NOT NULL
                     AND extracted_data->>'extraction_type' IS NULL THEN 'need_extraction'
                -- Extracted but not relevant
                WHEN (extracted_data->>'is_relevant' = 'false'
                      OR extracted_data->>'isRelevant' = 'false') THEN 'not_relevant'
                -- Extracted, relevant, high confidence (ready to approve)
                WHEN (extracted_data->>'is_relevant' = 'true'
                      OR extracted_data->>'isRelevant' = 'true')
                     AND COALESCE(extraction_confidence, 0) >= 0.85 THEN 'ready_to_approve'
                -- Extracted, relevant, needs review (low/medium confidence)
                WHEN (extracted_data->>'is_relevant' = 'true'
                      OR extracted_data->>'isRelevant' = 'true') THEN 'needs_review'
                -- Extracted but relevance unknown
                ELSE 'needs_review'
            END as stage,
            COUNT(*) as count,
            AVG(COALESCE(extraction_confidence, 0)) as avg_confidence
        FROM ingested_articles
        WHERE status = 'pending'
        GROUP BY 1
    """)

    # Legacy breakdown for backwards compatibility
    rows = await fetch("""
        SELECT
            CASE
                WHEN extracted_data->>'success' = 'true' THEN 'full_extraction'
                WHEN extracted_data->>'extraction_type' = 'universal' THEN 'full_extraction'
                WHEN extracted_data->>'matchedKeywords' IS NOT NULL THEN 'keyword_only'
                WHEN extracted_data IS NULL THEN 'no_extraction'
                ELSE 'other'
            END as extraction_type,
            COUNT(*) as count,
            AVG(CASE WHEN extraction_confidence IS NOT NULL THEN extraction_confidence ELSE 0 END) as avg_confidence
        FROM ingested_articles
        WHERE status = 'pending'
        GROUP BY 1
        ORDER BY count DESC
    """)

    relevance_rows = await fetch("""
        SELECT
            CASE
                WHEN extracted_data->>'is_relevant' = 'true'
                     OR extracted_data->>'isRelevant' = 'true' THEN 'relevant'
                WHEN extracted_data->>'is_relevant' = 'false'
                     OR extracted_data->>'isRelevant' = 'false' THEN 'not_relevant'
                ELSE 'unknown'
            END as relevance,
            COUNT(*) as count
        FROM ingested_articles
        WHERE status = 'pending'
          AND (extracted_data->>'success' = 'true'
               OR extracted_data->>'extraction_type' = 'universal')
        GROUP BY 1
    """)

    # Get schema type breakdown (universal vs legacy)
    schema_rows = await fetch("""
        SELECT
            CASE
                WHEN extracted_data->>'extraction_type' = 'universal' THEN 'universal'
                WHEN extracted_data->>'success' = 'true' THEN 'legacy'
                ELSE 'none'
            END as schema_type,
            COUNT(*) as count
        FROM ingested_articles
        WHERE status = 'pending'
        GROUP BY 1
    """)

    # Build stage counts dict for easy access
    stages = {row["stage"]: {"count": row["count"], "avg_confidence": float(row["avg_confidence"]) if row["avg_confidence"] else 0} for row in stage_rows}

    return {
        # New stage-based view
        "stages": {
            "need_extraction": stages.get("need_extraction", {"count": 0, "avg_confidence": 0}),
            "not_relevant": stages.get("not_relevant", {"count": 0, "avg_confidence": 0}),
            "needs_review": stages.get("needs_review", {"count": 0, "avg_confidence": 0}),
            "ready_to_approve": stages.get("ready_to_approve", {"count": 0, "avg_confidence": 0}),
        },
        # Legacy fields for backwards compatibility
        "by_extraction_type": [
            {
                "type": row["extraction_type"],
                "count": row["count"],
                "avg_confidence": float(row["avg_confidence"]) if row["avg_confidence"] else None
            }
            for row in rows
        ],
        "by_relevance": [
            {"relevance": row["relevance"], "count": row["count"]}
            for row in relevance_rows
        ],
        "by_schema_type": [
            {"schema": row["schema_type"], "count": row["count"]}
            for row in schema_rows
        ],
        "total_pending": sum(row["count"] for row in rows),
        "needs_upgrade": sum(
            row["count"] for row in schema_rows
            if row["schema_type"] == 'legacy'  # Only count extracted items with old schema
        )
    }


@router.post("/api/admin/queue/triage")
async def triage_queue_items(
    limit: int = Body(10, embed=True, ge=1, le=50),
    auto_reject: bool = Body(False, embed=True, description="Automatically reject items recommended for rejection"),
):
    """
    Run quick triage on queue items to determine relevance.
    This is faster and cheaper than full extraction.
    """
    from backend.services import get_extractor
    from backend.database import fetch, execute
    import asyncio

    extractor = get_extractor()
    if not extractor.is_available():
        return {"success": False, "error": "LLM not available"}

    # Get items that only have keyword matching (no full extraction)
    rows = await fetch("""
        SELECT id, title, content, source_url
        FROM ingested_articles
        WHERE status = 'pending'
          AND content IS NOT NULL
          AND (extracted_data->>'success' IS NULL OR extracted_data->>'success' != 'true')
        ORDER BY fetched_at ASC
        LIMIT $1
    """, limit)

    results = {
        "processed": 0,
        "extract_recommended": 0,
        "reject_recommended": 0,
        "review_recommended": 0,
        "auto_rejected": 0,
        "items": []
    }

    for row in rows:
        article_id = str(row["id"])
        title = row.get("title") or ""
        content = row.get("content") or ""

        triage_result = extractor.triage(title, content)
        results["processed"] += 1

        recommendation = triage_result.get("recommendation", "review")
        if recommendation == "extract":
            results["extract_recommended"] += 1
        elif recommendation == "reject":
            results["reject_recommended"] += 1
            # Auto-reject if enabled
            if auto_reject:
                await execute("""
                    UPDATE ingested_articles
                    SET status = 'rejected',
                        rejection_reason = $2,
                        reviewed_at = NOW()
                    WHERE id = $1
                """, row["id"], f"Triage: {triage_result.get('reason', 'Not a specific incident')}")
                results["auto_rejected"] += 1
        else:
            results["review_recommended"] += 1

        results["items"].append({
            "id": article_id,
            "title": title[:80] + "..." if len(title) > 80 else title,
            "triage": triage_result
        })

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.2)

    return {"success": True, **results}


@router.post("/api/admin/queue/batch-extract")
async def batch_extract_queue_items(
    limit: int = Body(10, embed=True, ge=1, le=100),
    re_extract: bool = Body(False, embed=True, description="Re-extract already extracted items"),
    use_legacy: bool = Body(False, embed=True, description="Use legacy category-based extraction instead of universal"),
):
    """
    Run universal LLM extraction on queue items.
    Extracts all actors, events, and details regardless of category.
    """
    from backend.services import get_extractor
    from backend.database import fetch, execute
    from backend.utils.state_normalizer import normalize_state
    import asyncio
    import json as json_module

    extractor = get_extractor()
    if not extractor.is_available():
        return {"success": False, "error": "LLM not available"}

    # Get items needing extraction
    if re_extract:
        # Re-extract items that had successful LLM extraction but with old schema (not universal)
        rows = await fetch("""
            SELECT id, title, content, source_url, extracted_data
            FROM ingested_articles
            WHERE status = 'pending'
              AND content IS NOT NULL
              AND extracted_data->>'success' = 'true'
              AND (extracted_data->>'extraction_type' IS NULL OR extracted_data->>'extraction_type' != 'universal')
            ORDER BY fetched_at ASC
            LIMIT $1
        """, limit)
    else:
        # Only extract items that haven't been successfully extracted
        rows = await fetch("""
            SELECT id, title, content, source_url, extracted_data
            FROM ingested_articles
            WHERE status = 'pending'
              AND content IS NOT NULL
              AND (extracted_data->>'success' IS NULL OR extracted_data->>'success' != 'true')
            ORDER BY fetched_at ASC
            LIMIT $1
        """, limit)

    results = {
        "processed": 0,
        "extracted": 0,
        "relevant": 0,
        "not_relevant": 0,
        "errors": 0,
        "extraction_type": "legacy" if use_legacy else "universal",
        "items": []
    }

    for row in rows:
        article_id = row["id"]
        title = row.get("title") or ""
        content = row.get("content") or ""
        full_text = f"Title: {title}\n\n{content}" if title else content

        try:
            # Use universal extraction by default
            if use_legacy:
                ext_result = extractor.extract(full_text)
            else:
                ext_result = extractor.extract_universal(full_text)

            results["processed"] += 1

            if ext_result.get("success"):
                results["extracted"] += 1

                # Normalize state if extracted (handle both schema formats)
                incident = ext_result.get("incident", {}) or ext_result.get("extracted_data", {})
                location = incident.get("location", {})
                state = location.get("state") if isinstance(location, dict) else incident.get("state")
                if state:
                    normalized_state = normalize_state(state)
                    if isinstance(location, dict):
                        ext_result["incident"]["location"]["state"] = normalized_state
                    elif "extracted_data" in ext_result:
                        ext_result["extracted_data"]["state"] = normalized_state

                if ext_result.get("is_relevant"):
                    results["relevant"] += 1
                else:
                    results["not_relevant"] += 1

                # Update the article with extraction results
                confidence = ext_result.get("confidence", 0.5)
                if not confidence and incident:
                    confidence = incident.get("overall_confidence", 0.5)
                relevance = 1.0 if ext_result.get("is_relevant") else 0.0

                await execute("""
                    UPDATE ingested_articles
                    SET extracted_data = $2,
                        extraction_confidence = $3,
                        relevance_score = $4,
                        extracted_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1
                """, article_id, json_module.dumps(ext_result), confidence, relevance)

                # Build result item
                categories = ext_result.get("categories", [])
                if not categories and incident:
                    categories = incident.get("categories", [])

                actors = ext_result.get("actors", [])
                actor_summary = f"{len(actors)} actors" if actors else None

                results["items"].append({
                    "id": str(article_id),
                    "title": title[:60] + "..." if len(title) > 60 else title,
                    "is_relevant": ext_result.get("is_relevant"),
                    "confidence": confidence,
                    "categories": categories,
                    "actors": actor_summary,
                })
            else:
                results["errors"] += 1
                results["items"].append({
                    "id": str(article_id),
                    "title": title[:60] + "..." if len(title) > 60 else title,
                    "error": ext_result.get("error")
                })
        except Exception as e:
            results["errors"] += 1
            results["items"].append({
                "id": str(article_id),
                "title": title[:60] + "..." if len(title) > 60 else title,
                "error": str(e)
            })

        # Delay to avoid rate limiting
        await asyncio.sleep(0.5)

    return {"success": True, **results}


@router.post("/api/admin/queue/bulk-reject-by-criteria")
async def bulk_reject_queue_items_by_criteria(
    ids: List[str] = Body(None, embed=True, description="Specific IDs to reject"),
    reject_not_relevant: bool = Body(False, embed=True, description="Reject all items with relevance_score = 0"),
    reject_low_confidence: float = Body(None, embed=True, description="Reject items below this confidence"),
    reason: str = Body("Bulk rejection", embed=True),
):
    """
    Bulk reject queue items based on criteria (IDs, relevance, confidence).
    """
    from backend.database import fetch, execute

    rejected_count = 0

    if ids:
        # Reject specific IDs
        for article_id in ids:
            try:
                await execute("""
                    UPDATE ingested_articles
                    SET status = 'rejected',
                        rejection_reason = $2,
                        reviewed_at = NOW()
                    WHERE id = $1 AND status = 'pending'
                """, uuid.UUID(article_id), reason)
                rejected_count += 1
            except Exception as e:
                logger.error(f"Error rejecting {article_id}: {e}")

    if reject_not_relevant:
        # Reject all not relevant items
        await execute("""
            UPDATE ingested_articles
            SET status = 'rejected',
                rejection_reason = $1,
                reviewed_at = NOW()
            WHERE status = 'pending'
              AND extracted_data IS NOT NULL
              AND (extracted_data->>'is_relevant' = 'false'
                   OR relevance_score = 0)
        """, "Not relevant to incident tracking")
        rows = await fetch("""
            SELECT COUNT(*) as cnt FROM ingested_articles
            WHERE status = 'rejected' AND rejection_reason = 'Not relevant to incident tracking'
              AND reviewed_at > NOW() - INTERVAL '1 minute'
        """)
        rejected_count += rows[0]["cnt"] if rows else 0

    if reject_low_confidence is not None:
        await execute("""
            UPDATE ingested_articles
            SET status = 'rejected',
                rejection_reason = $2,
                reviewed_at = NOW()
            WHERE status = 'pending'
              AND extraction_confidence IS NOT NULL
              AND extraction_confidence < $1
        """, reject_low_confidence, f"Low confidence (< {reject_low_confidence})")
        rows = await fetch("""
            SELECT COUNT(*) as cnt FROM ingested_articles
            WHERE status = 'rejected'
              AND rejection_reason LIKE 'Low confidence%'
              AND reviewed_at > NOW() - INTERVAL '1 minute'
        """)
        rejected_count += rows[0]["cnt"] if rows else 0

    return {
        "success": True,
        "rejected_count": rejected_count
    }


@router.get("/api/admin/queue/{article_id}")
async def get_queue_item(article_id: str):
    """Get a single queue item with full details."""
    import uuid

    if not USE_DATABASE:
        return {"error": "Database not enabled"}

    from backend.database import fetch

    query = """
        SELECT id, title, source_name, source_url, content, published_date,
               fetched_at, relevance_score, extraction_confidence, extracted_data, status
        FROM ingested_articles
        WHERE id = $1
    """
    rows = await fetch(query, uuid.UUID(article_id))
    if not rows:
        return {"error": "Article not found"}

    row = rows[0]
    return {
        "id": str(row["id"]),
        "title": row.get("title"),
        "source_name": row.get("source_name"),
        "source_url": row.get("source_url"),
        "content": row.get("content"),
        "published_date": str(row["published_date"]) if row.get("published_date") else None,
        "fetched_at": str(row["fetched_at"]) if row.get("fetched_at") else None,
        "extraction_confidence": float(row["extraction_confidence"]) if row.get("extraction_confidence") else None,
        "extracted_data": row.get("extracted_data"),
        "status": row.get("status"),
    }


@router.get("/api/admin/queue/{article_id}/suggestions")
async def get_ai_suggestions(article_id: str):
    """Get AI suggestions for low-confidence fields in an article."""
    import uuid

    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch

    try:
        article_uuid = uuid.UUID(article_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid article ID format")

    rows = await fetch("""
        SELECT extracted_data, content, title
        FROM ingested_articles
        WHERE id = $1
    """, article_uuid)

    if not rows:
        raise HTTPException(status_code=404, detail="Article not found")

    row = rows[0]
    extracted_data = row.get("extracted_data") or {}
    if isinstance(extracted_data, dict) and "extracted_data" in extracted_data:
        extracted_data = extracted_data.get("extracted_data") or {}

    # Identify low-confidence fields
    suggestions = []
    confidence_fields = ['date', 'state', 'city', 'incident_type', 'victim_name']

    for field in confidence_fields:
        conf_key = f"{field}_confidence"
        confidence = extracted_data.get(conf_key, 1.0)
        if confidence < 0.7:
            suggestions.append({
                "field": field,
                "current_value": extracted_data.get(field),
                "confidence": confidence,
                "suggestion": None,  # Would be populated by AI analysis
                "reason": f"Low confidence ({confidence:.0%}) - may need manual verification"
            })

    return {"article_id": article_id, "suggestions": suggestions}


@router.post("/api/admin/queue/{article_id}/extract-universal")
async def extract_article_universal(article_id: str):
    """Run universal extraction on an article to capture all entities."""
    import uuid

    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch, execute
    from backend.services.llm_extraction import get_extractor

    # Get article content
    query = """
        SELECT id, title, content, extracted_data
        FROM ingested_articles
        WHERE id = $1
    """
    rows = await fetch(query, uuid.UUID(article_id))
    if not rows:
        raise HTTPException(status_code=404, detail="Article not found")

    row = rows[0]
    content = row.get("content", "")
    title = row.get("title", "")

    if not content:
        return {"success": False, "error": "Article has no content"}

    # Run universal extraction
    extractor = get_extractor()
    if not extractor.is_available():
        return {"success": False, "error": "LLM extraction not available"}

    article_text = f"Title: {title}\n\n{content}" if title else content
    result = extractor.extract_universal(article_text)

    if result.get("success"):
        # Update the article with universal extraction data
        update_query = """
            UPDATE ingested_articles
            SET extracted_data = $1,
                extraction_confidence = $2,
                extraction_type = 'universal'
            WHERE id = $3
        """
        await execute(
            update_query,
            result,
            result.get("confidence", 0.5),
            uuid.UUID(article_id)
        )

    return result


@router.post("/api/admin/queue/{article_id}/approve")
async def approve_article(
    article_id: str,
    overrides: Optional[dict] = Body(None),
    force_create: bool = Body(False),
    link_to_existing_id: Optional[str] = Body(None),
):
    """Approve an article and create an incident with linked actors.

    If link_to_existing_id is provided, links the article as an additional source
    to the existing incident instead of creating a new one.
    """
    import uuid
    from datetime import datetime

    if not USE_DATABASE:
        return {"success": False, "error": "Database not enabled"}

    from backend.database import fetch, execute
    from backend.services.duplicate_detection import find_duplicate_incident

    # Get the article
    query = "SELECT * FROM ingested_articles WHERE id = $1"
    rows = await fetch(query, uuid.UUID(article_id))
    if not rows:
        return {"success": False, "error": "Article not found"}

    article = rows[0]

    extracted_data_raw = article.get("extracted_data") or {}
    # extracted_data might be the full result with nested extracted_data, or just the data
    if isinstance(extracted_data_raw, dict) and "extracted_data" in extracted_data_raw:
        extracted_data = extracted_data_raw.get("extracted_data") or {}
    else:
        extracted_data = extracted_data_raw

    # Apply overrides
    if overrides:
        extracted_data.update(overrides)

    # Determine category from extraction — use merge_info-aware resolver
    from backend.services.stage2_selector import resolve_category_from_merge_info
    merge_info = extracted_data_raw.get("merge_info") or extracted_data.get("merge_info")
    category = resolve_category_from_merge_info(merge_info, extracted_data)

    # If linking to existing incident, add as additional source
    if link_to_existing_id:
        existing_id = uuid.UUID(link_to_existing_id)

        # Verify the incident exists
        check_query = "SELECT id FROM incidents WHERE id = $1"
        check_rows = await fetch(check_query, existing_id)
        if not check_rows:
            return {"success": False, "error": "Existing incident not found"}

        # Add article as additional source
        source_query = """
            INSERT INTO incident_sources (incident_id, url, title, published_date, is_primary)
            VALUES ($1, $2, $3, $4, false)
            ON CONFLICT (incident_id, url) DO NOTHING
        """
        await execute(
            source_query,
            existing_id,
            article.get("source_url"),
            article.get("title"),
            article.get("published_date")
        )

        # Mark article as processed
        await execute(
            "UPDATE ingested_articles SET status = 'linked', processed_at = NOW() WHERE id = $1",
            uuid.UUID(article_id)
        )

        return {
            "success": True,
            "action": "linked_to_existing",
            "incident_id": str(existing_id),
            "message": "Article linked as additional source to existing incident"
        }

    # Check for duplicates using smart cross-source detection
    if not force_create:
        duplicate = await find_duplicate_incident(
            extracted_data,
            source_url=article.get("source_url"),
            date_window_days=30,
            name_threshold=0.7
        )

        if duplicate:
            matched = duplicate.get('matched_incident', {})
            return {
                "success": False,
                "error": "duplicate_detected",
                "match_type": duplicate.get('match_type'),
                "message": f"Duplicate detected: {duplicate.get('reason')}",
                "confidence": duplicate.get('confidence'),
                "existing_incident_id": duplicate.get('matched_id'),
                "existing_date": matched.get('date'),
                "existing_location": matched.get('location'),
                "existing_name": matched.get('matched_name'),
                "existing_source": matched.get('source_url'),
            }

    # Create incident via the creation service
    from backend.services.incident_creation_service import get_incident_creation_service
    svc = get_incident_creation_service()
    # Pop merge_info from extracted_data so it doesn't leak into incident fields
    approve_merge_info = extracted_data.pop("merge_info", None) or merge_info
    result = await svc.create_incident_from_extraction(
        extracted_data=extracted_data,
        article=dict(article),
        category=category,
        overrides=overrides,
        merge_info=approve_merge_info,
    )
    incident_id = result["incident_id"]

    # Update article status
    update_query = """
        UPDATE ingested_articles
        SET status = 'approved', incident_id = $1, reviewed_at = $2
        WHERE id = $3
    """
    await execute(update_query, uuid.UUID(incident_id), datetime.utcnow(), uuid.UUID(article_id))

    # Add article as primary source in incident_sources
    source_query = """
        INSERT INTO incident_sources (incident_id, url, title, published_date, is_primary)
        VALUES ($1, $2, $3, $4, true)
        ON CONFLICT (incident_id, url) DO NOTHING
    """
    await execute(
        source_query,
        uuid.UUID(incident_id),
        article.get("source_url"),
        article.get("title"),
        article.get("published_date")
    )

    return {
        "success": True,
        "incident_id": incident_id,
        "actors_created": result.get("actors_created", []),
        "category": result.get("category", category)
    }


@router.post("/api/admin/queue/{article_id}/reject")
async def reject_article(
    article_id: str,
    reason: str = Body(..., embed=True),
):
    """Reject an article."""
    import uuid
    from datetime import datetime

    if not USE_DATABASE:
        return {"success": False, "error": "Database not enabled"}

    from backend.database import execute

    query = """
        UPDATE ingested_articles
        SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
        WHERE id = $3
    """
    await execute(query, reason, datetime.utcnow(), uuid.UUID(article_id))

    return {"success": True}


@router.post("/api/admin/reset-pipeline-data")
async def reset_pipeline_data(
    confirm: bool = Body(False, embed=True),
    dry_run: bool = Body(True, embed=True),
):
    """Nuclear reset: delete all pipeline-generated data and reset articles
    so they can be re-extracted and re-approved through the full pipeline.

    Deletes: incidents (cascading incident_actors, incident_events,
    incident_sources), orphaned actors, orphaned events.
    Resets: ingested_articles status to 'pending', clears extracted_data.
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch, execute

    # Gather counts for preview
    counts = {}
    count_rows = await fetch("SELECT COUNT(*) as n FROM incidents")
    counts["incidents"] = count_rows[0]["n"]
    count_rows = await fetch("SELECT COUNT(*) as n FROM actors")
    counts["actors"] = count_rows[0]["n"]
    count_rows = await fetch("SELECT COUNT(*) as n FROM events")
    counts["events"] = count_rows[0]["n"]
    count_rows = await fetch(
        "SELECT COUNT(*) as n FROM ingested_articles WHERE status != 'pending'"
    )
    counts["articles_to_reset"] = count_rows[0]["n"]
    count_rows = await fetch("SELECT COUNT(*) as n FROM article_extractions")
    counts["article_extractions"] = count_rows[0]["n"]
    count_rows = await fetch("SELECT COUNT(*) as n FROM schema_extraction_results")
    counts["schema_extraction_results"] = count_rows[0]["n"]

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "will_delete": counts,
            "message": "Pass dry_run=false and confirm=true to execute",
        }

    if not confirm:
        return {
            "success": False,
            "error": "Must pass confirm=true to execute destructive reset",
            "will_delete": counts,
        }

    # 1. Delete all incidents (cascades incident_actors, incident_events, incident_sources)
    await execute("DELETE FROM incident_events")
    await execute("DELETE FROM incident_actors")
    await execute("DELETE FROM incident_sources")
    await execute("DELETE FROM incidents")

    # 2. Delete all actors (extraction-created, will be recreated)
    await execute("DELETE FROM actor_relations")
    await execute("DELETE FROM actors")

    # 3. Delete all events (will be recreated from extraction)
    await execute("DELETE FROM events")

    # 4. Clear extraction tables so re-extraction runs fresh
    await execute("DELETE FROM schema_extraction_results")
    await execute("DELETE FROM article_extractions")

    # 5. Reset ALL non-pending articles so they re-enter the pipeline
    await execute("""
        UPDATE ingested_articles
        SET status = 'pending',
            incident_id = NULL,
            extracted_data = NULL,
            extraction_confidence = NULL,
            extracted_at = NULL,
            relevance_score = NULL,
            relevance_reason = NULL,
            reviewed_at = NULL,
            rejection_reason = NULL,
            extraction_error_count = 0,
            last_extraction_error = NULL,
            last_extraction_error_at = NULL,
            extraction_error_category = NULL,
            latest_extraction_id = NULL
        WHERE status != 'pending'
    """)

    return {
        "success": True,
        "deleted": counts,
        "message": "All pipeline data reset. Articles are pending re-extraction.",
    }


@router.post("/api/admin/backfill-actors-events")
async def backfill_actors_events(
    limit: int = Body(100, embed=True),
    dry_run: bool = Body(False, embed=True),
):
    """Backfill actors, events, and domain/category for existing incidents
    that have linked articles with extracted_data but are missing these fields."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch
    from backend.services.incident_creation_service import get_incident_creation_service

    # Find incidents with extraction data but missing domain/actors/events
    query = """
        SELECT i.id as incident_id, i.category,
               ia2.extracted_data
        FROM incidents i
        JOIN ingested_articles ia2 ON ia2.incident_id = i.id
        WHERE ia2.extracted_data IS NOT NULL
          AND (
              i.domain_id IS NULL
              OR NOT EXISTS (
                  SELECT 1 FROM incident_actors iac WHERE iac.incident_id = i.id
              )
              OR NOT EXISTS (
                  SELECT 1 FROM incident_events ie WHERE ie.incident_id = i.id
              )
          )
        ORDER BY i.created_at DESC
        LIMIT $1
    """
    rows = await fetch(query, limit)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "candidates": len(rows),
        }

    svc = get_incident_creation_service()
    backfilled = 0
    errors = 0
    skipped = 0

    for row in rows:
        extracted_data = row.get("extracted_data") or {}
        if not isinstance(extracted_data, dict):
            skipped += 1
            continue

        # Unwrap nested extracted_data if present
        if "extracted_data" in extracted_data:
            extracted_data = extracted_data.get("extracted_data") or {}

        try:
            await svc.backfill_incident(
                incident_id=row["incident_id"],
                extracted_data=extracted_data,
                category=row.get("category", "crime"),
            )
            backfilled += 1
        except Exception as e:
            logger.error(f"Backfill error for incident {row['incident_id']}: {e}")
            errors += 1

    return {
        "success": True,
        "backfilled": backfilled,
        "errors": errors,
        "skipped": skipped,
    }
