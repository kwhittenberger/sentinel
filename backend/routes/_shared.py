"""
Shared utilities, constants, and state for route modules.
Extracted from main.py to support the route split.
"""

import os
import uuid
import json
import logging
from pathlib import Path
from typing import Optional
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Environment flags
USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"

# Data paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
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


def get_incidents_cache():
    return _incidents_cache


def set_incidents_cache(value):
    global _incidents_cache
    _incidents_cache = value


def clear_incidents_cache():
    global _incidents_cache
    _incidents_cache = None


def require_database():
    """FastAPI dependency to guard database-only endpoints."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")


def parse_uuid(value: str, label: str = "ID") -> uuid.UUID:
    """Parse a UUID string, raising 400 on invalid format."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {label} format")


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
    from backend.utils.geocoding import get_coords

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
    from backend.utils.geocoding import get_coords

    cache = get_incidents_cache()
    if cache is not None:
        return cache

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
    set_incidents_cache(deduplicated)
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
            uuid.UUID(event_id),
        )
    return {str(r["incident_id"]) for r in rows}
