"""
Event service for managing events and their relationships to incidents.
Events are parent groupings of related incidents (e.g., protest series, operations, crime sprees).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents an event that groups related incidents."""
    id: UUID
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None  # protest_series, enforcement_operation, crime_spree

    # Temporal
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    ongoing: bool = False

    # Geographic
    primary_state: Optional[str] = None
    primary_city: Optional[str] = None
    geographic_scope: Optional[str] = None  # local, regional, statewide, national
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # AI analysis
    ai_analysis: Optional[Dict] = None
    ai_summary: Optional[str] = None

    # Metadata
    tags: List[str] = field(default_factory=list)
    external_ids: Optional[Dict] = None

    # Computed
    incident_count: int = 0

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class IncidentEventLink:
    """Link between an incident and an event."""
    id: UUID
    incident_id: UUID
    event_id: UUID
    is_primary_event: bool = False
    sequence_number: Optional[int] = None
    assigned_by: str = "manual"  # 'manual' or 'ai'
    assignment_confidence: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class EventService:
    """
    Service for managing events and their relationships.

    Features:
    - CRUD for events
    - Link/unlink incidents to events
    - AI-suggested event groupings
    - Event timeline and geographic analysis
    """

    async def get_event(self, event_id: UUID) -> Optional[Event]:
        """Get an event by ID."""
        from backend.database import fetch

        query = """
            SELECT e.*, COUNT(ie.incident_id) as incident_count
            FROM events e
            LEFT JOIN incident_events ie ON e.id = ie.event_id
            WHERE e.id = $1
            GROUP BY e.id
        """
        rows = await fetch(query, event_id)

        if not rows:
            return None

        return self._row_to_event(rows[0])

    async def get_event_by_slug(self, slug: str) -> Optional[Event]:
        """Get an event by slug."""
        from backend.database import fetch

        query = """
            SELECT e.*, COUNT(ie.incident_id) as incident_count
            FROM events e
            LEFT JOIN incident_events ie ON e.id = ie.event_id
            WHERE e.slug = $1
            GROUP BY e.id
        """
        rows = await fetch(query, slug)

        if not rows:
            return None

        return self._row_to_event(rows[0])

    async def list_events(
        self,
        event_type: Optional[str] = None,
        state: Optional[str] = None,
        start_after: Optional[date] = None,
        end_before: Optional[date] = None,
        ongoing_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Event]:
        """List events with optional filters."""
        from backend.database import fetch

        conditions = []
        params = []
        param_num = 1

        if event_type:
            conditions.append(f"e.event_type = ${param_num}")
            params.append(event_type)
            param_num += 1

        if state:
            conditions.append(f"e.primary_state = ${param_num}")
            params.append(state)
            param_num += 1

        if start_after:
            conditions.append(f"e.start_date >= ${param_num}")
            params.append(start_after)
            param_num += 1

        if end_before:
            conditions.append(f"(e.end_date IS NULL OR e.end_date <= ${param_num})")
            params.append(end_before)
            param_num += 1

        if ongoing_only:
            conditions.append("e.ongoing = TRUE")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        query = f"""
            SELECT e.*, COUNT(ie.incident_id) as incident_count
            FROM events e
            LEFT JOIN incident_events ie ON e.id = ie.event_id
            WHERE {where_clause}
            GROUP BY e.id
            ORDER BY e.start_date DESC
            LIMIT ${param_num} OFFSET ${param_num + 1}
        """

        rows = await fetch(query, *params)
        return [self._row_to_event(row) for row in rows]

    async def create_event(
        self,
        name: str,
        start_date: date,
        event_type: Optional[str] = None,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        end_date: Optional[date] = None,
        ongoing: bool = False,
        primary_state: Optional[str] = None,
        primary_city: Optional[str] = None,
        geographic_scope: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        tags: Optional[List[str]] = None,
        external_ids: Optional[Dict] = None
    ) -> Event:
        """Create a new event."""
        from backend.database import fetch
        import uuid

        event_id = uuid.uuid4()

        # Generate slug if not provided
        if not slug:
            slug = name.lower().replace(" ", "-")[:100]

        query = """
            INSERT INTO events (
                id, name, slug, description, event_type,
                start_date, end_date, ongoing,
                primary_state, primary_city, geographic_scope,
                latitude, longitude, tags, external_ids
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING *
        """

        rows = await fetch(
            query,
            event_id, name, slug, description, event_type,
            start_date, end_date, ongoing,
            primary_state, primary_city, geographic_scope,
            latitude, longitude, tags or [], external_ids
        )

        event = self._row_to_event(rows[0])
        event.incident_count = 0
        return event

    async def update_event(
        self,
        event_id: UUID,
        updates: Dict[str, Any]
    ) -> Event:
        """Update an event."""
        from backend.database import fetch

        allowed_fields = [
            'name', 'description', 'event_type',
            'start_date', 'end_date', 'ongoing',
            'primary_state', 'primary_city', 'geographic_scope',
            'latitude', 'longitude', 'tags', 'external_ids',
            'ai_analysis', 'ai_summary'
        ]

        set_clauses = []
        params = []
        param_num = 1

        for field_name in allowed_fields:
            if field_name in updates:
                set_clauses.append(f"{field_name} = ${param_num}")
                params.append(updates[field_name])
                param_num += 1

        if not set_clauses:
            raise ValueError("No valid fields to update")

        set_clauses.append("updated_at = NOW()")
        params.append(event_id)

        query = f"""
            UPDATE events
            SET {', '.join(set_clauses)}
            WHERE id = ${param_num}
            RETURNING *
        """

        rows = await fetch(query, *params)
        if not rows:
            raise ValueError(f"Event {event_id} not found")

        return self._row_to_event(rows[0])

    async def delete_event(self, event_id: UUID) -> bool:
        """Delete an event and its incident links."""
        from backend.database import execute

        # Links are deleted via CASCADE
        await execute("DELETE FROM events WHERE id = $1", event_id)
        return True

    # ==================== Incident Linking ====================

    async def get_event_incidents(
        self,
        event_id: UUID,
        include_details: bool = True
    ) -> List[Dict]:
        """Get all incidents linked to an event."""
        from backend.database import fetch

        if include_details:
            query = """
                SELECT ie.*, i.date, i.state, i.city, i.category, i.description,
                       i.victim_name, ot.name as outcome_category, i.notes,
                       it.name as incident_type, it.display_name as incident_type_display
                FROM incident_events ie
                JOIN incidents i ON ie.incident_id = i.id
                LEFT JOIN incident_types it ON i.incident_type_id = it.id
                LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
                WHERE ie.event_id = $1
                ORDER BY ie.sequence_number, i.date
            """
        else:
            query = """
                SELECT ie.*
                FROM incident_events ie
                WHERE ie.event_id = $1
                ORDER BY ie.sequence_number
            """

        rows = await fetch(query, event_id)
        return [dict(row) for row in rows]

    async def get_event_actors(self, event_id: UUID) -> List[Dict]:
        """Get all actors associated with incidents in an event."""
        from backend.database import fetch

        query = """
            SELECT DISTINCT a.id, a.canonical_name, a.actor_type, a.aliases,
                   a.is_law_enforcement, ia.role,
                   COUNT(DISTINCT ia.incident_id) as incident_count
            FROM actors a
            JOIN incident_actors ia ON a.id = ia.actor_id
            JOIN incident_events ie ON ia.incident_id = ie.incident_id
            WHERE ie.event_id = $1
            GROUP BY a.id, a.canonical_name, a.actor_type, a.aliases,
                     a.is_law_enforcement, ia.role
            ORDER BY incident_count DESC, a.canonical_name
        """

        rows = await fetch(query, event_id)
        return [dict(row) for row in rows]

    async def get_incident_events(self, incident_id: UUID) -> List[Event]:
        """Get all events an incident is linked to."""
        from backend.database import fetch

        query = """
            SELECT e.*, ie.is_primary_event, ie.sequence_number
            FROM events e
            JOIN incident_events ie ON e.id = ie.event_id
            WHERE ie.incident_id = $1
            ORDER BY ie.is_primary_event DESC, e.start_date
        """

        rows = await fetch(query, incident_id)
        return [self._row_to_event(row) for row in rows]

    async def link_incident(
        self,
        event_id: UUID,
        incident_id: UUID,
        is_primary: bool = False,
        sequence_number: Optional[int] = None,
        assigned_by: str = "manual",
        confidence: Optional[float] = None,
        notes: Optional[str] = None
    ) -> IncidentEventLink:
        """Link an incident to an event."""
        from backend.database import fetch, execute
        import uuid

        link_id = uuid.uuid4()

        # If this is set as primary, unset other primaries for this incident
        if is_primary:
            await execute(
                "UPDATE incident_events SET is_primary_event = FALSE WHERE incident_id = $1",
                incident_id
            )

        query = """
            INSERT INTO incident_events (
                id, incident_id, event_id, is_primary_event,
                sequence_number, assigned_by, assignment_confidence, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (incident_id, event_id) DO UPDATE SET
                is_primary_event = EXCLUDED.is_primary_event,
                sequence_number = EXCLUDED.sequence_number,
                assigned_by = EXCLUDED.assigned_by,
                assignment_confidence = EXCLUDED.assignment_confidence,
                notes = EXCLUDED.notes
            RETURNING *
        """

        rows = await fetch(
            query,
            link_id, incident_id, event_id, is_primary,
            sequence_number, assigned_by, confidence, notes
        )

        return self._row_to_link(rows[0])

    async def unlink_incident(self, event_id: UUID, incident_id: UUID) -> bool:
        """Remove link between incident and event."""
        from backend.database import execute

        await execute(
            "DELETE FROM incident_events WHERE event_id = $1 AND incident_id = $2",
            event_id, incident_id
        )
        return True

    async def update_incident_link(
        self,
        event_id: UUID,
        incident_id: UUID,
        updates: Dict[str, Any]
    ) -> IncidentEventLink:
        """Update an incident-event link."""
        from backend.database import fetch, execute

        allowed_fields = ['is_primary_event', 'sequence_number', 'notes']

        set_clauses = []
        params = []
        param_num = 1

        for field_name in allowed_fields:
            if field_name in updates:
                set_clauses.append(f"{field_name} = ${param_num}")
                params.append(updates[field_name])
                param_num += 1

        if not set_clauses:
            raise ValueError("No valid fields to update")

        # If setting as primary, unset others first
        if updates.get('is_primary_event'):
            await execute(
                "UPDATE incident_events SET is_primary_event = FALSE WHERE incident_id = $1 AND event_id != $2",
                incident_id, event_id
            )

        params.extend([event_id, incident_id])

        query = f"""
            UPDATE incident_events
            SET {', '.join(set_clauses)}
            WHERE event_id = ${param_num} AND incident_id = ${param_num + 1}
            RETURNING *
        """

        rows = await fetch(query, *params)
        if not rows:
            raise ValueError(f"Link not found for event={event_id}, incident={incident_id}")

        return self._row_to_link(rows[0])

    # ==================== AI Suggestions ====================

    async def get_event_suggestions(
        self,
        incident_ids: Optional[List[UUID]] = None,
        min_incidents: int = 2,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get AI-suggested event groupings based on incident clustering.

        This is a placeholder for actual AI analysis. In production, this would:
        1. Analyze temporal proximity of incidents
        2. Check geographic clustering
        3. Look for common actors
        4. Analyze content similarity
        """
        from backend.database import fetch

        # Simple clustering by date + state
        query = """
            WITH incident_clusters AS (
                SELECT
                    date,
                    state,
                    COUNT(*) as count,
                    array_agg(id) as incident_ids
                FROM incidents
                WHERE curation_status = 'approved'
                  AND id NOT IN (SELECT incident_id FROM incident_events)
                GROUP BY date, state
                HAVING COUNT(*) >= $1
                ORDER BY count DESC, date DESC
                LIMIT $2
            )
            SELECT * FROM incident_clusters
        """

        rows = await fetch(query, min_incidents, limit)

        suggestions = []
        for row in rows:
            suggestions.append({
                "type": "date_state_cluster",
                "date": row["date"].isoformat() if row["date"] else None,
                "state": row["state"],
                "incident_count": row["count"],
                "incident_ids": [str(id) for id in row["incident_ids"]],
                "suggested_name": f"Incidents in {row['state']} on {row['date']}",
                "confidence": 0.6
            })

        return suggestions

    async def apply_suggestion(
        self,
        suggestion: Dict,
        name: Optional[str] = None
    ) -> Event:
        """Create an event from a suggestion."""
        incident_ids = suggestion.get("incident_ids", [])
        if not incident_ids:
            raise ValueError("Suggestion has no incident_ids")

        # Get date range from incidents
        from backend.database import fetch
        import uuid

        placeholders = ", ".join(f"${i+1}" for i in range(len(incident_ids)))
        query = f"""
            SELECT MIN(date) as start_date, MAX(date) as end_date,
                   MODE() WITHIN GROUP (ORDER BY state) as primary_state,
                   MODE() WITHIN GROUP (ORDER BY city) as primary_city
            FROM incidents
            WHERE id IN ({placeholders})
        """

        ids = [uuid.UUID(id) if isinstance(id, str) else id for id in incident_ids]
        rows = await fetch(query, *ids)

        if not rows:
            raise ValueError("Could not find incidents")

        row = rows[0]

        # Create the event
        event = await self.create_event(
            name=name or suggestion.get("suggested_name", "Grouped Incidents"),
            start_date=row["start_date"],
            end_date=row["end_date"] if row["end_date"] != row["start_date"] else None,
            event_type=suggestion.get("type", "cluster"),
            primary_state=row["primary_state"],
            primary_city=row["primary_city"]
        )

        # Link incidents
        for i, incident_id in enumerate(ids):
            await self.link_incident(
                event_id=event.id,
                incident_id=incident_id,
                is_primary=(i == 0),
                sequence_number=i + 1,
                assigned_by="ai",
                confidence=suggestion.get("confidence", 0.5)
            )

        # Update event with incident count
        event.incident_count = len(ids)
        return event

    # ==================== Helper Methods ====================

    def _row_to_event(self, row: Dict) -> Event:
        """Convert database row to Event object."""
        return Event(
            id=row["id"],
            name=row["name"],
            slug=row.get("slug"),
            description=row.get("description"),
            event_type=row.get("event_type"),
            start_date=row.get("start_date"),
            end_date=row.get("end_date"),
            ongoing=row.get("ongoing", False),
            primary_state=row.get("primary_state"),
            primary_city=row.get("primary_city"),
            geographic_scope=row.get("geographic_scope"),
            latitude=float(row["latitude"]) if row.get("latitude") else None,
            longitude=float(row["longitude"]) if row.get("longitude") else None,
            ai_analysis=row.get("ai_analysis"),
            ai_summary=row.get("ai_summary"),
            tags=row.get("tags") or [],
            external_ids=row.get("external_ids"),
            incident_count=row.get("incident_count", 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_link(self, row: Dict) -> IncidentEventLink:
        """Convert database row to IncidentEventLink object."""
        return IncidentEventLink(
            id=row["id"],
            incident_id=row["incident_id"],
            event_id=row["event_id"],
            is_primary_event=row.get("is_primary_event", False),
            sequence_number=row.get("sequence_number"),
            assigned_by=row.get("assigned_by", "manual"),
            assignment_confidence=float(row["assignment_confidence"]) if row.get("assignment_confidence") else None,
            notes=row.get("notes"),
            created_at=row.get("created_at"),
        )


# Singleton instance
_event_service: Optional[EventService] = None


def get_event_service() -> EventService:
    """Get the singleton EventService instance."""
    global _event_service
    if _event_service is None:
        _event_service = EventService()
    return _event_service
