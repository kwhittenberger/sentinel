"""
Events, Actors, and Persons API routes.

Extracted from main.py — event CRUD, actor CRUD/merge/linking,
and legacy person endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Body, HTTPException, Query

from backend.routes._shared import USE_DATABASE, require_database, parse_uuid

router = APIRouter(tags=["Events & Actors"])


# =====================
# Events API
# =====================


@router.get("/api/events")
async def list_events(
    event_type: Optional[str] = None,
    state: Optional[str] = None,
    ongoing_only: bool = False,
    limit: int = 50,
    offset: int = 0
):
    """List events."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.event_service import get_event_service

    event_service = get_event_service()
    events = await event_service.list_events(
        event_type=event_type,
        state=state,
        ongoing_only=ongoing_only,
        limit=limit,
        offset=offset,
    )

    return [
        {
            "id": str(e.id),
            "name": e.name,
            "slug": e.slug,
            "event_type": e.event_type,
            "start_date": e.start_date.isoformat() if e.start_date else None,
            "end_date": e.end_date.isoformat() if e.end_date else None,
            "ongoing": e.ongoing,
            "primary_state": e.primary_state,
            "primary_city": e.primary_city,
            "incident_count": e.incident_count,
        }
        for e in events
    ]


@router.get("/api/events/suggestions")
async def get_event_suggestions(
    limit: int = 20,
    category: Optional[str] = Query(None, description="Filter by category (enforcement/crime)"),
    state: Optional[str] = Query(None, description="Filter by state"),
    date_start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    exclude_linked: bool = Query(True, description="Exclude already-linked incidents"),
):
    """Get AI-suggested event groupings using smart clustering."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.event_clustering import get_clustering_service
    from datetime import date as date_type

    clustering_service = get_clustering_service()

    # Parse dates if provided
    start = date_type.fromisoformat(date_start) if date_start else None
    end = date_type.fromisoformat(date_end) if date_end else None

    suggestions = await clustering_service.generate_suggestions(
        category=category,
        state=state,
        date_start=start,
        date_end=end,
        exclude_linked=exclude_linked,
        limit=limit
    )
    return suggestions


@router.get("/api/events/{event_id}")
async def get_event(event_id: str, include_incidents: bool = True):
    """Get event with linked incidents."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.event_service import get_event_service
    import uuid

    event_service = get_event_service()

    try:
        event_uuid = uuid.UUID(event_id)
        event = await event_service.get_event(event_uuid)
    except ValueError:
        event = await event_service.get_event_by_slug(event_id)

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    result = {
        "id": str(event.id),
        "name": event.name,
        "slug": event.slug,
        "description": event.description,
        "event_type": event.event_type,
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "ongoing": event.ongoing,
        "primary_state": event.primary_state,
        "primary_city": event.primary_city,
        "geographic_scope": event.geographic_scope,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "ai_summary": event.ai_summary,
        "tags": event.tags,
        "incident_count": event.incident_count,
    }

    if include_incidents:
        incidents = await event_service.get_event_incidents(event.id)
        result["incidents"] = incidents
        # Also include actors for all incidents in this event
        actors = await event_service.get_event_actors(event.id)
        result["actors"] = actors

    return result


@router.post("/api/events")
async def create_event(data: dict = Body(...)):
    """Create a new event."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.event_service import get_event_service
    from datetime import date

    event_service = get_event_service()

    event = await event_service.create_event(
        name=data["name"],
        start_date=date.fromisoformat(data["start_date"]),
        event_type=data.get("event_type"),
        slug=data.get("slug"),
        description=data.get("description"),
        end_date=date.fromisoformat(data["end_date"]) if data.get("end_date") else None,
        ongoing=data.get("ongoing", False),
        primary_state=data.get("primary_state"),
        primary_city=data.get("primary_city"),
        geographic_scope=data.get("geographic_scope"),
        tags=data.get("tags"),
    )

    return {"id": str(event.id), "name": event.name, "slug": event.slug}


@router.post("/api/events/{event_id}/incidents")
async def link_incident_to_event(event_id: str, data: dict = Body(...)):
    """Link an incident to an event."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.event_service import get_event_service
    import uuid

    event_service = get_event_service()
    event_uuid = uuid.UUID(event_id)
    incident_uuid = uuid.UUID(data["incident_id"])

    link = await event_service.link_incident(
        event_id=event_uuid,
        incident_id=incident_uuid,
        is_primary=data.get("is_primary", False),
        sequence_number=data.get("sequence_number"),
        assigned_by=data.get("assigned_by", "manual"),
    )

    return {"id": str(link.id)}


