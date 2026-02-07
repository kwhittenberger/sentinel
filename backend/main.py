"""
FastAPI backend for Unified Incident Tracker dashboard.
Supports both ICE enforcement incidents and immigration-related crime cases.
"""

import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException, Depends, Body, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import json
from pathlib import Path
from datetime import datetime
import logging
import sys

# Add data_pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from data_pipeline.pipeline import DataPipeline, run_pipeline
from data_pipeline.config import SOURCES
from backend.utils.state_normalizer import normalize_state
from backend.utils.geocoding import get_coords, CITY_COORDS

logger = logging.getLogger(__name__)

# Check if we should use database
USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    if USE_DATABASE:
        from backend.database import get_pool, close_pool
        await get_pool()
        logger.info("Database connection pool initialized")

        if not USE_CELERY:
            # Start in-process job executor (legacy fallback)
            from backend.services.job_executor import get_executor
            executor = get_executor()
            await executor.start()
            logger.info("Background job executor started (in-process)")
        else:
            logger.info("Celery mode enabled — skipping in-process job executor")

        # Start WebSocket broadcast loop
        from backend.jobs_ws import job_update_manager
        await job_update_manager.start()

    yield

    if USE_DATABASE:
        # Stop WebSocket broadcast loop
        from backend.jobs_ws import job_update_manager
        await job_update_manager.stop()

        if not USE_CELERY:
            # Stop in-process job executor
            from backend.services.job_executor import get_executor
            executor = get_executor()
            await executor.stop()
            logger.info("Background job executor stopped")

        from backend.database import close_pool
        await close_pool()
        logger.info("Database connection pool closed")


