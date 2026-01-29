"""
Cross-reference enrichment service.

Two strategies for filling missing incident data:
1. Cross-incident merge: Copy fields from related incidents sharing actors, dates, or locations
2. Targeted LLM re-extraction: Ask Claude to focus on specific missing fields from linked articles
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Fields eligible for enrichment, mapped to their incident table column
ENRICHABLE_FIELDS = {
    "city": {"column": "city", "type": "text"},
    "county": {"column": "address", "type": "text"},  # stored in address if no county column
    "description": {"column": "description", "type": "text"},
    "victim_name": {"column": "victim_name", "type": "text"},
    "outcome_category": {"column": "outcome_category", "type": "text"},
    "outcome_description": {"column": "outcome_detail", "type": "text"},
    "latitude": {"column": "latitude", "type": "numeric"},
    "longitude": {"column": "longitude", "type": "numeric"},
}

# Fields that can be sourced from cross-incident merge
CROSS_INCIDENT_FIELDS = {
    "city", "county", "description", "latitude", "longitude",
    "outcome_category", "outcome_description",
}

# Fields that can be sourced from LLM re-extraction
LLM_REEXTRACT_FIELDS = {
    "city", "description", "victim_name",
    "outcome_category", "outcome_description",
}


@dataclass
class EnrichmentRunResult:
    """Result of an enrichment run."""
    run_id: str
    strategy: str
    total_incidents: int = 0
    incidents_enriched: int = 0
    fields_filled: int = 0
    errors: int = 0
    status: str = "completed"


class EnrichmentService:
    """Service for enriching incidents with missing data."""

    async def run_enrichment(
        self,
        strategy: str,
        params: Dict[str, Any],
        job_id: Optional[uuid.UUID] = None,
        progress_callback=None,
    ) -> EnrichmentRunResult:
        """
        Run an enrichment pass over incidents with missing data.

        Args:
            strategy: 'cross_incident', 'llm_reextract', or 'full' (both)
            params: Configuration including limit, target_fields, auto_apply, min_confidence
            job_id: Optional background job ID for tracking
            progress_callback: Optional async callback(progress, total, message)
        """
        from backend.database import fetch, execute

        run_id = uuid.uuid4()
        limit = params.get("limit", 100)
        target_fields = params.get("target_fields", list(ENRICHABLE_FIELDS.keys()))
        auto_apply = params.get("auto_apply", strategy == "cross_incident")
        min_confidence = params.get("min_confidence", 0.7)

        # Create enrichment run record
        await execute("""
            INSERT INTO enrichment_runs (id, job_id, strategy, params, total_incidents, status)
            VALUES ($1, $2, $3, $4, 0, 'running')
        """, run_id, job_id, strategy, params)

        result = EnrichmentRunResult(run_id=str(run_id), strategy=strategy)

        try:
            # Find candidates
            candidates = await self.find_enrichment_candidates(
                limit=limit, target_fields=target_fields
            )
            result.total_incidents = len(candidates)

            await execute("""
                UPDATE enrichment_runs SET total_incidents = $1 WHERE id = $2
            """, len(candidates), run_id)

            for i, candidate in enumerate(candidates):
                incident_id = candidate["id"]

                if progress_callback:
                    await progress_callback(
                        i, len(candidates),
                        f"Enriching incident {i+1}/{len(candidates)}"
                    )

                try:
                    fields_filled = 0

                    if strategy in ("cross_incident", "full"):
                        fields_filled += await self.enrich_from_related_incidents(
                            incident_id, run_id, target_fields, min_confidence, auto_apply
                        )

                    if strategy in ("llm_reextract", "full"):
                        fields_filled += await self.enrich_from_article_reextraction(
                            incident_id, run_id, target_fields, min_confidence, auto_apply
                        )

                    if fields_filled > 0:
                        result.incidents_enriched += 1
                        result.fields_filled += fields_filled

                except Exception as e:
                    logger.warning(f"Failed to enrich incident {incident_id}: {e}")
                    result.errors += 1

            # Complete the run
            await execute("""
                UPDATE enrichment_runs
                SET incidents_enriched = $1, fields_filled = $2,
                    completed_at = $3, status = 'completed'
                WHERE id = $4
            """, result.incidents_enriched, result.fields_filled, datetime.utcnow(), run_id)

        except Exception as e:
            logger.error(f"Enrichment run {run_id} failed: {e}")
            result.status = "failed"
            await execute("""
                UPDATE enrichment_runs SET status = 'failed', completed_at = $1 WHERE id = $2
            """, datetime.utcnow(), run_id)
            raise

        return result

    def _build_missing_count_expr(self, target_fields: Optional[List[str]] = None):
        """Build SQL expression and validated field list for missing field counting."""
        if not target_fields:
            target_fields = list(ENRICHABLE_FIELDS.keys())

        null_conditions = []
        for field_name in target_fields:
            field_info = ENRICHABLE_FIELDS.get(field_name)
            if field_info:
                col = field_info["column"]
                null_conditions.append(f"CASE WHEN {col} IS NULL THEN 1 ELSE 0 END")

        if not null_conditions:
            return None, target_fields

        return " + ".join(null_conditions), target_fields

    async def find_enrichment_candidates(
        self,
        limit: int = 100,
        offset: int = 0,
        target_fields: Optional[List[str]] = None,
    ) -> List[dict]:
        """
        Find incidents with missing enrichable fields.

        Returns incidents ordered by how many fields are missing (most gaps first).
        """
        from backend.database import fetch

        missing_count_expr, target_fields = self._build_missing_count_expr(target_fields)
        if not missing_count_expr:
            return []

        query = f"""
            SELECT i.id, i.date, i.state, i.city, i.category, i.title, i.description,
                   i.victim_name, i.outcome_category, i.outcome_detail,
                   i.address, i.latitude, i.longitude, i.curation_status,
                   (SELECT COUNT(*) FROM ingested_articles WHERE incident_id = i.id AND content IS NOT NULL) as article_count,
                   (SELECT COUNT(*) FROM incident_actors WHERE incident_id = i.id) as actor_count,
                   ({missing_count_expr}) as missing_count
            FROM incidents i
            WHERE ({missing_count_expr}) > 0
            ORDER BY ({missing_count_expr}) DESC, i.date DESC
            LIMIT $1 OFFSET $2
        """
        rows = await fetch(query, limit, offset)
        return [dict(row) for row in rows]

    async def count_enrichment_candidates(
        self,
        target_fields: Optional[List[str]] = None,
    ) -> int:
        """Count total incidents with missing enrichable fields (for pagination)."""
        from backend.database import fetchval

        missing_count_expr, _ = self._build_missing_count_expr(target_fields)
        if not missing_count_expr:
            return 0

        query = f"""
            SELECT COUNT(*)
            FROM incidents
            WHERE ({missing_count_expr}) > 0
        """
        return await fetchval(query)

    async def enrich_from_related_incidents(
        self,
        incident_id: uuid.UUID,
        run_id: uuid.UUID,
        target_fields: List[str],
        min_confidence: float = 0.7,
        auto_apply: bool = True,
    ) -> int:
        """
        Enrich an incident by copying fields from related incidents.

        Finds related incidents via:
        1. Shared actors (incident_actors table)
        2. Same date + state (co-occurring incidents)
        3. Title/description similarity

        Returns number of fields filled.
        """
        from backend.database import fetch, execute
        from backend.services.duplicate_detection import tokenize, jaccard_similarity

        # Get the incident's current data
        rows = await fetch("""
            SELECT * FROM incidents WHERE id = $1
        """, incident_id)
        if not rows:
            return 0

        incident = dict(rows[0])
        fields_filled = 0

        # Determine which target fields are actually NULL for this incident
        missing_fields = []
        for field_name in target_fields:
            if field_name not in CROSS_INCIDENT_FIELDS:
                continue
            field_info = ENRICHABLE_FIELDS.get(field_name)
            if field_info and incident.get(field_info["column"]) is None:
                missing_fields.append(field_name)

        if not missing_fields:
            return 0

        # Strategy 1: Find incidents with shared actors
        related_from_actors = await fetch("""
            SELECT DISTINCT i.*
            FROM incidents i
            JOIN incident_actors ia1 ON i.id = ia1.incident_id
            WHERE ia1.actor_id IN (
                SELECT actor_id FROM incident_actors WHERE incident_id = $1
            )
            AND i.id != $1
            AND i.curation_status = 'approved'
            LIMIT 10
        """, incident_id)

        for related in related_from_actors:
            related_dict = dict(related)
            for field_name in list(missing_fields):
                field_info = ENRICHABLE_FIELDS[field_name]
                col = field_info["column"]
                value = related_dict.get(col)
                if value is not None:
                    confidence = 0.8  # High confidence for actor-linked incidents
                    filled = await self._record_and_apply(
                        run_id=run_id,
                        incident_id=incident_id,
                        field_name=field_name,
                        old_value=None,
                        new_value=str(value),
                        source_type="cross_incident",
                        source_incident_id=related_dict["id"],
                        confidence=confidence,
                        auto_apply=auto_apply and confidence >= min_confidence,
                    )
                    if filled:
                        fields_filled += 1
                        missing_fields.remove(field_name)

        if not missing_fields:
            return fields_filled

        # Strategy 2: Same date + state
        if incident.get("date") and incident.get("state"):
            related_from_date_state = await fetch("""
                SELECT * FROM incidents
                WHERE date = $1 AND state = $2
                  AND id != $3
                  AND curation_status = 'approved'
                LIMIT 10
            """, incident["date"], incident["state"], incident_id)

            for related in related_from_date_state:
                related_dict = dict(related)
                for field_name in list(missing_fields):
                    field_info = ENRICHABLE_FIELDS[field_name]
                    col = field_info["column"]
                    value = related_dict.get(col)
                    if value is not None:
                        # Lower confidence for date+state match
                        confidence = 0.6
                        # Boost if same city
                        if (incident.get("city") and related_dict.get("city")
                                and incident["city"] == related_dict["city"]):
                            confidence = 0.75

                        filled = await self._record_and_apply(
                            run_id=run_id,
                            incident_id=incident_id,
                            field_name=field_name,
                            old_value=None,
                            new_value=str(value),
                            source_type="cross_incident",
                            source_incident_id=related_dict["id"],
                            confidence=confidence,
                            auto_apply=auto_apply and confidence >= min_confidence,
                        )
                        if filled:
                            fields_filled += 1
                            missing_fields.remove(field_name)

        if not missing_fields:
            return fields_filled

        # Strategy 3: Title/description similarity
        if incident.get("title") or incident.get("description"):
            search_text = incident.get("title", "") or incident.get("description", "")
            search_tokens = tokenize(search_text)

            if search_tokens:
                # Get recent incidents in same state for comparison
                comparison_pool = await fetch("""
                    SELECT * FROM incidents
                    WHERE state = $1
                      AND id != $2
                      AND curation_status = 'approved'
                      AND (title IS NOT NULL OR description IS NOT NULL)
                    ORDER BY date DESC
                    LIMIT 50
                """, incident.get("state", "Unknown"), incident_id)

                for related in comparison_pool:
                    related_dict = dict(related)
                    related_text = related_dict.get("title", "") or related_dict.get("description", "")
                    related_tokens = tokenize(related_text)

                    if not related_tokens:
                        continue

                    similarity = jaccard_similarity(search_tokens, related_tokens)
                    if similarity < 0.3:
                        continue

                    for field_name in list(missing_fields):
                        field_info = ENRICHABLE_FIELDS[field_name]
                        col = field_info["column"]
                        value = related_dict.get(col)
                        if value is not None:
                            confidence = min(0.9, similarity)
                            filled = await self._record_and_apply(
                                run_id=run_id,
                                incident_id=incident_id,
                                field_name=field_name,
                                old_value=None,
                                new_value=str(value),
                                source_type="cross_incident",
                                source_incident_id=related_dict["id"],
                                confidence=confidence,
                                auto_apply=auto_apply and confidence >= min_confidence,
                            )
                            if filled:
                                fields_filled += 1
                                missing_fields.remove(field_name)

                    if not missing_fields:
                        break

        return fields_filled

    async def enrich_from_article_reextraction(
        self,
        incident_id: uuid.UUID,
        run_id: uuid.UUID,
        target_fields: List[str],
        min_confidence: float = 0.7,
        auto_apply: bool = False,
    ) -> int:
        """
        Re-extract specific missing fields from linked articles using LLM.

        Returns number of fields filled.
        """
        import asyncio
        from backend.database import fetch, execute

        # Get incident and its linked articles
        rows = await fetch("""
            SELECT * FROM incidents WHERE id = $1
        """, incident_id)
        if not rows:
            return 0

        incident = dict(rows[0])

        # Find missing fields eligible for LLM re-extraction
        missing_fields = []
        for field_name in target_fields:
            if field_name not in LLM_REEXTRACT_FIELDS:
                continue
            field_info = ENRICHABLE_FIELDS.get(field_name)
            if field_info and incident.get(field_info["column"]) is None:
                missing_fields.append(field_name)

        if not missing_fields:
            return 0

        # Get linked articles
        articles = await fetch("""
            SELECT id, title, content
            FROM ingested_articles
            WHERE incident_id = $1
              AND content IS NOT NULL
              AND LENGTH(content) > 100
            ORDER BY published_date DESC
            LIMIT 3
        """, incident_id)

        if not articles:
            return 0

        # Build focused extraction prompt
        fields_description = self._build_fields_description(missing_fields)

        fields_filled = 0

        for article in articles:
            article_text = f"{article['title']}\n\n{article['content']}" if article['title'] else article['content']

            try:
                extracted = await self._focused_llm_extract(
                    article_text, missing_fields, fields_description
                )

                if not extracted:
                    continue

                for field_result in extracted:
                    fname = field_result.get("name")
                    fvalue = field_result.get("value")
                    fconfidence = float(field_result.get("confidence", 0))

                    if fname not in missing_fields or not fvalue:
                        continue
                    if fconfidence < min_confidence:
                        continue

                    filled = await self._record_and_apply(
                        run_id=run_id,
                        incident_id=incident_id,
                        field_name=fname,
                        old_value=None,
                        new_value=str(fvalue),
                        source_type="llm_reextract",
                        source_article_id=article["id"],
                        confidence=fconfidence,
                        auto_apply=auto_apply and fconfidence >= min_confidence,
                    )
                    if filled:
                        fields_filled += 1
                        missing_fields.remove(fname)

                if not missing_fields:
                    break

                # Rate limit between LLM calls
                await asyncio.sleep(2)

            except Exception as e:
                logger.warning(f"LLM re-extraction failed for article {article['id']}: {e}")

        return fields_filled

    async def apply_enrichment(self, enrichment_log_id: uuid.UUID) -> bool:
        """Apply a specific enrichment log entry to the incident."""
        from backend.database import fetch, execute

        rows = await fetch("""
            SELECT * FROM enrichment_log WHERE id = $1
        """, enrichment_log_id)
        if not rows:
            return False

        log_entry = dict(rows[0])
        if log_entry["applied"]:
            return True  # Already applied
        if log_entry["reverted"]:
            return False  # Was reverted, don't re-apply without explicit action

        field_info = ENRICHABLE_FIELDS.get(log_entry["field_name"])
        if not field_info:
            return False

        col = field_info["column"]

        # Only apply if field is still NULL (don't overwrite)
        check = await fetch(f"""
            SELECT {col} FROM incidents WHERE id = $1
        """, log_entry["incident_id"])
        if check and check[0][col] is not None:
            return False

        await execute(f"""
            UPDATE incidents SET {col} = $1 WHERE id = $2
        """, log_entry["new_value"], log_entry["incident_id"])

        await execute("""
            UPDATE enrichment_log SET applied = TRUE WHERE id = $1
        """, enrichment_log_id)

        return True

    async def revert_enrichment(self, enrichment_log_id: uuid.UUID) -> bool:
        """Revert a specific enrichment."""
        from backend.database import fetch, execute

        rows = await fetch("""
            SELECT * FROM enrichment_log WHERE id = $1
        """, enrichment_log_id)
        if not rows:
            return False

        log_entry = dict(rows[0])
        if not log_entry["applied"]:
            return False  # Nothing to revert
        if log_entry["reverted"]:
            return True  # Already reverted

        field_info = ENRICHABLE_FIELDS.get(log_entry["field_name"])
        if not field_info:
            return False

        col = field_info["column"]

        # Restore old value (NULL for enrichments that filled empty fields)
        if log_entry["old_value"] is None:
            await execute(f"""
                UPDATE incidents SET {col} = NULL WHERE id = $1
            """, log_entry["incident_id"])
        else:
            await execute(f"""
                UPDATE incidents SET {col} = $1 WHERE id = $2
            """, log_entry["old_value"], log_entry["incident_id"])

        await execute("""
            UPDATE enrichment_log SET reverted = TRUE, applied = FALSE WHERE id = $1
        """, enrichment_log_id)

        return True

    async def get_enrichment_stats(self) -> dict:
        """Get statistics about missing fields and enrichment potential."""
        from backend.database import fetch, fetchval

        total = await fetchval("SELECT COUNT(*) FROM incidents")

        field_gaps = {}
        for field_name, field_info in ENRICHABLE_FIELDS.items():
            col = field_info["column"]
            count = await fetchval(f"SELECT COUNT(*) FROM incidents WHERE {col} IS NULL")
            field_gaps[field_name] = count

        # Count incidents with linked articles (candidates for LLM re-extraction)
        with_articles = await fetchval("""
            SELECT COUNT(DISTINCT incident_id)
            FROM ingested_articles
            WHERE incident_id IS NOT NULL AND content IS NOT NULL
        """)

        # Count incidents with linked actors (candidates for cross-incident)
        with_actors = await fetchval("""
            SELECT COUNT(DISTINCT incident_id)
            FROM incident_actors
        """)

        # Recent enrichment stats
        recent_runs = await fetch("""
            SELECT strategy, SUM(incidents_enriched) as enriched, SUM(fields_filled) as filled
            FROM enrichment_runs
            WHERE status = 'completed' AND started_at > NOW() - INTERVAL '30 days'
            GROUP BY strategy
        """)

        return {
            "total_incidents": total,
            "field_gaps": field_gaps,
            "total_missing_fields": sum(field_gaps.values()),
            "incidents_with_articles": with_articles,
            "incidents_with_actors": with_actors,
            "recent_enrichments": {
                row["strategy"]: {
                    "incidents_enriched": row["enriched"],
                    "fields_filled": row["filled"],
                }
                for row in recent_runs
            },
        }

    async def get_run_history(self, limit: int = 20) -> List[dict]:
        """Get enrichment run history."""
        from backend.database import fetch

        rows = await fetch("""
            SELECT id, job_id, strategy, params, total_incidents,
                   incidents_enriched, fields_filled, started_at, completed_at, status
            FROM enrichment_runs
            ORDER BY started_at DESC
            LIMIT $1
        """, limit)

        runs = []
        for row in rows:
            run = dict(row)
            run["id"] = str(run["id"])
            if run.get("job_id"):
                run["job_id"] = str(run["job_id"])
            for ts_field in ("started_at", "completed_at"):
                if run.get(ts_field):
                    run[ts_field] = run[ts_field].isoformat()
            runs.append(run)

        return runs

    async def get_incident_enrichment_log(
        self, incident_id: uuid.UUID, limit: int = 50
    ) -> List[dict]:
        """Get enrichment audit log for a specific incident."""
        from backend.database import fetch

        rows = await fetch("""
            SELECT el.*, er.strategy as run_strategy
            FROM enrichment_log el
            JOIN enrichment_runs er ON el.run_id = er.id
            WHERE el.incident_id = $1
            ORDER BY el.created_at DESC
            LIMIT $2
        """, incident_id, limit)

        entries = []
        for row in rows:
            entry = dict(row)
            for uid_field in ("id", "run_id", "incident_id", "source_incident_id", "source_article_id"):
                if entry.get(uid_field):
                    entry[uid_field] = str(entry[uid_field])
            if entry.get("created_at"):
                entry["created_at"] = entry["created_at"].isoformat()
            if entry.get("confidence"):
                entry["confidence"] = float(entry["confidence"])
            entries.append(entry)

        return entries

    # --- Private helpers ---

    async def _record_and_apply(
        self,
        run_id: uuid.UUID,
        incident_id: uuid.UUID,
        field_name: str,
        old_value: Optional[str],
        new_value: str,
        source_type: str,
        confidence: float,
        auto_apply: bool,
        source_incident_id: Optional[uuid.UUID] = None,
        source_article_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Record an enrichment log entry and optionally apply it."""
        from backend.database import execute, fetch

        log_id = uuid.uuid4()

        await execute("""
            INSERT INTO enrichment_log (
                id, run_id, incident_id, field_name, old_value, new_value,
                source_type, source_incident_id, source_article_id,
                confidence, applied
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, FALSE)
        """,
            log_id, run_id, incident_id, field_name, old_value, new_value,
            source_type, source_incident_id, source_article_id,
            Decimal(str(confidence)),
        )

        if auto_apply:
            return await self.apply_enrichment(log_id)

        return True  # Recorded (not applied)

    def _build_fields_description(self, missing_fields: List[str]) -> str:
        """Build a human-readable description of fields to extract."""
        descriptions = {
            "city": "City where the incident occurred",
            "description": "A detailed description of what happened",
            "victim_name": "Name of the victim(s) involved",
            "outcome_category": "Outcome category (one of: death, injury, arrest, detention, deportation, release, acquittal, other)",
            "outcome_description": "Detailed description of the outcome",
        }
        lines = []
        for f in missing_fields:
            desc = descriptions.get(f, f)
            lines.append(f"- {f}: {desc}")
        return "\n".join(lines)

    async def _focused_llm_extract(
        self,
        article_text: str,
        missing_fields: List[str],
        fields_description: str,
    ) -> Optional[List[dict]]:
        """Use LLM to extract specific missing fields from article text."""
        import json

        try:
            from backend.services import get_extractor
            extractor = get_extractor()
            if not extractor or not extractor.client:
                logger.warning("LLM extractor not available for re-extraction")
                return None
        except Exception:
            logger.warning("Could not get LLM extractor")
            return None

        prompt = f"""You previously extracted data from this article. Some fields are missing.
Re-read the article and try to extract ONLY these missing fields:

{fields_description}

For each field, provide the value and your confidence (0.0-1.0).
Only include fields you can actually find evidence for in the text.

Return JSON: {{"fields": [{{"name": "...", "value": "...", "confidence": 0.0, "evidence": "..."}}]}}

Article text:
{article_text[:8000]}"""

        try:
            response = extractor.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text

            # Parse JSON from response
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            parsed = json.loads(content.strip())
            return parsed.get("fields", [])

        except Exception as e:
            logger.warning(f"Focused LLM extraction failed: {e}")
            return None


# Singleton
_enrichment_service: Optional[EnrichmentService] = None


def get_enrichment_service() -> EnrichmentService:
    """Get the singleton EnrichmentService instance."""
    global _enrichment_service
    if _enrichment_service is None:
        _enrichment_service = EnrichmentService()
    return _enrichment_service
