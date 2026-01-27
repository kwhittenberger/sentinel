"""
JSON importer for manual data import.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging

from ..sources.base import Incident

logger = logging.getLogger(__name__)


class JSONImporter:
    """Import incidents from JSON files."""

    def __init__(self, default_tier: int = 4):
        self.default_tier = default_tier

    def import_file(self, file_path: str | Path) -> List[Incident]:
        """Import incidents from a JSON file."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return self.import_data(data)

    def import_data(self, data: Union[List, Dict]) -> List[Incident]:
        """Import incidents from JSON data structure."""
        incidents = []

        # Handle different structures
        if isinstance(data, list):
            # Array of incidents
            for item in data:
                incident = self._parse_item(item)
                if incident:
                    incidents.append(incident)

        elif isinstance(data, dict):
            # Could be wrapped in a key
            if "incidents" in data:
                return self.import_data(data["incidents"])
            elif "data" in data:
                return self.import_data(data["data"])
            elif "results" in data:
                return self.import_data(data["results"])
            else:
                # Single incident
                incident = self._parse_item(data)
                if incident:
                    incidents.append(incident)

        logger.info(f"Imported {len(incidents)} incidents")
        return incidents

    def _parse_item(self, item: Dict[str, Any]) -> Optional[Incident]:
        """Parse a JSON object into an Incident."""
        if not isinstance(item, dict):
            return None

        # Check for required fields
        date = item.get("date")
        state = item.get("state")

        if not date or not state:
            logger.warning(f"Missing required fields in item: {item.get('id', 'unknown')}")
            return None

        try:
            # Set default tier if not specified
            tier = item.get("tier", item.get("source_tier", self.default_tier))

            incident = Incident(
                date=date,
                state=state,
                incident_type=item.get("incident_type", "other"),
                id=item.get("id"),
                source_id=item.get("source_id"),
                city=item.get("city"),
                county=item.get("county"),
                lat=item.get("lat"),
                lon=item.get("lon"),
                victim_name=item.get("victim_name"),
                victim_age=item.get("victim_age"),
                victim_nationality=item.get("victim_nationality"),
                victim_category=item.get("victim_category"),
                us_citizen=item.get("us_citizen", False),
                outcome=item.get("outcome"),
                outcome_category=item.get("outcome_category"),
                agency=item.get("agency"),
                agent_name=item.get("agent_name"),
                circumstances=item.get("circumstances"),
                notes=item.get("notes"),
                affected_count=item.get("affected_count", 1),
                incident_scale=item.get("incident_scale", "single"),
                affected_breakdown=item.get("affected_breakdown"),
                tier=tier,
                source_tier=item.get("source_tier", tier),
                source_url=item.get("source_url"),
                source_name=item.get("source_name"),
                collection_method=item.get("collection_method", "manual_import"),
                verified=item.get("verified", False),
                date_precision=item.get("date_precision", "day"),
                state_sanctuary_status=item.get("state_sanctuary_status"),
                local_sanctuary_status=item.get("local_sanctuary_status"),
                detainer_policy=item.get("detainer_policy"),
                related_incidents=item.get("related_incidents", []),
                linked_ids=item.get("linked_ids", []),
                canonical_incident_id=item.get("canonical_incident_id"),
                is_primary_record=item.get("is_primary_record", True),
            )
            return incident

        except Exception as e:
            logger.warning(f"Failed to parse item: {e}")
            return None

    def merge_with_existing(
        self,
        new_incidents: List[Incident],
        existing_file: str | Path,
        deduplicate: bool = True
    ) -> List[Incident]:
        """Merge new incidents with existing data file."""
        existing_file = Path(existing_file)

        if existing_file.exists():
            existing = self.import_file(existing_file)
        else:
            existing = []

        if deduplicate:
            # Remove duplicates based on matching
            merged = list(existing)
            for new in new_incidents:
                is_duplicate = False
                for ex in existing:
                    if new.matches(ex):
                        is_duplicate = True
                        logger.debug(f"Duplicate found: {new.id} matches {ex.id}")
                        break
                if not is_duplicate:
                    merged.append(new)
        else:
            merged = existing + new_incidents

        logger.info(f"Merged: {len(existing)} existing + {len(new_incidents)} new = {len(merged)} total")
        return merged


def import_json(file_path: str, tier: int = 4) -> List[Incident]:
    """Convenience function to import JSON file."""
    importer = JSONImporter(default_tier=tier)
    return importer.import_file(file_path)
