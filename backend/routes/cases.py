"""
Cases & Legal Tracking route module.
Extracted from main.py — cases, charges, charge history, prosecutorial actions,
bail decisions, dispositions, case linking, and prosecutor stats.
"""

import uuid

from fastapi import APIRouter, HTTPException, Body

from backend.routes._shared import USE_DATABASE

router = APIRouter(tags=["Cases"])


@router.get("/api/admin/cases")
async def list_cases(
    status: str = None,
    case_type: str = None,
    jurisdiction: str = None,
    search: str = None,
    page: int = 1,
    page_size: int = 50,
):
    """List cases with optional filters."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_cases(
        status=status, case_type=case_type, jurisdiction=jurisdiction,
        search=search, page=page, page_size=page_size,
    )


@router.post("/api/admin/cases")
async def create_case(data: dict = Body(...)):
    """Create a new case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    if "case_type" not in data:
        raise HTTPException(status_code=400, detail="case_type is required")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.create_case(data)


@router.get("/api/admin/cases/{case_id}")
async def get_case(case_id: str):
    """Get a case by ID."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    result = await service.get_case(cid)
    if not result:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.put("/api/admin/cases/{case_id}")
async def update_case(case_id: str, data: dict = Body(...)):
    """Update a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    result = await service.update_case(cid, data)
    if not result:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


# --- Charges ---

@router.get("/api/admin/cases/{case_id}/charges")
async def list_charges(case_id: str):
    """List charges for a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_charges(cid)


@router.post("/api/admin/cases/{case_id}/charges")
async def create_charge(case_id: str, data: dict = Body(...)):
    """Create a charge within a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    if "charge_number" not in data or "charge_description" not in data:
        raise HTTPException(status_code=400, detail="charge_number and charge_description are required")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.create_charge(cid, data)


@router.put("/api/admin/charges/{charge_id}")
async def update_charge(charge_id: str, data: dict = Body(...)):
    """Update a charge."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        chid = uuid.UUID(charge_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid charge ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    result = await service.update_charge(chid, data)
    if not result:
        raise HTTPException(status_code=404, detail="Charge not found")
    return result


# --- Charge History ---

@router.get("/api/admin/cases/{case_id}/charge-history")
async def list_charge_history(case_id: str, charge_id: str = None):
    """List charge history for a case, optionally filtered by charge."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
        chid = uuid.UUID(charge_id) if charge_id else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_charge_history(cid, chid)


@router.post("/api/admin/charge-history")
async def record_charge_event(data: dict = Body(...)):
    """Record a charge history event."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    for field in ("charge_id", "case_id", "event_type"):
        if field not in data:
            raise HTTPException(status_code=400, detail=f"{field} is required")

    data["charge_id"] = uuid.UUID(data["charge_id"])
    data["case_id"] = uuid.UUID(data["case_id"])
    if data.get("actor_id"):
        data["actor_id"] = uuid.UUID(data["actor_id"])

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.record_charge_event(data)


# --- Prosecutorial Actions ---

@router.get("/api/admin/cases/{case_id}/prosecutorial-actions")
async def list_prosecutorial_actions(case_id: str):
    """List prosecutorial actions for a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_prosecutorial_actions(cid)


@router.post("/api/admin/prosecutorial-actions")
async def create_prosecutorial_action(data: dict = Body(...)):
    """Create a prosecutorial action."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    for field in ("case_id", "action_type"):
        if field not in data:
            raise HTTPException(status_code=400, detail=f"{field} is required")

    data["case_id"] = uuid.UUID(data["case_id"])
    if data.get("prosecutor_id"):
        data["prosecutor_id"] = uuid.UUID(data["prosecutor_id"])

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.create_prosecutorial_action(data)


# --- Bail Decisions ---

@router.get("/api/admin/cases/{case_id}/bail-decisions")
async def list_bail_decisions(case_id: str):
    """List bail decisions for a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_bail_decisions(cid)


@router.post("/api/admin/bail-decisions")
async def create_bail_decision(data: dict = Body(...)):
    """Create a bail decision."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    for field in ("case_id", "decision_type"):
        if field not in data:
            raise HTTPException(status_code=400, detail=f"{field} is required")

    data["case_id"] = uuid.UUID(data["case_id"])
    if data.get("judge_id"):
        data["judge_id"] = uuid.UUID(data["judge_id"])

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.create_bail_decision(data)


# --- Dispositions ---

@router.get("/api/admin/cases/{case_id}/dispositions")
async def list_dispositions(case_id: str):
    """List dispositions for a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_dispositions(cid)


@router.post("/api/admin/dispositions")
async def create_disposition(data: dict = Body(...)):
    """Create a disposition."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    for field in ("case_id", "disposition_type"):
        if field not in data:
            raise HTTPException(status_code=400, detail=f"{field} is required")

    data["case_id"] = uuid.UUID(data["case_id"])
    if data.get("charge_id"):
        data["charge_id"] = uuid.UUID(data["charge_id"])
    if data.get("judge_id"):
        data["judge_id"] = uuid.UUID(data["judge_id"])

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.create_disposition(data)


# --- Case Linking ---

@router.get("/api/admin/cases/{case_id}/incidents")
async def list_case_incidents(case_id: str):
    """List incidents linked to a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_case_incidents(cid)


@router.post("/api/admin/cases/{case_id}/incidents")
async def link_case_incident(case_id: str, data: dict = Body(...)):
    """Link an incident to a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    data["case_id"] = uuid.UUID(case_id)
    if "incident_id" not in data:
        raise HTTPException(status_code=400, detail="incident_id is required")
    data["incident_id"] = uuid.UUID(data["incident_id"])

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.link_incident(data)


@router.get("/api/admin/cases/{case_id}/actors")
async def list_case_actors(case_id: str):
    """List actors linked to a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.list_case_actors(cid)


@router.post("/api/admin/cases/{case_id}/actors")
async def link_case_actor(case_id: str, data: dict = Body(...)):
    """Link an actor to a case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    data["case_id"] = uuid.UUID(case_id)
    if "actor_id" not in data:
        raise HTTPException(status_code=400, detail="actor_id is required")
    data["actor_id"] = uuid.UUID(data["actor_id"])
    if data.get("role_type_id"):
        data["role_type_id"] = uuid.UUID(data["role_type_id"])

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.link_actor(data)


# --- Prosecutor Stats ---

@router.get("/api/admin/prosecutor-stats")
async def get_prosecutor_stats(prosecutor_id: str = None):
    """Get prosecutor performance stats."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    pid = uuid.UUID(prosecutor_id) if prosecutor_id else None

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.get_prosecutor_stats(pid)


@router.post("/api/admin/prosecutor-stats/refresh")
async def refresh_prosecutor_stats():
    """Refresh the prosecutor stats materialized view."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    await service.refresh_prosecutor_stats()
    return {"success": True, "message": "Prosecutor stats refreshed"}
