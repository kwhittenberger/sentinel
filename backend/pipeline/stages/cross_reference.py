"""
Cross-reference stage - links incidents to events and suggests related incidents.
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


class CrossReferenceStage(PipelineStage):
    """Link incidents to events and find related incidents."""

    slug = "cross_reference"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Find and suggest cross-references.

        Config options:
        - find_events: Look for matching events (default: True)
        - find_related: Find related incidents (default: True)
        - max_suggestions: Max suggestions to return (default: 5)
        """
        if not context.extracted_data:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No extracted data"}
            )

        find_events = config.get("find_events", True)
        find_related = config.get("find_related", True)
        max_suggestions = config.get("max_suggestions", 5)

        suggested_events = []
        suggested_relations = []

        data = context.extracted_data
        incident_date = data.get("date")
        state = data.get("state")
        city = data.get("city")

        from backend.database import fetch

        # Find matching events
        if find_events and incident_date:
            query = """
                SELECT e.*, COUNT(ie.incident_id) as incident_count
                FROM events e
                LEFT JOIN incident_events ie ON e.id = ie.event_id
                WHERE e.start_date <= $1::date
                  AND (e.end_date IS NULL OR e.end_date >= $1::date OR e.ongoing)
                  AND (e.primary_state = $2 OR e.geographic_scope IN ('national', 'regional'))
                GROUP BY e.id
                ORDER BY
                    CASE WHEN e.primary_state = $2 THEN 0 ELSE 1 END,
                    incident_count DESC
                LIMIT $3
            """
            rows = await fetch(query, incident_date, state, max_suggestions)

            for row in rows:
                match_score = 0.5

                # Boost score for matching state
                if row["primary_state"] == state:
                    match_score += 0.2

                # Boost for matching city
                if city and row.get("primary_city") == city:
                    match_score += 0.2

                # Boost for ongoing events
                if row.get("ongoing"):
                    match_score += 0.1

                suggested_events.append({
                    "event_id": str(row["id"]),
                    "event_name": row["name"],
                    "event_type": row.get("event_type"),
                    "start_date": row["start_date"].isoformat() if row["start_date"] else None,
                    "primary_state": row.get("primary_state"),
                    "incident_count": row["incident_count"],
                    "match_score": min(1.0, match_score)
                })

        # Find related incidents
        if find_related:
            # Same date + state
            if incident_date and state:
                query = """
                    SELECT id, date, state, city, category, description
                    FROM incidents
                    WHERE date = $1::date AND state = $2
                      AND curation_status = 'approved'
                    LIMIT $3
                """
                rows = await fetch(query, incident_date, state, max_suggestions)

                for row in rows:
                    suggested_relations.append({
                        "incident_id": str(row["id"]),
                        "relation_type": "same_event",
                        "reason": f"Same date and state ({row['date']}, {row['state']})",
                        "match_score": 0.7,
                        "incident_summary": row.get("description", "")[:100]
                    })

            # Check for actor overlap
            for actor in context.detected_actors:
                if actor.get("actor_id"):
                    query = """
                        SELECT DISTINCT i.id, i.date, i.state, i.city, i.category, i.description, ia.role
                        FROM incidents i
                        JOIN incident_actors ia ON i.id = ia.incident_id
                        WHERE ia.actor_id = $1
                          AND i.curation_status = 'approved'
                        LIMIT $2
                    """
                    rows = await fetch(query, actor["actor_id"], max_suggestions)

                    for row in rows:
                        # Avoid duplicates
                        if not any(r["incident_id"] == str(row["id"]) for r in suggested_relations):
                            suggested_relations.append({
                                "incident_id": str(row["id"]),
                                "relation_type": "involves_same_actor",
                                "reason": f"Same actor ({actor.get('canonical_name', actor['extracted_name'])}) as {actor['role']}",
                                "match_score": 0.8,
                                "actor_id": actor["actor_id"],
                                "incident_summary": row.get("description", "")[:100]
                            })

        # Store in context
        for event in suggested_events:
            context.detected_relations.append({
                "type": "suggested_event",
                **event
            })

        for relation in suggested_relations:
            context.detected_relations.append({
                "type": "suggested_relation",
                **relation
            })

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "suggested_events": suggested_events,
                "suggested_relations": suggested_relations,
                "event_count": len(suggested_events),
                "relation_count": len(suggested_relations)
            }
        )
