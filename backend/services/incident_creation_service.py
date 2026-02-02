"""
Incident creation service — extracts incident creation logic from the approval
endpoint into a reusable service that populates the full extensibility system
(actors with role_type_id, events, domain/category, tags, custom_fields).
"""

import logging
import uuid
from datetime import datetime, date as date_type
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category → domain + category slug mapping
# ---------------------------------------------------------------------------
CATEGORY_DOMAIN_MAP: Dict[str, tuple] = {
    "enforcement": ("immigration", "enforcement"),
    "crime": ("immigration", "crime"),
    "protest": ("civil_rights", "protest"),
    "police_force": ("civil_rights", "police_force"),
    "arrest": ("criminal_justice", "arrest"),
    "prosecution": ("criminal_justice", "prosecution"),
    "trial": ("criminal_justice", "trial"),
    "sentencing": ("criminal_justice", "sentencing"),
}

# Map extended category slugs → legacy incident_category enum values.
# The incidents.category column is an enum {enforcement, crime}; the proper
# extensible category is stored in domain_id + category_id.
LEGACY_CATEGORY_MAP: Dict[str, str] = {
    "enforcement": "enforcement",
    "crime": "crime",
    # CJ domain → "crime" in legacy enum
    "arrest": "crime",
    "prosecution": "crime",
    "trial": "crime",
    "sentencing": "crime",
    "incarceration": "crime",
    "release": "crime",
    # CR domain → "enforcement" in legacy enum (closest match)
    "protest": "enforcement",
    "police_force": "enforcement",
    "civil_rights_violation": "enforcement",
    "litigation": "enforcement",
}

# Map extracted actor roles → legacy actor_role enum values
ROLE_TO_LEGACY: Dict[str, str] = {
    "victim": "victim",
    "offender": "offender",
    "defendant": "offender",
    "detainee": "victim",
    "journalist": "witness",
    "family_member": "witness",
    "witness": "witness",
    "officer": "officer",
    "ice_agent": "officer",
    "cbp_agent": "officer",
    "arresting_agency": "arresting_agency",
    "investigating_agency": "arresting_agency",
    "prosecuting_agency": "arresting_agency",
    "reporting_agency": "reporting_agency",
    "bystander": "bystander",
    "organizer": "organizer",
    "protester": "participant",
    "plaintiff": "participant",
}

AGENCY_NORMALIZE: Dict[str, str] = {
    "ICE": "U.S. Immigration and Customs Enforcement",
    "CBP": "U.S. Customs and Border Protection",
    "USCIS": "U.S. Citizenship and Immigration Services",
}


