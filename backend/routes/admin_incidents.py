"""
Admin incident CRUD routes.
Extracted from main.py — incident browser, editing, export, relationships.
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Body

from backend.routes._shared import USE_DATABASE, get_all_incidents, load_incidents

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin Incidents"])


# =====================
# Incident Relationships
# =====================


@router.get("/api/admin/incidents/{incident_id}/relationships")
async def list_incident_relationships(incident_id: str):
    """List relationships for an incident."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    relationships = await service.list_relationships(uuid.UUID(incident_id))
    return {"relationships": relationships}


@router.post("/api/admin/incidents/relationships")
async def create_incident_relationship(data: dict = Body(...)):
    """Create a relationship between two incidents."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    required = ["source_incident_id", "target_incident_id", "relationship_type"]
    for field in required:
        if field not in data:
            raise HTTPException(status_code=400, detail=f"{field} is required")
    # Convert string UUIDs
    data["source_incident_id"] = uuid.UUID(data["source_incident_id"])
    data["target_incident_id"] = uuid.UUID(data["target_incident_id"])
    try:
        rel = await service.create_relationship(data)
        if not rel:
            raise HTTPException(status_code=400, detail="Failed to create relationship")
        return rel
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================
# Incident Browser Endpoints
# =====================

@router.get("/api/admin/incidents")
async def admin_list_incidents(
    category: Optional[str] = Query(None, description="Filter by category: enforcement or crime"),
    state: Optional[str] = Query(None, description="Filter by state"),
    status: Optional[str] = Query(None, description="Filter by curation status"),
    search: Optional[str] = Query(None, description="Search text"),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List incidents with pagination and filters for admin management."""
    if USE_DATABASE:
        incidents = await get_all_incidents()
    else:
        incidents = load_incidents()

    # Apply filters
    if category:
        incidents = [i for i in incidents if i.get('category', 'enforcement') == category]
    if state:
        incidents = [i for i in incidents if i.get('state') == state]
    if status:
        incidents = [i for i in incidents if i.get('curation_status') == status]
    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]
    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]
    if search:
        search_lower = search.lower()
        incidents = [
            i for i in incidents
            if search_lower in (i.get('notes') or '').lower()
            or search_lower in (i.get('victim_name') or '').lower()
            or search_lower in (i.get('description') or '').lower()
            or search_lower in (i.get('city') or '').lower()
        ]

    total = len(incidents)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = incidents[start:end]

    return {
        "incidents": paginated,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/api/admin/incidents/{incident_id}")
async def admin_get_incident(incident_id: str):
    """Get a single incident by ID for admin editing."""
    if USE_DATABASE:
        from backend.database import fetch
        import uuid
        try:
            incident_uuid = uuid.UUID(incident_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid incident ID format")

        rows = await fetch("""
            SELECT i.*, it.name as incident_type,
                   ed.name as domain_name, ed.slug as domain_slug,
                   ec.name as category_name, ec.slug as category_slug
            FROM incidents i
            LEFT JOIN incident_types it ON i.incident_type_id = it.id
            LEFT JOIN event_domains ed ON i.domain_id = ed.id
            LEFT JOIN event_categories ec ON i.category_id = ec.id
            WHERE i.id = $1
        """, incident_uuid)

        if not rows:
            raise HTTPException(status_code=404, detail="Incident not found")

        row = dict(rows[0])
        if row.get('date'):
            row['date'] = row['date'].isoformat()

        # Fetch sources for this incident
        sources_query = """
            SELECT id, url, title, published_date, is_primary, created_at
            FROM incident_sources
            WHERE incident_id = $1
            ORDER BY is_primary DESC, created_at ASC
        """
        source_rows = await fetch(sources_query, incident_uuid)
        row['sources'] = [
            {
                'id': str(s['id']),
                'url': s['url'],
                'title': s.get('title'),
                'published_date': s['published_date'].isoformat() if s.get('published_date') else None,
                'is_primary': s.get('is_primary', False),
                'created_at': s['created_at'].isoformat() if s.get('created_at') else None,
            }
            for s in source_rows
        ]

        # Fetch actors linked to this incident
        actors_query = """
            SELECT a.id, a.canonical_name, a.actor_type, a.aliases,
                   a.gender, a.nationality, a.immigration_status, a.prior_deportations,
                   a.is_law_enforcement, a.is_government_entity, a.description,
                   ia.role, ia.role_detail, ia.is_primary,
                   art.name as role_type_name, art.slug as role_type_slug
            FROM actors a
            JOIN incident_actors ia ON a.id = ia.actor_id
            LEFT JOIN actor_role_types art ON ia.role_type_id = art.id
            WHERE ia.incident_id = $1
            ORDER BY ia.is_primary DESC NULLS LAST, ia.created_at ASC
        """
        actor_rows = await fetch(actors_query, incident_uuid)
        row['actors'] = [
            {
                'id': str(a['id']),
                'canonical_name': a['canonical_name'],
                'actor_type': a['actor_type'],
                'role': a['role'],
                'role_type': a.get('role_type_slug'),
                'role_type_name': a.get('role_type_name'),
                'is_primary': a.get('is_primary', False),
                'immigration_status': a.get('immigration_status'),
                'nationality': a.get('nationality'),
                'gender': a.get('gender'),
                'is_law_enforcement': a.get('is_law_enforcement', False),
                'prior_deportations': a.get('prior_deportations'),
            }
            for a in actor_rows
        ]

        # Fetch events linked to this incident
        events_query = """
            SELECT e.id, e.name, e.event_type, e.start_date, e.end_date, e.description
            FROM events e
            JOIN incident_events ie ON e.id = ie.event_id
            WHERE ie.incident_id = $1
            ORDER BY e.start_date ASC NULLS LAST
        """
        event_rows = await fetch(events_query, incident_uuid)
        row['linked_events'] = [
            {
                'id': str(ev['id']),
                'name': ev['name'],
                'event_type': ev.get('event_type'),
                'start_date': ev['start_date'].isoformat() if ev.get('start_date') else None,
                'description': ev.get('description'),
            }
            for ev in event_rows
        ]

        return row
    else:
        incidents = load_incidents()
        for inc in incidents:
            if inc.get('id') == incident_id:
                return inc
        raise HTTPException(status_code=404, detail="Incident not found")


@router.get("/api/admin/incidents/{incident_id}/articles")
async def admin_get_incident_articles(incident_id: str):
    """Get ingested articles linked to an incident, including content."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch
    import uuid
    try:
        incident_uuid = uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident ID format")

    rows = await fetch("""
        SELECT id, title, content, source_name, source_url, published_date, fetched_at,
               relevance_score, extraction_confidence, status, extracted_data
        FROM ingested_articles
        WHERE incident_id = $1
        ORDER BY published_date DESC NULLS LAST, fetched_at DESC
    """, incident_uuid)

    articles = []
    for row in rows:
        article = dict(row)
        article["id"] = str(article["id"])
        if article.get("published_date"):
            article["published_date"] = article["published_date"].isoformat()
        if article.get("fetched_at"):
            article["fetched_at"] = article["fetched_at"].isoformat()
        for num_field in ("relevance_score", "extraction_confidence"):
            if article.get(num_field) is not None:
                article[num_field] = float(article[num_field])
        # Parse extracted_data JSON
        ed = article.get("extracted_data")
        if isinstance(ed, str):
            import json as json_module
            try:
                ed = json_module.loads(ed)
            except Exception:
                ed = None
        # Unwrap nested extracted_data key if present
        if isinstance(ed, dict) and "extracted_data" in ed:
            ed = ed["extracted_data"]
        article["extracted_data"] = ed
        articles.append(article)

    return {"articles": articles, "total": len(articles)}


@router.put("/api/admin/incidents/{incident_id}")
async def admin_update_incident(incident_id: str, updates: dict = Body(...)):
    """Update an incident."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch
    import uuid
    from datetime import datetime, timezone

    try:
        incident_uuid = uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident ID format")

    # Build update query dynamically
    allowed_fields = [
        'date', 'state', 'city', 'description', 'notes', 'victim_name',
        'victim_age', 'victim_category', 'outcome_category', 'source_url',
        'source_tier', 'latitude', 'longitude', 'prior_deportations',
        'gang_affiliated', 'offender_immigration_status', 'curation_status'
    ]

    set_clauses = []
    params = []
    param_num = 1

    for field in allowed_fields:
        if field in updates:
            set_clauses.append(f"{field} = ${param_num}")
            params.append(updates[field])
            param_num += 1

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clauses.append(f"updated_at = ${param_num}")
    params.append(datetime.now(timezone.utc))
    param_num += 1

    params.append(incident_uuid)

    query = f"""
        UPDATE incidents
        SET {', '.join(set_clauses)}
        WHERE id = ${param_num}
        RETURNING id
    """

    result = await execute(query, *params)
    if "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail="Incident not found")

    return {"success": True, "incident_id": incident_id}


@router.delete("/api/admin/incidents/{incident_id}")
async def admin_delete_incident(incident_id: str, hard_delete: bool = Query(False)):
    """Delete (soft or hard) an incident."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid
    from datetime import datetime, timezone

    try:
        incident_uuid = uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident ID format")

    if hard_delete:
        result = await execute("DELETE FROM incidents WHERE id = $1", incident_uuid)
    else:
        result = await execute(
            "UPDATE incidents SET curation_status = 'archived', updated_at = $1 WHERE id = $2",
            datetime.now(timezone.utc), incident_uuid
        )

    return {"success": True, "deleted": incident_id}


@router.get("/api/admin/incidents/export")
async def admin_export_incidents(
    format: str = Query("json", description="Export format: json or csv"),
    category: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Export incidents in JSON or CSV format."""
    from fastapi.responses import Response
    import csv
    import io

    if USE_DATABASE:
        incidents = await get_all_incidents()
    else:
        incidents = load_incidents()

    # Apply filters
    if category:
        incidents = [i for i in incidents if i.get('category', 'enforcement') == category]
    if state:
        incidents = [i for i in incidents if i.get('state') == state]
    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]
    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    if format == "csv":
        output = io.StringIO()
        if incidents:
            fieldnames = list(incidents[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(incidents)
        content = output.getvalue()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=incidents.csv"}
        )
    else:
        return {"incidents": incidents, "total": len(incidents)}
