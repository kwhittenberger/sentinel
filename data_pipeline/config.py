"""
Configuration for data pipeline sources and settings.
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INCIDENTS_DIR = DATA_DIR / "incidents"
CACHE_DIR = DATA_DIR / ".cache"

# Ensure directories exist
CACHE_DIR.mkdir(exist_ok=True)

@dataclass
class SourceConfig:
    """Configuration for a data source."""
    name: str
    tier: int
    url: str
    enabled: bool = True
    requires_api_key: bool = False
    api_key_env_var: Optional[str] = None
    rate_limit_seconds: float = 1.0
    cache_hours: int = 24
    collection_method: str = "systematic_news"


# Data source configurations
SOURCES = {
    # Tier 1 - Official government sources
    "ice_deaths": SourceConfig(
        name="ICE Detainee Death Reporting",
        tier=1,
        url="https://www.ice.gov/detain/detainee-death-reporting",
        collection_method="official_report",
        cache_hours=168,  # Weekly
    ),
    "aila_deaths": SourceConfig(
        name="AILA Deaths at Adult Detention Centers",
        tier=1,
        url="https://www.aila.org/library/deaths-at-adult-detention-centers",
        collection_method="official_report",
        cache_hours=168,
    ),

    # Tier 2 - Investigative journalism
    "the_trace": SourceConfig(
        name="The Trace ICE Shootings Tracker",
        tier=2,
        url="https://www.thetrace.org/2025/12/immigration-ice-shootings-guns-tracker/",
        collection_method="investigative",
        cache_hours=72,
    ),
    "nbc_shootings": SourceConfig(
        name="NBC News ICE Shootings List",
        tier=2,
        url="https://www.nbcnews.com/news/us-news/ice-shootings-list-border-patrol-trump-immigration-operations-rcna254202",
        collection_method="investigative",
        cache_hours=72,
    ),
    "propublica_citizens": SourceConfig(
        name="ProPublica US Citizens Investigation",
        tier=2,
        url="https://www.propublica.org/article/immigration-dhs-american-citizens-arrested-detained-against-will",
        collection_method="investigative",
        cache_hours=168,
    ),

    # Tier 3 - Systematic news search
    "news_api": SourceConfig(
        name="News API",
        tier=3,
        url="https://newsapi.org/v2/everything",
        requires_api_key=True,
        api_key_env_var="NEWS_API_KEY",
        collection_method="systematic_news",
        rate_limit_seconds=0.5,
        cache_hours=24,
    ),
    "gdelt": SourceConfig(
        name="GDELT Project",
        tier=3,
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        collection_method="systematic_news",
        rate_limit_seconds=1.0,
        cache_hours=24,
    ),
}

# Search terms for news sources
NEWS_SEARCH_TERMS = [
    "ICE arrest",
    "ICE raid",
    "ICE shooting",
    "immigration enforcement shooting",
    "ICE detention death",
    "CBP shooting",
    "border patrol shooting",
    "immigration raid",
    "deportation arrest",
    "ICE protest",
    "immigration enforcement violence",
]

# State name to abbreviation mapping
STATE_ABBREVS = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
    "Puerto Rico": "PR",
}

# Incident type mappings
INCIDENT_TYPE_KEYWORDS = {
    "death_in_custody": ["death in custody", "died in detention", "died in ICE", "died in custody"],
    "shooting_by_agent": ["shot by", "agent shot", "officer shot", "opened fire", "shooting"],
    "less_lethal": ["pepper spray", "taser", "tear gas", "rubber bullets", "less-lethal"],
    "physical_force": ["tackled", "restrained", "chokehold", "physical force"],
    "wrongful_detention": ["wrongfully detained", "US citizen detained", "american citizen detained"],
    "wrongful_deportation": ["wrongfully deported", "US citizen deported", "american citizen deported"],
    "mass_raid": ["mass raid", "workplace raid", "large-scale enforcement", "hundreds arrested"],
}

# Victim category keywords
VICTIM_CATEGORY_KEYWORDS = {
    "detainee": ["detainee", "in custody", "detained person"],
    "enforcement_target": ["arrest target", "being arrested", "enforcement target"],
    "protester": ["protester", "demonstrator", "protest"],
    "journalist": ["journalist", "reporter", "press", "media"],
    "bystander": ["bystander", "uninvolved", "wrong person"],
    "us_citizen_collateral": ["US citizen", "american citizen", "citizen wrongly"],
    "officer": ["officer injured", "agent injured", "attacked officer"],
}

# Output file mappings
OUTPUT_FILES = {
    1: {
        "deaths": "tier1_deaths_in_custody.json",
    },
    2: {
        "shootings": "tier2_shootings.json",
        "less_lethal": "tier2_less_lethal.json",
    },
    3: {
        "incidents": "tier3_incidents.json",
    },
    4: {
        "incidents": "tier4_incidents.json",
    },
}
