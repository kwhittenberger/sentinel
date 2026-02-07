"""
Incident types and prompts management routes.
Extracted from main.py — CRUD for incident types, field definitions, prompts, and token usage.
"""

from typing import Optional
from fastapi import APIRouter, Body, HTTPException

from backend.routes._shared import USE_DATABASE

router = APIRouter(tags=["Types & Prompts"])


# =====================
# Incident Types API
# =====================

@router.get("/api/admin/types")
async def list_incident_types(
    category: Optional[str] = None,
    active_only: bool = True
):
    """List all incident types."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service, IncidentCategory

    type_service = get_incident_type_service()
    cat = IncidentCategory(category) if category else None
    types = await type_service.list_types(category=cat, active_only=active_only)

    return [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "display_name": t.display_name,
            "category": t.category.value,
            "icon": t.icon,
            "color": t.color,
            "is_active": t.is_active,
            "severity_weight": t.severity_weight,
        }
        for t in types
    ]


@router.get("/api/admin/types/{type_id}")
async def get_incident_type(type_id: str):
    """Get incident type with full configuration."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service
    import uuid

    type_service = get_incident_type_service()

    try:
        type_uuid = uuid.UUID(type_id)
    except ValueError:
        # Try by slug
        incident_type = await type_service.get_type_by_slug(type_id)
        if not incident_type:
            raise HTTPException(status_code=404, detail="Incident type not found")
    else:
        incident_type = await type_service.get_type(type_uuid)
        if not incident_type:
            raise HTTPException(status_code=404, detail="Incident type not found")

    fields = await type_service.get_field_definitions(incident_type.id)
    pipeline_config = await type_service.get_type_pipeline_config(incident_type.id)

    return {
        "id": str(incident_type.id),
        "name": incident_type.name,
        "slug": incident_type.slug,
        "display_name": incident_type.display_name,
        "description": incident_type.description,
        "category": incident_type.category.value,
        "icon": incident_type.icon,
        "color": incident_type.color,
        "is_active": incident_type.is_active,
        "severity_weight": incident_type.severity_weight,
        "approval_thresholds": incident_type.approval_thresholds,
        "validation_rules": incident_type.validation_rules,
        "fields": [
            {
                "id": str(f.id),
                "name": f.name,
                "display_name": f.display_name,
                "field_type": f.field_type.value,
                "required": f.required,
                "enum_values": f.enum_values,
                "extraction_hint": f.extraction_hint,
                "display_order": f.display_order,
            }
            for f in fields
        ],
        "pipeline_config": [
            {
                "id": str(pc.id),
                "stage_id": str(pc.pipeline_stage_id),
                "enabled": pc.enabled,
                "execution_order": pc.execution_order,
                "stage_config": pc.stage_config,
            }
            for pc in pipeline_config
        ],
    }


