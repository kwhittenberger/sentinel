"""
Prompt management service with database-backed storage, versioning, and A/B testing.
"""

import logging
import re
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from uuid import UUID
from enum import Enum

logger = logging.getLogger(__name__)


class PromptType(str, Enum):
    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"
    ENTITY_RESOLUTION = "entity_resolution"
    PATTERN_DETECTION = "pattern_detection"
    SUMMARIZATION = "summarization"
    ANALYSIS = "analysis"


class PromptStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TESTING = "testing"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


@dataclass
class Prompt:
    """Represents a prompt configuration."""
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    prompt_type: PromptType
    incident_type_id: Optional[UUID]

    system_prompt: str
    user_prompt_template: str
    output_schema: Optional[Dict]

    version: int
    parent_version_id: Optional[UUID]
    status: PromptStatus

    model_name: str
    max_tokens: int
    temperature: float

    traffic_percentage: int
    ab_test_group: Optional[str]

    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    activated_at: Optional[datetime]


@dataclass
class RenderedPrompt:
    """A prompt with variables substituted."""
    prompt: Prompt
    system_prompt: str
    user_prompt: str
    context: Dict[str, Any]


@dataclass
class ExecutionResult:
    """Result of a prompt execution."""
    success: bool
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    confidence_score: Optional[float] = None
    result_data: Optional[Dict] = None
    error_message: Optional[str] = None
    ab_variant: Optional[str] = None


