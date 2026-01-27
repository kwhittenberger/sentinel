"""
Base classes for data sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import hashlib
import time
import logging

from ..config import CACHE_DIR, SourceConfig

logger = logging.getLogger(__name__)


@dataclass
class Incident:
    """Standardized incident record."""
    # Required fields
    date: str  # ISO format YYYY-MM-DD
    state: str
    incident_type: str

    # Identity
    id: Optional[str] = None
    source_id: Optional[str] = None  # ID from original source

    # Location
    city: Optional[str] = None
    county: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    # Victim info
    victim_name: Optional[str] = None
    victim_age: Optional[int] = None
    victim_nationality: Optional[str] = None
    victim_category: Optional[str] = None
    us_citizen: bool = False

    # Incident details
    outcome: Optional[str] = None  # death, injury, arrest, etc.
    outcome_category: Optional[str] = None
    agency: Optional[str] = None  # ICE, CBP, etc.
    agent_name: Optional[str] = None
    circumstances: Optional[str] = None
    notes: Optional[str] = None

    # Scale
    affected_count: int = 1
    incident_scale: str = "single"  # single, small, medium, large, mass
    affected_breakdown: Optional[Dict[str, int]] = None

    # Source tracking
    tier: int = 4
    source_tier: Optional[int] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    collection_method: str = "ad_hoc"
    verified: bool = False

    # Dates
    date_precision: str = "day"  # day, week, month, year
    date_retrieved: Optional[str] = None

    # Classification
    state_sanctuary_status: Optional[str] = None
    local_sanctuary_status: Optional[str] = None
    detainer_policy: Optional[str] = None

    # Relations
    related_incidents: List[str] = field(default_factory=list)
    linked_ids: List[str] = field(default_factory=list)
    canonical_incident_id: Optional[str] = None
    is_primary_record: bool = True

    def __post_init__(self):
        """Generate ID if not provided."""
        if not self.id:
            self.id = self.generate_id()
        if not self.source_tier:
            self.source_tier = self.tier
        if not self.date_retrieved:
            self.date_retrieved = datetime.now().isoformat()

    def generate_id(self) -> str:
        """Generate a unique ID based on incident details."""
        # Create hash from key fields
        key_parts = [
            self.date or "",
            self.state or "",
            self.city or "",
            self.victim_name or "",
            self.incident_type or "",
        ]
        hash_input = "|".join(key_parts).encode()
        short_hash = hashlib.sha256(hash_input).hexdigest()[:8]

        tier_prefix = f"T{self.tier}"
        type_code = {
            "death_in_custody": "D",
            "shooting_by_agent": "S",
            "shooting_at_agent": "SA",
            "less_lethal": "LL",
            "physical_force": "PF",
            "wrongful_detention": "WD",
            "wrongful_deportation": "WX",
            "mass_raid": "MR",
        }.get(self.incident_type, "X")

        return f"{tier_prefix}-{type_code}-{short_hash}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        data = asdict(self)
        # Remove None values and empty lists
        return {k: v for k, v in data.items() if v is not None and v != [] and v != {}}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Incident":
        """Create Incident from dictionary."""
        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def matches(self, other: "Incident", threshold: float = 0.8) -> bool:
        """Check if this incident likely matches another (for deduplication)."""
        score = 0.0
        checks = 0

        # Date match (required)
        if self.date and other.date:
            if self.date == other.date:
                score += 1.0
            elif abs((datetime.fromisoformat(self.date) - datetime.fromisoformat(other.date)).days) <= 3:
                score += 0.5
            checks += 1

        # State match (required)
        if self.state and other.state:
            if self.state.lower() == other.state.lower():
                score += 1.0
            checks += 1

        # Name match (strong indicator)
        if self.victim_name and other.victim_name:
            if self._names_match(self.victim_name, other.victim_name):
                score += 2.0  # Weighted heavily
            checks += 2

        # City match
        if self.city and other.city:
            if self.city.lower() == other.city.lower():
                score += 0.5
            checks += 0.5

        # Type match
        if self.incident_type and other.incident_type:
            if self.incident_type == other.incident_type:
                score += 0.5
            checks += 0.5

        return (score / checks) >= threshold if checks > 0 else False

    @staticmethod
    def _names_match(name1: str, name2: str) -> bool:
        """Check if two names likely refer to the same person."""
        n1 = name1.lower().strip()
        n2 = name2.lower().strip()

        if n1 == n2:
            return True
        if n1 in n2 or n2 in n1:
            return True

        # Check last name + first initial
        parts1 = n1.split()
        parts2 = n2.split()
        if parts1 and parts2 and parts1[-1] == parts2[-1]:
            if len(parts1) > 1 and len(parts2) > 1:
                if parts1[0][0] == parts2[0][0]:
                    return True

        return False


class BaseSource(ABC):
    """Base class for data sources."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{config.name}")
        self._last_request_time = 0.0

    @abstractmethod
    def fetch(self) -> List[Incident]:
        """Fetch incidents from the source. Returns list of Incident objects."""
        pass

    @abstractmethod
    def parse_response(self, response: Any) -> List[Incident]:
        """Parse raw response into Incident objects."""
        pass

    def get_cache_path(self) -> Path:
        """Get path for cached data."""
        safe_name = self.config.name.replace(" ", "_").replace("/", "_")
        return CACHE_DIR / f"{safe_name}.json"

    def is_cache_valid(self) -> bool:
        """Check if cached data is still valid."""
        cache_path = self.get_cache_path()
        if not cache_path.exists():
            return False

        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        age_hours = (datetime.now() - mtime).total_seconds() / 3600
        return age_hours < self.config.cache_hours

    def load_cache(self) -> Optional[List[Dict]]:
        """Load data from cache."""
        cache_path = self.get_cache_path()
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                self.logger.info(f"Loaded {len(data)} items from cache")
                return data
            except Exception as e:
                self.logger.warning(f"Failed to load cache: {e}")
        return None

    def save_cache(self, data: List[Dict]):
        """Save data to cache."""
        cache_path = self.get_cache_path()
        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.info(f"Saved {len(data)} items to cache")
        except Exception as e:
            self.logger.warning(f"Failed to save cache: {e}")

    def rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.rate_limit_seconds:
            time.sleep(self.config.rate_limit_seconds - elapsed)
        self._last_request_time = time.time()

    def fetch_with_cache(self, force_refresh: bool = False) -> List[Incident]:
        """Fetch data, using cache if valid."""
        if not force_refresh and self.is_cache_valid():
            cached = self.load_cache()
            if cached:
                return [Incident.from_dict(d) for d in cached]

        self.logger.info(f"Fetching fresh data from {self.config.name}")
        incidents = self.fetch()

        # Save to cache
        self.save_cache([i.to_dict() for i in incidents])

        return incidents
