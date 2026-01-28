"""
Entity resolution stage - matches and creates actors from extracted data.
"""

import logging
from typing import Dict, Any, List, Optional

from backend.services.pipeline_orchestrator import (
    PipelineStage,
    PipelineContext,
    StageExecutionResult,
    StageResult,
)

logger = logging.getLogger(__name__)


class EntityResolutionStage(PipelineStage):
    """Match extracted entities to existing actors or create new ones."""

    slug = "entity_resolution"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Resolve extracted entities to actors.

        Config options:
        - auto_create: Automatically create new actors (default: False)
        - match_threshold: Similarity threshold for matching (default: 0.8)
        - categories: Entity categories to process (default: all)
        """
        from backend.services.actor_service import get_actor_service, ActorType

        if not context.extracted_data:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No extracted data"}
            )

        actor_service = get_actor_service()
        auto_create = config.get("auto_create", False)
        match_threshold = config.get("match_threshold", 0.8)

        detected_actors = []
        created_count = 0
        matched_count = 0

        # Extract person entities from different categories
        entities_to_process = []

        # Victim (for enforcement incidents)
        if context.extracted_data.get("victim_name"):
            entities_to_process.append({
                "name": context.extracted_data["victim_name"],
                "role": "victim",
                "type": ActorType.PERSON,
                "age": context.extracted_data.get("victim_age"),
            })

        # Offender (for crime incidents)
        if context.extracted_data.get("offender_name"):
            entities_to_process.append({
                "name": context.extracted_data["offender_name"],
                "role": "offender",
                "type": ActorType.PERSON,
                "age": context.extracted_data.get("offender_age"),
                "nationality": context.extracted_data.get("offender_nationality"),
                "immigration_status": context.extracted_data.get("offender_immigration_status"),
                "prior_deportations": context.extracted_data.get("prior_deportations", 0),
            })

        # Agency
        if context.extracted_data.get("agency"):
            agency_name = context.extracted_data["agency"]
            entities_to_process.append({
                "name": agency_name,
                "role": "arresting_agency" if context.detected_category == "crime" else "reporting_agency",
                "type": ActorType.AGENCY,
                "is_law_enforcement": True,
                "is_government_entity": True,
            })

        # Process each entity
        for entity in entities_to_process:
            name = entity.get("name")
            if not name or len(name) < 2:
                continue

            # Try to find existing actor
            matches = await actor_service.search_actors(
                name,
                actor_type=entity["type"],
                limit=5
            )

            best_match = None
            best_similarity = 0.0

            for match in matches:
                # Calculate similarity (simple for now)
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, name.lower(), match.canonical_name.lower()).ratio()

                # Also check aliases
                for alias in match.aliases:
                    alias_sim = SequenceMatcher(None, name.lower(), alias.lower()).ratio()
                    similarity = max(similarity, alias_sim)

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = match

            if best_match and best_similarity >= match_threshold:
                # Found a match
                detected_actors.append({
                    "actor_id": str(best_match.id),
                    "canonical_name": best_match.canonical_name,
                    "extracted_name": name,
                    "role": entity["role"],
                    "match_type": "existing",
                    "similarity": best_similarity,
                    "confidence": best_similarity
                })
                matched_count += 1
            elif auto_create:
                # Create new actor
                try:
                    new_actor = await actor_service.create_actor(
                        canonical_name=name,
                        actor_type=entity["type"],
                        date_of_birth=None,
                        gender=entity.get("gender"),
                        nationality=entity.get("nationality"),
                        immigration_status=entity.get("immigration_status"),
                        prior_deportations=entity.get("prior_deportations", 0),
                        is_law_enforcement=entity.get("is_law_enforcement", False),
                        is_government_entity=entity.get("is_government_entity", False),
                        confidence_score=0.7  # New entity confidence
                    )

                    detected_actors.append({
                        "actor_id": str(new_actor.id),
                        "canonical_name": new_actor.canonical_name,
                        "extracted_name": name,
                        "role": entity["role"],
                        "match_type": "created",
                        "confidence": 0.7
                    })
                    created_count += 1

                except Exception as e:
                    logger.error(f"Failed to create actor {name}: {e}")
                    detected_actors.append({
                        "actor_id": None,
                        "extracted_name": name,
                        "role": entity["role"],
                        "match_type": "pending",
                        "error": str(e)
                    })
            else:
                # Queue for manual review
                detected_actors.append({
                    "actor_id": None,
                    "extracted_name": name,
                    "role": entity["role"],
                    "match_type": "pending",
                    "best_match": {
                        "id": str(best_match.id) if best_match else None,
                        "name": best_match.canonical_name if best_match else None,
                        "similarity": best_similarity
                    } if best_match else None
                })

        context.detected_actors = detected_actors

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "detected_actors": detected_actors,
                "matched_count": matched_count,
                "created_count": created_count,
                "pending_count": len([a for a in detected_actors if a["match_type"] == "pending"])
            }
        )
