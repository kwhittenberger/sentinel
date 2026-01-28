"""
Event clustering service for intelligent incident grouping.

Uses configurable thresholds for:
- Geographic proximity (haversine distance)
- Temporal proximity (days apart)
- Incident type matching
- Category matching
- Actor overlap (optional)
- AI similarity analysis (optional, for future)
"""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Set
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class IncidentForClustering:
    """Minimal incident data needed for clustering."""
    id: UUID
    date: date
    latitude: Optional[float]
    longitude: Optional[float]
    city: Optional[str]
    state: str
    category: str
    incident_type: str
    incident_type_id: Optional[UUID]
    description: Optional[str]
    victim_name: Optional[str]


@dataclass
class ClusterSuggestion:
    """A suggested event cluster."""
    incident_ids: List[UUID]
    suggested_name: str
    event_type: str
    start_date: date
    end_date: date
    primary_state: str
    primary_city: Optional[str]
    incident_type: str
    category: str
    confidence: float
    reasoning: List[str]
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None


class EventClusteringService:
    """Service for clustering incidents into event suggestions."""

    def __init__(self):
        self._settings = None

    @property
    def settings(self) -> dict:
        """Get current settings (lazy load)."""
        if self._settings is None:
            from .settings import get_settings_service
            self._settings = get_settings_service().get_event_clustering()
        return self._settings

    def refresh_settings(self):
        """Force refresh settings from service."""
        from .settings import get_settings_service
        self._settings = get_settings_service().get_event_clustering()

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate the great circle distance in kilometers between two points
        on the earth (specified in decimal degrees).
        """
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))

        # Earth's radius in kilometers
        r = 6371
        return c * r

    def calculate_proximity_score(
        self,
        inc1: IncidentForClustering,
        inc2: IncidentForClustering
    ) -> Tuple[float, List[str]]:
        """
        Calculate how related two incidents are.
        Returns (score 0-1, list of reasons).
        """
        score = 0.0
        reasons = []
        max_score = 0.0

        settings = self.settings

        # Geographic proximity
        if inc1.latitude and inc1.longitude and inc2.latitude and inc2.longitude:
            distance = self.haversine_distance(
                inc1.latitude, inc1.longitude,
                inc2.latitude, inc2.longitude
            )
            max_distance = settings['max_distance_km']

            if distance <= max_distance:
                geo_score = 1.0 - (distance / max_distance)
                score += geo_score * 0.3  # 30% weight for geography
                reasons.append(f"Within {distance:.1f}km of each other")
            elif settings['require_coordinates']:
                return 0.0, ["Too far apart geographically"]
            max_score += 0.3
        elif not settings['require_coordinates']:
            # Fall back to city/state matching
            if inc1.city and inc2.city and inc1.city.lower() == inc2.city.lower():
                score += 0.25
                reasons.append(f"Same city: {inc1.city}")
                max_score += 0.3
            elif inc1.state == inc2.state:
                score += 0.1
                reasons.append(f"Same state: {inc1.state}")
                max_score += 0.3
            else:
                return 0.0, ["Different locations"]

        # Temporal proximity
        days_apart = abs((inc1.date - inc2.date).days)
        max_days = settings['max_time_window_days']

        if days_apart <= max_days:
            time_score = 1.0 - (days_apart / max_days)
            score += time_score * 0.3  # 30% weight for time
            if days_apart == 0:
                reasons.append("Same day")
            else:
                reasons.append(f"{days_apart} days apart")
        else:
            return 0.0, [f"Too far apart in time ({days_apart} days)"]
        max_score += 0.3

        # Incident type matching
        if settings['require_same_incident_type']:
            if inc1.incident_type_id == inc2.incident_type_id:
                score += 0.25
                reasons.append(f"Same incident type: {inc1.incident_type}")
            else:
                return 0.0, ["Different incident types"]
        else:
            if inc1.incident_type_id == inc2.incident_type_id:
                score += 0.2
                reasons.append(f"Same incident type: {inc1.incident_type}")
        max_score += 0.25

        # Category matching
        if settings['require_same_category']:
            if inc1.category == inc2.category:
                score += 0.15
                reasons.append(f"Same category: {inc1.category}")
            else:
                return 0.0, ["Different categories"]
        else:
            if inc1.category == inc2.category:
                score += 0.1
                reasons.append(f"Same category: {inc1.category}")
        max_score += 0.15

        # Normalize score
        if max_score > 0:
            normalized_score = min(1.0, score / max_score)
        else:
            normalized_score = 0.0

        return normalized_score, reasons

    async def get_incidents_for_clustering(
        self,
        category: Optional[str] = None,
        state: Optional[str] = None,
        date_start: Optional[date] = None,
        date_end: Optional[date] = None,
        exclude_linked: bool = True
    ) -> List[IncidentForClustering]:
        """Load incidents from database for clustering analysis."""
        from backend.database import fetch

        conditions = ["i.curation_status = 'approved'"]
        params = []
        param_num = 1

        if exclude_linked:
            conditions.append("i.id NOT IN (SELECT incident_id FROM incident_events)")

        if category:
            conditions.append(f"i.category = ${param_num}")
            params.append(category)
            param_num += 1

        if state:
            conditions.append(f"i.state = ${param_num}")
            params.append(state)
            param_num += 1

        if date_start:
            conditions.append(f"i.date >= ${param_num}")
            params.append(date_start)
            param_num += 1

        if date_end:
            conditions.append(f"i.date <= ${param_num}")
            params.append(date_end)
            param_num += 1

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT i.id, i.date, i.latitude, i.longitude, i.city, i.state,
                   i.category, it.name as incident_type, i.incident_type_id,
                   i.description, i.victim_name
            FROM incidents i
            LEFT JOIN incident_types it ON i.incident_type_id = it.id
            WHERE {where_clause}
            ORDER BY i.date, i.state, i.city
        """

        rows = await fetch(query, *params)

        return [
            IncidentForClustering(
                id=row['id'],
                date=row['date'],
                latitude=float(row['latitude']) if row['latitude'] else None,
                longitude=float(row['longitude']) if row['longitude'] else None,
                city=row['city'],
                state=row['state'],
                category=row['category'],
                incident_type=row['incident_type'] or 'unknown',
                incident_type_id=row['incident_type_id'],
                description=row['description'],
                victim_name=row['victim_name'],
            )
            for row in rows
        ]

    def cluster_incidents(
        self,
        incidents: List[IncidentForClustering]
    ) -> List[ClusterSuggestion]:
        """
        Cluster incidents into event suggestions using union-find algorithm.
        """
        if len(incidents) < 2:
            return []

        settings = self.settings
        min_confidence = settings['min_confidence_threshold']
        min_size = settings['min_cluster_size']

        # Build adjacency based on proximity scores
        n = len(incidents)
        parent = list(range(n))
        rank = [0] * n
        cluster_reasons: Dict[Tuple[int, int], List[str]] = {}

        def find(x: int) -> int:
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: int, y: int):
            px, py = find(x), find(y)
            if px == py:
                return
            if rank[px] < rank[py]:
                px, py = py, px
            parent[py] = px
            if rank[px] == rank[py]:
                rank[px] += 1

        # Calculate pairwise proximities and union related incidents
        for i in range(n):
            for j in range(i + 1, n):
                score, reasons = self.calculate_proximity_score(
                    incidents[i], incidents[j]
                )
                if score >= min_confidence:
                    union(i, j)
                    cluster_reasons[(min(i, j), max(i, j))] = reasons

        # Group by cluster
        clusters: Dict[int, List[int]] = {}
        for i in range(n):
            root = find(i)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(i)

        # Generate suggestions for clusters meeting minimum size
        suggestions = []
        for root, member_indices in clusters.items():
            if len(member_indices) < min_size:
                continue

            members = [incidents[i] for i in member_indices]

            # Gather all reasons from cluster edges
            all_reasons: Set[str] = set()
            for i in member_indices:
                for j in member_indices:
                    if i < j:
                        key = (i, j)
                        if key in cluster_reasons:
                            all_reasons.update(cluster_reasons[key])

            # Calculate cluster properties
            dates = [m.date for m in members]
            start_date = min(dates)
            end_date = max(dates)

            # Most common state/city
            states = [m.state for m in members]
            primary_state = max(set(states), key=states.count)

            cities = [m.city for m in members if m.city]
            primary_city = max(set(cities), key=cities.count) if cities else None

            # Get incident type (should be same if required)
            incident_type = members[0].incident_type
            category = members[0].category

            # Calculate center coordinates
            coords = [(m.latitude, m.longitude) for m in members if m.latitude and m.longitude]
            if coords:
                center_lat = sum(c[0] for c in coords) / len(coords)
                center_lon = sum(c[1] for c in coords) / len(coords)
            else:
                center_lat = center_lon = None

            # Generate name
            location_str = f"{primary_city}, {primary_state}" if primary_city else primary_state
            date_str = start_date.strftime("%b %Y")
            type_str = incident_type.replace('_', ' ').title()
            suggested_name = f"{type_str} - {location_str} ({date_str})"

            # Determine event type
            if category == 'enforcement':
                event_type = 'enforcement_operation'
            else:
                event_type = 'crime_cluster'

            # Calculate overall confidence
            # Higher confidence for: more incidents, closer together, same day
            size_factor = min(1.0, len(members) / 5)  # Max out at 5 incidents
            time_span = (end_date - start_date).days
            time_factor = 1.0 - min(0.5, time_span / 14)  # Penalize long spans
            confidence = 0.5 + (size_factor * 0.25) + (time_factor * 0.25)

            suggestions.append(ClusterSuggestion(
                incident_ids=[m.id for m in members],
                suggested_name=suggested_name,
                event_type=event_type,
                start_date=start_date,
                end_date=end_date,
                primary_state=primary_state,
                primary_city=primary_city,
                incident_type=incident_type,
                category=category,
                confidence=min(1.0, confidence),
                reasoning=list(all_reasons),
                center_lat=center_lat,
                center_lon=center_lon,
            ))

        # Sort by confidence descending
        suggestions.sort(key=lambda x: (-x.confidence, -len(x.incident_ids)))

        return suggestions

    async def generate_suggestions(
        self,
        category: Optional[str] = None,
        state: Optional[str] = None,
        date_start: Optional[date] = None,
        date_end: Optional[date] = None,
        exclude_linked: bool = True,
        limit: int = 20
    ) -> List[Dict]:
        """Generate event suggestions from incidents."""
        self.refresh_settings()

        incidents = await self.get_incidents_for_clustering(
            category=category,
            state=state,
            date_start=date_start,
            date_end=date_end,
            exclude_linked=exclude_linked
        )

        logger.info(f"Clustering {len(incidents)} incidents")

        suggestions = self.cluster_incidents(incidents)

        logger.info(f"Generated {len(suggestions)} cluster suggestions")

        return [
            {
                "incident_ids": [str(id) for id in s.incident_ids],
                "suggested_name": s.suggested_name,
                "event_type": s.event_type,
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat(),
                "primary_state": s.primary_state,
                "primary_city": s.primary_city,
                "incident_type": s.incident_type,
                "category": s.category,
                "incident_count": len(s.incident_ids),
                "confidence": s.confidence,
                "reasoning": s.reasoning,
                "center_lat": s.center_lat,
                "center_lon": s.center_lon,
            }
            for s in suggestions[:limit]
        ]


# Singleton instance
_clustering_service: Optional[EventClusteringService] = None


def get_clustering_service() -> EventClusteringService:
    """Get the singleton EventClusteringService instance."""
    global _clustering_service
    if _clustering_service is None:
        _clustering_service = EventClusteringService()
    return _clustering_service