@router.delete("/api/events/{event_id}/incidents/{incident_id}")
async def unlink_incident_from_event(event_id: str, incident_id: str):
    """Unlink an incident from an event."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.event_service import get_event_service
    import uuid

    event_service = get_event_service()
    await event_service.unlink_incident(uuid.UUID(event_id), uuid.UUID(incident_id))
    return {"success": True}


# =====================
# Actors API
# =====================


@router.get("/api/actors")
async def list_actors(
    actor_type: Optional[str] = None,
    search: Optional[str] = None,
    is_law_enforcement: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
):
    """List actors."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service, ActorType

    actor_service = get_actor_service()

    at = ActorType(actor_type) if actor_type else None

    if search:
        actors = await actor_service.search_actors(search, actor_type=at, limit=limit)
    else:
        actors = await actor_service.list_actors(
            actor_type=at,
            is_law_enforcement=is_law_enforcement,
            limit=limit,
            offset=offset,
        )

    return [
        {
            "id": str(a.id),
            "canonical_name": a.canonical_name,
            "actor_type": a.actor_type.value,
            "aliases": a.aliases,
            "immigration_status": a.immigration_status,
            "is_law_enforcement": a.is_law_enforcement,
            "incident_count": a.incident_count,
            "roles_played": a.roles_played,
        }
        for a in actors
    ]