app = FastAPI(
    title="Sentinel API",
    description="Incident analysis and pattern detection platform",
    version="2.0.0",
    lifespan=lifespan
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INCIDENTS_DIR = DATA_DIR / "incidents"

INCIDENT_FILES = [
    ("tier1_deaths_in_custody.json", 1),
    ("tier2_shootings.json", 2),
    ("tier2_less_lethal.json", 2),
    ("tier3_incidents.json", 3),
    ("tier4_incidents.json", 4),
]

NON_IMMIGRANT_CATEGORIES = {
    'us_citizen', 'bystander', 'officer', 'protester',
    'journalist', 'us_citizen_collateral', 'legal_resident'
}

# Cache for loaded data
_incidents_cache = None


def is_non_immigrant(row: dict) -> bool:
    """Check if incident involves non-immigrant."""
    victim_cat = str(row.get('victim_category', '')).lower()
    us_citizen = row.get('us_citizen', False)
    protest_related = row.get('protest_related', False)

    return (
        victim_cat in NON_IMMIGRANT_CATEGORIES or
        us_citizen or
        protest_related or
        'citizen' in victim_cat or
        'protest' in victim_cat
    )


def normalize_name(name: str) -> str:
    """Normalize victim name for deduplication."""
    if not name:
        return ''
    name = str(name).lower().strip()
    for suffix in [' jr', ' sr', ' ii', ' iii', ' iv']:
        name = name.replace(suffix, '')
    return ''.join(c for c in name if c.isalnum() or c.isspace())


def names_match(name1: str, name2: str) -> bool:
    """Check if two names match."""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    if n1 in n2 or n2 in n1:
        return True

    parts1 = n1.split()
    parts2 = n2.split()
    if parts1 and parts2 and parts1[-1] == parts2[-1]:
        if len(parts1) > 1 and len(parts2) > 1:
            if parts1[0][0] == parts2[0][0]:
                return True
    return False


async def load_incidents_from_db() -> list:
    """Load incidents from PostgreSQL database."""
    from backend.database import fetch

    rows = await fetch("""
        SELECT
            i.id::text,
            i.legacy_id,
            i.category::text,
            i.date,
            i.state,
            sc.name as state_name,
            i.city,
            it.name as incident_type,
            vt.name as victim_category,
            ot.name as outcome_category,
            i.victim_name,
            i.victim_age,
            i.notes,
            i.description,
            i.source_url,
            i.source_name,
            i.source_tier::text as tier,
            i.latitude as lat,
            i.longitude as lon,
            i.affected_count,
            i.us_citizen,
            i.protest_related,
            i.state_sanctuary_status,
            i.local_sanctuary_status,
            i.detainer_policy,
            i.offender_immigration_status,
            i.prior_deportations,
            i.gang_affiliated,
            i.curation_status::text,
            i.extraction_confidence
        FROM incidents i
        LEFT JOIN incident_types it ON i.incident_type_id = it.id
        LEFT JOIN state_codes sc ON i.state = sc.code
        LEFT JOIN victim_types vt ON i.victim_type_id = vt.id
        LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
        WHERE i.curation_status = 'approved'
        ORDER BY i.date DESC
    """)

    incidents = []
    for row in rows:
        inc = dict(row)
        # Convert date to string
        if inc['date']:
            inc['date'] = inc['date'].isoformat()
        # Convert tier to int
        inc['tier'] = int(inc['tier']) if inc['tier'] else 4
        # Geocode fallback for rows missing coordinates
        if not inc.get('lat') or not inc.get('lon'):
            lat, lon = get_coords(inc.get('city'), inc.get('state'))
            inc['lat'] = lat
            inc['lon'] = lon
        # Compute is_non_immigrant and is_death
        inc['is_non_immigrant'] = is_non_immigrant(inc)
        outcome = str(inc.get('outcome_category') or '').lower()
        incident_type = str(inc.get('incident_type') or '').lower()
        inc['is_death'] = outcome == 'death' or 'death' in incident_type or 'homicide' in incident_type
        incidents.append(inc)

    return incidents


def load_incidents() -> list:
    """Load and deduplicate all incidents from JSON files."""
    global _incidents_cache
    if _incidents_cache is not None:
        return _incidents_cache

    all_incidents = []

    for filename, tier in INCIDENT_FILES:
        filepath = INCIDENTS_DIR / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                incidents = json.load(f)
                for inc in incidents:
                    inc['tier'] = tier
                    inc['source_file'] = filename
                    inc['category'] = 'enforcement'  # JSON files are enforcement only

                    # Add coordinates
                    lat, lon = get_coords(inc.get('city'), inc.get('state'))
                    inc['lat'] = lat
                    inc['lon'] = lon

                    # Add computed fields
                    inc['is_non_immigrant'] = is_non_immigrant(inc)

                    # Check if death
                    outcome = str(inc.get('outcome_category', '')).lower()
                    incident_type = str(inc.get('incident_type', '')).lower()
                    inc['is_death'] = outcome == 'death' or 'death' in incident_type

                    all_incidents.append(inc)

    # Deduplicate
    deduplicated = deduplicate_incidents(all_incidents)
    _incidents_cache = deduplicated
    return deduplicated


def deduplicate_incidents(incidents: list) -> list:
    """Remove duplicate incidents, keeping highest confidence tier."""
    # Group by date + state
    groups = {}
    for inc in incidents:
        date = inc.get('date', '')[:10] if inc.get('date') else ''
        state = inc.get('state', '')
        key = f"{date}|{state}"
        if key not in groups:
            groups[key] = []
        groups[key].append(inc)

    result = []
    for key, group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        # Sort by tier (lower = better)
        group.sort(key=lambda x: x.get('tier', 99))

        kept = []
        matched_indices = set()

        for i, inc1 in enumerate(group):
            if i in matched_indices:
                continue

            duplicates = []
            for j, inc2 in enumerate(group[i+1:], start=i+1):
                if j in matched_indices:
                    continue

                # Check name match
                if names_match(inc1.get('victim_name'), inc2.get('victim_name')):
                    duplicates.append(inc2['id'])
                    matched_indices.add(j)
                # Check incident type match for specific types
                elif inc1.get('incident_type') == inc2.get('incident_type'):
                    itype = str(inc1.get('incident_type', '')).lower()
                    if any(t in itype for t in ['shooting', 'death_in_custody', 'vehicle_ramming']):
                        duplicates.append(inc2['id'])
                        matched_indices.add(j)

            if duplicates:
                inc1['linked_ids'] = duplicates
            kept.append(inc1)

        result.extend(kept)

    return result


async def get_all_incidents() -> list:
    """Get all incidents - from database if enabled, otherwise from JSON."""
    if USE_DATABASE:
        return await load_incidents_from_db()
    else:
        return load_incidents()


def filter_incidents(
    tiers: Optional[str] = None,
    states: Optional[str] = None,
    categories: Optional[str] = None,
    non_immigrant_only: bool = False,
    death_only: bool = False,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> list:
    """Filter incidents - shared logic (sync version for JSON)."""
    incidents = load_incidents()
    return _apply_filters(incidents, tiers, states, categories, non_immigrant_only, death_only, date_start, date_end)


async def filter_incidents_async(
    tiers: Optional[str] = None,
    states: Optional[str] = None,
    categories: Optional[str] = None,
    non_immigrant_only: bool = False,
    death_only: bool = False,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> list:
    """Filter incidents - async version for database."""
    incidents = await get_all_incidents()
    return _apply_filters(incidents, tiers, states, categories, non_immigrant_only, death_only, date_start, date_end)


def _apply_filters(
    incidents: list,
    tiers: Optional[str] = None,
    states: Optional[str] = None,
    categories: Optional[str] = None,
    non_immigrant_only: bool = False,
    death_only: bool = False,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> list:
    """Apply filters to incidents list."""
    if tiers:
        tier_list = [int(t) for t in tiers.split(',')]
        incidents = [i for i in incidents if i.get('tier') in tier_list]

    if states:
        state_list = [s.strip() for s in states.split(',')]
        incidents = [i for i in incidents if i.get('state') in state_list]

    if categories:
        cat_list = [c.strip() for c in categories.split(',')]
        incidents = [i for i in incidents if i.get('victim_category') in cat_list]

    if non_immigrant_only:
        incidents = [i for i in incidents if i.get('is_non_immigrant')]

    if death_only:
        incidents = [i for i in incidents if i.get('is_death')]

    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]

    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    return incidents


async def _get_event_incident_ids(event_id: str) -> set:
    """Get set of incident IDs linked to an event."""
    from backend.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT incident_id FROM incident_events WHERE event_id = $1",
            __import__('uuid').UUID(event_id),
        )
    return {str(r["incident_id"]) for r in rows}


@app.get("/api/incidents")
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


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get a single incident by ID."""
    if USE_DATABASE:
        from backend.database import fetch
        import uuid
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


@app.get("/api/stats")
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


@app.get("/api/incidents/{incident_id}/connections")
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


@app.get("/api/filters")
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


@app.get("/api/domains-summary")
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


# =====================
# Admin API Endpoints
# =====================

@app.get("/api/admin/status")
def get_admin_status():
    """Get current data status for admin panel."""
    global _incidents_cache

    # Clear cache to get fresh data
    _incidents_cache = None
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


@app.post("/api/admin/pipeline/fetch")
def admin_fetch(
    source: Optional[str] = Query(None, description="Source name to fetch, or all if not specified"),
    force_refresh: bool = Query(False, description="Force refresh cached data"),
):
    """Fetch data from sources."""
    global _incidents_cache

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
        _incidents_cache = None

        return {
            "success": True,
            "operation": "fetch",
            **result,
        }
    except Exception as e:
        logger.exception("Fetch failed")
        return {"success": False, "error": str(e)}


@app.post("/api/admin/pipeline/process")
def admin_process():
    """Process existing data (validate, normalize, dedupe, geocode)."""
    global _incidents_cache

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
        _incidents_cache = None

        return {
            "success": True,
            "operation": "process",
            "stats": stats,
        }
    except Exception as e:
        logger.exception("Process failed")
        return {"success": False, "error": str(e)}


@app.post("/api/admin/pipeline/run")
def admin_run_pipeline(
    force_refresh: bool = Query(False, description="Force refresh cached data"),
):
    """Run full pipeline (fetch + process + save)."""
    global _incidents_cache

    try:
        result = run_pipeline(force_refresh=force_refresh)

        # Clear cache
        _incidents_cache = None

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

@app.get("/api/admin/queue")
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


@app.get("/api/admin/articles/audit")
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


@app.post("/api/admin/queue/submit")
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

@app.get("/api/admin/queue/tiered")
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


@app.post("/api/admin/queue/bulk-approve")
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


@app.post("/api/admin/queue/bulk-reject")
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


@app.post("/api/admin/queue/auto-approve")
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


@app.get("/api/admin/queue/extraction-status")
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


@app.post("/api/admin/queue/triage")
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


@app.post("/api/admin/queue/batch-extract")
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


@app.post("/api/admin/queue/bulk-reject-by-criteria")
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


@app.get("/api/admin/queue/{article_id}")
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


@app.post("/api/admin/queue/{article_id}/extract-universal")
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


@app.post("/api/admin/queue/{article_id}/approve")
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


@app.post("/api/admin/queue/{article_id}/reject")
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


@app.post("/api/admin/reset-pipeline-data")
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


@app.post("/api/admin/backfill-actors-events")
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


# =====================
# Duplicate Detection Endpoints
# =====================

@app.get("/api/admin/duplicates/config")
def get_duplicate_config():
    """Get duplicate detection configuration."""
    from backend.services import get_detector
    detector = get_detector()
    return detector.get_config()


@app.post("/api/admin/duplicates/check")
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

@app.get("/api/admin/auto-approval/config")
def get_auto_approval_config():
    """Get auto-approval configuration."""
    from backend.services import get_auto_approval_service
    service = get_auto_approval_service()
    return service.get_config()


@app.put("/api/admin/auto-approval/config")
def update_auto_approval_config(updates: dict = Body(...)):
    """Update auto-approval configuration."""
    from backend.services import get_auto_approval_service
    service = get_auto_approval_service()
    service.update_config(updates)
    return {"success": True, "config": service.get_config()}


@app.post("/api/admin/auto-approval/evaluate")
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

@app.get("/api/admin/llm-extraction/status")
def get_extraction_status():
    """Get LLM extraction service status."""
    from backend.services import get_extractor
    extractor = get_extractor()
    return {
        "available": extractor.is_available(),
        "model": "claude-sonnet-4-20250514" if extractor.is_available() else None
    }


@app.post("/api/admin/llm-extraction/extract")
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

@app.get("/api/admin/pipeline/config")
def get_pipeline_config():
    """Get unified pipeline configuration."""
    from backend.services import get_pipeline
    pipeline = get_pipeline()
    return pipeline.get_stats()


@app.post("/api/admin/pipeline/process-article")
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
# Person Endpoints
# =====================

@app.get("/api/persons")
def get_persons(
    role: Optional[str] = Query(None, description="Filter by role: victim, offender"),
    gang_affiliated: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List persons (victims and offenders)."""
    # Placeholder - will be implemented with database
    return {"persons": [], "total": 0}


@app.get("/api/persons/{person_id}")
def get_person(person_id: str):
    """Get person details with their incidents."""
    # Placeholder - will be implemented with database
    return {"error": "Database not enabled"}, 501


# =====================
# Analytics Endpoints
# =====================

@app.get("/api/stats/comparison")
async def get_comparison_stats(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get comparison statistics between enforcement and crime incidents."""
    if USE_DATABASE:
        incidents = await filter_incidents_async(date_start=date_start, date_end=date_end)
    else:
        incidents = filter_incidents(date_start=date_start, date_end=date_end)

    enforcement = [i for i in incidents if i.get('category', 'enforcement') == 'enforcement']
    crime = [i for i in incidents if i.get('category') == 'crime']

    enforcement_deaths = sum(1 for i in enforcement if i.get('is_death'))
    crime_deaths = sum(1 for i in crime if i.get('is_death'))

    # By state
    by_state = {}
    for inc in incidents:
        state = inc.get('state')
        if not state:
            continue
        if state not in by_state:
            by_state[state] = {
                'name': state,
                'enforcement_incidents': 0,
                'crime_incidents': 0,
                'enforcement_deaths': 0,
                'crime_deaths': 0,
            }
        cat = inc.get('category', 'enforcement')
        if cat == 'enforcement':
            by_state[state]['enforcement_incidents'] += 1
            if inc.get('is_death'):
                by_state[state]['enforcement_deaths'] += 1
        else:
            by_state[state]['crime_incidents'] += 1
            if inc.get('is_death'):
                by_state[state]['crime_deaths'] += 1

    return {
        "enforcement_incidents": len(enforcement),
        "crime_incidents": len(crime),
        "enforcement_deaths": enforcement_deaths,
        "crime_deaths": crime_deaths,
        "by_jurisdiction": list(by_state.values()),
    }


@app.get("/api/stats/sanctuary")
async def get_sanctuary_correlation(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get sanctuary policy correlation analysis."""
    if USE_DATABASE:
        incidents = await filter_incidents_async(date_start=date_start, date_end=date_end)
    else:
        incidents = filter_incidents(date_start=date_start, date_end=date_end)

    # Group by sanctuary status
    by_status = {
        'sanctuary': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
        'anti_sanctuary': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
        'neutral': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
        'unknown': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
    }

    for inc in incidents:
        status = inc.get('state_sanctuary_status', 'unknown') or 'unknown'
        if status not in by_status:
            status = 'unknown'

        by_status[status]['incidents'] += 1
        if inc.get('is_death'):
            by_status[status]['deaths'] += 1
        if inc.get('is_non_immigrant'):
            by_status[status]['non_immigrant'] += 1

    return {
        "by_sanctuary_status": by_status,
        "total_incidents": len(incidents),
    }


# =====================
# Settings Endpoints
# =====================

@app.get("/api/admin/settings")
def get_all_settings():
    """Get all application settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_all()


@app.get("/api/admin/settings/auto-approval")
def get_settings_auto_approval():
    """Get auto-approval settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_auto_approval()


@app.put("/api/admin/settings/auto-approval")
def update_settings_auto_approval(config: dict = Body(...)):
    """Update auto-approval settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_auto_approval(config)


@app.get("/api/admin/settings/duplicate")
def get_settings_duplicate():
    """Get duplicate detection settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_duplicate_detection()


@app.put("/api/admin/settings/duplicate")
def update_settings_duplicate(config: dict = Body(...)):
    """Update duplicate detection settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_duplicate_detection(config)


@app.get("/api/admin/settings/pipeline")
def get_settings_pipeline():
    """Get pipeline settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_pipeline()


@app.put("/api/admin/settings/pipeline")
def update_settings_pipeline(config: dict = Body(...)):
    """Update pipeline settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_pipeline(config)


@app.get("/api/admin/settings/event-clustering")
def get_settings_event_clustering():
    """Get event clustering settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_event_clustering()


@app.put("/api/admin/settings/event-clustering")
def update_settings_event_clustering(config: dict = Body(...)):
    """Update event clustering settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_event_clustering(config)


# =====================
# LLM Provider Endpoints
# =====================

@app.get("/api/admin/settings/llm")
def get_settings_llm():
    """Get LLM provider settings."""
    from backend.services import get_settings_service
    return get_settings_service().get_llm()


@app.put("/api/admin/settings/llm")
def update_settings_llm(config: dict = Body(...)):
    """Update LLM provider settings."""
    from backend.services import get_settings_service
    return get_settings_service().update_llm(config)


@app.get("/api/admin/llm/providers")
def get_llm_provider_status():
    """Get availability status of each LLM provider."""
    from backend.services.llm_provider import get_llm_router
    router = get_llm_router()
    return {
        "providers": {
            name: {
                "available": available,
                "name": name,
            }
            for name, available in router.provider_status().items()
        }
    }


@app.get("/api/admin/llm/models")
def get_llm_available_models():
    """Get available models from each provider."""
    from backend.services.llm_provider import get_llm_router
    router = get_llm_router()

    models = {
        "anthropic": [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
        ],
        "ollama": [],
    }

    if router.ollama.is_available():
        models["ollama"] = router.ollama.list_models()

    return {"models": models}


# =====================
# Domain & Category Endpoints
# =====================

@app.get("/api/admin/domains")
async def list_domains(include_inactive: bool = Query(False)):
    """List all event domains."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    return {"domains": await service.list_domains(include_inactive=include_inactive)}


@app.post("/api/admin/domains")
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


@app.get("/api/admin/domains/{slug}")
async def get_domain(slug: str):
    """Get a domain by slug."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    domain = await service.get_domain(slug)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@app.put("/api/admin/domains/{slug}")
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


@app.get("/api/admin/domains/{slug}/categories")
async def list_categories_for_domain(slug: str, include_inactive: bool = Query(False)):
    """List categories within a domain."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    categories = await service.list_categories(domain_slug=slug, include_inactive=include_inactive)
    return {"categories": categories}


@app.post("/api/admin/domains/{slug}/categories")
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


@app.get("/api/admin/categories/{category_id}")
async def get_category(category_id: str):
    """Get a single category with field definitions."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    category = await service.get_category(uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@app.put("/api/admin/categories/{category_id}")
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


@app.get("/api/admin/incidents/{incident_id}/relationships")
async def list_incident_relationships(incident_id: str):
    """List relationships for an incident."""
    from backend.services.domain_service import get_domain_service
    service = get_domain_service()
    relationships = await service.list_relationships(uuid.UUID(incident_id))
    return {"relationships": relationships}


@app.post("/api/admin/incidents/relationships")
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

@app.get("/api/admin/incidents")
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


@app.get("/api/admin/incidents/{incident_id}")
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


@app.get("/api/admin/incidents/{incident_id}/articles")
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


@app.put("/api/admin/incidents/{incident_id}")
async def admin_update_incident(incident_id: str, updates: dict = Body(...)):
    """Update an incident."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch
    import uuid
    from datetime import datetime

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
    params.append(datetime.utcnow())
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


@app.delete("/api/admin/incidents/{incident_id}")
async def admin_delete_incident(incident_id: str, hard_delete: bool = Query(False)):
    """Delete (soft or hard) an incident."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid
    from datetime import datetime

    try:
        incident_uuid = uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident ID format")

    if hard_delete:
        result = await execute("DELETE FROM incidents WHERE id = $1", incident_uuid)
    else:
        result = await execute(
            "UPDATE incidents SET curation_status = 'archived', updated_at = $1 WHERE id = $2",
            datetime.utcnow(), incident_uuid
        )

    return {"success": True, "deleted": incident_id}


@app.get("/api/admin/incidents/export")
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


# =====================
# Job Queue Endpoints
# =====================

@app.get("/api/admin/jobs")
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
):
    """List background jobs."""
    if not USE_DATABASE:
        return {"jobs": [], "total": 0}

    from backend.database import fetch

    _JOB_COLS = """id, job_type, status, progress, total, message,
            created_at, started_at, completed_at, error,
            celery_task_id, retry_count, max_retries, queue, priority"""

    if status:
        query = f"""
            SELECT {_JOB_COLS}
            FROM background_jobs
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await fetch(query, status, limit)
    else:
        query = f"""
            SELECT {_JOB_COLS}
            FROM background_jobs
            ORDER BY created_at DESC
            LIMIT $1
        """
        rows = await fetch(query, limit)

    jobs = []
    for row in rows:
        job = dict(row)
        job['id'] = str(job['id'])
        for field in ['created_at', 'started_at', 'completed_at']:
            if job.get(field):
                job[field] = job[field].isoformat()
        jobs.append(job)

    return {"jobs": jobs, "total": len(jobs)}


def _dispatch_celery_task(job_type: str, job_id: str, params: dict):
    """Send a job to the appropriate Celery task queue."""
    from backend.tasks.fetch_tasks import run_fetch
    from backend.tasks.extraction_tasks import run_process, run_batch_extract
    from backend.tasks.enrichment_tasks import run_batch_enrich, run_enrichment
    from backend.tasks.pipeline_tasks import run_full_pipeline

    _TASK_MAP = {
        "fetch": run_fetch,
        "process": run_process,
        "batch_extract": run_batch_extract,
        "batch_enrich": run_batch_enrich,
        "cross_reference_enrich": run_enrichment,
        "full_pipeline": run_full_pipeline,
    }

    task_fn = _TASK_MAP.get(job_type)
    if task_fn is None:
        logger.warning(f"No Celery task mapped for job_type={job_type}")
        return
    task_fn.delay(job_id, params)


@app.post("/api/admin/jobs")
async def create_job(
    job_type: str = Body(..., embed=True),
    params: Optional[dict] = Body(None, embed=True),
):
    """Create a new background job."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid
    from datetime import datetime

    # Map job_type to Celery queue name
    _QUEUE_MAP = {
        "fetch": "fetch",
        "process": "extraction",
        "batch_extract": "extraction",
        "batch_enrich": "enrichment",
        "cross_reference_enrich": "enrichment",
        "full_pipeline": "default",
    }

    job_id = uuid.uuid4()
    queue = _QUEUE_MAP.get(job_type, "default")

    await execute("""
        INSERT INTO background_jobs (id, job_type, status, params, created_at, queue)
        VALUES ($1, $2, 'pending', $3, $4, $5)
    """, job_id, job_type, params or {}, datetime.utcnow(), queue)

    if USE_CELERY:
        _dispatch_celery_task(job_type, str(job_id), params or {})

    # Notify WebSocket clients
    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(str(job_id))

    return {"success": True, "job_id": str(job_id)}


@app.get("/api/admin/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status and details."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch
    import uuid

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await fetch("""
        SELECT * FROM background_jobs WHERE id = $1
    """, job_uuid)

    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    job = dict(rows[0])
    job['id'] = str(job['id'])
    for field in ['created_at', 'started_at', 'completed_at']:
        if job.get(field):
            job[field] = job[field].isoformat()

    return job


@app.delete("/api/admin/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a pending or running job."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch
    import uuid
    from datetime import datetime

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    # If Celery mode, revoke the task before updating DB
    if USE_CELERY:
        rows = await db_fetch(
            "SELECT celery_task_id FROM background_jobs WHERE id = $1", job_uuid
        )
        if rows and rows[0].get("celery_task_id"):
            from backend.celery_app import app as celery_app

            celery_app.control.revoke(
                rows[0]["celery_task_id"], terminate=True, signal="SIGTERM"
            )

    result = await execute("""
        UPDATE background_jobs
        SET status = 'cancelled', completed_at = $1
        WHERE id = $2 AND status IN ('pending', 'running')
    """, datetime.utcnow(), job_uuid)

    # Notify WebSocket clients
    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(job_id)

    return {"success": True, "cancelled": job_id}


@app.delete("/api/admin/jobs/{job_id}/delete")
async def hard_delete_job(job_id: str):
    """Hard-delete a terminal-state job (completed, failed, cancelled)."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await db_fetch(
        "SELECT status FROM background_jobs WHERE id = $1", job_uuid
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    if rows[0]["status"] in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete active job. Cancel it first.",
        )

    await execute("DELETE FROM background_jobs WHERE id = $1", job_uuid)
    return {"success": True, "deleted": job_id}


@app.post("/api/admin/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    """Re-create a failed job with the same type and params."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await db_fetch(
        "SELECT job_type, params, queue FROM background_jobs WHERE id = $1",
        job_uuid,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    original = rows[0]
    new_id = uuid.uuid4()
    queue = original.get("queue") or "default"

    await execute("""
        INSERT INTO background_jobs (id, job_type, status, params, created_at, queue)
        VALUES ($1, $2, 'pending', $3, $4, $5)
    """, new_id, original["job_type"], original.get("params") or {}, datetime.utcnow(), queue)

    if USE_CELERY:
        _dispatch_celery_task(original["job_type"], str(new_id), original.get("params") or {})

    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(str(new_id))

    return {"success": True, "new_job_id": str(new_id)}


@app.post("/api/admin/jobs/{job_id}/unstick")
async def unstick_job(job_id: str):
    """Reset a stale running job back to pending and re-dispatch."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await db_fetch(
        "SELECT status, job_type, params, queue, celery_task_id FROM background_jobs WHERE id = $1",
        job_uuid,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    job = rows[0]
    if job["status"] != "running":
        raise HTTPException(status_code=409, detail="Only running jobs can be unstuck")

    # Revoke the old Celery task if possible
    if USE_CELERY and job.get("celery_task_id"):
        from backend.celery_app import app as celery_app
        celery_app.control.revoke(job["celery_task_id"], terminate=True, signal="SIGTERM")

    await execute("""
        UPDATE background_jobs
        SET status = 'pending',
            started_at = NULL,
            celery_task_id = NULL,
            error = 'Unstuck by admin',
            retry_count = COALESCE(retry_count, 0) + 1
        WHERE id = $1
    """, job_uuid)

    # Re-dispatch
    if USE_CELERY:
        _dispatch_celery_task(job["job_type"], job_id, job.get("params") or {})

    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(job_id)

    return {"success": True, "unstuck": job_id}


# =====================
# WebSocket: Job Updates
# =====================


@app.websocket("/ws/jobs")
async def websocket_jobs(ws: WebSocket):
    """Real-time job status stream."""
    from backend.jobs_ws import job_update_manager

    await job_update_manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client may send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await job_update_manager.disconnect(ws)


# =====================
# Metrics Endpoints
# =====================


@app.get("/api/metrics/overview")
async def metrics_overview():
    """Queue and worker stats via Celery inspect (cached 5s)."""
    if not USE_CELERY:
        return {
            "queues": {},
            "workers": {},
            "totals": {"active_tasks": 0, "reserved_tasks": 0, "total_workers": 0},
        }
    from backend.metrics import get_metrics_overview
    return await get_metrics_overview()


@app.get("/api/metrics/task-performance")
async def metrics_task_performance(period: str = Query("24h")):
    """Per-task performance stats from task_metrics table."""
    if not USE_DATABASE:
        return {"tasks": []}

    # Parse period string (e.g. "24h", "7d")
    hours = 24
    if period.endswith("h"):
        hours = int(period[:-1])
    elif period.endswith("d"):
        hours = int(period[:-1]) * 24

    from backend.metrics import get_task_performance
    return await get_task_performance(hours)


@app.get("/api/admin/queue/{article_id}/suggestions")
async def get_ai_suggestions(article_id: str):
    """Get AI suggestions for low-confidence fields in an article."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch
    import uuid

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


# =====================
# Analytics Endpoints (Extended)
# =====================

@app.get("/api/admin/analytics/overview")
async def get_analytics_overview(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get overview analytics for the admin dashboard."""
    if USE_DATABASE:
        incidents = await get_all_incidents()
        from backend.database import fetch

        # Get queue stats
        queue_stats = await fetch("""
            SELECT status, COUNT(*) as count
            FROM ingested_articles
            GROUP BY status
        """)
        queue_by_status = {row["status"]: row["count"] for row in queue_stats}
    else:
        incidents = load_incidents()
        queue_by_status = {"pending": 0, "approved": 0, "rejected": 0}

    # Apply date filters to incidents
    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]
    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    total = len(incidents)
    enforcement = sum(1 for i in incidents if i.get('category', 'enforcement') == 'enforcement')
    crime = sum(1 for i in incidents if i.get('category') == 'crime')
    deaths = sum(1 for i in incidents if i.get('is_death'))
    states = len(set(i.get('state') for i in incidents if i.get('state')))

    return {
        "total_incidents": total,
        "enforcement_incidents": enforcement,
        "crime_incidents": crime,
        "total_deaths": deaths,
        "states_affected": states,
        "queue_stats": queue_by_status,
        "ingested_total": sum(queue_by_status.values()),
        "approved_total": queue_by_status.get("approved", 0),
        "rejected_total": queue_by_status.get("rejected", 0),
        "pending_review": queue_by_status.get("pending", 0),
    }


@app.get("/api/admin/analytics/conversion")
async def get_conversion_funnel(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get conversion funnel statistics."""
    if not USE_DATABASE:
        return {"funnel": []}

    from backend.database import fetch

    # Get article counts by status
    query = """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE relevance_score > 0.5) as relevant,
            COUNT(*) FILTER (WHERE status = 'approved') as approved,
            COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
            COUNT(*) FILTER (WHERE status = 'pending') as pending
        FROM ingested_articles
    """
    rows = await fetch(query)

    if rows:
        stats = dict(rows[0])
        return {
            "funnel": [
                {"stage": "Ingested", "count": stats["total"]},
                {"stage": "Relevant", "count": stats["relevant"]},
                {"stage": "Approved", "count": stats["approved"]},
            ],
            "rejected": stats["rejected"],
            "pending": stats["pending"],
        }

    return {"funnel": [], "rejected": 0, "pending": 0}


@app.get("/api/admin/analytics/sources")
async def get_source_analytics(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get analytics broken down by source."""
    if not USE_DATABASE:
        return {"sources": []}

    from backend.database import fetch

    query = """
        SELECT
            source_name,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'approved') as approved,
            COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
            AVG(extraction_confidence) as avg_confidence
        FROM ingested_articles
        GROUP BY source_name
        ORDER BY total DESC
        LIMIT 20
    """
    rows = await fetch(query)

    sources = []
    for row in rows:
        sources.append({
            "source_name": row.get("source_name") or "Unknown",
            "total": row["total"],
            "approved": row["approved"],
            "rejected": row["rejected"],
            "avg_confidence": float(row["avg_confidence"]) if row.get("avg_confidence") else None,
            "approval_rate": row["approved"] / row["total"] if row["total"] > 0 else 0,
        })

    return {"sources": sources}


@app.get("/api/admin/analytics/geographic")
async def get_geographic_analytics(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get analytics broken down by state."""
    if USE_DATABASE:
        incidents = await get_all_incidents()
    else:
        incidents = load_incidents()

    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]
    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    by_state = {}
    for inc in incidents:
        state = inc.get('state')
        if not state:
            continue
        if state not in by_state:
            by_state[state] = {
                'state': state,
                'total': 0,
                'enforcement': 0,
                'crime': 0,
                'deaths': 0,
            }
        by_state[state]['total'] += 1
        cat = inc.get('category', 'enforcement')
        if cat == 'enforcement':
            by_state[state]['enforcement'] += 1
        else:
            by_state[state]['crime'] += 1
        if inc.get('is_death'):
            by_state[state]['deaths'] += 1

    return {"states": list(by_state.values())}


# =====================
# Feed Management Endpoints
# =====================

@app.get("/api/admin/feeds")
async def list_feeds():
    """List all data sources."""
    if not USE_DATABASE:
        # Return static sources from config
        return {
            "feeds": [
                {"name": name, "enabled": config.enabled, "tier": config.tier}
                for name, config in SOURCES.items()
            ]
        }

    from backend.database import fetch

    rows = await fetch("""
        SELECT id, name, url, source_type, tier, fetcher_class,
               interval_minutes, is_active, last_fetched, last_error, created_at
        FROM sources
        ORDER BY tier, name
    """)

    feeds = []
    for row in rows:
        feed = dict(row)
        feed['id'] = str(feed['id'])
        feed['active'] = feed.pop('is_active')
        # Cast tier enum to int for frontend
        feed['tier'] = int(feed['tier']) if feed.get('tier') else 3
        for field in ['last_fetched', 'created_at']:
            if feed.get(field):
                feed[field] = feed[field].isoformat()
        feeds.append(feed)

    return {"feeds": feeds}


@app.post("/api/admin/feeds")
async def create_feed(
    name: str = Body(..., embed=True),
    url: str = Body(..., embed=True),
    source_type: str = Body("news", embed=True),
    tier: int = Body(3, embed=True),
    interval_minutes: int = Body(60, embed=True),
):
    """Create a new data source."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid
    from datetime import datetime

    feed_id = uuid.uuid4()
    await execute("""
        INSERT INTO sources (id, name, url, source_type, tier, interval_minutes, is_active, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, true, $7)
    """, feed_id, name, url, source_type, str(tier), interval_minutes, datetime.utcnow())

    return {"success": True, "feed_id": str(feed_id)}


@app.put("/api/admin/feeds/{feed_id}")
async def update_feed(feed_id: str, updates: dict = Body(...)):
    """Update an RSS feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid

    try:
        feed_uuid = uuid.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    allowed_fields = ['name', 'url', 'source_type', 'tier', 'fetcher_class', 'fetcher_config', 'interval_minutes', 'is_active']
    # Map frontend field names to DB column names
    field_map = {'active': 'is_active'}
    set_clauses = []
    params = []
    param_num = 1

    for field in list(updates.keys()):
        db_field = field_map.get(field, field)
        if db_field in allowed_fields:
            set_clauses.append(f"{db_field} = ${param_num}")
            value = updates[field]
            # Cast tier to string for the enum column
            if db_field == 'tier':
                value = str(value)
            params.append(value)
            param_num += 1

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    params.append(feed_uuid)
    query = f"UPDATE sources SET {', '.join(set_clauses)} WHERE id = ${param_num}"
    await execute(query, *params)

    return {"success": True}


@app.delete("/api/admin/feeds/{feed_id}")
async def delete_feed(feed_id: str):
    """Delete an RSS feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid

    try:
        feed_uuid = uuid.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    await execute("DELETE FROM sources WHERE id = $1", feed_uuid)
    return {"success": True}


@app.post("/api/admin/feeds/{feed_id}/fetch")
async def fetch_feed(feed_id: str):
    """Manually fetch a specific data source."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch, execute
    import uuid as uuid_mod

    try:
        feed_uuid = uuid_mod.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    rows = await fetch("SELECT id, name, url, source_type, fetcher_class FROM sources WHERE id = $1", feed_uuid)
    if not rows:
        raise HTTPException(status_code=404, detail="Source not found")

    source = dict(rows[0])
    source_type = source.get('source_type', '')

    # Only RSS/news sources with URLs can be fetched via feedparser right now
    if source_type in ('news',) and source.get('url') and not source.get('fetcher_class'):
        try:
            import feedparser
            import httpx
            response_data = httpx.get(source['url'], timeout=30)
            parsed = feedparser.parse(response_data.text)
            count = len(parsed.entries) if parsed.entries else 0
            from datetime import datetime
            await execute("UPDATE sources SET last_fetched = $1, last_error = NULL WHERE id = $2", datetime.utcnow(), feed_uuid)
            return {"success": True, "message": f"Fetched {count} entries from {source['name']}"}
        except Exception as e:
            from datetime import datetime
            await execute("UPDATE sources SET last_error = $1 WHERE id = $2", str(e), feed_uuid)
            return {"success": False, "message": f"Fetch failed: {e}"}
    else:
        fetcher = source.get('fetcher_class') or 'none'
        return {"success": True, "message": f"Fetch initiated for {source['name']} (fetcher: {fetcher} — not yet integrated)"}


@app.post("/api/admin/feeds/{feed_id}/toggle")
async def toggle_feed(feed_id: str, active: bool = Body(..., embed=True)):
    """Enable or disable a feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid

    try:
        feed_uuid = uuid.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    await execute("UPDATE sources SET is_active = $1 WHERE id = $2", active, feed_uuid)
    return {"success": True, "active": active}


# =====================
# Incident Types API
# =====================

@app.get("/api/admin/types")
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


@app.get("/api/admin/types/{type_id}")
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


@app.post("/api/admin/types")
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


@app.put("/api/admin/types/{type_id}")
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


@app.get("/api/admin/types/{type_id}/fields")
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


@app.post("/api/admin/types/{type_id}/fields")
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

@app.get("/api/admin/prompts")
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


@app.get("/api/admin/prompts/{prompt_id}")
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


@app.post("/api/admin/prompts")
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


@app.put("/api/admin/prompts/{prompt_id}")
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


@app.post("/api/admin/prompts/{prompt_id}/activate")
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


@app.get("/api/admin/prompts/{prompt_id}/executions")
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


@app.get("/api/admin/prompts/token-usage")
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


# =====================
# Events API
# =====================

@app.get("/api/events")
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


@app.get("/api/events/suggestions")
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


@app.get("/api/events/{event_id}")
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


@app.post("/api/events")
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


@app.post("/api/events/{event_id}/incidents")
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


@app.delete("/api/events/{event_id}/incidents/{incident_id}")
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

@app.get("/api/actors")
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


@app.get("/api/actors/merge-suggestions")
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


@app.get("/api/actors/{actor_id}/similar")
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


@app.post("/api/actors/merge")
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


@app.get("/api/actors/{actor_id}")
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


@app.post("/api/actors")
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


@app.put("/api/actors/{actor_id}")
async def update_actor(actor_id: str, data: dict = Body(...)):
    """Update an actor."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.actor_service import get_actor_service
    import uuid

    actor_service = get_actor_service()
    actor = await actor_service.update_actor(uuid.UUID(actor_id), data)
    return {"id": str(actor.id), "canonical_name": actor.canonical_name}


@app.post("/api/actors/{actor_id}/incidents")
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
# Pipeline API (New Orchestrator)
# =====================

@app.get("/api/admin/pipeline/stages")
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


@app.post("/api/admin/pipeline/execute")
async def execute_pipeline(data: dict = Body(...)):
    """Execute the configurable pipeline on an article."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.pipeline_orchestrator import get_pipeline_orchestrator
    import uuid

    orchestrator = get_pipeline_orchestrator()

    incident_type_id = uuid.UUID(data["incident_type_id"]) if data.get("incident_type_id") else None
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

@app.get("/api/admin/enrichment/stats")
async def get_enrichment_stats():
    """Get missing field counts and enrichment summary."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.enrichment_service import get_enrichment_service
    service = get_enrichment_service()
    return await service.get_enrichment_stats()


@app.get("/api/admin/enrichment/candidates")
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


@app.post("/api/admin/enrichment/run")
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
    """, job_id, params, datetime.utcnow())

    return {"success": True, "job_id": str(job_id)}


@app.get("/api/admin/enrichment/runs")
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


@app.get("/api/admin/enrichment/log/{incident_id}")
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


@app.post("/api/admin/enrichment/revert/{log_id}")
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
# Cases & Legal Tracking
# =====================

@app.get("/api/admin/cases")
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


@app.post("/api/admin/cases")
async def create_case(data: dict = Body(...)):
    """Create a new case."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    if "case_type" not in data:
        raise HTTPException(status_code=400, detail="case_type is required")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.create_case(data)


@app.get("/api/admin/cases/{case_id}")
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


@app.put("/api/admin/cases/{case_id}")
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

@app.get("/api/admin/cases/{case_id}/charges")
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


@app.post("/api/admin/cases/{case_id}/charges")
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


@app.put("/api/admin/charges/{charge_id}")
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

@app.get("/api/admin/cases/{case_id}/charge-history")
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


@app.post("/api/admin/charge-history")
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

@app.get("/api/admin/cases/{case_id}/prosecutorial-actions")
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


@app.post("/api/admin/prosecutorial-actions")
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

@app.get("/api/admin/cases/{case_id}/bail-decisions")
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


@app.post("/api/admin/bail-decisions")
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

@app.get("/api/admin/cases/{case_id}/dispositions")
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


@app.post("/api/admin/dispositions")
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

@app.get("/api/admin/cases/{case_id}/incidents")
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


@app.post("/api/admin/cases/{case_id}/incidents")
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


@app.get("/api/admin/cases/{case_id}/actors")
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


@app.post("/api/admin/cases/{case_id}/actors")
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

@app.get("/api/admin/prosecutor-stats")
async def get_prosecutor_stats(prosecutor_id: str = None):
    """Get prosecutor performance stats."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    pid = uuid.UUID(prosecutor_id) if prosecutor_id else None

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    return await service.get_prosecutor_stats(pid)


@app.post("/api/admin/prosecutor-stats/refresh")
async def refresh_prosecutor_stats():
    """Refresh the prosecutor stats materialized view."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.services.criminal_justice_service import get_criminal_justice_service
    service = get_criminal_justice_service()
    await service.refresh_prosecutor_stats()
    return {"success": True, "message": "Prosecutor stats refreshed"}


# =====================
# Extraction Schemas
# =====================


@app.get("/api/admin/extraction-schemas")
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


@app.get("/api/admin/extraction-schemas/{schema_id}")
async def get_extraction_schema(schema_id: str):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    result = await service.get_schema(schema_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schema not found")
    return result


@app.post("/api/admin/extraction-schemas")
async def create_extraction_schema(data: dict = Body(...)):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.create_schema(data)


@app.put("/api/admin/extraction-schemas/{schema_id}")
async def update_extraction_schema(schema_id: str, data: dict = Body(...)):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    result = await service.update_schema(schema_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Schema not found")
    return result


@app.post("/api/admin/extraction-schemas/{schema_id}/extract")
async def run_extraction(schema_id: str, data: dict = Body(...)):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.extract_from_article(
        article_text=data["article_text"],
        schema_id=schema_id,
    )


@app.get("/api/admin/extraction-schemas/{schema_id}/quality")
async def get_extraction_quality(schema_id: str, sample_size: int = 100):
    from backend.services.generic_extraction import get_generic_extraction_service
    service = get_generic_extraction_service()
    return await service.get_production_quality(schema_id, sample_size)


@app.post("/api/admin/extraction-schemas/{schema_id}/deploy")
async def deploy_schema(schema_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        return await service.deploy_to_production(
            schema_id, data["test_run_id"], data.get("require_passing_tests", True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/extraction-schemas/{schema_id}/rollback")
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


@app.post("/api/admin/two-stage/extract-stage1")
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


@app.post("/api/admin/two-stage/extract-stage2")
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


@app.post("/api/admin/two-stage/extract-full")
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


@app.post("/api/admin/two-stage/reextract")
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


@app.get("/api/admin/two-stage/status/{article_id}")
async def two_stage_status(article_id: str):
    """Get extraction pipeline status for an article."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.get_extraction_status(article_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/admin/two-stage/extractions/{extraction_id}")
async def two_stage_extraction_detail(extraction_id: str):
    """Get full Stage 1 extraction with linked Stage 2 results."""
    from backend.services.two_stage_extraction import get_two_stage_service
    service = get_two_stage_service()
    try:
        return await service.get_extraction_detail(extraction_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/two-stage/batch-extract")
async def two_stage_batch_extract(data: dict = Body(...)):
    """Run two-stage pipeline with merge on a batch of pending articles.

    Body: { "limit": 50, "include_previously_failed": false }

    Includes circuit breaker: stops on permanent errors (credits exhausted,
    auth failure) and on 3 consecutive identical transient errors.
    """
    import asyncio
    import json
    import uuid as uuid_mod
    from datetime import datetime
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
                    """, uuid_mod.UUID(incident_id), datetime.utcnow(), row['id'])
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
                """, decision.reason[:500], datetime.utcnow(), row['id'])
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


# =====================
# Prompt Testing
# =====================


@app.get("/api/admin/prompt-tests/datasets")
async def list_test_datasets(
    domain_id: Optional[str] = None,
    category_id: Optional[str] = None,
):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"datasets": await service.list_datasets(domain_id, category_id)}


@app.post("/api/admin/prompt-tests/datasets")
async def create_test_dataset(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return await service.create_dataset(data)


@app.get("/api/admin/prompt-tests/datasets/{dataset_id}")
async def get_test_dataset(dataset_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    result = await service.get_dataset(dataset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return result


@app.get("/api/admin/prompt-tests/datasets/{dataset_id}/cases")
async def list_test_cases(dataset_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"cases": await service.list_test_cases(dataset_id)}


@app.post("/api/admin/prompt-tests/cases")
async def create_test_case(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return await service.create_test_case(data)


@app.get("/api/admin/prompt-tests/runs")
async def list_test_runs(
    schema_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"runs": await service.list_test_runs(schema_id, dataset_id)}


@app.get("/api/admin/prompt-tests/runs/{run_id}")
async def get_test_run(run_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    result = await service.get_test_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Test run not found")
    return result


@app.post("/api/admin/prompt-tests/run")
async def execute_test_run(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        return await service.run_test_suite(
            data["schema_id"],
            data["dataset_id"],
            provider_name=data.get("provider_name"),
            model_name=data.get("model_name"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================
# Model Comparisons
# =====================


@app.get("/api/admin/prompt-tests/comparisons")
async def list_comparisons(limit: int = 50):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"comparisons": await service.list_comparisons(limit)}


@app.get("/api/admin/prompt-tests/comparisons/{comparison_id}")
async def get_comparison(comparison_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    result = await service.get_comparison(comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return result


@app.get("/api/admin/prompt-tests/comparisons/{comparison_id}/runs")
async def get_comparison_runs(comparison_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return await service.get_comparison_runs(comparison_id)


@app.post("/api/admin/prompt-tests/comparisons")
async def create_and_run_comparison(data: dict = Body(...)):
    import asyncio
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    comparison = await service.create_comparison(data)
    # Launch comparison execution in the background
    asyncio.create_task(service.run_comparison(comparison["id"]))
    return comparison


# =====================
# Calibration Mode
# =====================


@app.post("/api/admin/prompt-tests/calibrations")
async def create_and_run_calibration(data: dict = Body(...)):
    import asyncio
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    comparison = await service.create_calibration_comparison(data)
    asyncio.create_task(service.run_calibration(comparison["id"]))
    return comparison


@app.post("/api/admin/prompt-tests/pipeline-calibrations")
async def create_and_run_pipeline_calibration(data: dict = Body(...)):
    import asyncio
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    comparison = await service.create_pipeline_comparison(data)
    asyncio.create_task(service.run_pipeline_calibration(comparison["id"]))
    return comparison


@app.get("/api/admin/prompt-tests/calibrations/{comparison_id}/articles")
async def list_calibration_articles(comparison_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    articles = await service.list_calibration_articles(comparison_id)
    return {"articles": articles}


@app.post("/api/admin/prompt-tests/calibrations/{comparison_id}/articles/{article_id}/review")
async def review_calibration_article(comparison_id: str, article_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        result = await service.review_calibration_article(
            article_id=article_id,
            chosen_config=data.get("chosen_config"),
            golden_extraction=data.get("golden_extraction"),
            notes=data.get("reviewer_notes"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/prompt-tests/generate-prompt-improvement")
async def generate_prompt_improvement(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        result = await service.generate_prompt_improvement(data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/prompt-tests/calibrations/{comparison_id}/save-dataset")
async def save_calibration_as_dataset(comparison_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        dataset = await service.save_calibration_as_dataset(
            comparison_id=comparison_id,
            name=data["name"],
            description=data.get("description"),
        )
        return dataset
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=400, detail="'name' is required")


# =====================
# Recidivism & Analytics
# =====================


@app.get("/api/admin/recidivism/summary")
async def get_recidivism_summary():
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.get_analytics_summary()


@app.get("/api/admin/recidivism/actors")
async def list_recidivists(
    min_incidents: int = 2,
    page: int = 1,
    page_size: int = 50,
):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.list_recidivists(min_incidents, page, page_size)


@app.get("/api/admin/recidivism/actors/{actor_id}")
async def get_recidivism_profile(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.get_full_recidivism_profile(actor_id)


@app.get("/api/admin/recidivism/actors/{actor_id}/history")
async def get_actor_incident_history(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return {"history": await service.get_actor_history(actor_id)}


@app.get("/api/admin/recidivism/actors/{actor_id}/indicator")
async def get_actor_recidivism_indicator(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.get_recidivism_indicator(actor_id)


@app.get("/api/admin/recidivism/actors/{actor_id}/lifecycle")
async def get_defendant_lifecycle(actor_id: str):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return {"lifecycle": await service.get_defendant_lifecycle(actor_id)}


@app.post("/api/admin/recidivism/refresh")
async def refresh_recidivism_analysis():
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.refresh_recidivism_analysis()


# =====================
# Import Sagas
# =====================


@app.get("/api/admin/import-sagas")
async def list_import_sagas(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.list_import_sagas(status, page, page_size)


@app.post("/api/admin/import-sagas")
async def create_import_saga(data: dict = Body(...)):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    return await service.create_import_saga(data)


@app.put("/api/admin/import-sagas/{saga_id}")
async def update_import_saga(saga_id: str, data: dict = Body(...)):
    from backend.services.recidivism_service import get_recidivism_service
    service = get_recidivism_service()
    result = await service.update_import_saga(saga_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Saga not found")
    return result


# =====================
# Health Check
# =====================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    status = {"status": "healthy", "database": "disabled"}

    if USE_DATABASE:
        try:
            from backend.database import check_connection
            db_healthy = await check_connection()
            status["database"] = "connected" if db_healthy else "error"
        except Exception as e:
            status["database"] = f"error: {str(e)}"

    return status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
