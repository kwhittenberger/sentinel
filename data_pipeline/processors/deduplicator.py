"""
Deduplication logic for incident records.
"""

from typing import List, Dict, Set, Tuple
from collections import defaultdict
import logging

from ..sources.base import Incident

logger = logging.getLogger(__name__)


class Deduplicator:
    """Deduplicate incident records, keeping best source."""

    def __init__(self, match_threshold: float = 0.8):
        self.match_threshold = match_threshold

    def deduplicate(self, incidents: List[Incident]) -> List[Incident]:
        """
        Deduplicate incidents, keeping the highest-tier source.

        Returns list of unique incidents with linked_ids populated for duplicates.
        """
        if not incidents:
            return []

        # Group by date and state for efficient matching
        groups = self._group_by_date_state(incidents)

        result = []
        processed_ids: Set[str] = set()

        for key, group in groups.items():
            if len(group) == 1:
                result.append(group[0])
                continue

            # Find duplicate clusters within the group
            clusters = self._find_clusters(group)

            for cluster in clusters:
                if len(cluster) == 1:
                    result.append(cluster[0])
                else:
                    # Keep best record, link others
                    primary, linked = self._select_primary(cluster)
                    primary.linked_ids = [inc.id for inc in linked]
                    primary.is_primary_record = True
                    for inc in linked:
                        inc.is_primary_record = False
                    result.append(primary)

        original_count = len(incidents)
        final_count = len(result)
        duplicate_count = original_count - final_count

        logger.info(f"Deduplication: {original_count} -> {final_count} ({duplicate_count} duplicates merged)")

        return result

    def _group_by_date_state(self, incidents: List[Incident]) -> Dict[str, List[Incident]]:
        """Group incidents by date and state."""
        groups = defaultdict(list)

        for inc in incidents:
            # Use date prefix (year-month) for broader matching
            date_prefix = inc.date[:7] if inc.date else "unknown"
            key = f"{date_prefix}|{inc.state or 'unknown'}"
            groups[key].append(inc)

        return groups

    def _find_clusters(self, incidents: List[Incident]) -> List[List[Incident]]:
        """Find clusters of matching incidents within a group."""
        n = len(incidents)
        if n == 0:
            return []

        # Union-find structure
        parent = list(range(n))

        def find(x: int) -> int:
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: int, y: int):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Compare all pairs
        for i in range(n):
            for j in range(i + 1, n):
                if self._is_match(incidents[i], incidents[j]):
                    union(i, j)

        # Group by root
        clusters_dict = defaultdict(list)
        for i in range(n):
            clusters_dict[find(i)].append(incidents[i])

        return list(clusters_dict.values())

    def _is_match(self, inc1: Incident, inc2: Incident) -> bool:
        """Check if two incidents likely refer to the same event."""
        return inc1.matches(inc2, self.match_threshold)

    def _select_primary(self, cluster: List[Incident]) -> Tuple[Incident, List[Incident]]:
        """
        Select the primary record from a cluster.

        Priority:
        1. Lower tier (more reliable source)
        2. More complete data
        3. Earlier date_retrieved (first found)
        """
        # Sort by tier first, then by completeness
        sorted_cluster = sorted(cluster, key=lambda x: (
            x.tier,
            -self._completeness_score(x),
            x.date_retrieved or "9999"
        ))

        primary = sorted_cluster[0]
        linked = sorted_cluster[1:]

        # Merge data from linked records into primary
        primary = self._merge_records(primary, linked)

        return primary, linked

    def _completeness_score(self, incident: Incident) -> int:
        """Score an incident by data completeness."""
        score = 0
        fields = [
            'victim_name', 'victim_age', 'victim_nationality',
            'city', 'agency', 'circumstances', 'notes',
            'source_url', 'source_name', 'outcome_category',
        ]

        for field in fields:
            if getattr(incident, field, None):
                score += 1

        return score

    def _merge_records(self, primary: Incident, linked: List[Incident]) -> Incident:
        """Merge data from linked records into primary, filling gaps."""
        fillable_fields = [
            'victim_name', 'victim_age', 'victim_nationality', 'victim_category',
            'city', 'county', 'lat', 'lon',
            'agency', 'agent_name', 'circumstances',
            'outcome', 'outcome_category',
            'affected_count', 'affected_breakdown',
        ]

        for field in fillable_fields:
            if not getattr(primary, field, None):
                for inc in linked:
                    value = getattr(inc, field, None)
                    if value:
                        setattr(primary, field, value)
                        break

        # Merge notes
        all_notes = [primary.notes] if primary.notes else []
        for inc in linked:
            if inc.notes and inc.notes not in all_notes:
                all_notes.append(inc.notes)

        if len(all_notes) > 1:
            primary.notes = " | ".join(all_notes)

        # Track all sources
        all_sources = []
        if primary.source_url:
            all_sources.append(primary.source_url)
        for inc in linked:
            if inc.source_url and inc.source_url not in all_sources:
                all_sources.append(inc.source_url)

        if len(all_sources) > 1:
            # Store additional sources in related_incidents or notes
            if not primary.related_incidents:
                primary.related_incidents = []
            for inc in linked:
                if inc.id and inc.id not in primary.related_incidents:
                    primary.related_incidents.append(inc.id)

        return primary


def deduplicate_incidents(incidents: List[Incident]) -> List[Incident]:
    """Convenience function to deduplicate incidents."""
    dedup = Deduplicator()
    return dedup.deduplicate(incidents)
