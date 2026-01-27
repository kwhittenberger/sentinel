"""
CSV importer for manual data import.
"""

import csv
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from ..sources.base import Incident
from ..config import STATE_ABBREVS

logger = logging.getLogger(__name__)


class CSVImporter:
    """Import incidents from CSV files."""

    # Common column name mappings
    COLUMN_MAPPINGS = {
        # Date columns
        "date": ["date", "incident_date", "event_date", "occurred_date"],
        "state": ["state", "st", "state_name", "location_state"],
        "city": ["city", "location", "city_name", "location_city"],

        # Victim info
        "victim_name": ["victim_name", "name", "person_name", "individual", "decedent"],
        "victim_age": ["victim_age", "age", "years_old"],
        "victim_nationality": ["victim_nationality", "nationality", "country", "country_of_origin"],

        # Incident info
        "incident_type": ["incident_type", "type", "event_type", "category"],
        "outcome": ["outcome", "result", "status"],
        "agency": ["agency", "law_enforcement_agency", "arresting_agency"],
        "notes": ["notes", "description", "details", "circumstances", "summary"],

        # Source info
        "source_url": ["source_url", "url", "link", "source_link"],
        "source_name": ["source_name", "source", "publication"],
    }

    def __init__(self, default_tier: int = 4):
        self.default_tier = default_tier

    def import_file(self, file_path: str | Path, encoding: str = "utf-8") -> List[Incident]:
        """Import incidents from a CSV file."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        incidents = []
        errors = []

        with open(file_path, 'r', encoding=encoding) as f:
            # Try to detect delimiter
            sample = f.read(4096)
            f.seek(0)

            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample)
            except csv.Error:
                dialect = csv.excel

            reader = csv.DictReader(f, dialect=dialect)

            # Map columns to our schema
            column_map = self._map_columns(reader.fieldnames or [])
            logger.info(f"Column mapping: {column_map}")

            for row_num, row in enumerate(reader, start=2):
                try:
                    incident = self._parse_row(row, column_map)
                    if incident:
                        incidents.append(incident)
                except Exception as e:
                    errors.append(f"Row {row_num}: {e}")

        if errors:
            logger.warning(f"Import errors ({len(errors)}):\n" + "\n".join(errors[:10]))

        logger.info(f"Imported {len(incidents)} incidents from {file_path.name}")
        return incidents

    def _map_columns(self, fieldnames: List[str]) -> Dict[str, str]:
        """Map CSV columns to our schema fields."""
        column_map = {}
        fieldnames_lower = {f.lower().strip(): f for f in fieldnames}

        for our_field, possible_names in self.COLUMN_MAPPINGS.items():
            for name in possible_names:
                if name in fieldnames_lower:
                    column_map[our_field] = fieldnames_lower[name]
                    break

        return column_map

    def _parse_row(self, row: Dict[str, str], column_map: Dict[str, str]) -> Optional[Incident]:
        """Parse a CSV row into an Incident."""
        def get_value(field: str) -> Optional[str]:
            col = column_map.get(field)
            if col and col in row:
                val = row[col].strip()
                return val if val else None
            return None

        # Required fields
        date = get_value("date")
        state = get_value("state")

        if not date or not state:
            return None

        # Normalize state name
        state = self._normalize_state(state)
        if not state:
            return None

        # Parse incident type
        incident_type = get_value("incident_type") or "other"

        # Parse age
        age_str = get_value("victim_age")
        age = None
        if age_str:
            try:
                age = int(age_str)
            except ValueError:
                pass

        # Determine outcome
        outcome = get_value("outcome")
        outcome_cat = None
        if outcome:
            outcome_lower = outcome.lower()
            if any(w in outcome_lower for w in ["death", "died", "killed", "fatal"]):
                outcome_cat = "death"
            elif any(w in outcome_lower for w in ["injury", "injured", "wounded"]):
                outcome_cat = "injury"
            else:
                outcome_cat = outcome_lower

        incident = Incident(
            date=self._normalize_date(date),
            state=state,
            city=get_value("city"),
            incident_type=incident_type,
            victim_name=get_value("victim_name"),
            victim_age=age,
            victim_nationality=get_value("victim_nationality"),
            outcome=outcome_cat,
            outcome_category=outcome_cat,
            agency=get_value("agency"),
            notes=get_value("notes"),
            tier=self.default_tier,
            source_url=get_value("source_url"),
            source_name=get_value("source_name"),
            collection_method="manual_import",
            verified=False,
        )

        return incident

    def _normalize_state(self, state: str) -> Optional[str]:
        """Normalize state name."""
        state = state.strip()

        # Check if it's already a full name
        if state in STATE_ABBREVS:
            return state

        # Check if it's an abbreviation
        state_upper = state.upper()
        for full_name, abbrev in STATE_ABBREVS.items():
            if abbrev == state_upper:
                return full_name

        # Try case-insensitive match
        state_lower = state.lower()
        for full_name in STATE_ABBREVS.keys():
            if full_name.lower() == state_lower:
                return full_name

        logger.warning(f"Unknown state: {state}")
        return None

    def _normalize_date(self, date_str: str) -> str:
        """Normalize date to ISO format."""
        from datetime import datetime

        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y/%m/%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Return as-is if we can't parse
        return date_str


def import_csv(file_path: str, tier: int = 4) -> List[Incident]:
    """Convenience function to import CSV file."""
    importer = CSVImporter(default_tier=tier)
    return importer.import_file(file_path)
