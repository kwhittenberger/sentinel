"""
Public incident routes — read-only endpoints for the dashboard.
Extracted from main.py.
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

from backend.routes._shared import (
    USE_DATABASE,
    filter_incidents,
    filter_incidents_async,
    load_incidents,
    _get_event_incident_ids,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Incidents"])


@router.get("/api/incidents")
async def get_incidents(
    tiers: Optional[str] = Query(None, description="Comma-separated tier numbers"),
    states: Optional[str] = Query(None, description="Comma-separated states"),
    categories: Optional[str] = Query(None, description="Comma-separated victim categories"),
    category: Optional[str] = Query(None, description="Incident category: enforcement or crime"),
    non_immigrant_only: bool = Query(False),
    death_only: bool = Query(False),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    gang_affiliated: Optional[bool] = Query(None, description="Filter by gang affiliation"),
    prior_deportations_min: Optional[int] = Query(None, description="Minimum prior deportations"),
    search: Optional[str] = Query(None, description="Full-text search"),
    event_id: Optional[str] = Query(None, description="Filter to incidents linked to this event"),
):
    """Get filtered incidents."""
    if USE_DATABASE:
        incidents = await filter_incidents_async(tiers, states, categories, non_immigrant_only, death_only, date_start, date_end)
    else:
        incidents = filter_incidents(tiers, states, categories, non_immigrant_only, death_only, date_start, date_end)

    # Apply category filter (enforcement/crime)
    if category:
        incidents = [i for i in incidents if i.get('category', 'enforcement') == category]

    # Apply crime-specific filters
    if gang_affiliated is not None:
        incidents = [i for i in incidents if i.get('gang_affiliated') == gang_affiliated]

    if prior_deportations_min is not None:
        incidents = [i for i in incidents if (i.get('prior_deportations') or 0) >= prior_deportations_min]

    # Apply search filter
    if search:
        search_lower = search.lower()
        incidents = [
            i for i in incidents
            if search_lower in (i.get('notes') or '').lower()
            or search_lower in (i.get('victim_name') or '').lower()
            or search_lower in (i.get('description') or '').lower()
            or search_lower in (i.get('city') or '').lower()
        ]

    # Filter by event
    if event_id and USE_DATABASE:
        linked_ids = await _get_event_incident_ids(event_id)
        incidents = [i for i in incidents if str(i.get('id', '')) in linked_ids]

    return {"incidents": incidents, "total": len(incidents)}


@router.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get a single incident by ID."""
    if USE_DATABASE:
        from backend.database import fetch
        try:
            incident_uuid = uuid.UUID(incident_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid incident ID format")

        query = """
            SELECT i.*, it.name as incident_type, it.display_name as incident_type_display,
                   sc.name as state_name,
                   ed.name as domain_name, ed.slug as domain_slug,
                   ec.name as category_name, ec.slug as category_slug
            FROM incidents i
            LEFT JOIN incident_types it ON i.incident_type_id = it.id
            LEFT JOIN state_codes sc ON i.state = sc.code
            LEFT JOIN event_domains ed ON i.domain_id = ed.id
            LEFT JOIN event_categories ec ON i.category_id = ec.id
            WHERE i.id = $1
        """
        rows = await fetch(query, incident_uuid)
        if not rows:
            raise HTTPException(status_code=404, detail="Incident not found")

        row = dict(rows[0])
        # Convert UUID and date fields
        row['id'] = str(row['id'])
        if row.get('incident_type_id'):
            row['incident_type_id'] = str(row['incident_type_id'])
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

    # Fallback to file-based
    incidents = load_incidents()
    for inc in incidents:
        if inc.get('id') == incident_id:
            return inc
    raise HTTPException(status_code=404, detail="Incident not found")


@router.get("/api/stats")
async def get_stats(
    tiers: Optional[str] = Query(None),
    states: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="Incident category: enforcement or crime"),
    non_immigrant_only: bool = Query(False),
    death_only: bool = Query(False),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    event_id: Optional[str] = Query(None, description="Filter to incidents linked to this event"),
):
    """Get summary statistics."""
    if USE_DATABASE:
        incidents = await filter_incidents_async(tiers=tiers, states=states, non_immigrant_only=non_immigrant_only, death_only=death_only, date_start=date_start, date_end=date_end)
    else:
        incidents = filter_incidents(tiers=tiers, states=states, non_immigrant_only=non_immigrant_only, death_only=death_only, date_start=date_start, date_end=date_end)

    # Apply category filter if specified
    if category:
        incidents = [i for i in incidents if i.get('category', 'enforcement') == category]

    # Filter by event
    if event_id and USE_DATABASE:
        linked_ids = await _get_event_incident_ids(event_id)
        incidents = [i for i in incidents if str(i.get('id', '')) in linked_ids]

    # Calculate stats
    total = len(incidents)
    deaths = sum(1 for i in incidents if i.get('is_death'))
    states_affected = len(set(i.get('state') for i in incidents if i.get('state')))
    non_immigrant = sum(1 for i in incidents if i.get('is_non_immigrant'))

    # By category
    by_category = {'enforcement': 0, 'crime': 0}
    category_deaths = {'enforcement': 0, 'crime': 0}
    for i in incidents:
        cat = i.get('category', 'enforcement')
        by_category[cat] = by_category.get(cat, 0) + 1
        if i.get('is_death'):
            category_deaths[cat] = category_deaths.get(cat, 0) + 1

    # By tier
    by_tier = {}
    for i in incidents:
        t = i.get('tier')
        by_tier[t] = by_tier.get(t, 0) + 1

    # By state (top 10)
    by_state = {}
    for i in incidents:
        s = i.get('state')
        if s:
            by_state[s] = by_state.get(s, 0) + 1
    by_state = dict(sorted(by_state.items(), key=lambda x: -x[1])[:10])

    # By incident type
    by_type = {}
    for i in incidents:
        t = i.get('incident_type')
        if t:
            by_type[t] = by_type.get(t, 0) + 1

    result = {
        "total_incidents": total,
        "total_deaths": deaths,
        "states_affected": states_affected,
        "non_immigrant_incidents": non_immigrant,
        "by_category": by_category,
        "category_deaths": category_deaths,
        "by_tier": by_tier,
        "by_state": by_state,
        "by_incident_type": by_type,
    }

    # Add pipeline stats and incident stats when using database
    if USE_DATABASE:
        try:
            from backend.database import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                pipeline_row = await conn.fetchrow("""
                    SELECT
                        (SELECT count(*) FROM ingested_articles) AS articles_ingested,
                        (SELECT count(*) FROM ingested_articles WHERE status = 'pending') AS pending_review,
                        (SELECT count(*) FROM event_domains WHERE is_active = true AND archived_at IS NULL) AS domains_active,
                        (SELECT count(*) FROM incident_events) AS events_tracked,
                        (SELECT avg(overall_confidence) FROM article_extractions WHERE status = 'completed') AS avg_extraction_confidence
                """)
                result["pipeline_stats"] = {
                    "articles_ingested": pipeline_row["articles_ingested"],
                    "pending_review": pipeline_row["pending_review"],
                    "domains_active": pipeline_row["domains_active"],
                    "events_tracked": pipeline_row["events_tracked"],
                    "avg_extraction_confidence": float(pipeline_row["avg_extraction_confidence"]) if pipeline_row["avg_extraction_confidence"] is not None else None,
                }

                # Incident-focused stats for dashboard
                incident_stats_row = await conn.fetchrow("""
                    SELECT
                        (SELECT count(*) FROM incidents i JOIN outcome_types ot ON i.outcome_type_id = ot.id WHERE ot.name = 'death') AS fatal_outcomes,
                        (SELECT count(*) FROM incidents i JOIN outcome_types ot ON i.outcome_type_id = ot.id WHERE ot.name = 'serious_injury') AS serious_injuries,
                        (SELECT count(DISTINCT event_id) FROM incident_events) AS events_tracked,
                        (SELECT avg(overall_confidence) FROM article_extractions WHERE status = 'completed') AS avg_confidence
                """)
                # Domain counts — incidents linked to domains via incidents.domain_id
                domain_rows = await conn.fetch("""
                    SELECT ed.name, count(*) AS cnt
                    FROM event_domains ed
                    JOIN incidents i ON i.domain_id = ed.id
                    WHERE ed.is_active = true AND ed.archived_at IS NULL
                    GROUP BY ed.name
                    ORDER BY cnt DESC
                """)
                domain_counts = {r["name"]: r["cnt"] for r in domain_rows} if domain_rows else {}

                result["incident_stats"] = {
                    "fatal_outcomes": incident_stats_row["fatal_outcomes"],
                    "serious_injuries": incident_stats_row["serious_injuries"],
                    "domain_counts": domain_counts,
                    "events_tracked": incident_stats_row["events_tracked"],
                    "avg_confidence": float(incident_stats_row["avg_confidence"]) if incident_stats_row["avg_confidence"] is not None else None,
                }
        except Exception as e:
            logger.warning(f"Failed to fetch pipeline stats: {e}")
            result["pipeline_stats"] = None
            result["incident_stats"] = None

    return result