@router.post("/api/admin/types")
async def create_incident_type(data: dict = Body(...)):
    """Create a new incident type."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service, IncidentCategory

    type_service = get_incident_type_service()

    incident_type = await type_service.create_type(
        name=data["name"],
        category=IncidentCategory(data["category"]),
        slug=data.get("slug"),
        display_name=data.get("display_name"),
        description=data.get("description"),
        icon=data.get("icon"),
        color=data.get("color"),
        severity_weight=data.get("severity_weight", 1.0),
        approval_thresholds=data.get("approval_thresholds"),
        validation_rules=data.get("validation_rules"),
    )

    return {"id": str(incident_type.id), "name": incident_type.name, "slug": incident_type.slug}


@router.put("/api/admin/types/{type_id}")
async def update_incident_type(type_id: str, data: dict = Body(...)):
    """Update an incident type."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service
    import uuid

    type_service = get_incident_type_service()

    try:
        type_uuid = uuid.UUID(type_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid type ID")

    incident_type = await type_service.update_type(type_uuid, data)
    return {"id": str(incident_type.id), "name": incident_type.name}


@router.get("/api/admin/types/{type_id}/fields")
async def get_type_fields(type_id: str):
    """Get field definitions for an incident type."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service
    import uuid

    type_service = get_incident_type_service()
    type_uuid = uuid.UUID(type_id)
    fields = await type_service.get_field_definitions(type_uuid)

    return [
        {
            "id": str(f.id),
            "name": f.name,
            "display_name": f.display_name,
            "field_type": f.field_type.value,
            "description": f.description,
            "required": f.required,
            "enum_values": f.enum_values,
            "extraction_hint": f.extraction_hint,
            "display_order": f.display_order,
            "show_in_list": f.show_in_list,
            "show_in_detail": f.show_in_detail,
        }
        for f in fields
    ]


@router.post("/api/admin/types/{type_id}/fields")
async def create_type_field(type_id: str, data: dict = Body(...)):
    """Create a field definition for an incident type."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.incident_type_service import get_incident_type_service, FieldType
    import uuid

    type_service = get_incident_type_service()
    type_uuid = uuid.UUID(type_id)

    field_def = await type_service.create_field(
        incident_type_id=type_uuid,
        name=data["name"],
        display_name=data["display_name"],
        field_type=FieldType(data["field_type"]),
        description=data.get("description"),
        enum_values=data.get("enum_values"),
        required=data.get("required", False),
        extraction_hint=data.get("extraction_hint"),
        display_order=data.get("display_order", 0),
    )

    return {"id": str(field_def.id), "name": field_def.name}


# =====================
# Prompts API
# =====================

@router.get("/api/admin/prompts")
async def list_prompts(
    prompt_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50
):
    """List prompts with optional filters."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.prompt_manager import get_prompt_manager, PromptType, PromptStatus

    prompt_manager = get_prompt_manager()

    pt = PromptType(prompt_type) if prompt_type else None
    ps = PromptStatus(status) if status else None

    prompts = await prompt_manager.list_prompts(prompt_type=pt, status=ps, limit=limit)

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "slug": p.slug,
            "prompt_type": p.prompt_type.value,
            "version": p.version,
            "status": p.status.value,
            "model_name": p.model_name,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in prompts
    ]


@router.get("/api/admin/prompts/{prompt_id}")
async def get_prompt(prompt_id: str):
    """Get prompt with version history."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.prompt_manager import get_prompt_manager
    import uuid

    prompt_manager = get_prompt_manager()

    try:
        prompt_uuid = uuid.UUID(prompt_id)
        prompt = await prompt_manager.get_prompt_by_id(prompt_uuid)
    except ValueError:
        # Try loading by slug
        prompts = await prompt_manager.list_prompts(limit=100)
        prompt = next((p for p in prompts if p.slug == prompt_id), None)

    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Get version history
    history = await prompt_manager.get_version_history(prompt.slug)

    return {
        "id": str(prompt.id),
        "name": prompt.name,
        "slug": prompt.slug,
        "description": prompt.description,
        "prompt_type": prompt.prompt_type.value,
        "incident_type_id": str(prompt.incident_type_id) if prompt.incident_type_id else None,
        "system_prompt": prompt.system_prompt,
        "user_prompt_template": prompt.user_prompt_template,
        "output_schema": prompt.output_schema,
        "version": prompt.version,
        "status": prompt.status.value,
        "model_name": prompt.model_name,
        "max_tokens": prompt.max_tokens,
        "temperature": prompt.temperature,
        "traffic_percentage": prompt.traffic_percentage,
        "ab_test_group": prompt.ab_test_group,
        "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
        "activated_at": prompt.activated_at.isoformat() if prompt.activated_at else None,
        "version_history": [
            {
                "id": str(v.id),
                "version": v.version,
                "status": v.status.value,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in history
        ],
    }


@router.post("/api/admin/prompts")
async def create_prompt(data: dict = Body(...)):
    """Create a new prompt."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.prompt_manager import get_prompt_manager, PromptType
    import uuid as uuid_module

    prompt_manager = get_prompt_manager()

    prompt = await prompt_manager.create_prompt(
        name=data["name"],
        slug=data["slug"],
        prompt_type=PromptType(data["prompt_type"]),
        system_prompt=data["system_prompt"],
        user_prompt_template=data["user_prompt_template"],
        description=data.get("description"),
        incident_type_id=uuid_module.UUID(data["incident_type_id"]) if data.get("incident_type_id") else None,
        output_schema=data.get("output_schema"),
        model_name=data.get("model_name", "claude-sonnet-4-20250514"),
        max_tokens=data.get("max_tokens", 2000),
        temperature=data.get("temperature", 0.0),
    )

    return {"id": str(prompt.id), "name": prompt.name, "slug": prompt.slug, "version": prompt.version}


@router.put("/api/admin/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, data: dict = Body(...)):
    """Update a prompt (creates new version)."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.prompt_manager import get_prompt_manager
    import uuid

    prompt_manager = get_prompt_manager()
    prompt_uuid = uuid.UUID(prompt_id)

    new_version = await prompt_manager.create_version(prompt_uuid, data)
    return {
        "id": str(new_version.id),
        "version": new_version.version,
        "status": new_version.status.value,
    }


@router.post("/api/admin/prompts/{prompt_id}/activate")
async def activate_prompt(prompt_id: str):
    """Activate a specific prompt version."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.prompt_manager import get_prompt_manager
    import uuid

    prompt_manager = get_prompt_manager()
    prompt_uuid = uuid.UUID(prompt_id)

    activated = await prompt_manager.activate_version(prompt_uuid)
    return {"id": str(activated.id), "status": activated.status.value}


@router.get("/api/admin/prompts/{prompt_id}/executions")
async def get_prompt_executions(prompt_id: str, days: int = 30):
    """Get execution statistics for a prompt."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.prompt_manager import get_prompt_manager
    import uuid

    prompt_manager = get_prompt_manager()
    prompt_uuid = uuid.UUID(prompt_id)

    stats = await prompt_manager.get_execution_stats(prompt_uuid, days=days)
    return stats


@router.get("/api/admin/prompts/token-usage")
async def get_token_usage_summary(days: int = 30):
    """Get token usage and cost summary across all prompts."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch

    # Overall token usage
    overall_query = """
        SELECT
            COUNT(*) as total_executions,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(input_tokens + output_tokens) as total_tokens,
            AVG(confidence_score) as avg_confidence,
            MIN(created_at) as first_execution,
            MAX(created_at) as last_execution
        FROM prompt_executions
        WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
    """ % days

    overall_rows = await fetch(overall_query)
    overall = dict(overall_rows[0]) if overall_rows else {}

    # By prompt breakdown (from view)
    by_prompt_query = """
        SELECT * FROM token_cost_summary
        ORDER BY estimated_cost_usd DESC
        LIMIT 20
    """
    by_prompt_rows = await fetch(by_prompt_query)

    # Daily usage (from view)
    daily_query = """
        SELECT * FROM token_usage_by_day
        ORDER BY date DESC
        LIMIT 30
    """
    daily_rows = await fetch(daily_query)

    # Format results
    return {
        "overall": {
            "total_executions": overall.get("total_executions", 0),
            "total_input_tokens": int(overall.get("total_input_tokens") or 0),
            "total_output_tokens": int(overall.get("total_output_tokens") or 0),
            "total_tokens": int(overall.get("total_tokens") or 0),
            "avg_confidence": float(overall.get("avg_confidence") or 0),
            "first_execution": str(overall.get("first_execution")) if overall.get("first_execution") else None,
            "last_execution": str(overall.get("last_execution")) if overall.get("last_execution") else None,
        },
        "by_prompt": [
            {
                "slug": row["slug"],
                "version": row["version"],
                "model_name": row["model_name"],
                "executions": row["executions"],
                "total_input_tokens": int(row["total_input_tokens"] or 0),
                "total_output_tokens": int(row["total_output_tokens"] or 0),
                "estimated_cost_usd": float(row["estimated_cost_usd"] or 0),
            }
            for row in by_prompt_rows
        ],
        "daily": [
            {
                "date": str(row["date"]),
                "slug": row["slug"],
                "version": row["version"],
                "prompt_type": row["prompt_type"],
                "executions": row["executions"],
                "total_input_tokens": int(row["total_input_tokens"] or 0),
                "total_output_tokens": int(row["total_output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "avg_confidence": float(row["avg_confidence"] or 0) if row.get("avg_confidence") else None,
            }
            for row in daily_rows
        ],
    }
