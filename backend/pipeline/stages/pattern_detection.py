"""
Pattern detection stage - detects patterns and clusters in incidents.
"""

import logging
from typing import Dict, Any

from backend.services.pipeline_orchestrator import (
    PipelineStage,
    PipelineContext,
    StageExecutionResult,
    StageResult,
)

logger = logging.getLogger(__name__)


class PatternDetectionStage(PipelineStage):
    """Detect patterns and clusters related to the current article."""

    slug = "pattern_detection"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Detect patterns related to this article.

        Config options:
        - check_temporal: Check for temporal clustering (default: True)
        - check_geographic: Check for geographic clustering (default: True)
        - check_actor: Check for actor patterns (default: True)
        - lookback_days: Days to look back for patterns (default: 30)
        """
        if not context.extracted_data:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No extracted data"}
            )

        patterns = []
        check_temporal = config.get("check_temporal", True)
        check_geographic = config.get("check_geographic", True)
        check_actor = config.get("check_actor", True)
        lookback_days = config.get("lookback_days", 30)

        data = context.extracted_data
        incident_date = data.get("date")
        state = data.get("state")
        city = data.get("city")

        from backend.database import fetch

        # Temporal clustering - same date or close dates
        if check_temporal and incident_date:
            query = """
                SELECT COUNT(*) as count, array_agg(id) as ids
                FROM incidents
                WHERE date BETWEEN ($1::date - INTERVAL '%s days') AND ($1::date + INTERVAL '1 day')
                  AND category = $2
                  AND curation_status = 'approved'
            """ % lookback_days

            rows = await fetch(query, incident_date, context.detected_category or 'enforcement')

            if rows and rows[0]["count"] > 2:
                patterns.append({
                    "type": "temporal_cluster",
                    "description": f"{rows[0]['count']} incidents in {lookback_days} day period",
                    "incident_count": rows[0]["count"],
                    "incident_ids": [str(id) for id in (rows[0]["ids"] or [])][:10],
                    "confidence": min(0.9, 0.5 + (rows[0]["count"] * 0.05))
                })

        # Geographic clustering - same state/city
        if check_geographic and state:
            if city:
                query = """
                    SELECT COUNT(*) as count, array_agg(id) as ids
                    FROM incidents
                    WHERE state = $1 AND city = $2
                      AND date >= (NOW() - INTERVAL '%s days')
                      AND curation_status = 'approved'
                """ % lookback_days
                rows = await fetch(query, state, city)
            else:
                query = """
                    SELECT COUNT(*) as count, array_agg(id) as ids
                    FROM incidents
                    WHERE state = $1
                      AND date >= (NOW() - INTERVAL '%s days')
                      AND curation_status = 'approved'
                """ % lookback_days
                rows = await fetch(query, state)

            if rows and rows[0]["count"] > 3:
                location = f"{city}, {state}" if city else state
                patterns.append({
                    "type": "geographic_cluster",
                    "description": f"{rows[0]['count']} incidents in {location}",
                    "location": location,
                    "incident_count": rows[0]["count"],
                    "incident_ids": [str(id) for id in (rows[0]["ids"] or [])][:10],
                    "confidence": min(0.9, 0.4 + (rows[0]["count"] * 0.05))
                })

        # Actor patterns - same offender/victim appearing
        if check_actor and context.detected_actors:
            for actor in context.detected_actors:
                if actor.get("actor_id"):
                    query = """
                        SELECT COUNT(DISTINCT ia.incident_id) as count,
                               array_agg(DISTINCT ia.incident_id) as ids
                        FROM incident_actors ia
                        JOIN incidents i ON ia.incident_id = i.id
                        WHERE ia.actor_id = $1
                          AND i.curation_status = 'approved'
                    """
                    rows = await fetch(query, actor["actor_id"])

                    if rows and rows[0]["count"] > 1:
                        patterns.append({
                            "type": "actor_pattern",
                            "description": f"Actor {actor.get('canonical_name', actor['extracted_name'])} appears in {rows[0]['count']} incidents",
                            "actor_id": actor["actor_id"],
                            "actor_name": actor.get("canonical_name", actor["extracted_name"]),
                            "role": actor["role"],
                            "incident_count": rows[0]["count"],
                            "incident_ids": [str(id) for id in (rows[0]["ids"] or [])][:10],
                            "confidence": 0.8
                        })

        context.detected_relations.extend([
            {"type": "pattern", **p} for p in patterns
        ])

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "patterns_detected": len(patterns),
                "patterns": patterns
            }
        )
