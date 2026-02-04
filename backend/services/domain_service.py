"""
Domain service for managing event domains and categories.

Provides CRUD operations for the event taxonomy system that replaces
the binary enforcement/crime category model.
"""

import logging
from typing import Optional, List, Dict, Any
from uuid import UUID

logger = logging.getLogger(__name__)


class DomainService:
    """Service for managing event domains and categories."""

    # --- Domains ---

    async def list_domains(self, include_inactive: bool = False) -> List[dict]:
        """List all event domains."""
        from backend.database import fetch

        if include_inactive:
            query = "SELECT * FROM event_domains ORDER BY display_order, name"
        else:
            query = "SELECT * FROM event_domains WHERE is_active = TRUE ORDER BY display_order, name"

        rows = await fetch(query)
        return [self._serialize_domain(row) for row in rows]

    async def get_domain(self, slug: str) -> Optional[dict]:
        """Get a domain by slug."""
        from backend.database import fetchrow

        row = await fetchrow(
            "SELECT * FROM event_domains WHERE slug = $1",
            slug
        )
        return self._serialize_domain(row) if row else None

    async def get_domain_by_id(self, domain_id: UUID) -> Optional[dict]:
        """Get a domain by ID."""
        from backend.database import fetchrow

        row = await fetchrow(
            "SELECT * FROM event_domains WHERE id = $1",
            domain_id
        )
        return self._serialize_domain(row) if row else None

    async def create_domain(self, data: Dict[str, Any]) -> dict:
        """Create a new event domain."""
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO event_domains (name, slug, description, icon, color, display_order, relevance_scope)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """,
            data["name"],
            data["slug"],
            data.get("description"),
            data.get("icon"),
            data.get("color"),
            data.get("display_order", 0),
            data.get("relevance_scope"),
        )
        logger.info(f"Created domain: {data['slug']}")
        return self._serialize_domain(row)

    async def update_domain(self, slug: str, data: Dict[str, Any]) -> Optional[dict]:
        """Update an existing domain."""
        from backend.database import fetchrow

        row = await fetchrow("""
            UPDATE event_domains SET
                name = COALESCE($2, name),
                description = COALESCE($3, description),
                icon = COALESCE($4, icon),
                color = COALESCE($5, color),
                is_active = COALESCE($6, is_active),
                display_order = COALESCE($7, display_order),
                relevance_scope = COALESCE($8, relevance_scope),
                updated_at = NOW()
            WHERE slug = $1
            RETURNING *
        """,
            slug,
            data.get("name"),
            data.get("description"),
            data.get("icon"),
            data.get("color"),
            data.get("is_active"),
            data.get("display_order"),
            data.get("relevance_scope"),
        )
        if row:
            logger.info(f"Updated domain: {slug}")
        return self._serialize_domain(row) if row else None

    # --- Categories ---

    async def list_categories(
        self,
        domain_slug: Optional[str] = None,
        domain_id: Optional[UUID] = None,
        include_inactive: bool = False,
    ) -> List[dict]:
        """List categories, optionally filtered by domain."""
        from backend.database import fetch

        conditions = []
        params = []
        idx = 1

        if domain_slug:
            conditions.append(f"ed.slug = ${idx}")
            params.append(domain_slug)
            idx += 1
        elif domain_id:
            conditions.append(f"ec.domain_id = ${idx}")
            params.append(domain_id)
            idx += 1

        if not include_inactive:
            conditions.append("ec.is_active = TRUE")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = await fetch(f"""
            SELECT ec.*, ed.slug as domain_slug, ed.name as domain_name
            FROM event_categories ec
            JOIN event_domains ed ON ec.domain_id = ed.id
            {where_clause}
            ORDER BY ec.display_order, ec.name
        """, *params)

        return [self._serialize_category(row) for row in rows]

    async def get_category(self, category_id: UUID) -> Optional[dict]:
        """Get a category by ID."""
        from backend.database import fetchrow

        row = await fetchrow("""
            SELECT ec.*, ed.slug as domain_slug, ed.name as domain_name
            FROM event_categories ec
            JOIN event_domains ed ON ec.domain_id = ed.id
            WHERE ec.id = $1
        """, category_id)
        return self._serialize_category(row) if row else None

    async def get_category_by_slug(self, domain_slug: str, category_slug: str) -> Optional[dict]:
        """Get a category by domain + category slug."""
        from backend.database import fetchrow

        row = await fetchrow("""
            SELECT ec.*, ed.slug as domain_slug, ed.name as domain_name
            FROM event_categories ec
            JOIN event_domains ed ON ec.domain_id = ed.id
            WHERE ed.slug = $1 AND ec.slug = $2
        """, domain_slug, category_slug)
        return self._serialize_category(row) if row else None

    async def create_category(self, domain_slug: str, data: Dict[str, Any]) -> Optional[dict]:
        """Create a category within a domain."""
        from backend.database import fetchrow

        domain = await self.get_domain(domain_slug)
        if not domain:
            return None

        domain_id = domain["id"]

        row = await fetchrow("""
            INSERT INTO event_categories (
                domain_id, parent_category_id, name, slug, description,
                icon, display_order, required_fields, optional_fields, field_definitions
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10::jsonb)
            RETURNING *
        """,
            domain_id,
            data.get("parent_category_id"),
            data["name"],
            data["slug"],
            data.get("description"),
            data.get("icon"),
            data.get("display_order", 0),
            data.get("required_fields", "[]"),
            data.get("optional_fields", "[]"),
            data.get("field_definitions", "{}"),
        )
        if row:
            logger.info(f"Created category: {domain_slug}/{data['slug']}")
            # Re-fetch with domain info
            return await self.get_category(row["id"])
        return None

    async def update_category(self, category_id: UUID, data: Dict[str, Any]) -> Optional[dict]:
        """Update an existing category."""
        from backend.database import fetchrow, execute
        import json

        sets = ["updated_at = NOW()"]
        params = [category_id]
        idx = 2

        for field in ("name", "description", "icon", "is_active", "display_order"):
            if field in data:
                sets.append(f"{field} = ${idx}")
                params.append(data[field])
                idx += 1

        for jsonb_field in ("required_fields", "optional_fields", "field_definitions"):
            if jsonb_field in data:
                sets.append(f"{jsonb_field} = ${idx}::jsonb")
                val = data[jsonb_field]
                params.append(json.loads(val) if isinstance(val, str) else val)
                idx += 1

        if data.get("parent_category_id") is not None:
            sets.append(f"parent_category_id = ${idx}")
            params.append(data["parent_category_id"])
            idx += 1

        row = await fetchrow(f"""
            UPDATE event_categories SET {', '.join(sets)}
            WHERE id = $1
            RETURNING *
        """, *params)

        if row:
            logger.info(f"Updated category: {category_id}")
            return await self.get_category(category_id)
        return None

    # --- Relationships ---

    async def list_relationships(self, incident_id: UUID) -> List[dict]:
        """List relationships for an incident (as source or target)."""
        from backend.database import fetch

        rows = await fetch("""
            SELECT er.*,
                   si.title as source_title, si.date as source_date,
                   ti.title as target_title, ti.date as target_date,
                   rt.description as type_description, rt.is_directional
            FROM event_relationships er
            JOIN incidents si ON er.source_incident_id = si.id
            JOIN incidents ti ON er.target_incident_id = ti.id
            JOIN relationship_types rt ON er.relationship_type = rt.name
            WHERE er.source_incident_id = $1 OR er.target_incident_id = $1
            ORDER BY er.created_at DESC
        """, incident_id)

        return [self._serialize_relationship(row) for row in rows]

    async def create_relationship(self, data: Dict[str, Any]) -> Optional[dict]:
        """Create a relationship between two incidents."""
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO event_relationships (
                source_incident_id, target_incident_id, relationship_type,
                sequence_order, description, confidence, created_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """,
            data["source_incident_id"],
            data["target_incident_id"],
            data["relationship_type"],
            data.get("sequence_order"),
            data.get("description"),
            data.get("confidence"),
            data.get("created_by", "manual"),
        )
        return self._serialize_relationship(row) if row else None

    # --- Serialization ---

    def _serialize_domain(self, row) -> dict:
        if row is None:
            return None
        d = dict(row)
        for uid_field in ("id",):
            if d.get(uid_field):
                d[uid_field] = str(d[uid_field])
        for ts_field in ("created_at", "updated_at", "archived_at"):
            if d.get(ts_field):
                d[ts_field] = d[ts_field].isoformat()
        return d

    def _serialize_category(self, row) -> dict:
        if row is None:
            return None
        d = dict(row)
        for uid_field in ("id", "domain_id", "parent_category_id"):
            if d.get(uid_field):
                d[uid_field] = str(d[uid_field])
        for ts_field in ("created_at", "updated_at", "archived_at"):
            if d.get(ts_field):
                d[ts_field] = d[ts_field].isoformat()
        return d

    def _serialize_relationship(self, row) -> dict:
        if row is None:
            return None
        d = dict(row)
        for uid_field in ("id", "source_incident_id", "target_incident_id", "case_id"):
            if d.get(uid_field):
                d[uid_field] = str(d[uid_field])
        for ts_field in ("created_at",):
            if d.get(ts_field):
                d[ts_field] = d[ts_field].isoformat()
        if d.get("confidence"):
            d["confidence"] = float(d["confidence"])
        return d


# Singleton
_domain_service: Optional[DomainService] = None


def get_domain_service() -> DomainService:
    """Get the singleton DomainService instance."""
    global _domain_service
    if _domain_service is None:
        _domain_service = DomainService()
    return _domain_service
