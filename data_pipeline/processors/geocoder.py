"""
Geocoding for incident locations.
"""

from typing import List, Optional, Tuple, Dict
import logging
import time

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from ..sources.base import Incident
from ..config import CACHE_DIR

logger = logging.getLogger(__name__)

# Built-in city coordinates (expanded from backend)
CITY_COORDS: Dict[str, Tuple[float, float]] = {
    # Major cities
    "Chicago, Illinois": (41.8781, -87.6298),
    "Los Angeles, California": (34.0522, -118.2437),
    "New York, New York": (40.7128, -74.0060),
    "New York City, New York": (40.7128, -74.0060),
    "Houston, Texas": (29.7604, -95.3698),
    "Phoenix, Arizona": (33.4484, -112.0740),
    "Philadelphia, Pennsylvania": (39.9526, -75.1652),
    "San Antonio, Texas": (29.4241, -98.4936),
    "San Diego, California": (32.7157, -117.1611),
    "Dallas, Texas": (32.7767, -96.7970),
    "San Jose, California": (37.3382, -121.8863),
    "Austin, Texas": (30.2672, -97.7431),
    "Jacksonville, Florida": (30.3322, -81.6557),
    "Fort Worth, Texas": (32.7555, -97.3308),
    "Columbus, Ohio": (39.9612, -82.9988),
    "Charlotte, North Carolina": (35.2271, -80.8431),
    "San Francisco, California": (37.7749, -122.4194),
    "Indianapolis, Indiana": (39.7684, -86.1581),
    "Seattle, Washington": (47.6062, -122.3321),
    "Denver, Colorado": (39.7392, -104.9903),
    "Washington, District of Columbia": (38.9072, -77.0369),
    "Boston, Massachusetts": (42.3601, -71.0589),
    "El Paso, Texas": (31.7619, -106.4850),
    "Nashville, Tennessee": (36.1627, -86.7816),
    "Detroit, Michigan": (42.3314, -83.0458),
    "Portland, Oregon": (45.5152, -122.6784),
    "Memphis, Tennessee": (35.1495, -90.0490),
    "Oklahoma City, Oklahoma": (35.4676, -97.5164),
    "Las Vegas, Nevada": (36.1699, -115.1398),
    "Louisville, Kentucky": (38.2527, -85.7585),
    "Baltimore, Maryland": (39.2904, -76.6122),
    "Milwaukee, Wisconsin": (43.0389, -87.9065),
    "Albuquerque, New Mexico": (35.0844, -106.6504),
    "Tucson, Arizona": (32.2226, -110.9747),
    "Fresno, California": (36.7378, -119.7871),
    "Sacramento, California": (38.5816, -121.4944),
    "Atlanta, Georgia": (33.7490, -84.3880),
    "Miami, Florida": (25.7617, -80.1918),
    "Tampa, Florida": (27.9506, -82.4572),
    "Orlando, Florida": (28.5383, -81.3792),
    "Minneapolis, Minnesota": (44.9778, -93.2650),
    "St. Paul, Minnesota": (44.9537, -93.0900),
    "Newark, New Jersey": (40.7357, -74.1724),
    "Oakland, California": (37.8044, -122.2712),
    "Omaha, Nebraska": (41.2565, -95.9345),
    "New Orleans, Louisiana": (29.9511, -90.0715),
    "Salt Lake City, Utah": (40.7608, -111.8910),
    "San Juan, Puerto Rico": (18.4655, -66.1057),
    # Add more as needed...
}


class Geocoder:
    """Add geographic coordinates to incidents."""

    def __init__(self, use_api: bool = False, api_key: Optional[str] = None):
        self.use_api = use_api and HAS_REQUESTS
        self.api_key = api_key
        self._cache: Dict[str, Tuple[float, float]] = dict(CITY_COORDS)
        self._load_cache()

    def geocode(self, incident: Incident) -> Incident:
        """Add lat/lon to incident if missing."""
        if incident.lat and incident.lon:
            return incident  # Already has coordinates

        if not incident.city and not incident.state:
            return incident  # Can't geocode

        # Try to find coordinates
        coords = self._get_coords(incident.city, incident.state)
        if coords:
            incident.lat, incident.lon = coords

        return incident

    def geocode_batch(self, incidents: List[Incident]) -> List[Incident]:
        """Geocode a batch of incidents."""
        geocoded = 0
        failed = 0

        for inc in incidents:
            had_coords = bool(inc.lat and inc.lon)
            self.geocode(inc)
            if not had_coords and inc.lat:
                geocoded += 1
            elif not had_coords:
                failed += 1

        logger.info(f"Geocoding: {geocoded} new, {failed} failed, {len(incidents) - geocoded - failed} already had coords")
        self._save_cache()

        return incidents

    def _get_coords(self, city: Optional[str], state: str) -> Optional[Tuple[float, float]]:
        """Get coordinates for a location."""
        # Try cache with full location
        if city:
            key = f"{city}, {state}"
            if key in self._cache:
                return self._cache[key]

            # Try without parenthetical
            city_clean = city.split('(')[0].strip()
            key_clean = f"{city_clean}, {state}"
            if key_clean in self._cache:
                return self._cache[key_clean]

        # Try state capital/major city as fallback
        # (could add state -> major city mapping)

        # Try API if enabled
        if self.use_api and city:
            coords = self._geocode_api(city, state)
            if coords:
                key = f"{city}, {state}"
                self._cache[key] = coords
                return coords

        return None

    def _geocode_api(self, city: str, state: str) -> Optional[Tuple[float, float]]:
        """Geocode using external API (Nominatim/OpenStreetMap)."""
        if not HAS_REQUESTS:
            return None

        try:
            # Using Nominatim (free, no API key required)
            # Be respectful of rate limits
            time.sleep(1)

            response = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": f"{city}, {state}, USA",
                    "format": "json",
                    "limit": 1,
                },
                headers={"User-Agent": "ICE Incidents Research Bot"},
                timeout=10,
            )
            response.raise_for_status()

            results = response.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                logger.debug(f"Geocoded {city}, {state}: ({lat}, {lon})")
                return (lat, lon)

        except Exception as e:
            logger.warning(f"Geocoding failed for {city}, {state}: {e}")

        return None

    def _load_cache(self):
        """Load geocoding cache from disk."""
        cache_file = CACHE_DIR / "geocode_cache.json"
        if cache_file.exists():
            try:
                import json
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                self._cache.update({k: tuple(v) for k, v in cached.items()})
                logger.info(f"Loaded {len(cached)} cached geocodes")
            except Exception as e:
                logger.warning(f"Failed to load geocode cache: {e}")

    def _save_cache(self):
        """Save geocoding cache to disk."""
        cache_file = CACHE_DIR / "geocode_cache.json"
        try:
            import json
            # Only save API-fetched coords (not built-in)
            to_save = {k: list(v) for k, v in self._cache.items() if k not in CITY_COORDS}
            with open(cache_file, 'w') as f:
                json.dump(to_save, f, indent=2)
            logger.info(f"Saved {len(to_save)} geocodes to cache")
        except Exception as e:
            logger.warning(f"Failed to save geocode cache: {e}")

    def add_known_location(self, city: str, state: str, lat: float, lon: float):
        """Add a known location to the cache."""
        key = f"{city}, {state}"
        self._cache[key] = (lat, lon)


def geocode_incidents(incidents: List[Incident], use_api: bool = False) -> List[Incident]:
    """Convenience function to geocode incidents."""
    geocoder = Geocoder(use_api=use_api)
    return geocoder.geocode_batch(incidents)
