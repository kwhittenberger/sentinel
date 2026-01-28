"""
FastAPI backend for Unified Incident Tracker dashboard.
Supports both ICE enforcement incidents and immigration-related crime cases.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException, Depends, Body
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

logger = logging.getLogger(__name__)

# Check if we should use database
USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    if USE_DATABASE:
        from backend.database import get_pool, close_pool
        await get_pool()
        logger.info("Database connection pool initialized")

        # Start background job executor
        from backend.services.job_executor import get_executor
        executor = get_executor()
        await executor.start()
        logger.info("Background job executor started")

    yield

    if USE_DATABASE:
        # Stop job executor
        from backend.services.job_executor import get_executor
        executor = get_executor()
        await executor.stop()
        logger.info("Background job executor stopped")

        from backend.database import close_pool
        await close_pool()
        logger.info("Database connection pool closed")


app = FastAPI(
    title="Unified Incident Tracker API",
    description="API for ICE enforcement incidents and immigration-related crime cases",
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

# City coordinates
CITY_COORDS = {
    # Major cities
    "Chicago, Illinois": (41.8781, -87.6298),
    "Los Angeles, California": (34.0522, -118.2437),
    "Minneapolis, Minnesota": (44.9778, -93.2650),
    "New York, New York": (40.7128, -74.0060),
    "New York City, New York": (40.7128, -74.0060),
    "Portland, Oregon": (45.5152, -122.6784),
    "San Francisco, California": (37.7749, -122.4194),
    "Seattle, Washington": (47.6062, -122.3321),
    "Newark, New Jersey": (40.7357, -74.1724),
    "Denver, Colorado": (39.7392, -104.9903),
    "Phoenix, Arizona": (33.4484, -112.0740),
    "Houston, Texas": (29.7604, -95.3698),
    "Dallas, Texas": (32.7767, -96.7970),
    "Austin, Texas": (30.2672, -97.7431),
    "Atlanta, Georgia": (33.7490, -84.3880),
    "Miami, Florida": (25.7617, -80.1918),
    "Boston, Massachusetts": (42.3601, -71.0589),
    "Philadelphia, Pennsylvania": (39.9526, -75.1652),
    "San Diego, California": (32.7157, -117.1611),
    "Oakland, California": (37.8044, -122.2712),
    "Sacramento, California": (38.5816, -121.4944),
    "San Antonio, Texas": (29.4241, -98.4936),
    "El Paso, Texas": (31.7619, -106.4850),
    "Tucson, Arizona": (32.2226, -110.9747),
    "Washington, District of Columbia": (38.9072, -77.0369),
    "Washington DC, District of Columbia": (38.9072, -77.0369),
    "Baltimore, Maryland": (39.2904, -76.6122),
    "Detroit, Michigan": (42.3314, -83.0458),
    "Las Vegas, Nevada": (36.1699, -115.1398),
    "North Las Vegas, Nevada": (36.1989, -115.1175),
    "Milwaukee, Wisconsin": (43.0389, -87.9065),
    "Albuquerque, New Mexico": (35.0844, -106.6504),
    # California cities
    "Paramount, California": (33.8894, -118.1597),
    "Northridge, Los Angeles, California": (34.2283, -118.5366),
    "Adelanto, California": (34.5828, -117.4092),
    "Van Nuys, California": (34.1897, -118.4514),
    "Santa Ana, California": (33.7455, -117.8677),
    "Montclair, California": (34.0775, -117.6897),
    "San Bernardino, California": (34.1083, -117.2898),
    "Ontario, California": (34.0633, -117.6509),
    "Camarillo, California": (34.2164, -119.0376),
    "Bakersfield, California": (35.3733, -119.0187),
    "Encinitas, California": (33.0370, -117.2920),
    "Chula Vista, California": (32.6401, -117.0842),
    "Glendale, California": (34.1425, -118.2551),
    "Highland, California": (34.1283, -117.2086),
    "Dublin, California": (37.7022, -121.9358),
    "Monrovia, California": (34.1442, -117.9990),
    # Texas cities
    "Alvarado, Texas": (32.4068, -97.2128),
    "McAllen, Texas": (26.2034, -98.2300),
    "Laredo, Texas": (27.5064, -99.5075),
    "Rio Grande City (Starr County), Texas": (26.3796, -98.8203),
    "Sarita, Texas": (27.2214, -97.7886),
    "Dallas-Fort Worth, Texas": (32.8998, -97.0403),
    "Dilley, Texas": (28.6674, -99.1706),
    # Illinois cities
    "Broadview, Illinois": (41.8639, -87.8534),
    "Franklin Park, Illinois": (41.9314, -87.8656),
    "Elgin, Illinois": (42.0354, -88.2825),
    "Lyons, Illinois": (41.8131, -87.8181),
    # Minnesota cities
    "Minneapolis (26th & Nicollet), Minnesota": (44.9578, -93.2780),
    "Minneapolis (Federal Building), Minnesota": (44.9765, -93.2680),
    "St. Paul, Minnesota": (44.9537, -93.0900),
    "Hopkins, Minnesota": (44.9252, -93.4183),
    "Crystal (Robbinsdale), Minnesota": (45.0322, -93.3599),
    "Minneapolis-St. Paul Airport, Minnesota": (44.8848, -93.2223),
    # Other state cities
    "Aurora, Colorado": (39.7294, -104.8319),
    "Colorado Springs, Colorado": (38.8339, -104.8214),
    "Durango, Colorado": (37.2753, -107.8801),
    "Tacoma, Washington": (47.2529, -122.4443),
    "SeaTac, Washington": (47.4435, -122.2961),
    "Bellingham, Washington": (48.7519, -122.4787),
    "Spokane, Washington": (47.6588, -117.4260),
    "San Jose, California": (37.3382, -121.8863),
    "Fresno, California": (36.7378, -119.7871),
    "Fort Bliss, Texas": (31.8134, -106.4224),
    "Lumpkin, Georgia": (32.0507, -84.7991),
    "Eloy, Arizona": (32.7559, -111.5548),
    "Norfolk, Virginia": (36.8508, -76.2859),
    "San Juan, Puerto Rico": (18.4655, -66.1057),
    "Rolla, Missouri": (37.9514, -91.7712),
    "Pompano Beach, Florida": (26.2379, -80.1248),
    "Valdosta, Georgia": (30.8327, -83.2785),
    "Karnes City, Texas": (28.8850, -97.9006),
    "Florence, Arizona": (33.0314, -111.3873),
    "Victorville, California": (34.5362, -117.2928),
    "Conroe, Texas": (30.3119, -95.4561),
    "Calexico, California": (32.6789, -115.4989),
    "Orlando, Florida": (28.5383, -81.3792),
    "Tampa, Florida": (27.9506, -82.4572),
    "Jacksonville, Florida": (30.3322, -81.6557),
    "Charlotte, North Carolina": (35.2271, -80.8431),
    "Salisbury, North Carolina": (35.6708, -80.4742),
    "Des Moines, Iowa": (41.5868, -93.6250),
    "Iowa City, Iowa": (41.6611, -91.5302),
    "Fitchburg, Massachusetts": (42.5834, -71.8023),
    "Medford, Massachusetts": (42.4184, -71.1062),
    "Worcester, Massachusetts": (42.2626, -71.8023),
    "Oklahoma City, Oklahoma": (35.4676, -97.5164),
    "Liberty, Missouri": (39.2461, -94.4191),
    "St. Peters, Missouri": (38.8004, -90.6265),
    "Glen Burnie, Maryland": (39.1626, -76.6247),
    "Laurel, Maryland": (39.0993, -76.8483),
    "Gettysburg, Pennsylvania": (39.8309, -77.2311),
    "Philipsburg, Pennsylvania": (40.8962, -78.2206),
    "Baldwin, Michigan": (43.9011, -85.8517),
    "Lovejoy, Georgia": (33.4365, -84.3149),
    "Brookhaven, Georgia": (33.8651, -84.3363),
    "Tucker, Georgia": (33.8554, -84.2171),
    "Ellabell, Georgia": (32.1335, -81.4687),
    "East Meadow, New York": (40.7140, -73.5590),
    "Brooklyn, New York": (40.6782, -73.9442),
    "Bronx, New York": (40.8448, -73.8648),
    "Manhattan (SoHo/Canal St), New York": (40.7195, -74.0020),
    "Manhattan (Canal Street), New York": (40.7178, -74.0011),
    "Manhattan (26 Federal Plaza), New York": (40.7146, -74.0019),
    "Kent, New York": (41.4773, -73.7340),
    "Natchez, Mississippi": (31.5604, -91.4032),
    "New Orleans, Louisiana": (29.9511, -90.0715),
    "Baton Rouge, Louisiana": (30.4515, -91.1871),
    "Angola, Louisiana": (30.9557, -91.5968),
    "Jena, Louisiana": (31.6855, -92.1332),
    "Riviera Beach, Florida": (26.7753, -80.0581),
    "Homestead, Florida": (25.4687, -80.4776),
    "Tallahassee, Florida": (30.4383, -84.2807),
    "Nashville, Tennessee": (36.1627, -86.7816),
    "Memphis, Tennessee": (35.1495, -90.0490),
    "Huntsville, Alabama": (34.7304, -86.5861),
    "Montgomery, Alabama": (32.3792, -86.3077),
    "Foley, Alabama": (30.4066, -87.6836),
    "Omaha, Nebraska": (41.2565, -95.9345),
    "New Haven, Connecticut": (41.3083, -72.9279),
    "Providence, Rhode Island": (41.8240, -71.4128),
    "Columbus, Ohio": (39.9612, -82.9988),
    "Indianapolis, Indiana": (39.7684, -86.1581),
    "Seymour, Indiana": (38.9592, -85.8903),
    "Greenville, South Carolina": (34.8526, -82.3940),
    "Salt Lake City, Utah": (40.7608, -111.8910),
    "Woodburn, Oregon": (45.1437, -122.8557),
    "Elizabeth, New Jersey": (40.6640, -74.2107),
    "Estancia, New Mexico": (34.7581, -106.0544),
}

NON_IMMIGRANT_CATEGORIES = {
    'us_citizen', 'bystander', 'officer', 'protester',
    'journalist', 'us_citizen_collateral', 'legal_resident'
}

# Cache for loaded data
_incidents_cache = None


def get_coords(city: str, state: str) -> tuple:
    """Get coordinates for a city/state."""
    if not city or not state:
        return None, None

    city_state = f"{city}, {state}"
    if city_state in CITY_COORDS:
        return CITY_COORDS[city_state]

    # Try partial match
    city_clean = str(city).split(',')[0].split('(')[0].strip()
    city_state_clean = f"{city_clean}, {state}"
    if city_state_clean in CITY_COORDS:
        return CITY_COORDS[city_state_clean]

    # Try state match with city contains
    for key, coords in CITY_COORDS.items():
        if ',' in key:
            key_city, key_state = key.rsplit(',', 1)
            key_state = key_state.strip()
            if state == key_state and city_clean.lower() in key_city.lower():
                return coords

    return None, None


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
            i.city,
            it.name as incident_type,
            i.victim_category::text,
            i.outcome_category::text,
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

    return {"incidents": incidents, "total": len(incidents)}


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    """Get a single incident by ID."""
    incidents = load_incidents()
    for inc in incidents:
        if inc.get('id') == incident_id:
            return inc
    return {"error": "Not found"}, 404


@app.get("/api/stats")
async def get_stats(
    tiers: Optional[str] = Query(None),
    states: Optional[str] = Query(None),
    non_immigrant_only: bool = Query(False),
    death_only: bool = Query(False),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get summary statistics."""
    if USE_DATABASE:
        incidents = await filter_incidents_async(tiers=tiers, states=states, non_immigrant_only=non_immigrant_only, death_only=death_only, date_start=date_start, date_end=date_end)
    else:
        incidents = filter_incidents(tiers=tiers, states=states, non_immigrant_only=non_immigrant_only, death_only=death_only, date_start=date_start, date_end=date_end)

    # Calculate stats
    total = len(incidents)
    deaths = sum(1 for i in incidents if i.get('is_death'))
    states_affected = len(set(i.get('state') for i in incidents if i.get('state')))
    non_immigrant = sum(1 for i in incidents if i.get('is_non_immigrant'))

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

    return {
        "total_incidents": total,
        "total_deaths": deaths,
        "states_affected": states_affected,
        "non_immigrant_incidents": non_immigrant,
        "by_tier": by_tier,
        "by_state": by_state,
        "by_incident_type": by_type,
    }


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
        WHERE status = 'pending'
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

    # Map tier to confidence threshold
    tier_thresholds = {
        "high": (0.85, 1.0),
        "medium": (0.50, 0.85),
        "low": (0.0, 0.50),
    }

    if tier not in tier_thresholds:
        raise HTTPException(status_code=400, detail="Invalid tier. Must be: high, medium, low")

    min_conf, max_conf = tier_thresholds[tier]

    # Get articles in tier
    query = """
        SELECT id, extracted_data, source_url, extraction_confidence
        FROM ingested_articles
        WHERE status = 'pending'
          AND extraction_confidence >= $1
          AND extraction_confidence < $2
        ORDER BY extraction_confidence DESC
        LIMIT $3
    """
    rows = await fetch(query, min_conf, max_conf, limit)

    approved_count = 0
    incident_ids = []

    for row in rows:
        article_id = row["id"]
        extracted_data = row.get("extracted_data") or {}
        if isinstance(extracted_data, dict) and "extracted_data" in extracted_data:
            extracted_data = extracted_data.get("extracted_data") or {}

        # Create incident
        incident_id = uuid.uuid4()
        incident_date = None
        date_str = extracted_data.get("date")
        if date_str:
            try:
                from datetime import date as date_type
                incident_date = date_type.fromisoformat(date_str)
            except:
                pass
        if not incident_date:
            incident_date = datetime.utcnow().date()

        # Get or create incident_type_id (simplified - use a default)
        incident_type_name = extracted_data.get("incident_type", "other")
        type_rows = await fetch("SELECT id FROM incident_types WHERE name = $1 LIMIT 1", incident_type_name)
        if type_rows:
            incident_type_id = type_rows[0]["id"]
        else:
            incident_type_id = uuid.uuid4()
            await execute(
                "INSERT INTO incident_types (id, name, category) VALUES ($1, $2, $3)",
                incident_type_id, incident_type_name, "crime"
            )

        await execute("""
            INSERT INTO incidents (
                id, category, date, state, city, incident_type_id,
                description, source_url, source_tier, curation_status,
                extraction_confidence, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """,
            incident_id, "crime", incident_date,
            extracted_data.get("state"), extracted_data.get("city"),
            incident_type_id, extracted_data.get("description"),
            row.get("source_url"), "2", "approved",
            float(row["extraction_confidence"]) if row.get("extraction_confidence") else None,
            datetime.utcnow()
        )

        # Update article status
        await execute("""
            UPDATE ingested_articles
            SET status = 'approved', incident_id = $1, reviewed_at = $2
            WHERE id = $3
        """, incident_id, datetime.utcnow(), article_id)

        approved_count += 1
        incident_ids.append(str(incident_id))

    return {
        "success": True,
        "approved_count": approved_count,
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

    tier_thresholds = {
        "high": (0.85, 1.0),
        "medium": (0.50, 0.85),
        "low": (0.0, 0.50),
    }

    if tier not in tier_thresholds:
        raise HTTPException(status_code=400, detail="Invalid tier. Must be: high, medium, low")

    min_conf, max_conf = tier_thresholds[tier]

    result = await execute("""
        UPDATE ingested_articles
        SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
        WHERE id IN (
            SELECT id FROM ingested_articles
            WHERE status = 'pending'
              AND extraction_confidence >= $3
              AND extraction_confidence < $4
            LIMIT $5
        )
    """, reason, datetime.utcnow(), min_conf, max_conf, limit)

    # Parse result to get count
    rejected_count = 0
    if "UPDATE" in result:
        try:
            rejected_count = int(result.split()[1])
        except:
            pass

    return {"success": True, "rejected_count": rejected_count}


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


@app.post("/api/admin/queue/{article_id}/approve")
async def approve_article(
    article_id: str,
    overrides: Optional[dict] = Body(None),
):
    """Approve an article and create an incident."""
    import uuid
    from datetime import datetime

    if not USE_DATABASE:
        return {"success": False, "error": "Database not enabled"}

    from backend.database import fetch, execute

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

    # Create incident from extracted data
    incident_id = str(uuid.uuid4())

    # Parse date - default to today if not provided
    date_str = extracted_data.get("date")
    incident_date = None
    if date_str:
        try:
            from datetime import date as date_type
            incident_date = date_type.fromisoformat(date_str)
        except:
            pass
    if not incident_date:
        incident_date = datetime.utcnow().date()

    # Get or create incident_type_id
    incident_type_name = extracted_data.get("incident_type", "other")
    type_query = "SELECT id FROM incident_types WHERE name = $1 LIMIT 1"
    type_rows = await fetch(type_query, incident_type_name)
    if type_rows:
        incident_type_id = type_rows[0]["id"]
    else:
        # Create new incident type
        import uuid as uuid_mod
        incident_type_id = uuid_mod.uuid4()
        await execute(
            "INSERT INTO incident_types (id, name, category) VALUES ($1, $2, $3)",
            incident_type_id, incident_type_name, "crime"
        )

    insert_query = """
        INSERT INTO incidents (
            id, category, date, state, city, incident_type_id,
            description, source_url, source_tier, curation_status,
            extraction_confidence, victim_name, victim_age,
            prior_deportations, gang_affiliated, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        RETURNING id
    """

    await execute(
        insert_query,
        uuid.UUID(incident_id),
        "crime",  # Default to crime category for new articles
        incident_date,
        extracted_data.get("state"),
        extracted_data.get("city"),
        incident_type_id,
        extracted_data.get("description"),
        article.get("source_url"),
        "2",  # Default tier as string
        "approved",
        float(article["extraction_confidence"]) if article.get("extraction_confidence") else None,
        extracted_data.get("victim_name"),
        extracted_data.get("victim_age"),
        extracted_data.get("prior_deportations", 0),
        extracted_data.get("gang_affiliated", False),
        datetime.utcnow()
    )

    # Update article status
    update_query = """
        UPDATE ingested_articles
        SET status = 'approved', incident_id = $1, reviewed_at = $2
        WHERE id = $3
    """
    await execute(update_query, uuid.UUID(incident_id), datetime.utcnow(), uuid.UUID(article_id))

    return {"success": True, "incident_id": incident_id}


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
            SELECT i.*, it.name as incident_type
            FROM incidents i
            LEFT JOIN incident_types it ON i.incident_type_id = it.id
            WHERE i.id = $1
        """, incident_uuid)

        if not rows:
            raise HTTPException(status_code=404, detail="Incident not found")

        row = dict(rows[0])
        if row.get('date'):
            row['date'] = row['date'].isoformat()
        return row
    else:
        incidents = load_incidents()
        for inc in incidents:
            if inc.get('id') == incident_id:
                return inc
        raise HTTPException(status_code=404, detail="Incident not found")


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

    if status:
        query = """
            SELECT id, job_type, status, progress, total, message, created_at, started_at, completed_at, error
            FROM background_jobs
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await fetch(query, status, limit)
    else:
        query = """
            SELECT id, job_type, status, progress, total, message, created_at, started_at, completed_at, error
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

    job_id = uuid.uuid4()
    await execute("""
        INSERT INTO background_jobs (id, job_type, status, params, created_at)
        VALUES ($1, $2, 'pending', $3, $4)
    """, job_id, job_type, params or {}, datetime.utcnow())

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

    from backend.database import execute
    import uuid
    from datetime import datetime

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    result = await execute("""
        UPDATE background_jobs
        SET status = 'cancelled', completed_at = $1
        WHERE id = $2 AND status IN ('pending', 'running')
    """, datetime.utcnow(), job_uuid)

    return {"success": True, "cancelled": job_id}


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
    """List all RSS feeds."""
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
        SELECT id, name, url, feed_type, interval_minutes, active, last_fetched, created_at
        FROM rss_feeds
        ORDER BY name
    """)

    feeds = []
    for row in rows:
        feed = dict(row)
        feed['id'] = str(feed['id'])
        for field in ['last_fetched', 'created_at']:
            if feed.get(field):
                feed[field] = feed[field].isoformat()
        feeds.append(feed)

    return {"feeds": feeds}


