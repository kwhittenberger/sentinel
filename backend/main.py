"""
FastAPI backend for ICE Violent Confrontations dashboard.
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import json
from pathlib import Path
from datetime import datetime
import pandas as pd

app = FastAPI(title="ICE Incidents API")

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
    "Chicago, Illinois": (41.8781, -87.6298),
    "Los Angeles, California": (34.0522, -118.2437),
    "Minneapolis, Minnesota": (44.9778, -93.2650),
    "New York, New York": (40.7128, -74.0060),
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
    "Baltimore, Maryland": (39.2904, -76.6122),
    "Detroit, Michigan": (42.3314, -83.0458),
    "Las Vegas, Nevada": (36.1699, -115.1398),
    "Milwaukee, Wisconsin": (43.0389, -87.9065),
    "Albuquerque, New Mexico": (35.0844, -106.6504),
    "Broadview, Illinois": (41.8639, -87.8534),
    "Aurora, Colorado": (39.7294, -104.8319),
    "Minneapolis (26th & Nicollet), Minnesota": (44.9578, -93.2780),
    "Minneapolis (Federal Building), Minnesota": (44.9765, -93.2680),
    "St. Paul, Minnesota": (44.9537, -93.0900),
    "Hopkins, Minnesota": (44.9252, -93.4183),
    "Tacoma, Washington": (47.2529, -122.4443),
    "San Jose, California": (37.3382, -121.8863),
    "Fresno, California": (36.7378, -119.7871),
    "Fort Bliss, Texas": (31.8134, -106.4224),
    "Lumpkin, Georgia": (32.0507, -84.7991),
    "Eloy, Arizona": (32.7559, -111.5548),
    "Franklin Park, Illinois": (41.9314, -87.8656),
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


def load_incidents() -> list:
    """Load and deduplicate all incidents."""
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


def filter_incidents(
    tiers: Optional[str] = None,
    states: Optional[str] = None,
    categories: Optional[str] = None,
    non_immigrant_only: bool = False,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> list:
    """Filter incidents - shared logic."""
    incidents = load_incidents()

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

    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]

    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    return incidents


@app.get("/api/incidents")
def get_incidents(
    tiers: Optional[str] = Query(None, description="Comma-separated tier numbers"),
    states: Optional[str] = Query(None, description="Comma-separated states"),
    categories: Optional[str] = Query(None, description="Comma-separated categories"),
    non_immigrant_only: bool = Query(False),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get filtered incidents."""
    incidents = filter_incidents(tiers, states, categories, non_immigrant_only, date_start, date_end)
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
def get_stats(
    tiers: Optional[str] = Query(None),
    states: Optional[str] = Query(None),
    non_immigrant_only: bool = Query(False),
):
    """Get summary statistics."""
    incidents = filter_incidents(tiers=tiers, states=states, non_immigrant_only=non_immigrant_only)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