class IncidentCreationService:
    """Reusable service that creates a fully-populated incident from extraction data."""

    # Universal minimum required fields when no schema info is available
    _DEFAULT_REQUIRED: List[str] = ['date', 'state']

    # Only validate fields that the creation service actually checks
    _VALIDATABLE_FIELDS = {'date', 'state', 'incident_type', 'victim_category', 'outcome_category'}

    async def _get_required_fields(self, merge_info: Optional[Dict[str, Any]]) -> List[str]:
        """Derive required fields from the extraction schema(s) that produced the data.

        When merge_info has sources with schema_ids, query extraction_schemas
        for each contributing schema's required_fields and return the union.
        Falls back to universal minimums for legacy articles or missing info.
        """
        if not merge_info:
            return list(self._DEFAULT_REQUIRED)

        sources = merge_info.get("sources")
        if not sources or not isinstance(sources, list):
            return list(self._DEFAULT_REQUIRED)

        # Collect schema_ids from ALL contributing sources (not just the base —
        # merged data contains fields from every schema, so validation should
        # cover the union of their requirements)
        schema_ids = []
        for src in sources:
            sid = src.get("schema_id")
            if sid:
                schema_ids.append(str(sid))
        schema_ids = list(dict.fromkeys(schema_ids))  # dedupe, preserve order

        if not schema_ids:
            return list(self._DEFAULT_REQUIRED)

        try:
            from backend.database import fetch
            rows = await fetch("""
                SELECT required_fields
                FROM extraction_schemas
                WHERE id = ANY($1::uuid[])
                  AND is_active = TRUE
            """, schema_ids)

            # Union the required fields across all contributing schemas
            union: set = set()
            for row in rows:
                rf = row.get("required_fields")
                if rf and isinstance(rf, list):
                    union.update(rf)

            if not union:
                return list(self._DEFAULT_REQUIRED)

            # Intersect with fields the creation service actually validates
            return sorted(union & self._VALIDATABLE_FIELDS)
        except Exception as e:
            logger.warning("Failed to load required_fields from extraction_schemas: %s", e)
            return list(self._DEFAULT_REQUIRED)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_incident_from_extraction(
        self,
        extracted_data: Dict[str, Any],
        article: Dict[str, Any],
        category: str,
        overrides: Optional[Dict[str, Any]] = None,
        merge_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an incident with actors, events, domain/category, tags and
        custom_fields from universal extraction output.

        Returns ``{"incident_id": str, "actors_created": list, "category": str}``.
        """
        from backend.database import fetch, execute
        from backend.utils.state_normalizer import normalize_state
        from backend.services.auto_approval import normalize_extracted_fields

        # Normalize field names/structure so creation works across all schemas
        extracted_data = normalize_extracted_fields(extracted_data)

        if overrides:
            extracted_data = {**extracted_data, **overrides}

        # --- unpack universal format ---
        incident_info = extracted_data.get("incident", {}) if isinstance(extracted_data, dict) else {}
        location_info = incident_info.get("location", {}) if isinstance(incident_info, dict) else {}
        outcome_info = incident_info.get("outcome", {}) if isinstance(incident_info, dict) else {}

        date_str = incident_info.get("date") or extracted_data.get("date")
        # Check universal format (incident.location), flat format (state), and
        # non-universal nested format (location.state) for broader schema compat
        top_location = extracted_data.get("location", {}) if isinstance(extracted_data.get("location"), dict) else {}
        state_str = location_info.get("state") or extracted_data.get("state") or top_location.get("state")
        city_str = location_info.get("city") or extracted_data.get("city") or top_location.get("city")
        description = incident_info.get("summary") or extracted_data.get("description")

        incident_date = self._parse_date(date_str)

        # --- incident type ---
        incident_types_list = incident_info.get("incident_types", [])
        incident_type_name = (
            incident_types_list[0] if incident_types_list
            else extracted_data.get("incident_type", "other")
        )
        incident_type_id = await self._get_or_create_incident_type(
            incident_type_name, category,
        )

        # --- outcome ---
        outcome_category_name = extracted_data.get("outcome_category")
        if not outcome_category_name and outcome_info.get("severity"):
            outcome_category_name = outcome_info["severity"]
        if not outcome_category_name and extracted_data.get("involves_fatality"):
            outcome_category_name = "death"
        outcome_type_id = await self._get_or_create_outcome_type(outcome_category_name)

        # --- victim / offender flat fields (backward compat) ---
        actors_list = extracted_data.get("actors", [])
        victim_name = extracted_data.get("victim_name")
        victim_age = extracted_data.get("victim_age")
        victim_category_name = extracted_data.get("victim_category")
        offender_immigration_status = extracted_data.get("offender_immigration_status")
        prior_deportations = extracted_data.get("prior_deportations", 0)
        gang_affiliated = extracted_data.get("gang_affiliated", False)

        if actors_list and not victim_name:
            for actor in actors_list:
                roles = actor.get("roles", [])
                if "victim" in roles:
                    victim_name = victim_name or actor.get("name")
                    victim_age = victim_age or actor.get("age")
                if "offender" in roles or "defendant" in roles:
                    offender_immigration_status = (
                        offender_immigration_status or actor.get("immigration_status")
                    )
                    prior_deportations = prior_deportations or actor.get("prior_deportations", 0)
                    if actor.get("gang_affiliation"):
                        gang_affiliated = True

        victim_type_id = await self._get_or_create_victim_type(victim_category_name)

        # --- domain / category ---
        domain_id, category_id = await self._resolve_domain_category(
            extracted_data, category,
        )

        # --- tags & custom_fields ---
        tags = self._build_tags(extracted_data, incident_info)
        custom_fields = self._build_custom_fields(extracted_data)

        # --- validate required fields before insert ---
        # Use schema-level required_fields from the extraction_schemas that
        # produced this data (via merge_info); fall back to universal minimums.
        required = await self._get_required_fields(merge_info)
        field_sources = {
            'date': date_str,
            'state': state_str,
            'incident_type': incident_type_name,
            'victim_category': victim_category_name,
            'outcome_category': outcome_category_name,
        }
        missing = [f for f in required
                   if field_sources.get(f) is None or field_sources.get(f) == '']
        if missing:
            raise ValueError(
                f"Cannot create incident: missing required fields for "
                f"{category}: {', '.join(missing)}"
            )

        # --- Geocode ---
        from backend.utils.geocoding import get_coords
        normalized_state = normalize_state(state_str)
        lat, lon = get_coords(city_str, normalized_state)

        # --- INSERT incident ---
        incident_id = uuid.uuid4()
        insert_query = """
            INSERT INTO incidents (
                id, category, date, state, city, incident_type_id,
                description, source_url, source_tier, curation_status,
                extraction_confidence, victim_name, victim_age, victim_type_id,
                outcome_type_id, offender_immigration_status,
                prior_deportations, gang_affiliated,
                domain_id, category_id, tags, custom_fields,
                latitude, longitude,
                created_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13, $14,
                $15, $16,
                $17, $18,
                $19, $20, $21, $22,
                $23, $24,
                $25
            )
            RETURNING id
        """
        legacy_category = LEGACY_CATEGORY_MAP.get(category, "crime")
        await execute(
            insert_query,
            incident_id,
            legacy_category,
            incident_date,
            normalized_state,
            city_str,
            incident_type_id,
            description,
            article.get("source_url"),
            "2",
            "approved",
            float(article["extraction_confidence"]) if article.get("extraction_confidence") else None,
            victim_name,
            victim_age,
            victim_type_id,
            outcome_type_id,
            offender_immigration_status,
            prior_deportations or 0,
            gang_affiliated or False,
            domain_id,
            category_id,
            tags or [],
            custom_fields or {},
            lat,
            lon,
            datetime.utcnow(),
        )

        # --- actors (full iteration) ---
        created_actors = await self._create_actors(
            incident_id, extracted_data, actors_list, category,
        )

        # --- events ---
        await self._create_events(incident_id, extracted_data)

        return {
            "incident_id": str(incident_id),
            "actors_created": created_actors,
            "category": category,
        }

    async def backfill_incident(
        self,
        incident_id: uuid.UUID,
        extracted_data: Dict[str, Any],
        category: str,
    ) -> Dict[str, Any]:
        """
        Backfill an existing incident with actors, events, and domain/category
        from its article's extracted_data.  Uses ON CONFLICT DO NOTHING for
        idempotency.
        """
        from backend.database import execute

        stats = {"actors": 0, "events": 0, "domain_set": False}

        # --- domain / category ---
        domain_id, category_id = await self._resolve_domain_category(
            extracted_data, category,
        )
        if domain_id:
            await execute(
                "UPDATE incidents SET domain_id = $1, category_id = $2 WHERE id = $3 AND domain_id IS NULL",
                domain_id, category_id, incident_id,
            )
            stats["domain_set"] = True

        # --- tags & custom_fields ---
        tags = self._build_tags(extracted_data, extracted_data.get("incident", {}))
        custom_fields = self._build_custom_fields(extracted_data)
        if tags:
            await execute(
                "UPDATE incidents SET tags = $1 WHERE id = $2 AND (tags IS NULL OR tags = '{}')",
                tags, incident_id,
            )
        if custom_fields:
            await execute(
                "UPDATE incidents SET custom_fields = $1 WHERE id = $2 AND (custom_fields IS NULL OR custom_fields = '{}'::jsonb)",
                custom_fields, incident_id,
            )

        # --- actors ---
        actors_list = extracted_data.get("actors", [])
        created = await self._create_actors(
            incident_id, extracted_data, actors_list, category,
        )
        stats["actors"] = len(created)

        # --- events ---
        events_created = await self._create_events(incident_id, extracted_data)
        stats["events"] = events_created

        return stats

    # ------------------------------------------------------------------
    # Domain / category resolution
    # ------------------------------------------------------------------

    async def _resolve_domain_category(
        self,
        extracted_data: Dict[str, Any],
        legacy_category: str,
    ) -> tuple:
        """Return (domain_id, category_id) or (None, None)."""
        from backend.database import fetch

        # Priority: classification_hints > extracted categories > legacy category
        cat_slug = None

        # 1. classification_hints from Stage 1 IR
        hints = extracted_data.get("classification_hints", [])
        if isinstance(hints, list):
            for hint in hints:
                if isinstance(hint, dict) and hint.get("category"):
                    cat_slug = hint["category"]
                    break
                elif isinstance(hint, str):
                    cat_slug = hint
                    break

        # 2. extracted categories array
        if not cat_slug:
            categories = extracted_data.get("categories", [])
            if isinstance(categories, list) and categories:
                cat_slug = categories[0]

        # 3. legacy category
        if not cat_slug:
            cat_slug = legacy_category

        mapping = CATEGORY_DOMAIN_MAP.get(cat_slug)
        if not mapping:
            # Fall back to immigration domain with the legacy category
            mapping = CATEGORY_DOMAIN_MAP.get(legacy_category, ("immigration", legacy_category))

        domain_slug, category_slug = mapping

        rows = await fetch(
            """
            SELECT ec.id as category_id, ed.id as domain_id
            FROM event_categories ec
            JOIN event_domains ed ON ec.domain_id = ed.id
            WHERE ed.slug = $1 AND ec.slug = $2
            """,
            domain_slug, category_slug,
        )
        if rows:
            return rows[0]["domain_id"], rows[0]["category_id"]
        return None, None

    # ------------------------------------------------------------------
    # Actors
    # ------------------------------------------------------------------

    async def _create_actors(
        self,
        incident_id: uuid.UUID,
        extracted_data: Dict[str, Any],
        actors_list: List[Dict],
        category: str,
    ) -> List[Dict]:
        """Create actors from the actors[] array and legacy flat fields."""
        created_actors: List[Dict] = []

        if actors_list:
            for actor_data in actors_list:
                result = await self._process_actor(incident_id, actor_data)
                if result:
                    created_actors.extend(result)
        else:
            # Fall back to legacy flat fields
            created_actors = await self._create_legacy_actors(
                incident_id, extracted_data, category,
            )

        return created_actors

    async def _process_actor(
        self,
        incident_id: uuid.UUID,
        actor_data: Dict[str, Any],
    ) -> List[Dict]:
        """Process a single actor from the actors[] array."""
        from backend.database import fetch, execute

        name = (actor_data.get("name") or "").strip()
        if not name or len(name) < 2:
            return []

        actor_type = actor_data.get("actor_type", "person")
        roles = actor_data.get("roles", [])

        # Normalize agency names
        if actor_type == "agency":
            name = AGENCY_NORMALIZE.get(name.upper(), name)

        # Find or create actor
        existing = await fetch(
            """
            SELECT id, canonical_name FROM actors
            WHERE LOWER(canonical_name) = LOWER($1)
               OR $1 = ANY(aliases)
            LIMIT 1
            """,
            name,
        )

        if existing:
            actor_id = existing[0]["id"]
            was_created = False
        else:
            actor_id = uuid.uuid4()
            is_le = actor_data.get("is_law_enforcement", False) or actor_type == "agency"
            is_govt = actor_data.get("is_government_entity", False) or actor_type == "agency"

            await execute(
                """
                INSERT INTO actors (
                    id, canonical_name, actor_type, aliases,
                    gender, nationality, immigration_status, prior_deportations,
                    is_law_enforcement, is_government_entity, confidence_score,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW(), NOW())
                """,
                actor_id,
                name,
                actor_type,
                [],
                actor_data.get("gender"),
                actor_data.get("nationality") or actor_data.get("country_of_origin"),
                actor_data.get("immigration_status"),
                actor_data.get("prior_deportations", 0),
                is_le,
                is_govt,
                actor_data.get("name_confidence", 0.7),
            )
            was_created = True

        # Link actor to incident for each role
        created: List[Dict] = []
        for role in (roles or ["participant"]):
            legacy_role = ROLE_TO_LEGACY.get(role, "participant")
            role_type_id = await self._resolve_role_type(role)
            confidence = actor_data.get("name_confidence", 0.7)

            await execute(
                """
                INSERT INTO incident_actors (
                    id, incident_id, actor_id, role, role_type_id,
                    assigned_by, assignment_confidence, created_at
                ) VALUES ($1, $2, $3, $4, $5, 'extraction', $6, NOW())
                ON CONFLICT (incident_id, actor_id, role) DO UPDATE
                    SET role_type_id = EXCLUDED.role_type_id
                """,
                uuid.uuid4(),
                incident_id,
                actor_id,
                legacy_role,
                role_type_id,
                confidence,
            )

            if was_created:
                created.append({
                    "id": str(actor_id),
                    "name": name,
                    "type": actor_type,
                    "role": legacy_role,
                })

        return created

    async def _create_legacy_actors(
        self,
        incident_id: uuid.UUID,
        extracted_data: Dict[str, Any],
        category: str,
    ) -> List[Dict]:
        """Fall back to creating actors from flat extracted fields."""
        created: List[Dict] = []

        offender_name = extracted_data.get("offender_name")
        if offender_name:
            result = await self._process_actor(incident_id, {
                "name": offender_name,
                "actor_type": "person",
                "roles": ["offender"],
                "nationality": (
                    extracted_data.get("offender_nationality")
                    or extracted_data.get("offender_country_of_origin")
                ),
                "immigration_status": extracted_data.get("offender_immigration_status"),
                "prior_deportations": extracted_data.get("prior_deportations", 0),
            })
            created.extend(result)

        victim_name = extracted_data.get("victim_name")
        if victim_name and category == "enforcement":
            result = await self._process_actor(incident_id, {
                "name": victim_name,
                "actor_type": "person",
                "roles": ["victim"],
            })
            created.extend(result)

        agency_name = extracted_data.get("agency")
        if agency_name:
            result = await self._process_actor(incident_id, {
                "name": agency_name,
                "actor_type": "agency",
                "roles": ["arresting_agency" if category == "crime" else "reporting_agency"],
                "is_law_enforcement": True,
                "is_government_entity": True,
            })
            created.extend(result)

        return created

    async def _resolve_role_type(self, role_slug: str) -> Optional[uuid.UUID]:
        """Look up actor_role_types.id by slug. Returns None if not found."""
        from backend.database import fetch

        rows = await fetch(
            "SELECT id FROM actor_role_types WHERE slug = $1 AND is_active = TRUE LIMIT 1",
            role_slug,
        )
        return rows[0]["id"] if rows else None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def _create_events(
        self,
        incident_id: uuid.UUID,
        extracted_data: Dict[str, Any],
    ) -> int:
        """Create events from the events[] array and link to incident."""
        from backend.database import fetch, execute

        events_list = extracted_data.get("events", [])
        if not events_list:
            return 0

        created_count = 0
        for evt in events_list:
            event_type = evt.get("event_type", "unknown")
            description = evt.get("description", "")
            event_date = self._parse_date(evt.get("date"))

            event_name = f"{event_type.replace('_', ' ').title()}"
            if event_date:
                event_name += f" ({event_date.isoformat()})"

            event_id = uuid.uuid4()
            await execute(
                """
                INSERT INTO events (
                    id, name, event_type, start_date, description,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
                """,
                event_id,
                event_name,
                event_type,
                event_date or datetime.utcnow().date(),
                description,
            )

            await execute(
                """
                INSERT INTO incident_events (
                    id, incident_id, event_id, assigned_by, assignment_confidence, created_at
                ) VALUES ($1, $2, $3, 'extraction', 0.8, NOW())
                ON CONFLICT (incident_id, event_id) DO NOTHING
                """,
                uuid.uuid4(),
                incident_id,
                event_id,
            )
            created_count += 1

        return created_count

    # ------------------------------------------------------------------
    # Tags & custom fields
    # ------------------------------------------------------------------

    def _build_tags(
        self,
        extracted_data: Dict[str, Any],
        incident_info: Dict[str, Any],
    ) -> List[str]:
        tags: List[str] = []
        for t in (incident_info or {}).get("incident_types", []):
            if t and t not in tags:
                tags.append(t)
        for c in extracted_data.get("categories", []):
            if c and c not in tags:
                tags.append(c)
        return tags

    def _build_custom_fields(
        self,
        extracted_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        policy = extracted_data.get("policy_context", {})
        if not isinstance(policy, dict):
            return {}
        fields: Dict[str, Any] = {}
        if policy.get("sanctuary_jurisdiction") is not None:
            fields["sanctuary_jurisdiction"] = policy["sanctuary_jurisdiction"]
        if policy.get("ice_detainer_status"):
            fields["ice_detainer_status"] = policy["ice_detainer_status"]
        if policy.get("policy_mentioned"):
            fields["policy_mentioned"] = policy["policy_mentioned"]
        return fields

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_date(self, date_str: Optional[str]) -> Optional[date_type]:
        if not date_str:
            return None
        try:
            return date_type.fromisoformat(date_str)
        except Exception:
            return None

    async def _get_or_create_incident_type(
        self, name: str, category: str,
    ) -> uuid.UUID:
        from backend.database import fetch, execute

        rows = await fetch(
            "SELECT id FROM incident_types WHERE name = $1 LIMIT 1", name,
        )
        if rows:
            return rows[0]["id"]

        # incident_types.category is a legacy enum {enforcement, crime}
        legacy_cat = LEGACY_CATEGORY_MAP.get(category, "crime")
        new_id = uuid.uuid4()
        await execute(
            "INSERT INTO incident_types (id, name, category) VALUES ($1, $2, $3)",
            new_id, name, legacy_cat,
        )
        return new_id

    async def _get_or_create_outcome_type(
        self, name: Optional[str],
    ) -> Optional[uuid.UUID]:
        if not name:
            return None
        from backend.database import fetch

        rows = await fetch(
            "SELECT get_or_create_outcome_type($1) as id", name,
        )
        return rows[0]["id"] if rows else None

    async def _get_or_create_victim_type(
        self, name: Optional[str],
    ) -> Optional[uuid.UUID]:
        if not name:
            return None
        from backend.database import fetch

        rows = await fetch(
            "SELECT get_or_create_victim_type($1) as id", name,
        )
        return rows[0]["id"] if rows else None


# Singleton
_service: Optional[IncidentCreationService] = None


def get_incident_creation_service() -> IncidentCreationService:
    global _service
    if _service is None:
        _service = IncidentCreationService()
    return _service