@app.post("/api/admin/feeds")
async def create_feed(
    name: str = Body(..., embed=True),
    url: str = Body(..., embed=True),
    feed_type: str = Body("rss", embed=True),
    interval_minutes: int = Body(60, embed=True),
):
    """Create a new RSS feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid
    from datetime import datetime

    feed_id = uuid.uuid4()
    await execute("""
        INSERT INTO rss_feeds (id, name, url, feed_type, interval_minutes, active, created_at)
        VALUES ($1, $2, $3, $4, $5, true, $6)
    """, feed_id, name, url, feed_type, interval_minutes, datetime.utcnow())

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

    allowed_fields = ['name', 'url', 'feed_type', 'interval_minutes', 'active']
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

    params.append(feed_uuid)
    query = f"UPDATE rss_feeds SET {', '.join(set_clauses)} WHERE id = ${param_num}"
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

    await execute("DELETE FROM rss_feeds WHERE id = $1", feed_uuid)
    return {"success": True}


@app.post("/api/admin/feeds/{feed_id}/fetch")
async def fetch_feed(feed_id: str):
    """Manually fetch a specific feed."""
    # Placeholder - would integrate with the data pipeline
    return {"success": True, "message": "Feed fetch initiated", "feed_id": feed_id}


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

    await execute("UPDATE rss_feeds SET active = $1 WHERE id = $2", active, feed_uuid)
    return {"success": True, "active": active}


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