@router.get("/api/actors/merge-suggestions")
async def get_merge_suggestions(similarity_threshold: float = 0.5, limit: int = 50):
    """
    Get suggestions for actors that might be duplicates.

    Uses multiple matching strategies:
    - Trigram similarity (pg_trgm)
    - Name containment (e.g., "Alex Pretti" contained in "Alex Jeffrey Pretti")
    - First/last name matching (handles middle name differences)
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service

    actor_service = get_actor_service()
    suggestions = await actor_service.get_merge_suggestions(
        similarity_threshold=similarity_threshold,
        limit=limit,
    )
    return suggestions


@router.get("/api/actors/{actor_id}/similar")
async def get_similar_actors(actor_id: str, threshold: float = 0.4, limit: int = 10):
    """Find actors similar to a specific actor."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch
    import uuid

    try:
        actor_uuid = uuid.UUID(actor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid actor ID")

    # Get the actor's name
    actor_row = await fetch("SELECT canonical_name, actor_type FROM actors WHERE id = $1", actor_uuid)
    if not actor_row:
        raise HTTPException(status_code=404, detail="Actor not found")

    actor_name = actor_row[0]["canonical_name"]
    actor_type = actor_row[0]["actor_type"]

    # Find similar actors using multiple strategies
    query = """
        WITH target AS (
            SELECT
                $1::uuid as id,
                $2::text as name,
                split_part(lower($2), ' ', 1) as first_name,
                split_part(lower($2), ' ', -1) as last_name
        )
        SELECT DISTINCT a.id, a.canonical_name,
               GREATEST(
                   similarity(a.canonical_name, t.name),
                   CASE WHEN lower(a.canonical_name) LIKE '%' || lower(t.name) || '%'
                        OR lower(t.name) LIKE '%' || lower(a.canonical_name) || '%'
                   THEN 0.85 ELSE 0 END,
                   CASE WHEN split_part(lower(a.canonical_name), ' ', 1) = t.first_name
                        AND split_part(lower(a.canonical_name), ' ', -1) = t.last_name
                        AND t.first_name != '' AND t.last_name != ''
                   THEN 0.9 ELSE 0 END
               ) as best_similarity
        FROM actors a, target t
        WHERE a.id != t.id
          AND NOT a.is_merged
          AND a.actor_type = $3
          AND (
              similarity(a.canonical_name, t.name) > $4
              OR lower(a.canonical_name) LIKE '%' || lower(t.name) || '%'
              OR lower(t.name) LIKE '%' || lower(a.canonical_name) || '%'
              OR (
                  split_part(lower(a.canonical_name), ' ', 1) = t.first_name
                  AND split_part(lower(a.canonical_name), ' ', -1) = t.last_name
                  AND length(t.first_name) > 2 AND length(t.last_name) > 2
              )
          )
        ORDER BY best_similarity DESC
        LIMIT $5
    """

    rows = await fetch(query, actor_uuid, actor_name, actor_type, threshold, limit)

    return [
        {
            "id": str(row["id"]),
            "canonical_name": row["canonical_name"],
            "similarity": float(row["best_similarity"])
        }
        for row in rows
    ]


@router.post("/api/actors/merge")
async def merge_actors(data: dict = Body(...)):
    """Merge multiple actors into one."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service
    import uuid

    actor_service = get_actor_service()

    primary_id = uuid.UUID(data["primary_actor_id"])
    secondary_ids = [uuid.UUID(id) for id in data.get("secondary_actor_ids", [data.get("secondary_actor_id")])]

    merged = await actor_service.merge_actors(
        primary_actor_id=primary_id,
        secondary_actor_ids=secondary_ids,
        merge_aliases=data.get("merge_aliases", True),
    )

    return {"id": str(merged.id), "canonical_name": merged.canonical_name, "aliases": merged.aliases}


@router.get("/api/actors/{actor_id}")
async def get_actor(actor_id: str, include_incidents: bool = True):
    """Get actor with incident history."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service
    import uuid

    actor_service = get_actor_service()
    actor_uuid = uuid.UUID(actor_id)

    actor = await actor_service.get_actor(actor_uuid)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    result = {
        "id": str(actor.id),
        "canonical_name": actor.canonical_name,
        "actor_type": actor.actor_type.value,
        "aliases": actor.aliases,
        "date_of_birth": actor.date_of_birth.isoformat() if actor.date_of_birth else None,
        "gender": actor.gender,
        "nationality": actor.nationality,
        "immigration_status": actor.immigration_status,
        "prior_deportations": actor.prior_deportations,
        "organization_type": actor.organization_type,
        "is_government_entity": actor.is_government_entity,
        "is_law_enforcement": actor.is_law_enforcement,
        "jurisdiction": actor.jurisdiction,
        "description": actor.description,
        "confidence_score": actor.confidence_score,
        "incident_count": actor.incident_count,
        "roles_played": actor.roles_played,
    }

    if include_incidents:
        incidents = await actor_service.get_actor_incidents(actor_uuid)
        result["incidents"] = incidents

    relations = await actor_service.get_actor_relations(actor_uuid)
    result["relations"] = [
        {
            "id": str(r.id),
            "related_actor_id": str(r.related_actor_id),
            "relation_type": r.relation_type.value,
            "confidence": r.confidence,
        }
        for r in relations
    ]

    return result


@router.post("/api/actors")
async def create_actor(data: dict = Body(...)):
    """Create a new actor."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service, ActorType
    from datetime import date

    actor_service = get_actor_service()

    actor = await actor_service.create_actor(
        canonical_name=data["canonical_name"],
        actor_type=ActorType(data["actor_type"]),
        aliases=data.get("aliases"),
        date_of_birth=date.fromisoformat(data["date_of_birth"]) if data.get("date_of_birth") else None,
        gender=data.get("gender"),
        nationality=data.get("nationality"),
        immigration_status=data.get("immigration_status"),
        prior_deportations=data.get("prior_deportations", 0),
        organization_type=data.get("organization_type"),
        is_government_entity=data.get("is_government_entity", False),
        is_law_enforcement=data.get("is_law_enforcement", False),
        jurisdiction=data.get("jurisdiction"),
        description=data.get("description"),
    )

    return {"id": str(actor.id), "canonical_name": actor.canonical_name}


@router.put("/api/actors/{actor_id}")
async def update_actor(actor_id: str, data: dict = Body(...)):
    """Update an actor."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service
    import uuid

    actor_service = get_actor_service()
    actor = await actor_service.update_actor(uuid.UUID(actor_id), data)
    return {"id": str(actor.id), "canonical_name": actor.canonical_name}


@router.post("/api/actors/{actor_id}/incidents")
async def link_actor_to_incident(actor_id: str, data: dict = Body(...)):
    """Link an actor to an incident."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service, ActorRole
    import uuid

    actor_service = get_actor_service()

    link = await actor_service.link_actor_to_incident(
        incident_id=uuid.UUID(data["incident_id"]),
        actor_id=uuid.UUID(actor_id),
        role=ActorRole(data["role"]),
        role_detail=data.get("role_detail"),
        is_primary=data.get("is_primary", False),
        assigned_by=data.get("assigned_by", "manual"),
    )

    return {"id": str(link.id)}


# =====================
# Persons API (Legacy)
# =====================


@router.get("/api/persons")
def get_persons(
    role: Optional[str] = Query(None, description="Filter by role: victim, offender"),
    gang_affiliated: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List persons (victims and offenders)."""
    # Placeholder - will be implemented with database
    return {"persons": [], "total": 0}


@router.get("/api/persons/{person_id}")
def get_person(person_id: str):
    """Get person details with their incidents."""
    # Placeholder - will be implemented with database
    return {"error": "Database not enabled"}, 501
