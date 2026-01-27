"""
Main data pipeline orchestrator.
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from .sources.base import Incident
from .sources.ice_gov import ICEGovSource, AILASource
from .sources.the_trace import TheTraceSource, NBCShootingsSource
from .sources.news_api import NewsAPISource, GDELTSource
from .importers.csv_importer import CSVImporter
from .importers.json_importer import JSONImporter
from .importers.validator import SchemaValidator, ValidationResult
from .processors.normalizer import Normalizer
from .processors.deduplicator import Deduplicator
from .processors.geocoder import Geocoder
from .config import INCIDENTS_DIR, OUTPUT_FILES, SOURCES

logger = logging.getLogger(__name__)


class DataPipeline:
    """
    Main pipeline for collecting, processing, and storing incident data.

    Usage:
        pipeline = DataPipeline()

        # Fetch from all sources
        pipeline.fetch_all()

        # Or fetch from specific sources
        pipeline.fetch_source("ice_deaths")
        pipeline.fetch_source("the_trace")

        # Import manual data
        pipeline.import_csv("my_data.csv", tier=3)
        pipeline.import_json("my_data.json", tier=2)

        # Process and save
        pipeline.process()
        pipeline.save()
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or INCIDENTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Pipeline components
        self.validator = SchemaValidator()
        self.normalizer = Normalizer()
        self.deduplicator = Deduplicator()
        self.geocoder = Geocoder()

        # Collected incidents by tier
        self.incidents: Dict[int, List[Incident]] = {1: [], 2: [], 3: [], 4: []}

        # Available sources
        self._sources = {
            "ice_deaths": ICEGovSource,
            "aila_deaths": AILASource,
            "the_trace": TheTraceSource,
            "nbc_shootings": NBCShootingsSource,
            "news_api": NewsAPISource,
            "gdelt": GDELTSource,
        }

    def fetch_all(self, force_refresh: bool = False) -> int:
        """Fetch from all enabled sources. Returns total incidents fetched."""
        total = 0

        for source_name, source_class in self._sources.items():
            config = SOURCES.get(source_name)
            if not config or not config.enabled:
                continue

            try:
                total += self.fetch_source(source_name, force_refresh)
            except Exception as e:
                logger.error(f"Failed to fetch from {source_name}: {e}")

        return total

    def fetch_source(self, source_name: str, force_refresh: bool = False) -> int:
        """Fetch from a specific source. Returns number of incidents fetched."""
        if source_name not in self._sources:
            raise ValueError(f"Unknown source: {source_name}")

        source_class = self._sources[source_name]

        try:
            source = source_class()
            incidents = source.fetch_with_cache(force_refresh=force_refresh)

            # Add to appropriate tier
            for inc in incidents:
                tier = inc.tier
                if 1 <= tier <= 4:
                    self.incidents[tier].append(inc)

            logger.info(f"Fetched {len(incidents)} incidents from {source_name}")
            return len(incidents)

        except Exception as e:
            logger.error(f"Error fetching from {source_name}: {e}")
            return 0

    def import_csv(self, file_path: str, tier: int = 4) -> int:
        """Import incidents from CSV file."""
        importer = CSVImporter(default_tier=tier)
        incidents = importer.import_file(file_path)

        for inc in incidents:
            if 1 <= tier <= 4:
                self.incidents[tier].append(inc)

        logger.info(f"Imported {len(incidents)} incidents from CSV")
        return len(incidents)

    def import_json(self, file_path: str, tier: int = 4) -> int:
        """Import incidents from JSON file."""
        importer = JSONImporter(default_tier=tier)
        incidents = importer.import_file(file_path)

        for inc in incidents:
            actual_tier = inc.tier or tier
            if 1 <= actual_tier <= 4:
                self.incidents[actual_tier].append(inc)

        logger.info(f"Imported {len(incidents)} incidents from JSON")
        return len(incidents)

    def add_incident(self, incident: Incident):
        """Add a single incident."""
        tier = incident.tier
        if 1 <= tier <= 4:
            self.incidents[tier].append(incident)

    def process(self, validate: bool = True, normalize: bool = True,
                deduplicate: bool = True, geocode: bool = True) -> Dict[str, Any]:
        """
        Process all collected incidents.

        Returns statistics about processing.
        """
        stats = {
            "original_counts": {t: len(self.incidents[t]) for t in [1, 2, 3, 4]},
            "validation_errors": 0,
            "duplicates_removed": 0,
            "geocoded": 0,
        }

        for tier in [1, 2, 3, 4]:
            incidents = self.incidents[tier]
            if not incidents:
                continue

            logger.info(f"Processing tier {tier}: {len(incidents)} incidents")

            # Validate
            if validate:
                valid, results = self.validator.validate_batch(incidents)
                stats["validation_errors"] += sum(len(r.errors) for r in results)
                incidents = valid

            # Normalize
            if normalize:
                incidents = self.normalizer.normalize_batch(incidents)

            # Deduplicate
            if deduplicate:
                original_count = len(incidents)
                incidents = self.deduplicator.deduplicate(incidents)
                stats["duplicates_removed"] += original_count - len(incidents)

            # Geocode
            if geocode:
                before_count = sum(1 for i in incidents if i.lat and i.lon)
                incidents = self.geocoder.geocode_batch(incidents)
                after_count = sum(1 for i in incidents if i.lat and i.lon)
                stats["geocoded"] += after_count - before_count

            self.incidents[tier] = incidents

        stats["final_counts"] = {t: len(self.incidents[t]) for t in [1, 2, 3, 4]}
        stats["total"] = sum(stats["final_counts"].values())

        logger.info(f"Processing complete: {stats['total']} total incidents")
        return stats

    def save(self, merge_existing: bool = True) -> List[Path]:
        """
        Save processed incidents to files.

        If merge_existing is True, merge with existing data files.
        Returns list of files written.
        """
        written_files = []

        # Load existing data if merging
        existing_data: Dict[int, Dict[str, List[Dict]]] = {}
        if merge_existing:
            existing_data = self._load_existing_data()

        for tier, incidents in self.incidents.items():
            if not incidents:
                continue

            # Group by output file category
            file_groups = self._group_for_output(incidents, tier)

            for category, incs in file_groups.items():
                filename = OUTPUT_FILES.get(tier, {}).get(category)
                if not filename:
                    filename = f"tier{tier}_{category}.json"

                output_path = self.output_dir / filename

                # Merge with existing if applicable
                if merge_existing and tier in existing_data and category in existing_data[tier]:
                    incs = self._merge_incidents(existing_data[tier][category], incs)

                # Convert to dict and save
                data = [inc.to_dict() for inc in incs]
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                written_files.append(output_path)
                logger.info(f"Wrote {len(data)} incidents to {output_path.name}")

        return written_files

    def _load_existing_data(self) -> Dict[int, Dict[str, List[Dict]]]:
        """Load existing data files."""
        existing = {}

        for tier, categories in OUTPUT_FILES.items():
            existing[tier] = {}
            for category, filename in categories.items():
                filepath = self.output_dir / filename
                if filepath.exists():
                    try:
                        with open(filepath, 'r') as f:
                            existing[tier][category] = json.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to load {filepath}: {e}")

        return existing

    def _group_for_output(self, incidents: List[Incident], tier: int) -> Dict[str, List[Incident]]:
        """Group incidents by output category."""
        groups: Dict[str, List[Incident]] = {}

        for inc in incidents:
            if tier == 1:
                category = "deaths"
            elif tier == 2:
                if "shooting" in (inc.incident_type or ""):
                    category = "shootings"
                else:
                    category = "less_lethal"
            else:
                category = "incidents"

            if category not in groups:
                groups[category] = []
            groups[category].append(inc)

        return groups

    def _merge_incidents(self, existing: List[Dict], new: List[Incident]) -> List[Incident]:
        """Merge new incidents with existing data."""
        # Convert existing to Incident objects
        existing_incidents = [Incident.from_dict(d) for d in existing]

        # Combine and deduplicate
        combined = existing_incidents + new
        return self.deduplicator.deduplicate(combined)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of current data."""
        summary = {
            "total_incidents": sum(len(self.incidents[t]) for t in [1, 2, 3, 4]),
            "by_tier": {t: len(self.incidents[t]) for t in [1, 2, 3, 4]},
            "by_state": {},
            "by_type": {},
            "deaths": 0,
            "with_coordinates": 0,
        }

        for tier_incidents in self.incidents.values():
            for inc in tier_incidents:
                # By state
                state = inc.state or "Unknown"
                summary["by_state"][state] = summary["by_state"].get(state, 0) + 1

                # By type
                inc_type = inc.incident_type or "other"
                summary["by_type"][inc_type] = summary["by_type"].get(inc_type, 0) + 1

                # Deaths
                if inc.outcome_category == "death":
                    summary["deaths"] += 1

                # Coordinates
                if inc.lat and inc.lon:
                    summary["with_coordinates"] += 1

        return summary


def run_pipeline(
    sources: Optional[List[str]] = None,
    import_files: Optional[List[str]] = None,
    force_refresh: bool = False,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the complete data pipeline.

    Args:
        sources: List of source names to fetch, or None for all
        import_files: List of CSV/JSON files to import
        force_refresh: Force refresh of cached data
        output_dir: Override output directory

    Returns:
        Summary statistics
    """
    pipeline = DataPipeline(
        output_dir=Path(output_dir) if output_dir else None
    )

    # Fetch from sources
    if sources is None:
        pipeline.fetch_all(force_refresh=force_refresh)
    else:
        for source in sources:
            pipeline.fetch_source(source, force_refresh=force_refresh)

    # Import files
    if import_files:
        for filepath in import_files:
            if filepath.endswith('.csv'):
                pipeline.import_csv(filepath)
            elif filepath.endswith('.json'):
                pipeline.import_json(filepath)

    # Process
    stats = pipeline.process()

    # Save
    pipeline.save()

    # Return summary
    return {
        "processing_stats": stats,
        "summary": pipeline.get_summary(),
    }
