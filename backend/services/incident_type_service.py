"""
Incident type service for managing dynamic incident types, field definitions, and pipeline configuration.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from enum import Enum

logger = logging.getLogger(__name__)


class FieldType(str, Enum):
    STRING = "string"
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ENUM = "enum"
    ARRAY = "array"
    REFERENCE = "reference"


class IncidentCategory(str, Enum):
    ENFORCEMENT = "enforcement"
    CRIME = "crime"


@dataclass
class FieldDefinition:
    """Custom field definition for an incident type."""
    id: UUID
    incident_type_id: UUID
    name: str
    display_name: str
    field_type: FieldType
    description: Optional[str] = None
    enum_values: Optional[List[str]] = None
    reference_table: Optional[str] = None
    default_value: Optional[str] = None
    required: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    pattern: Optional[str] = None
    extraction_hint: Optional[str] = None
    display_order: int = 0
    show_in_list: bool = True
    show_in_detail: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class IncidentType:
    """Incident type with full configuration."""
    id: UUID
    name: str
    category: IncidentCategory
    slug: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: bool = True
    parent_type_id: Optional[UUID] = None
    severity_weight: float = 1.0
    pipeline_config: Dict = field(default_factory=dict)
    approval_thresholds: Dict = field(default_factory=dict)
    validation_rules: List = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PipelineStage:
    """Pipeline stage configuration."""
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    handler_class: str
    default_order: int
    config_schema: Optional[Dict]
    is_active: bool


@dataclass
class TypePipelineConfig:
    """Per-type pipeline stage configuration."""
    id: UUID
    incident_type_id: UUID
    pipeline_stage_id: UUID
    enabled: bool
    execution_order: Optional[int]
    stage_config: Dict
    prompt_id: Optional[UUID]


class IncidentTypeService:
    """
    Service for managing incident types and their configurations.

    Features:
    - CRUD for incident types
    - Field definition management
    - Pipeline configuration per type
    - Approval threshold configuration
    """

    async def get_type(self, type_id: UUID) -> Optional[IncidentType]:
        """Get an incident type by ID."""
        from backend.database import fetch

        query = "SELECT * FROM incident_types WHERE id = $1"
        rows = await fetch(query, type_id)

        if not rows:
            return None

        return self._row_to_type(rows[0])

    async def get_type_by_slug(self, slug: str) -> Optional[IncidentType]:
        """Get an incident type by slug."""
        from backend.database import fetch

        query = "SELECT * FROM incident_types WHERE slug = $1"
        rows = await fetch(query, slug)

        if not rows:
            return None

        return self._row_to_type(rows[0])

    async def get_type_by_name(self, name: str) -> Optional[IncidentType]:
        """Get an incident type by name."""
        from backend.database import fetch

        query = "SELECT * FROM incident_types WHERE name = $1"
        rows = await fetch(query, name)

        if not rows:
            return None

        return self._row_to_type(rows[0])

    async def list_types(
        self,
        category: Optional[IncidentCategory] = None,
        active_only: bool = True,
        parent_id: Optional[UUID] = None
    ) -> List[IncidentType]:
        """List incident types with optional filters."""
        from backend.database import fetch

        conditions = []
        params = []
        param_num = 1

        if category:
            conditions.append(f"category = ${param_num}")
            params.append(category.value)
            param_num += 1

        if active_only:
            conditions.append("is_active = TRUE")

        if parent_id:
            conditions.append(f"parent_type_id = ${param_num}")
            params.append(parent_id)
        elif parent_id is None and not any("parent_type_id" in c for c in conditions):
            # Get top-level types by default (no parent)
            pass

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT * FROM incident_types
            WHERE {where_clause}
            ORDER BY category, severity_weight DESC, name
        """

        rows = await fetch(query, *params)
        return [self._row_to_type(row) for row in rows]

    async def create_type(
        self,
        name: str,
        category: IncidentCategory,
        slug: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        parent_type_id: Optional[UUID] = None,
        severity_weight: float = 1.0,
        pipeline_config: Optional[Dict] = None,
        approval_thresholds: Optional[Dict] = None,
        validation_rules: Optional[List] = None
    ) -> IncidentType:
        """Create a new incident type."""
        from backend.database import fetch
        import uuid

        type_id = uuid.uuid4()

        # Generate slug if not provided
        if not slug:
            slug = name.lower().replace(" ", "_").replace("-", "_")

        # Default approval thresholds based on category
        if not approval_thresholds:
            if category == IncidentCategory.ENFORCEMENT:
                approval_thresholds = {
                    "min_confidence_auto_approve": 0.90,
                    "min_confidence_review": 0.50,
                    "auto_reject_below": 0.30,
                    "field_confidence_threshold": 0.75
                }
            else:
                approval_thresholds = {
                    "min_confidence_auto_approve": 0.85,
                    "min_confidence_review": 0.50,
                    "auto_reject_below": 0.30,
                    "field_confidence_threshold": 0.70
                }

        query = """
            INSERT INTO incident_types (
                id, name, category, slug, display_name, description,
                icon, color, parent_type_id, severity_weight,
                pipeline_config, approval_thresholds, validation_rules,
                is_active
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, TRUE)
            RETURNING *
        """

        rows = await fetch(
            query,
            type_id, name, category.value, slug, display_name or name, description,
            icon, color, parent_type_id, severity_weight,
            pipeline_config or {}, approval_thresholds, validation_rules or []
        )

        incident_type = self._row_to_type(rows[0])

        # Create default pipeline config for new type
        await self._create_default_pipeline_config(type_id)

        return incident_type

    async def update_type(
        self,
        type_id: UUID,
        updates: Dict[str, Any]
    ) -> IncidentType:
        """Update an incident type."""
        from backend.database import execute, fetch

        allowed_fields = [
            'name', 'display_name', 'description', 'icon', 'color',
            'is_active', 'parent_type_id', 'severity_weight',
            'pipeline_config', 'approval_thresholds', 'validation_rules'
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

        set_clauses.append(f"updated_at = NOW()")
        params.append(type_id)

        query = f"""
            UPDATE incident_types
            SET {', '.join(set_clauses)}
            WHERE id = ${param_num}
            RETURNING *
        """

        rows = await fetch(query, *params)
        if not rows:
            raise ValueError(f"Incident type {type_id} not found")

        return self._row_to_type(rows[0])

    async def delete_type(self, type_id: UUID, soft_delete: bool = True) -> bool:
        """Delete (or soft-delete) an incident type."""
        from backend.database import execute

        if soft_delete:
            await execute(
                "UPDATE incident_types SET is_active = FALSE, updated_at = NOW() WHERE id = $1",
                type_id
            )
        else:
            await execute("DELETE FROM incident_types WHERE id = $1", type_id)

        return True

    # ==================== Field Definitions ====================

    async def get_field_definitions(self, type_id: UUID) -> List[FieldDefinition]:
        """Get all field definitions for an incident type."""
        from backend.database import fetch

        query = """
            SELECT * FROM field_definitions
            WHERE incident_type_id = $1
            ORDER BY display_order, name
        """

        rows = await fetch(query, type_id)
        return [self._row_to_field(row) for row in rows]

    async def get_field_definition(self, field_id: UUID) -> Optional[FieldDefinition]:
        """Get a specific field definition."""
        from backend.database import fetch

        query = "SELECT * FROM field_definitions WHERE id = $1"
        rows = await fetch(query, field_id)

        if not rows:
            return None

        return self._row_to_field(rows[0])

    async def create_field(
        self,
        incident_type_id: UUID,
        name: str,
        display_name: str,
        field_type: FieldType,
        description: Optional[str] = None,
        enum_values: Optional[List[str]] = None,
        required: bool = False,
        extraction_hint: Optional[str] = None,
        display_order: int = 0
    ) -> FieldDefinition:
        """Create a new field definition."""
        from backend.database import fetch
        import uuid

        field_id = uuid.uuid4()

        query = """
            INSERT INTO field_definitions (
                id, incident_type_id, name, display_name, field_type,
                description, enum_values, required, extraction_hint, display_order
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
        """

        rows = await fetch(
            query,
            field_id, incident_type_id, name, display_name, field_type.value,
            description, enum_values, required, extraction_hint, display_order
        )

        return self._row_to_field(rows[0])

    async def update_field(
        self,
        field_id: UUID,
        updates: Dict[str, Any]
    ) -> FieldDefinition:
        """Update a field definition."""
        from backend.database import fetch

        allowed_fields = [
            'display_name', 'description', 'enum_values', 'reference_table',
            'default_value', 'required', 'min_value', 'max_value', 'pattern',
            'extraction_hint', 'display_order', 'show_in_list', 'show_in_detail'
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
        params.append(field_id)

        query = f"""
            UPDATE field_definitions
            SET {', '.join(set_clauses)}
            WHERE id = ${param_num}
            RETURNING *
        """

        rows = await fetch(query, *params)
        if not rows:
            raise ValueError(f"Field definition {field_id} not found")

        return self._row_to_field(rows[0])

    async def delete_field(self, field_id: UUID) -> bool:
        """Delete a field definition."""
        from backend.database import execute

        await execute("DELETE FROM field_definitions WHERE id = $1", field_id)
        return True

    # ==================== Pipeline Configuration ====================

    async def get_pipeline_stages(self, active_only: bool = True) -> List[PipelineStage]:
        """Get all available pipeline stages."""
        from backend.database import fetch

        if active_only:
            query = "SELECT * FROM pipeline_stages WHERE is_active = TRUE ORDER BY default_order"
        else:
            query = "SELECT * FROM pipeline_stages ORDER BY default_order"

        rows = await fetch(query)
        return [self._row_to_stage(row) for row in rows]

    async def get_type_pipeline_config(self, type_id: UUID) -> List[TypePipelineConfig]:
        """Get pipeline configuration for an incident type."""
        from backend.database import fetch

        query = """
            SELECT itpc.*, ps.name as stage_name, ps.slug as stage_slug, ps.default_order
            FROM incident_type_pipeline_config itpc
            JOIN pipeline_stages ps ON itpc.pipeline_stage_id = ps.id
            WHERE itpc.incident_type_id = $1
            ORDER BY COALESCE(itpc.execution_order, ps.default_order)
        """

        rows = await fetch(query, type_id)
        return [self._row_to_pipeline_config(row) for row in rows]

    async def update_type_pipeline_config(
        self,
        type_id: UUID,
        stage_id: UUID,
        enabled: Optional[bool] = None,
        execution_order: Optional[int] = None,
        stage_config: Optional[Dict] = None,
        prompt_id: Optional[UUID] = None
    ) -> TypePipelineConfig:
        """Update pipeline configuration for a specific stage."""
        from backend.database import fetch

        # Check if config exists
        check_query = """
            SELECT id FROM incident_type_pipeline_config
            WHERE incident_type_id = $1 AND pipeline_stage_id = $2
        """
        existing = await fetch(check_query, type_id, stage_id)

        if existing:
            # Update existing
            set_clauses = []
            params = []
            param_num = 1

            if enabled is not None:
                set_clauses.append(f"enabled = ${param_num}")
                params.append(enabled)
                param_num += 1

            if execution_order is not None:
                set_clauses.append(f"execution_order = ${param_num}")
                params.append(execution_order)
                param_num += 1

            if stage_config is not None:
                set_clauses.append(f"stage_config = ${param_num}")
                params.append(stage_config)
                param_num += 1

            if prompt_id is not None:
                set_clauses.append(f"prompt_id = ${param_num}")
                params.append(prompt_id)
                param_num += 1

            if not set_clauses:
                # Nothing to update, return existing
                rows = await fetch(
                    "SELECT * FROM incident_type_pipeline_config WHERE id = $1",
                    existing[0]["id"]
                )
                return self._row_to_pipeline_config(rows[0])

            set_clauses.append("updated_at = NOW()")
            params.extend([type_id, stage_id])

            query = f"""
                UPDATE incident_type_pipeline_config
                SET {', '.join(set_clauses)}
                WHERE incident_type_id = ${param_num} AND pipeline_stage_id = ${param_num + 1}
                RETURNING *
            """

            rows = await fetch(query, *params)
        else:
            # Insert new
            import uuid
            config_id = uuid.uuid4()

            query = """
                INSERT INTO incident_type_pipeline_config (
                    id, incident_type_id, pipeline_stage_id,
                    enabled, execution_order, stage_config, prompt_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """

            rows = await fetch(
                query,
                config_id, type_id, stage_id,
                enabled if enabled is not None else True,
                execution_order,
                stage_config or {},
                prompt_id
            )

        return self._row_to_pipeline_config(rows[0])

    async def _create_default_pipeline_config(self, type_id: UUID):
        """Create default pipeline configuration for a new type."""
        from backend.database import fetch, execute

        # Get all active stages
        stages = await self.get_pipeline_stages(active_only=True)

        for stage in stages:
            import uuid
            config_id = uuid.uuid4()

            await execute("""
                INSERT INTO incident_type_pipeline_config (
                    id, incident_type_id, pipeline_stage_id, enabled, stage_config
                ) VALUES ($1, $2, $3, TRUE, '{}')
                ON CONFLICT (incident_type_id, pipeline_stage_id) DO NOTHING
            """, config_id, type_id, stage.id)

    # ==================== Approval Thresholds ====================

    async def get_approval_thresholds(self, type_id: UUID) -> Dict:
        """Get approval thresholds for an incident type."""
        incident_type = await self.get_type(type_id)
        if not incident_type:
            return {}
        return incident_type.approval_thresholds

    async def update_approval_thresholds(
        self,
        type_id: UUID,
        thresholds: Dict
    ) -> Dict:
        """Update approval thresholds for an incident type."""
        from backend.database import fetch

        # Merge with existing
        current = await self.get_approval_thresholds(type_id)
        current.update(thresholds)

        query = """
            UPDATE incident_types
            SET approval_thresholds = $1, updated_at = NOW()
            WHERE id = $2
            RETURNING approval_thresholds
        """

        rows = await fetch(query, current, type_id)
        return rows[0]["approval_thresholds"] if rows else {}

    # ==================== Required Fields ====================

    async def get_required_fields(self, type_id: UUID) -> List[str]:
        """Get required field names for an incident type."""
        fields = await self.get_field_definitions(type_id)
        return [f.name for f in fields if f.required]

    async def get_extraction_schema(self, type_id: UUID) -> Dict:
        """Generate JSON schema for LLM extraction based on field definitions."""
        fields = await self.get_field_definitions(type_id)

        properties = {}
        required = []

        for field_def in fields:
            prop = {"description": field_def.extraction_hint or field_def.description or ""}

            if field_def.field_type == FieldType.STRING:
                prop["type"] = "string"
            elif field_def.field_type == FieldType.TEXT:
                prop["type"] = "string"
            elif field_def.field_type == FieldType.INTEGER:
                prop["type"] = "integer"
            elif field_def.field_type == FieldType.DECIMAL:
                prop["type"] = "number"
            elif field_def.field_type == FieldType.BOOLEAN:
                prop["type"] = "boolean"
            elif field_def.field_type == FieldType.DATE:
                prop["type"] = "string"
                prop["format"] = "date"
            elif field_def.field_type == FieldType.DATETIME:
                prop["type"] = "string"
                prop["format"] = "date-time"
            elif field_def.field_type == FieldType.ENUM:
                prop["type"] = "string"
                if field_def.enum_values:
                    prop["enum"] = field_def.enum_values
            elif field_def.field_type == FieldType.ARRAY:
                prop["type"] = "array"
            elif field_def.field_type == FieldType.REFERENCE:
                prop["type"] = "string"
                prop["description"] += f" (reference to {field_def.reference_table})"

            properties[field_def.name] = prop

            # Add confidence field
            properties[f"{field_def.name}_confidence"] = {
                "type": "number",
                "minimum": 0,
                "maximum": 1
            }

            if field_def.required:
                required.append(field_def.name)

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

    # ==================== Helper Methods ====================

    def _row_to_type(self, row: Dict) -> IncidentType:
        """Convert database row to IncidentType object."""
        return IncidentType(
            id=row["id"],
            name=row["name"],
            category=IncidentCategory(row["category"]),
            slug=row.get("slug"),
            display_name=row.get("display_name"),
            description=row.get("description"),
            icon=row.get("icon"),
            color=row.get("color"),
            is_active=row.get("is_active", True),
            parent_type_id=row.get("parent_type_id"),
            severity_weight=float(row.get("severity_weight", 1.0)),
            pipeline_config=row.get("pipeline_config") or {},
            approval_thresholds=row.get("approval_thresholds") or {},
            validation_rules=row.get("validation_rules") or [],
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_field(self, row: Dict) -> FieldDefinition:
        """Convert database row to FieldDefinition object."""
        return FieldDefinition(
            id=row["id"],
            incident_type_id=row["incident_type_id"],
            name=row["name"],
            display_name=row["display_name"],
            field_type=FieldType(row["field_type"]),
            description=row.get("description"),
            enum_values=row.get("enum_values"),
            reference_table=row.get("reference_table"),
            default_value=row.get("default_value"),
            required=row.get("required", False),
            min_value=float(row["min_value"]) if row.get("min_value") else None,
            max_value=float(row["max_value"]) if row.get("max_value") else None,
            pattern=row.get("pattern"),
            extraction_hint=row.get("extraction_hint"),
            display_order=row.get("display_order", 0),
            show_in_list=row.get("show_in_list", True),
            show_in_detail=row.get("show_in_detail", True),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_stage(self, row: Dict) -> PipelineStage:
        """Convert database row to PipelineStage object."""
        return PipelineStage(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            description=row.get("description"),
            handler_class=row["handler_class"],
            default_order=row["default_order"],
            config_schema=row.get("config_schema"),
            is_active=row.get("is_active", True),
        )

    def _row_to_pipeline_config(self, row: Dict) -> TypePipelineConfig:
        """Convert database row to TypePipelineConfig object."""
        return TypePipelineConfig(
            id=row["id"],
            incident_type_id=row["incident_type_id"],
            pipeline_stage_id=row["pipeline_stage_id"],
            enabled=row.get("enabled", True),
            execution_order=row.get("execution_order"),
            stage_config=row.get("stage_config") or {},
            prompt_id=row.get("prompt_id"),
        )


# Singleton instance
_incident_type_service: Optional[IncidentTypeService] = None


def get_incident_type_service() -> IncidentTypeService:
    """Get the singleton IncidentTypeService instance."""
    global _incident_type_service
    if _incident_type_service is None:
        _incident_type_service = IncidentTypeService()
    return _incident_type_service
