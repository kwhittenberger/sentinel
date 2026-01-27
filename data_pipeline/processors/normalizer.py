"""
Data normalization for incident records.
"""

from typing import List, Optional
import re
import logging

from ..sources.base import Incident
from ..config import STATE_ABBREVS, INCIDENT_TYPE_KEYWORDS, VICTIM_CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)


class Normalizer:
    """Normalize incident data for consistency."""

    def normalize(self, incident: Incident) -> Incident:
        """Normalize a single incident."""
        # Normalize state name
        if incident.state:
            incident.state = self._normalize_state(incident.state)

        # Normalize city name
        if incident.city:
            incident.city = self._normalize_city(incident.city)

        # Normalize incident type
        if incident.incident_type:
            incident.incident_type = self._normalize_incident_type(incident.incident_type)

        # Normalize outcome
        if incident.outcome:
            incident.outcome_category = self._normalize_outcome(incident.outcome)
        elif incident.outcome_category:
            incident.outcome_category = self._normalize_outcome(incident.outcome_category)

        # Normalize victim category
        if incident.victim_category:
            incident.victim_category = self._normalize_victim_category(incident.victim_category)

        # Normalize victim name
        if incident.victim_name:
            incident.victim_name = self._normalize_name(incident.victim_name)

        # Set incident scale from affected count
        if incident.affected_count:
            incident.incident_scale = self._calculate_scale(incident.affected_count)

        # Ensure source_tier matches tier
        if not incident.source_tier:
            incident.source_tier = incident.tier

        return incident

    def normalize_batch(self, incidents: List[Incident]) -> List[Incident]:
        """Normalize a batch of incidents."""
        normalized = [self.normalize(inc) for inc in incidents]
        logger.info(f"Normalized {len(normalized)} incidents")
        return normalized

    def _normalize_state(self, state: str) -> str:
        """Normalize state name to full name."""
        state = state.strip()

        # Already full name
        if state in STATE_ABBREVS:
            return state

        # Convert abbreviation
        state_upper = state.upper()
        for full_name, abbrev in STATE_ABBREVS.items():
            if abbrev == state_upper:
                return full_name

        # Case-insensitive match
        state_lower = state.lower()
        for full_name in STATE_ABBREVS.keys():
            if full_name.lower() == state_lower:
                return full_name

        return state  # Return as-is if no match

    def _normalize_city(self, city: str) -> str:
        """Normalize city name."""
        city = city.strip()

        # Title case
        city = city.title()

        # Fix common abbreviations
        replacements = {
            "St ": "St. ",
            "St.": "St.",
            "Mt ": "Mt. ",
            "Mt.": "Mt.",
            "Ft ": "Fort ",
            "Ft.": "Fort",
            " Dc": " DC",
            " dc": " DC",
        }

        for old, new in replacements.items():
            city = city.replace(old, new)

        return city

    def _normalize_incident_type(self, incident_type: str) -> str:
        """Normalize incident type to standard values."""
        type_lower = incident_type.lower().strip()

        # Direct mapping
        standard_types = {
            "death_in_custody": "death_in_custody",
            "death in custody": "death_in_custody",
            "custody death": "death_in_custody",
            "shooting_by_agent": "shooting_by_agent",
            "shooting by agent": "shooting_by_agent",
            "agent shooting": "shooting_by_agent",
            "officer-involved shooting": "shooting_by_agent",
            "shooting_at_agent": "shooting_at_agent",
            "shooting at agent": "shooting_at_agent",
            "less_lethal": "less_lethal",
            "less lethal": "less_lethal",
            "non-lethal": "less_lethal",
            "taser": "less_lethal",
            "pepper spray": "less_lethal",
            "physical_force": "physical_force",
            "physical force": "physical_force",
            "use of force": "physical_force",
            "wrongful_detention": "wrongful_detention",
            "wrongful detention": "wrongful_detention",
            "wrongful_deportation": "wrongful_deportation",
            "wrongful deportation": "wrongful_deportation",
            "mass_raid": "mass_raid",
            "mass raid": "mass_raid",
            "workplace raid": "mass_raid",
            "raid": "enforcement_action",
            "arrest": "enforcement_action",
            "enforcement": "enforcement_action",
            "protest": "protest_related",
        }

        if type_lower in standard_types:
            return standard_types[type_lower]

        # Check keywords
        for standard_type, keywords in INCIDENT_TYPE_KEYWORDS.items():
            if any(kw in type_lower for kw in keywords):
                return standard_type

        # Convert spaces and dashes to underscores
        normalized = re.sub(r'[\s-]+', '_', type_lower)
        return normalized

    def _normalize_outcome(self, outcome: str) -> str:
        """Normalize outcome to standard values."""
        outcome_lower = outcome.lower().strip()

        mappings = {
            "death": "death",
            "died": "death",
            "killed": "death",
            "fatal": "death",
            "fatality": "death",
            "deceased": "death",
            "injury": "injury",
            "injured": "injury",
            "wounded": "injury",
            "hospitalized": "injury",
            "arrest": "arrest",
            "arrested": "arrest",
            "apprehended": "arrest",
            "detention": "detention",
            "detained": "detention",
            "deportation": "deportation",
            "deported": "deportation",
            "removed": "deportation",
            "release": "release",
            "released": "release",
        }

        for key, value in mappings.items():
            if key in outcome_lower:
                return value

        return "unknown"

    def _normalize_victim_category(self, category: str) -> str:
        """Normalize victim category."""
        cat_lower = category.lower().strip()

        mappings = {
            "detainee": "detainee",
            "in custody": "detainee",
            "enforcement_target": "enforcement_target",
            "target": "enforcement_target",
            "protester": "protester",
            "demonstrator": "protester",
            "activist": "protester",
            "journalist": "journalist",
            "reporter": "journalist",
            "media": "journalist",
            "press": "journalist",
            "bystander": "bystander",
            "uninvolved": "bystander",
            "innocent": "bystander",
            "us_citizen": "us_citizen_collateral",
            "american": "us_citizen_collateral",
            "citizen": "us_citizen_collateral",
            "officer": "officer",
            "agent": "officer",
        }

        for key, value in mappings.items():
            if key in cat_lower:
                return value

        return category

    def _normalize_name(self, name: str) -> str:
        """Normalize person name."""
        name = name.strip()

        # Title case
        name = name.title()

        # Fix common issues
        name = re.sub(r'\s+', ' ', name)  # Multiple spaces

        # Handle suffixes
        suffixes = ["Jr", "Sr", "Ii", "Iii", "Iv"]
        for suffix in suffixes:
            pattern = rf'\b{suffix}\b'
            name = re.sub(pattern, suffix.upper() if suffix in ["Ii", "Iii", "Iv"] else suffix + ".", name, flags=re.IGNORECASE)

        return name

    def _calculate_scale(self, count: int) -> str:
        """Calculate incident scale from affected count."""
        if count <= 1:
            return "single"
        elif count <= 5:
            return "small"
        elif count <= 50:
            return "medium"
        elif count <= 200:
            return "large"
        else:
            return "mass"


def normalize_incidents(incidents: List[Incident]) -> List[Incident]:
    """Convenience function to normalize incidents."""
    normalizer = Normalizer()
    return normalizer.normalize_batch(incidents)
