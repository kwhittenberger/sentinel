"""
Domain and category management routes.
Extracted from main.py.
"""

import uuid

from fastapi import APIRouter, Query, HTTPException, Body

router = APIRouter(tags=["Domains"])


# =====================
# Domain Endpoints
# =====================

@router.get("/api/admin/domains")
async def list_domains(include_inactive: bool = Query(False)):
    """List all event domains."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    return {"domains": await service.list_domains(include_inactive=include_inactive)}


@router.post("/api/admin/domains")
async def create_domain(data: dict = Body(...)):
    """Create a new event domain."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    if not data.get("name") or not data.get("slug"):
        raise HTTPException(status_code=400, detail="name and slug are required")
    try:
        domain = await service.create_domain(data)
        return domain
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/admin/domains/{slug}")
async def get_domain(slug: str):
    """Get a domain by slug."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    domain = await service.get_domain(slug)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@router.put("/api/admin/domains/{slug}")
async def update_domain(slug: str, data: dict = Body(...)):
    """Update a domain."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    try:
        domain = await service.update_domain(slug, data)
        if not domain:
            raise HTTPException(status_code=404, detail="Domain not found")
        return domain
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================
# Category Endpoints (nested under domains)
# =====================

@router.get("/api/admin/domains/{slug}/categories")
async def list_categories_for_domain(slug: str, include_inactive: bool = Query(False)):
    """List categories within a domain."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    categories = await service.list_categories(domain_slug=slug, include_inactive=include_inactive)
    return {"categories": categories}


@router.post("/api/admin/domains/{slug}/categories")
async def create_category(slug: str, data: dict = Body(...)):
    """Create a category within a domain."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    if not data.get("name") or not data.get("slug"):
        raise HTTPException(status_code=400, detail="name and slug are required")
    try:
        category = await service.create_category(slug, data)
        if not category:
            raise HTTPException(status_code=404, detail="Domain not found")
        return category
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================
# Category Endpoints (standalone)
# =====================

@router.get("/api/admin/categories/{category_id}")
async def get_category(category_id: str):
    """Get a single category with field definitions."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    category = await service.get_category(uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.get("/api/admin/category-fields")
async def get_category_fields():
    """All category fields grouped by domain, from DB with 60s cache."""
    from backend.services.extraction_prompts import get_all_category_fields_async
    return await get_all_category_fields_async()


@router.put("/api/admin/categories/{category_id}")
async def update_category(category_id: str, data: dict = Body(...)):
    """Update a category."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    try:
        category = await service.update_category(uuid.UUID(category_id), data)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        return category
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
