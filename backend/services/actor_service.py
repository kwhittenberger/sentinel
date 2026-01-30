"""
Actor service for managing actors (persons, organizations, agencies) and their relationships.
Actors are first-class entities that can be linked to multiple incidents.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from uuid import UUID
from enum import Enum

logger = logging.getLogger(__name__)


class ActorType(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    AGENCY = "agency"
    GROUP = "group"


class ActorRole(str, Enum):
    VICTIM = "victim"
    OFFENDER = "offender"
    WITNESS = "witness"
    OFFICER = "officer"
    ARRESTING_AGENCY = "arresting_agency"
    REPORTING_AGENCY = "reporting_agency"
    BYSTANDER = "bystander"
    ORGANIZER = "organizer"
    PARTICIPANT = "participant"


class ActorRelationType(str, Enum):
    ALIAS_OF = "alias_of"
    MEMBER_OF = "member_of"
    AFFILIATED_WITH = "affiliated_with"
    EMPLOYED_BY = "employed_by"
    FAMILY_OF = "family_of"
    ASSOCIATED_WITH = "associated_with"


@dataclass
class Actor:
    """Represents an actor (person, org, agency, group)."""
    id: UUID
    canonical_name: str
    actor_type: ActorType
    aliases: List[str] = field(default_factory=list)

    # Person-specific
    date_of_birth: Optional[date] = None
    date_of_death: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    immigration_status: Optional[str] = None
    prior_deportations: int = 0

    # Organization-specific
    organization_type: Optional[str] = None
    parent_org_id: Optional[UUID] = None
    is_government_entity: bool = False
    is_law_enforcement: bool = False
    jurisdiction: Optional[str] = None

    # Profile
    description: Optional[str] = None
    profile_data: Optional[Dict] = None
    external_ids: Optional[Dict] = None

    # Entity resolution
    confidence_score: Optional[float] = None
    merged_from: List[UUID] = field(default_factory=list)
    is_merged: bool = False

    # Computed
    incident_count: int = 0
    roles_played: List[str] = field(default_factory=list)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class IncidentActorLink:
    """Link between an incident and an actor."""
    id: UUID
    incident_id: UUID
    actor_id: UUID
    role: ActorRole
    role_detail: Optional[str] = None
    is_primary: bool = False
    sequence_number: Optional[int] = None
    assigned_by: str = "manual"
    assignment_confidence: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class ActorRelation:
    """Relationship between two actors."""
    id: UUID
    actor_id: UUID
    related_actor_id: UUID
    relation_type: ActorRelationType
    confidence: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ActorService:
    """
    Service for managing actors and their relationships.

    Features:
    - CRUD for actors
    - Link/unlink actors to incidents
    - Actor relationship management
    - Entity resolution and merging
    - Search with fuzzy matching
    """

    async def get_actor(self, actor_id: UUID) -> Optional[Actor]:
        """Get an actor by ID."""
        from backend.database import fetch

        query = """
            SELECT a.*, COUNT(DISTINCT ia.incident_id) as incident_count,
                   array_agg(DISTINCT ia.role) FILTER (WHERE ia.role IS NOT NULL) as roles_played
            FROM actors a
            LEFT JOIN incident_actors ia ON a.id = ia.actor_id
            WHERE a.id = $1 AND NOT a.is_merged
            GROUP BY a.id
        """
        rows = await fetch(query, actor_id)

        if not rows:
            return None

        return self._row_to_actor(rows[0])

    async def list_actors(
        self,
        actor_type: Optional[ActorType] = None,
        search: Optional[str] = None,
        immigration_status: Optional[str] = None,
        is_law_enforcement: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Actor]:
        """List actors with optional filters."""
        from backend.database import fetch

        conditions = ["NOT a.is_merged"]
        params = []
        param_num = 1

        if actor_type:
            conditions.append(f"a.actor_type = ${param_num}")
            params.append(actor_type.value)
            param_num += 1

        if search:
            # Fuzzy search on name and aliases
            conditions.append(f"(a.canonical_name ILIKE ${param_num} OR ${param_num} = ANY(a.aliases))")
            params.append(f"%{search}%")
            param_num += 1

        if immigration_status:
            conditions.append(f"a.immigration_status = ${param_num}")
            params.append(immigration_status)
            param_num += 1

        if is_law_enforcement is not None:
            conditions.append(f"a.is_law_enforcement = ${param_num}")
            params.append(is_law_enforcement)
            param_num += 1

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        query = f"""
            SELECT a.*, COUNT(DISTINCT ia.incident_id) as incident_count,
                   array_agg(DISTINCT ia.role) FILTER (WHERE ia.role IS NOT NULL) as roles_played
            FROM actors a
            LEFT JOIN incident_actors ia ON a.id = ia.actor_id
            WHERE {where_clause}
            GROUP BY a.id
            ORDER BY a.canonical_name
            LIMIT ${param_num} OFFSET ${param_num + 1}
        """

        rows = await fetch(query, *params)
        return [self._row_to_actor(row) for row in rows]

    async def search_actors(
        self,
        query_text: str,
        actor_type: Optional[ActorType] = None,
        limit: int = 20
    ) -> List[Actor]:
        """Search actors with fuzzy matching."""
        from backend.database import fetch

        conditions = ["NOT a.is_merged"]
        params = [f"%{query_text}%"]
        param_num = 2

        if actor_type:
            conditions.append(f"a.actor_type = ${param_num}")
            params.append(actor_type.value)
            param_num += 1

        where_clause = " AND ".join(conditions)
        params.append(limit)

        query = f"""
            SELECT a.*, COUNT(DISTINCT ia.incident_id) as incident_count,
                   similarity(a.canonical_name, $1) as name_similarity
            FROM actors a
            LEFT JOIN incident_actors ia ON a.id = ia.actor_id
            WHERE {where_clause}
              AND (a.canonical_name ILIKE $1 OR a.canonical_name % $1 OR $1 ILIKE ANY(a.aliases))
            GROUP BY a.id
            ORDER BY name_similarity DESC, a.canonical_name
            LIMIT ${param_num}
        """

        rows = await fetch(query, query_text, *params[1:])
        return [self._row_to_actor(row) for row in rows]

    async def create_actor(
        self,
        canonical_name: str,
        actor_type: ActorType,
        aliases: Optional[List[str]] = None,
        date_of_birth: Optional[date] = None,
        gender: Optional[str] = None,
        nationality: Optional[str] = None,
        immigration_status: Optional[str] = None,
        prior_deportations: int = 0,
        organization_type: Optional[str] = None,
        parent_org_id: Optional[UUID] = None,
        is_government_entity: bool = False,
        is_law_enforcement: bool = False,
        jurisdiction: Optional[str] = None,
        description: Optional[str] = None,
        profile_data: Optional[Dict] = None,
        external_ids: Optional[Dict] = None,
        confidence_score: Optional[float] = None
    ) -> Actor:
        """Create a new actor."""
        from backend.database import fetch
        import uuid

        actor_id = uuid.uuid4()

        query = """
            INSERT INTO actors (
                id, canonical_name, actor_type, aliases,
                date_of_birth, gender, nationality, immigration_status, prior_deportations,
                organization_type, parent_org_id, is_government_entity, is_law_enforcement, jurisdiction,
                description, profile_data, external_ids, confidence_score
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
            RETURNING *
        """

        rows = await fetch(
            query,
            actor_id, canonical_name, actor_type.value, aliases or [],
            date_of_birth, gender, nationality, immigration_status, prior_deportations,
            organization_type, parent_org_id, is_government_entity, is_law_enforcement, jurisdiction,
            description, profile_data, external_ids, confidence_score
        )

        actor = self._row_to_actor(rows[0])
        actor.incident_count = 0
        return actor

    async def update_actor(
        self,
        actor_id: UUID,
        updates: Dict[str, Any]
    ) -> Actor:
        """Update an actor."""
        from backend.database import fetch

        allowed_fields = [
            'canonical_name', 'aliases',
            'date_of_birth', 'date_of_death', 'gender', 'nationality',
            'immigration_status', 'prior_deportations',
            'organization_type', 'parent_org_id', 'is_government_entity',
            'is_law_enforcement', 'jurisdiction',
            'description', 'profile_data', 'external_ids', 'confidence_score'
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
        params.append(actor_id)

        query = f"""
            UPDATE actors
            SET {', '.join(set_clauses)}
            WHERE id = ${param_num}
            RETURNING *
        """

        rows = await fetch(query, *params)
        if not rows:
            raise ValueError(f"Actor {actor_id} not found")

        return self._row_to_actor(rows[0])

    async def delete_actor(self, actor_id: UUID) -> bool:
        """Delete an actor and its links."""
        from backend.database import execute

        # Links are deleted via CASCADE
        await execute("DELETE FROM actors WHERE id = $1", actor_id)
        return True

    # ==================== Incident Linking ====================

    async def get_actor_incidents(
        self,
        actor_id: UUID,
        role: Optional[ActorRole] = None
    ) -> List[Dict]:
        """Get all incidents linked to an actor."""
        from backend.database import fetch

        conditions = ["ia.actor_id = $1"]
        params = [actor_id]
        param_num = 2

        if role:
            conditions.append(f"ia.role = ${param_num}")
            params.append(role.value)

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT ia.*, i.date, i.state, i.city, i.category, i.description,
                   it.name as incident_type
            FROM incident_actors ia
            JOIN incidents i ON ia.incident_id = i.id
            LEFT JOIN incident_types it ON i.incident_type_id = it.id
            WHERE {where_clause}
            ORDER BY i.date DESC
        """

        rows = await fetch(query, *params)
        return [dict(row) for row in rows]

    async def get_incident_actors(
        self,
        incident_id: UUID,
        role: Optional[ActorRole] = None
    ) -> List[Actor]:
        """Get all actors linked to an incident."""
        from backend.database import fetch

        conditions = ["ia.incident_id = $1"]
        params = [incident_id]
        param_num = 2

        if role:
            conditions.append(f"ia.role = ${param_num}")
            params.append(role.value)

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT a.*, ia.role, ia.is_primary, ia.role_detail
            FROM actors a
            JOIN incident_actors ia ON a.id = ia.actor_id
            WHERE {where_clause}
            ORDER BY ia.is_primary DESC, ia.sequence_number
        """

        rows = await fetch(query, *params)
        return [self._row_to_actor(row) for row in rows]

    async def link_actor_to_incident(
        self,
        incident_id: UUID,
        actor_id: UUID,
        role: ActorRole,
        role_detail: Optional[str] = None,
        is_primary: bool = False,
        sequence_number: Optional[int] = None,
        assigned_by: str = "manual",
        confidence: Optional[float] = None,
        notes: Optional[str] = None
    ) -> IncidentActorLink:
        """Link an actor to an incident."""
        from backend.database import fetch, execute
        import uuid

        link_id = uuid.uuid4()

        # If this is set as primary for this role, unset others
        if is_primary:
            await execute(
                "UPDATE incident_actors SET is_primary = FALSE WHERE incident_id = $1 AND role = $2",
                incident_id, role.value
            )

        query = """
            INSERT INTO incident_actors (
                id, incident_id, actor_id, role, role_detail,
                is_primary, sequence_number, assigned_by, assignment_confidence, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (incident_id, actor_id, role) DO UPDATE SET
                role_detail = EXCLUDED.role_detail,
                is_primary = EXCLUDED.is_primary,
                sequence_number = EXCLUDED.sequence_number,
                assigned_by = EXCLUDED.assigned_by,
                assignment_confidence = EXCLUDED.assignment_confidence,
                notes = EXCLUDED.notes
            RETURNING *
        """

        rows = await fetch(
            query,
            link_id, incident_id, actor_id, role.value, role_detail,
            is_primary, sequence_number, assigned_by, confidence, notes
        )

        return self._row_to_incident_link(rows[0])

    async def unlink_actor_from_incident(
        self,
        incident_id: UUID,
        actor_id: UUID,
        role: Optional[ActorRole] = None
    ) -> bool:
        """Remove link between actor and incident."""
        from backend.database import execute

        if role:
            await execute(
                "DELETE FROM incident_actors WHERE incident_id = $1 AND actor_id = $2 AND role = $3",
                incident_id, actor_id, role.value
            )
        else:
            await execute(
                "DELETE FROM incident_actors WHERE incident_id = $1 AND actor_id = $2",
                incident_id, actor_id
            )
        return True

    # ==================== Actor Relationships ====================

    async def get_actor_relations(
        self,
        actor_id: UUID,
        relation_type: Optional[ActorRelationType] = None
    ) -> List[ActorRelation]:
        """Get all relations for an actor."""
        from backend.database import fetch

        conditions = ["(ar.actor_id = $1 OR ar.related_actor_id = $1)"]
        params = [actor_id]
        param_num = 2

        if relation_type:
            conditions.append(f"ar.relation_type = ${param_num}")
            params.append(relation_type.value)

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT ar.*
            FROM actor_relations ar
            WHERE {where_clause}
            ORDER BY ar.created_at DESC
        """

        rows = await fetch(query, *params)
        return [self._row_to_relation(row) for row in rows]

    async def add_relation(
        self,
        actor_id: UUID,
        related_actor_id: UUID,
        relation_type: ActorRelationType,
        confidence: Optional[float] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        notes: Optional[str] = None
    ) -> ActorRelation:
        """Add a relationship between two actors."""
        from backend.database import fetch
        import uuid

        relation_id = uuid.uuid4()

        query = """
            INSERT INTO actor_relations (
                id, actor_id, related_actor_id, relation_type,
                confidence, start_date, end_date, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (actor_id, related_actor_id, relation_type) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                notes = EXCLUDED.notes
            RETURNING *
        """

        rows = await fetch(
            query,
            relation_id, actor_id, related_actor_id, relation_type.value,
            confidence, start_date, end_date, notes
        )

        return self._row_to_relation(rows[0])

    async def remove_relation(
        self,
        actor_id: UUID,
        related_actor_id: UUID,
        relation_type: ActorRelationType
    ) -> bool:
        """Remove a relationship between two actors."""
        from backend.database import execute

        await execute(
            "DELETE FROM actor_relations WHERE actor_id = $1 AND related_actor_id = $2 AND relation_type = $3",
            actor_id, related_actor_id, relation_type.value
        )
        return True

    # ==================== Entity Resolution ====================

    async def get_merge_suggestions(
        self,
        similarity_threshold: float = 0.5,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get suggestions for actors that might be the same entity.

        Uses multiple matching strategies:
        1. Trigram similarity (pg_trgm)
        2. Name containment (one name contains the other)
        3. First/last name matching
        """
        from backend.database import fetch

        # Strategy 1: Trigram similarity
        query_similarity = """
            SELECT a1.id as actor1_id, a1.canonical_name as actor1_name,
                   a2.id as actor2_id, a2.canonical_name as actor2_name,
                   similarity(a1.canonical_name, a2.canonical_name) as similarity,
                   'trigram' as match_type
            FROM actors a1
            JOIN actors a2 ON a1.id < a2.id
            WHERE NOT a1.is_merged AND NOT a2.is_merged
              AND a1.actor_type = a2.actor_type
              AND similarity(a1.canonical_name, a2.canonical_name) > $1
        """

        # Strategy 2: Name containment (short name contained in long name)
        query_containment = """
            SELECT a1.id as actor1_id, a1.canonical_name as actor1_name,
                   a2.id as actor2_id, a2.canonical_name as actor2_name,
                   CASE
                       WHEN length(a1.canonical_name) <= length(a2.canonical_name)
                       THEN length(a1.canonical_name)::float / length(a2.canonical_name)
                       ELSE length(a2.canonical_name)::float / length(a1.canonical_name)
                   END as similarity,
                   'containment' as match_type
            FROM actors a1
            JOIN actors a2 ON a1.id < a2.id
            WHERE NOT a1.is_merged AND NOT a2.is_merged
              AND a1.actor_type = a2.actor_type
              AND a1.actor_type = 'person'
              AND (
                  lower(a2.canonical_name) LIKE '%' || lower(a1.canonical_name) || '%'
                  OR lower(a1.canonical_name) LIKE '%' || lower(a2.canonical_name) || '%'
              )
              AND length(a1.canonical_name) >= 5  -- Avoid very short matches
              AND length(a2.canonical_name) >= 5
        """

        # Strategy 3: First and last name match (handles middle name differences)
        query_first_last = """
            WITH name_parts AS (
                SELECT
                    id,
                    canonical_name,
                    actor_type,
                    split_part(lower(canonical_name), ' ', 1) as first_name,
                    split_part(lower(canonical_name), ' ', -1) as last_name,
                    array_length(string_to_array(canonical_name, ' '), 1) as name_parts
                FROM actors
                WHERE NOT is_merged AND actor_type = 'person'
            )
            SELECT
                n1.id as actor1_id, n1.canonical_name as actor1_name,
                n2.id as actor2_id, n2.canonical_name as actor2_name,
                0.85 as similarity,
                'first_last' as match_type
            FROM name_parts n1
            JOIN name_parts n2 ON n1.id < n2.id
            WHERE n1.first_name = n2.first_name
              AND n1.last_name = n2.last_name
              AND n1.first_name != ''
              AND n1.last_name != ''
              AND n1.name_parts != n2.name_parts  -- Different number of parts
              AND length(n1.first_name) > 2
              AND length(n1.last_name) > 2
        """

        # Execute all queries
        rows_similarity = await fetch(query_similarity, similarity_threshold)
        rows_containment = await fetch(query_containment)
        rows_first_last = await fetch(query_first_last)

        # Combine and deduplicate
        seen_pairs = set()
        suggestions = []

        def add_suggestion(row, reason_prefix):
            pair_key = tuple(sorted([str(row["actor1_id"]), str(row["actor2_id"])]))
            if pair_key in seen_pairs:
                return
            seen_pairs.add(pair_key)

            match_type = row.get("match_type", "trigram")
            if match_type == "containment":
                reason = f"Name containment match"
            elif match_type == "first_last":
                reason = f"First/last name match (possible middle name difference)"
            else:
                reason = f"Name similarity: {row['similarity']:.0%}"

            suggestions.append({
                "actor1_id": str(row["actor1_id"]),
                "actor1_name": row["actor1_name"],
                "actor2_id": str(row["actor2_id"]),
                "actor2_name": row["actor2_name"],
                "similarity": float(row["similarity"]),
                "reason": reason,
                "match_type": match_type
            })

        # First/last name matches are highest confidence for this use case
        for row in rows_first_last:
            add_suggestion(row, "first_last")

        # Then containment matches
        for row in rows_containment:
            add_suggestion(row, "containment")

        # Then trigram similarity
        for row in rows_similarity:
            add_suggestion(row, "trigram")

        # Sort by similarity descending and limit
        suggestions.sort(key=lambda x: (-x["similarity"], x["actor1_name"]))
        return suggestions[:limit]

    async def merge_actors(
        self,
        primary_actor_id: UUID,
        secondary_actor_ids: List[UUID],
        merge_aliases: bool = True
    ) -> Actor:
        """
        Merge multiple actors into one.

        The primary actor is kept, secondary actors are marked as merged.
        All incident links are transferred to the primary actor.
        """
        from backend.database import fetch, execute

        primary = await self.get_actor(primary_actor_id)
        if not primary:
            raise ValueError(f"Primary actor {primary_actor_id} not found")

        # Collect all aliases from secondary actors
        all_aliases = list(primary.aliases)
        merged_ids = list(primary.merged_from)

        for secondary_id in secondary_actor_ids:
            secondary = await self.get_actor(secondary_id)
            if not secondary:
                continue

            if merge_aliases:
                # Add secondary name and aliases to primary
                if secondary.canonical_name not in all_aliases:
                    all_aliases.append(secondary.canonical_name)
                for alias in secondary.aliases:
                    if alias not in all_aliases:
                        all_aliases.append(alias)

            # Transfer incident links:
            # First remove secondary links that would duplicate existing primary links
            await execute("""
                DELETE FROM incident_actors
                WHERE actor_id = $2
                  AND (incident_id, role) IN (
                      SELECT incident_id, role FROM incident_actors WHERE actor_id = $1
                  )
            """, primary_actor_id, secondary_id)
            # Then transfer remaining secondary links to primary
            await execute("""
                UPDATE incident_actors SET actor_id = $1 WHERE actor_id = $2
            """, primary_actor_id, secondary_id)

            # Transfer actor relations:
            # First remove relations between primary and secondary (would become self-relations)
            await execute("""
                DELETE FROM actor_relations
                WHERE (actor_id = $1 AND related_actor_id = $2)
                   OR (actor_id = $2 AND related_actor_id = $1)
            """, primary_actor_id, secondary_id)
            # Remove secondary's outgoing relations that duplicate primary's
            await execute("""
                DELETE FROM actor_relations
                WHERE actor_id = $2
                  AND (related_actor_id, relation_type) IN (
                      SELECT related_actor_id, relation_type
                      FROM actor_relations WHERE actor_id = $1
                  )
            """, primary_actor_id, secondary_id)
            # Remove secondary's incoming relations that duplicate primary's
            await execute("""
                DELETE FROM actor_relations
                WHERE related_actor_id = $2
                  AND (actor_id, relation_type) IN (
                      SELECT actor_id, relation_type
                      FROM actor_relations WHERE related_actor_id = $1
                  )
            """, primary_actor_id, secondary_id)
            # Now safely transfer remaining relations
            await execute("""
                UPDATE actor_relations SET actor_id = $1 WHERE actor_id = $2
            """, primary_actor_id, secondary_id)
            await execute("""
                UPDATE actor_relations SET related_actor_id = $1 WHERE related_actor_id = $2
            """, primary_actor_id, secondary_id)

            # Mark secondary as merged
            await execute("""
                UPDATE actors SET is_merged = TRUE, updated_at = NOW() WHERE id = $1
            """, secondary_id)

            merged_ids.append(secondary_id)

        # Update primary with merged info
        await execute("""
            UPDATE actors
            SET aliases = $1, merged_from = $2, updated_at = NOW()
            WHERE id = $3
        """, all_aliases, merged_ids, primary_actor_id)

        return await self.get_actor(primary_actor_id)

    # ==================== Migration ====================

    async def migrate_from_persons(self, batch_size: int = 100) -> Dict:
        """
        Migrate data from legacy persons table to actors table.
        Returns migration statistics.
        """
        from backend.database import fetch, execute
        import uuid

        stats = {"migrated": 0, "skipped": 0, "errors": 0}

        # Get persons not yet migrated
        query = """
            SELECT p.*
            FROM persons p
            WHERE NOT EXISTS (
                SELECT 1 FROM actors a
                WHERE a.external_ids->>'migrated_from_person' = p.id::text
            )
            LIMIT $1
        """

        rows = await fetch(query, batch_size)

        for row in rows:
            try:
                actor_id = uuid.uuid4()

                await execute("""
                    INSERT INTO actors (
                        id, canonical_name, actor_type, aliases,
                        date_of_birth, gender, nationality,
                        immigration_status, prior_deportations,
                        external_ids, profile_data
                    ) VALUES ($1, $2, 'person', $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                    actor_id,
                    row["name"] or f"Unknown Person {row['id']}",
                    row.get("aliases") or [],
                    row.get("date_of_birth"),
                    row.get("gender"),
                    row.get("nationality"),
                    row.get("immigration_status"),
                    row.get("prior_deportations", 0),
                    {"migrated_from_person": str(row["id"]), **(row.get("external_ids") or {})},
                    {
                        "us_citizen": row.get("us_citizen"),
                        "occupation": row.get("occupation"),
                        "gang_affiliated": row.get("gang_affiliated"),
                        "gang_name": row.get("gang_name"),
                        "prior_convictions": row.get("prior_convictions"),
                        "prior_violent_convictions": row.get("prior_violent_convictions"),
                        "reentry_after_deportation": row.get("reentry_after_deportation"),
                        "visa_type": row.get("visa_type"),
                        "visa_overstay": row.get("visa_overstay"),
                    }
                )

                # Migrate incident_persons links
                await execute("""
                    INSERT INTO incident_actors (id, incident_id, actor_id, role, assigned_by)
                    SELECT uuid_generate_v4(), ip.incident_id, $1, ip.role::text::actor_role, 'migration'
                    FROM incident_persons ip
                    WHERE ip.person_id = $2
                    ON CONFLICT DO NOTHING
                """, actor_id, row["id"])

                stats["migrated"] += 1

            except Exception as e:
                logger.error(f"Error migrating person {row['id']}: {e}")
                stats["errors"] += 1

        return stats

    # ==================== Helper Methods ====================

    def _row_to_actor(self, row: Dict) -> Actor:
        """Convert database row to Actor object."""
        return Actor(
            id=row["id"],
            canonical_name=row["canonical_name"],
            actor_type=ActorType(row["actor_type"]),
            aliases=row.get("aliases") or [],
            date_of_birth=row.get("date_of_birth"),
            date_of_death=row.get("date_of_death"),
            gender=row.get("gender"),
            nationality=row.get("nationality"),
            immigration_status=row.get("immigration_status"),
            prior_deportations=row.get("prior_deportations", 0),
            organization_type=row.get("organization_type"),
            parent_org_id=row.get("parent_org_id"),
            is_government_entity=row.get("is_government_entity", False),
            is_law_enforcement=row.get("is_law_enforcement", False),
            jurisdiction=row.get("jurisdiction"),
            description=row.get("description"),
            profile_data=row.get("profile_data"),
            external_ids=row.get("external_ids"),
            confidence_score=float(row["confidence_score"]) if row.get("confidence_score") else None,
            merged_from=row.get("merged_from") or [],
            is_merged=row.get("is_merged", False),
            incident_count=row.get("incident_count", 0),
            roles_played=[r for r in (row.get("roles_played") or []) if r],
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_incident_link(self, row: Dict) -> IncidentActorLink:
        """Convert database row to IncidentActorLink object."""
        return IncidentActorLink(
            id=row["id"],
            incident_id=row["incident_id"],
            actor_id=row["actor_id"],
            role=ActorRole(row["role"]),
            role_detail=row.get("role_detail"),
            is_primary=row.get("is_primary", False),
            sequence_number=row.get("sequence_number"),
            assigned_by=row.get("assigned_by", "manual"),
            assignment_confidence=float(row["assignment_confidence"]) if row.get("assignment_confidence") else None,
            notes=row.get("notes"),
            created_at=row.get("created_at"),
        )

    def _row_to_relation(self, row: Dict) -> ActorRelation:
        """Convert database row to ActorRelation object."""
        return ActorRelation(
            id=row["id"],
            actor_id=row["actor_id"],
            related_actor_id=row["related_actor_id"],
            relation_type=ActorRelationType(row["relation_type"]),
            confidence=float(row["confidence"]) if row.get("confidence") else None,
            start_date=row.get("start_date"),
            end_date=row.get("end_date"),
            notes=row.get("notes"),
            created_at=row.get("created_at"),
        )


# Singleton instance
_actor_service: Optional[ActorService] = None


def get_actor_service() -> ActorService:
    """Get the singleton ActorService instance."""
    global _actor_service
    if _actor_service is None:
        _actor_service = ActorService()
    return _actor_service