@router.get("/api/incidents/{incident_id}/connections")
async def get_incident_connections(incident_id: str):
    """Get incidents connected via shared events or duplicate links."""
    if not USE_DATABASE:
        return {"incident_id": incident_id, "events": []}

    from backend.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Find events this incident belongs to
        event_rows = await conn.fetch("""
            SELECT e.id, e.name, e.slug
            FROM events e
            JOIN incident_events ie ON ie.event_id = e.id
            WHERE ie.incident_id = $1
        """, uuid.UUID(incident_id))

        events = []
        for er in event_rows:
            # Fetch sibling incidents in each event
            siblings = await conn.fetch("""
                SELECT i.id, i.date, i.city, i.state, it.name AS incident_type,
                       ot.name AS outcome_category, i.victim_name
                FROM incidents i
                JOIN incident_events ie ON ie.incident_id = i.id
                LEFT JOIN incident_types it ON i.incident_type_id = it.id
                LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
                WHERE ie.event_id = $1 AND i.id != $2
                ORDER BY i.date DESC
                LIMIT 20
            """, er["id"], uuid.UUID(incident_id))
            events.append({
                "event_id": str(er["id"]),
                "event_name": er["name"],
                "event_slug": er["slug"],
                "incidents": [
                    {
                        "id": str(s["id"]),
                        "date": s["date"].isoformat() if s["date"] else None,
                        "city": s["city"],
                        "state": s["state"],
                        "incident_type": s["incident_type"],
                        "outcome_category": s["outcome_category"],
                        "victim_name": s["victim_name"],
                    }
                    for s in siblings
                ],
            })

        return {"incident_id": incident_id, "events": events}


