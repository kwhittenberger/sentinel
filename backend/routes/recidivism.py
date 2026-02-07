"""
Recidivism analytics and import saga routes.
Extracted from main.py.
"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(tags=["Recidivism"])


# =====================
# Recidivism & Analytics
# =====================


@router.get("/api/admin/recidivism/summary")
async def get_recidivism_summary():
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.get_analytics_summary()


@router.get("/api/admin/recidivism/actors")
async def list_recidivists(
    min_incidents: int = 2,
    page: int = 1,
    page_size: int = 50,
):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.list_recidivists(min_incidents, page, page_size)


@router.get("/api/admin/recidivism/actors/{actor_id}")
async def get_recidivism_profile(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.get_full_recidivism_profile(actor_id)


@router.get("/api/admin/recidivism/actors/{actor_id}/history")
async def get_actor_incident_history(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return {"history": await service.get_actor_history(actor_id)}


@router.get("/api/admin/recidivism/actors/{actor_id}/indicator")
async def get_actor_recidivism_indicator(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.get_recidivism_indicator(actor_id)


@router.get("/api/admin/recidivism/actors/{actor_id}/lifecycle")
async def get_defendant_lifecycle(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return {"lifecycle": await service.get_defendant_lifecycle(actor_id)}


@router.post("/api/admin/recidivism/refresh")
async def refresh_recidivism_analysis():
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.refresh_recidivism_analysis()


# =====================
# Import Sagas
# =====================


@router.get("/api/admin/import-sagas")
async def list_import_sagas(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.list_import_sagas(status, page, page_size)


@router.post("/api/admin/import-sagas")
async def create_import_saga(data: dict = Body(...)):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.create_import_saga(data)


@router.put("/api/admin/import-sagas/{saga_id}")
async def update_import_saga(saga_id: str, data: dict = Body(...)):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    result = await service.update_import_saga(saga_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Saga not found")
    return result
