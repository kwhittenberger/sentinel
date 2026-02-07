"""
Settings, admin config, duplicate detection, auto-approval,
LLM extraction, and LLM provider routes.
Extracted from main.py.
"""

import logging

from fastapi import APIRouter, HTTPException, Body

from backend.routes._shared import (
    USE_DATABASE,
    get_all_incidents,
    load_incidents,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings"])


# =====================
# Duplicate Detection Endpoints
# =====================

@router.get("/api/admin/duplicates/config")
def get_duplicate_config():
    """Get duplicate detection configuration."""
    from backend.services import get_detector
    detector = get_detector()
    return detector.get_config()


@router.post("/api/admin/duplicates/check")
async def check_duplicate(
    article: dict = Body(...),
):
    """Check if an article is a duplicate."""
    from backend.services import get_detector

    detector = get_detector()

    # Get existing articles to compare against
    if USE_DATABASE:
        existing = await get_all_incidents()
    else:
        existing = load_incidents()

    result = detector.check_duplicate(article, existing)

    if result:
        return {"is_duplicate": True, **result}
    return {"is_duplicate": False}


# =====================
# Auto-Approval Endpoints
# =====================

@router.get("/api/admin/auto-approval/config")
def get_auto_approval_config():
    """Get auto-approval configuration."""
    from backend.services import get_auto_approval_service
    service = get_auto_approval_service()
    return service.get_config()


@router.put("/api/admin/auto-approval/config")
def update_auto_approval_config(updates: dict = Body(...)):
    """Update auto-approval configuration."""
    from backend.services import get_auto_approval_service
    service = get_auto_approval_service()
    service.update_config(updates)
    return {"success": True, "config": service.get_config()}


@router.post("/api/admin/auto-approval/evaluate")
def evaluate_article(article: dict = Body(...)):
    """Evaluate an article for auto-approval."""
    from backend.services import get_auto_approval_service
    service = get_auto_approval_service()
    result = service.evaluate(article)
    return {
        "decision": result.decision,
        "confidence": result.confidence,
        "reason": result.reason,
        "details": result.details
    }


# =====================
# LLM Extraction Endpoints
# =====================

@router.get("/api/admin/llm-extraction/status")
def get_extraction_status():
    """Get LLM extraction service status."""
    from backend.services import get_extractor
    extractor = get_extractor()
    return {
        "available": extractor.is_available(),
        "model": "claude-sonnet-4-20250514" if extractor.is_available() else None
    }


@router.post("/api/admin/llm-extraction/extract")
def extract_from_article(
    content: str = Body(..., embed=True),
    document_type: str = Body("news_article", embed=True),
):
    """Extract incident data from article content."""
    from backend.services import get_extractor

    extractor = get_extractor()
    if not extractor.is_available():
        return {"success": False, "error": "LLM extraction not available"}

    result = extractor.extract(content, document_type)
    return result


# =====================
# Unified Pipeline Endpoints
# =====================

@router.get("/api/admin/pipeline/config")
def get_pipeline_config():
    """Get unified pipeline configuration."""
    from backend.services import get_pipeline
    pipeline = get_pipeline()
    return pipeline.get_stats()


@router.post("/api/admin/pipeline/process-article")
async def process_article_pipeline(
    article: dict = Body(...),
    skip_duplicate_check: bool = Body(False),
    skip_extraction: bool = Body(False),
    skip_approval: bool = Body(False),
):
    """Process a single article through the unified pipeline."""
    from backend.services import get_pipeline

    pipeline = get_pipeline()

    # Get existing articles for duplicate check
    existing = []
    if not skip_duplicate_check:
        if USE_DATABASE:
            existing = await get_all_incidents()
        else:
            existing = load_incidents()

    result = await pipeline.process_single(
        article,
        existing_articles=existing,
        skip_duplicate_check=skip_duplicate_check,
        skip_extraction=skip_extraction,
        skip_approval=skip_approval
    )

    return {
        "success": result.success,
        "article_id": result.article_id,
        "steps_completed": result.steps_completed,
        "duplicate_result": result.duplicate_result,
        "extraction_result": result.extraction_result,
        "approval_result": result.approval_result,
        "final_decision": result.final_decision,
        "error": result.error
    }


# =====================
# Settings Endpoints
# =====================

@router.get("/api/admin/settings")
def get_all_settings():
    """Get all application settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_all()


@router.get("/api/admin/settings/auto-approval")
def get_settings_auto_approval():
    """Get auto-approval settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_auto_approval()


@router.put("/api/admin/settings/auto-approval")
def update_settings_auto_approval(config: dict = Body(...)):
    """Update auto-approval settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_auto_approval(config)


@router.get("/api/admin/settings/duplicate")
def get_settings_duplicate():
    """Get duplicate detection settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_duplicate_detection()


@router.put("/api/admin/settings/duplicate")
def update_settings_duplicate(config: dict = Body(...)):
    """Update duplicate detection settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_duplicate_detection(config)


@router.get("/api/admin/settings/pipeline")
def get_settings_pipeline():
    """Get pipeline settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_pipeline()


@router.put("/api/admin/settings/pipeline")
def update_settings_pipeline(config: dict = Body(...)):
    """Update pipeline settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_pipeline(config)


@router.get("/api/admin/settings/event-clustering")
def get_settings_event_clustering():
    """Get event clustering settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_event_clustering()


@router.put("/api/admin/settings/event-clustering")
def update_settings_event_clustering(config: dict = Body(...)):
    """Update event clustering settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_event_clustering(config)


# =====================
# LLM Provider Endpoints
# =====================

@router.get("/api/admin/settings/llm")
def get_settings_llm():
    """Get LLM provider settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_llm()


@router.put("/api/admin/settings/llm")
def update_settings_llm(config: dict = Body(...)):
    """Update LLM provider settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_llm(config)


@router.get("/api/admin/llm/providers")
def get_llm_provider_status():
    """Get availability status of each LLM provider."""
    from backend.services.llm_provider import get_llm_router
    llm_router = get_llm_router()
    return {
        "providers": {
            name: {
                "available": available,
                "name": name,
            }
            for name, available in llm_router.provider_status().items()
        }
    }


@router.get("/api/admin/llm/models")
def get_llm_available_models():
    """Get available models from each provider."""
    from backend.services.llm_provider import get_llm_router
    llm_router = get_llm_router()

    models = {
        "anthropic": [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
        ],
        "ollama": [],
    }

    if llm_router.ollama.is_available():
        models["ollama"] = llm_router.ollama.list_models()

    return {"models": models}