class PromptManager:
    """
    Database-backed prompt management with caching and versioning.

    Features:
    - Load prompts from database with caching
    - Template variable substitution
    - Version management (create, activate, rollback)
    - A/B testing support
    - Execution tracking for analytics
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        """
        Initialize the prompt manager.

        Args:
            cache_ttl_seconds: How long to cache prompts (default 5 minutes)
        """
        self._cache: Dict[str, Tuple[Prompt, datetime]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)

    def _cache_key(
        self,
        prompt_type: PromptType,
        incident_type_id: Optional[UUID] = None,
        slug: Optional[str] = None
    ) -> str:
        """Generate a cache key."""
        parts = [prompt_type.value]
        if incident_type_id:
            parts.append(str(incident_type_id))
        if slug:
            parts.append(slug)
        return ":".join(parts)

    def _is_cache_valid(self, cache_entry: Tuple[Prompt, datetime]) -> bool:
        """Check if a cache entry is still valid."""
        _, loaded_at = cache_entry
        return datetime.utcnow() - loaded_at < self._cache_ttl

    async def get_prompt(
        self,
        prompt_type: PromptType,
        incident_type_id: Optional[UUID] = None,
        ab_context: Optional[Dict] = None,
        slug: Optional[str] = None
    ) -> Optional[Prompt]:
        """
        Load active prompt from database, with type-specific override and A/B selection.

        Args:
            prompt_type: Type of prompt to load
            incident_type_id: Optional incident type for type-specific prompts
            ab_context: Optional context for A/B test selection
            slug: Optional specific slug to load

        Returns:
            Prompt if found, None otherwise
        """
        from backend.database import fetch

        # Check cache first
        cache_key = self._cache_key(prompt_type, incident_type_id, slug)
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if self._is_cache_valid(entry):
                prompt = entry[0]
                # Handle A/B testing
                if prompt.traffic_percentage < 100 and ab_context:
                    return await self._select_ab_variant(prompt, ab_context)
                return prompt

        # Build query
        if slug:
            query = """
                SELECT * FROM prompts
                WHERE slug = $1 AND status = 'active'
                ORDER BY version DESC LIMIT 1
            """
            rows = await fetch(query, slug)
        elif incident_type_id:
            # Try type-specific first, then fall back to global
            query = """
                SELECT * FROM prompts
                WHERE prompt_type = $1 AND status = 'active'
                  AND (incident_type_id = $2 OR incident_type_id IS NULL)
                ORDER BY incident_type_id NULLS LAST, version DESC
                LIMIT 1
            """
            rows = await fetch(query, prompt_type.value, incident_type_id)
        else:
            query = """
                SELECT * FROM prompts
                WHERE prompt_type = $1 AND status = 'active'
                  AND incident_type_id IS NULL
                ORDER BY version DESC LIMIT 1
            """
            rows = await fetch(query, prompt_type.value)

        if not rows:
            logger.warning(f"No active prompt found for type={prompt_type}, incident_type={incident_type_id}")
            return None

        prompt = self._row_to_prompt(rows[0])

        # Cache it
        self._cache[cache_key] = (prompt, datetime.utcnow())

        # Handle A/B testing
        if prompt.traffic_percentage < 100 and ab_context:
            return await self._select_ab_variant(prompt, ab_context)

        return prompt

    async def get_prompt_by_id(self, prompt_id: UUID) -> Optional[Prompt]:
        """Load a specific prompt by ID."""
        from backend.database import fetch

        query = "SELECT * FROM prompts WHERE id = $1"
        rows = await fetch(query, prompt_id)

        if not rows:
            return None

        return self._row_to_prompt(rows[0])

    async def list_prompts(
        self,
        prompt_type: Optional[PromptType] = None,
        status: Optional[PromptStatus] = None,
        incident_type_id: Optional[UUID] = None,
        limit: int = 50
    ) -> List[Prompt]:
        """List prompts with optional filters."""
        from backend.database import fetch

        conditions = []
        params = []
        param_num = 1

        if prompt_type:
            conditions.append(f"prompt_type = ${param_num}")
            params.append(prompt_type.value)
            param_num += 1

        if status:
            conditions.append(f"status = ${param_num}")
            params.append(status.value)
            param_num += 1

        if incident_type_id:
            conditions.append(f"incident_type_id = ${param_num}")
            params.append(incident_type_id)
            param_num += 1

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        query = f"""
            SELECT * FROM prompts
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_num}
        """

        rows = await fetch(query, *params)
        return [self._row_to_prompt(row) for row in rows]

    async def _select_ab_variant(
        self,
        primary_prompt: Prompt,
        ab_context: Dict
    ) -> Prompt:
        """Select A/B test variant based on context."""
        # Use a deterministic hash for consistent assignment
        context_key = ab_context.get("session_id") or ab_context.get("article_id") or ""
        hash_val = hash(f"{primary_prompt.id}:{context_key}") % 100

        if hash_val < primary_prompt.traffic_percentage:
            return primary_prompt

        # Load variant(s) in the same test group
        from backend.database import fetch

        if primary_prompt.ab_test_group:
            query = """
                SELECT * FROM prompts
                WHERE ab_test_group = $1 AND status IN ('active', 'testing')
                  AND id != $2
                ORDER BY traffic_percentage DESC
            """
            rows = await fetch(query, primary_prompt.ab_test_group, primary_prompt.id)

            if rows:
                # Select from variants based on remaining traffic
                remaining = 100 - primary_prompt.traffic_percentage
                variant_hash = (hash_val - primary_prompt.traffic_percentage) * 100 // remaining

                cumulative = 0
                for row in rows:
                    variant = self._row_to_prompt(row)
                    cumulative += variant.traffic_percentage
                    if variant_hash < cumulative:
                        return variant

        return primary_prompt

    def render_prompt(
        self,
        prompt: Prompt,
        context: Dict[str, Any]
    ) -> RenderedPrompt:
        """
        Substitute {{variables}} in prompt template.

        Args:
            prompt: The prompt to render
            context: Variables to substitute

        Returns:
            RenderedPrompt with substituted text
        """
        def substitute(text: str) -> str:
            # Match {{variable}} or {{ variable }}
            pattern = r'\{\{\s*(\w+)\s*\}\}'
            def replacer(match):
                var_name = match.group(1)
                return str(context.get(var_name, match.group(0)))
            return re.sub(pattern, replacer, text)

        return RenderedPrompt(
            prompt=prompt,
            system_prompt=substitute(prompt.system_prompt),
            user_prompt=substitute(prompt.user_prompt_template),
            context=context
        )

    async def create_prompt(
        self,
        name: str,
        slug: str,
        prompt_type: PromptType,
        system_prompt: str,
        user_prompt_template: str,
        description: Optional[str] = None,
        incident_type_id: Optional[UUID] = None,
        output_schema: Optional[Dict] = None,
        model_name: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2000,
        temperature: float = 0.0,
        created_by: Optional[UUID] = None
    ) -> Prompt:
        """Create a new prompt (version 1)."""
        from backend.database import fetch
        import uuid

        prompt_id = uuid.uuid4()

        query = """
            INSERT INTO prompts (
                id, name, slug, description, prompt_type, incident_type_id,
                system_prompt, user_prompt_template, output_schema,
                version, status, model_name, max_tokens, temperature, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING *
        """

        rows = await fetch(
            query,
            prompt_id, name, slug, description, prompt_type.value, incident_type_id,
            system_prompt, user_prompt_template, output_schema,
            1, PromptStatus.DRAFT.value, model_name, max_tokens, temperature, created_by
        )

        return self._row_to_prompt(rows[0])

    async def create_version(
        self,
        prompt_id: UUID,
        updates: Dict[str, Any],
        created_by: Optional[UUID] = None
    ) -> Prompt:
        """
        Create new version of a prompt (immutable versioning).

        Args:
            prompt_id: ID of the prompt to version
            updates: Fields to update in new version
            created_by: User creating the version

        Returns:
            New prompt version
        """
        from backend.database import fetch
        import uuid

        # Load current prompt
        current = await self.get_prompt_by_id(prompt_id)
        if not current:
            raise ValueError(f"Prompt {prompt_id} not found")

        # Get max version for this slug
        version_query = "SELECT MAX(version) as max_v FROM prompts WHERE slug = $1"
        version_rows = await fetch(version_query, current.slug)
        new_version = (version_rows[0]["max_v"] or 0) + 1

        # Create new version
        new_id = uuid.uuid4()
        new_prompt = Prompt(
            id=new_id,
            name=updates.get("name", current.name),
            slug=current.slug,  # Slug stays the same
            description=updates.get("description", current.description),
            prompt_type=current.prompt_type,
            incident_type_id=updates.get("incident_type_id", current.incident_type_id),
            system_prompt=updates.get("system_prompt", current.system_prompt),
            user_prompt_template=updates.get("user_prompt_template", current.user_prompt_template),
            output_schema=updates.get("output_schema", current.output_schema),
            version=new_version,
            parent_version_id=prompt_id,
            status=PromptStatus.DRAFT,
            model_name=updates.get("model_name", current.model_name),
            max_tokens=updates.get("max_tokens", current.max_tokens),
            temperature=updates.get("temperature", current.temperature),
            traffic_percentage=updates.get("traffic_percentage", 100),
            ab_test_group=updates.get("ab_test_group", current.ab_test_group),
            created_by=created_by,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            activated_at=None
        )

        query = """
            INSERT INTO prompts (
                id, name, slug, description, prompt_type, incident_type_id,
                system_prompt, user_prompt_template, output_schema,
                version, parent_version_id, status,
                model_name, max_tokens, temperature,
                traffic_percentage, ab_test_group, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
            RETURNING *
        """

        rows = await fetch(
            query,
            new_prompt.id, new_prompt.name, new_prompt.slug, new_prompt.description,
            new_prompt.prompt_type.value, new_prompt.incident_type_id,
            new_prompt.system_prompt, new_prompt.user_prompt_template, new_prompt.output_schema,
            new_prompt.version, new_prompt.parent_version_id, new_prompt.status.value,
            new_prompt.model_name, new_prompt.max_tokens, new_prompt.temperature,
            new_prompt.traffic_percentage, new_prompt.ab_test_group, new_prompt.created_by
        )

        return self._row_to_prompt(rows[0])

    async def activate_version(self, prompt_id: UUID) -> Prompt:
        """
        Set specific version as active, deactivating others with same slug.

        Args:
            prompt_id: ID of the prompt version to activate

        Returns:
            Activated prompt
        """
        from backend.database import execute, fetch

        # Get the prompt to activate
        prompt = await self.get_prompt_by_id(prompt_id)
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        # Deactivate other versions
        await execute(
            "UPDATE prompts SET status = 'deprecated' WHERE slug = $1 AND status = 'active'",
            prompt.slug
        )

        # Activate this version
        await execute(
            "UPDATE prompts SET status = 'active', activated_at = NOW() WHERE id = $1",
            prompt_id
        )

        # Invalidate cache
        await self.invalidate_cache()

        # Return updated prompt
        rows = await fetch("SELECT * FROM prompts WHERE id = $1", prompt_id)
        return self._row_to_prompt(rows[0])

    async def rollback(self, slug: str) -> Optional[Prompt]:
        """
        Revert to previous active version.

        Args:
            slug: Slug of the prompt to rollback

        Returns:
            Previously active prompt if found
        """
        from backend.database import fetch

        # Find the most recently deprecated version
        query = """
            SELECT * FROM prompts
            WHERE slug = $1 AND status = 'deprecated'
            ORDER BY activated_at DESC NULLS LAST, version DESC
            LIMIT 1
        """
        rows = await fetch(query, slug)

        if not rows:
            logger.warning(f"No previous version to rollback to for {slug}")
            return None

        previous = self._row_to_prompt(rows[0])
        return await self.activate_version(previous.id)

    async def get_version_history(self, slug: str) -> List[Prompt]:
        """Get all versions of a prompt by slug."""
        from backend.database import fetch

        query = """
            SELECT * FROM prompts
            WHERE slug = $1
            ORDER BY version DESC
        """
        rows = await fetch(query, slug)
        return [self._row_to_prompt(row) for row in rows]

    async def record_execution(
        self,
        prompt_id: UUID,
        result: ExecutionResult,
        article_id: Optional[UUID] = None,
        incident_id: Optional[UUID] = None
    ):
        """
        Track execution for analytics.

        Args:
            prompt_id: ID of the executed prompt
            result: Execution result
            article_id: Optional associated article
            incident_id: Optional associated incident
        """
        from backend.database import execute
        import uuid

        execution_id = uuid.uuid4()

        query = """
            INSERT INTO prompt_executions (
                id, prompt_id, article_id, incident_id,
                input_tokens, output_tokens, latency_ms,
                success, error_message, confidence_score,
                result_data, ab_variant
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """

        await execute(
            query,
            execution_id, prompt_id, article_id, incident_id,
            result.input_tokens, result.output_tokens, result.latency_ms,
            result.success, result.error_message, result.confidence_score,
            result.result_data, result.ab_variant
        )

    async def get_execution_stats(
        self,
        prompt_id: UUID,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get execution statistics for a prompt."""
        from backend.database import fetch

        query = """
            SELECT
                COUNT(*) as total_executions,
                COUNT(*) FILTER (WHERE success) as successful,
                COUNT(*) FILTER (WHERE NOT success) as failed,
                AVG(latency_ms) as avg_latency_ms,
                AVG(input_tokens) as avg_input_tokens,
                AVG(output_tokens) as avg_output_tokens,
                AVG(confidence_score) as avg_confidence
            FROM prompt_executions
            WHERE prompt_id = $1 AND created_at > NOW() - INTERVAL '%s days'
        """ % days

        rows = await fetch(query, prompt_id)

        if rows:
            row = rows[0]
            return {
                "total_executions": row["total_executions"],
                "successful": row["successful"],
                "failed": row["failed"],
                "success_rate": row["successful"] / row["total_executions"] if row["total_executions"] > 0 else 0,
                "avg_latency_ms": float(row["avg_latency_ms"]) if row["avg_latency_ms"] else None,
                "avg_input_tokens": float(row["avg_input_tokens"]) if row["avg_input_tokens"] else None,
                "avg_output_tokens": float(row["avg_output_tokens"]) if row["avg_output_tokens"] else None,
                "avg_confidence": float(row["avg_confidence"]) if row["avg_confidence"] else None,
            }

        return {}

    async def invalidate_cache(self, prompt_id: Optional[UUID] = None):
        """
        Clear cache on prompt updates.

        Args:
            prompt_id: Optional specific prompt to invalidate, or all if None
        """
        if prompt_id:
            # Could implement more targeted invalidation
            # For now, just clear all
            self._cache.clear()
        else:
            self._cache.clear()

        logger.debug("Prompt cache invalidated")

    def _row_to_prompt(self, row: Dict) -> Prompt:
        """Convert database row to Prompt object."""
        return Prompt(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            description=row.get("description"),
            prompt_type=PromptType(row["prompt_type"]),
            incident_type_id=row.get("incident_type_id"),
            system_prompt=row["system_prompt"],
            user_prompt_template=row["user_prompt_template"],
            output_schema=row.get("output_schema"),
            version=row["version"],
            parent_version_id=row.get("parent_version_id"),
            status=PromptStatus(row["status"]),
            model_name=row.get("model_name", "claude-sonnet-4-20250514"),
            max_tokens=row.get("max_tokens", 2000),
            temperature=float(row.get("temperature", 0.0)),
            traffic_percentage=row.get("traffic_percentage", 100),
            ab_test_group=row.get("ab_test_group"),
            created_by=row.get("created_by"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            activated_at=row.get("activated_at"),
        )


# Singleton instance
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """Get the singleton PromptManager instance."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