@router.get("/api/filters")
def get_filter_options():
    """Get available filter options."""
    incidents = load_incidents()

    states = sorted(set(i.get('state') for i in incidents if i.get('state')))
    categories = sorted(set(i.get('victim_category') for i in incidents if i.get('victim_category')))

    dates = [i.get('date') for i in incidents if i.get('date')]
    date_min = min(dates)[:10] if dates else None
    date_max = max(dates)[:10] if dates else None

    return {
        "states": states,
        "categories": categories,
        "tiers": [1, 2, 3, 4],
        "date_min": date_min,
        "date_max": date_max,
    }


@router.get("/api/domains-summary")
async def get_domains_summary():
    """Get event domains with their categories for filter dropdowns."""
    if not USE_DATABASE:
        return {"domains": []}

    from backend.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        domain_rows = await conn.fetch("""
            SELECT id, name, slug
            FROM event_domains
            WHERE is_active = true AND archived_at IS NULL
            ORDER BY display_order, name
        """)

        domains = []
        for d in domain_rows:
            cat_rows = await conn.fetch("""
                SELECT id, name, slug
                FROM event_categories
                WHERE domain_id = $1 AND is_active = true
                ORDER BY name
            """, d["id"])
            domains.append({
                "id": str(d["id"]),
                "name": d["name"],
                "slug": d["slug"],
                "categories": [
                    {"id": str(c["id"]), "name": c["name"], "slug": c["slug"]}
                    for c in cat_rows
                ],
            })

    return {"domains": domains}
