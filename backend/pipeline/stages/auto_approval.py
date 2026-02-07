"""
Auto-approval stage - evaluates whether an article can be automatically approved.
"""

import logging
from typing import Dict, Any

from backend.services.pipeline_orchestrator import (
    PipelineStage,
    PipelineContext,
    StageExecutionResult,
    StageResult,
)
from backend.services.thresholds import (
    AUTO_APPROVE_CONFIDENCE,
    REVIEW_CONFIDENCE,
    AUTO_REJECT_CONFIDENCE,
    FIELD_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


class AutoApprovalStage(PipelineStage):
    """Evaluate extracted data for automatic approval."""

    slug = "auto_approval"

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Evaluate for auto-approval based on type-specific thresholds.

        Config options:
        - enable_auto_approve: Enable auto-approval (default: True)
        - enable_auto_reject: Enable auto-rejection (default: True)
        - min_confidence_auto_approve: Threshold for auto-approve (default: from type)
        - min_confidence_review: Threshold for review (default: from type)
        - auto_reject_below: Threshold for auto-reject (default: from type)
        """
        if not context.extracted_data:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "decision": "needs_review",
                    "reason": "No extracted data"
                }
            )

        # Get thresholds from type config or stage config
        thresholds = await self._get_thresholds(context.incident_type_id, config)

        enable_auto_approve = config.get("enable_auto_approve", True)
        enable_auto_reject = config.get("enable_auto_reject", True)

        data = context.extracted_data
        confidence = data.get("overall_confidence", 0.0)

        # Check for auto-reject
        if enable_auto_reject and confidence < thresholds["auto_reject_below"]:
            context.final_decision = "auto_reject"
            context.decision_reason = f"Confidence ({confidence:.0%}) below reject threshold ({thresholds['auto_reject_below']:.0%})"
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "decision": "auto_reject",
                    "confidence": confidence,
                    "threshold": thresholds["auto_reject_below"],
                    "reason": context.decision_reason
                }
            )

        # Check validation errors
        if context.validation_errors:
            context.final_decision = "needs_review"
            context.decision_reason = f"Validation errors: {', '.join(context.validation_errors)}"
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "decision": "needs_review",
                    "confidence": confidence,
                    "validation_errors": context.validation_errors,
                    "reason": context.decision_reason
                }
            )

        # Check field-level confidence
        field_threshold = thresholds.get("field_confidence_threshold", 0.7)
        low_confidence_fields = []

        # Get required fields
        required_fields = thresholds.get("required_fields", ["date", "state", "incident_type"])

        for field in required_fields:
            field_conf_key = f"{field}_confidence"
            field_conf = data.get(field_conf_key, 1.0)

            if field_conf < field_threshold:
                low_confidence_fields.append(f"{field} ({field_conf:.0%})")

        if low_confidence_fields:
            context.final_decision = "needs_review"
            context.decision_reason = f"Low confidence fields: {', '.join(low_confidence_fields)}"
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "decision": "needs_review",
                    "confidence": confidence,
                    "low_confidence_fields": low_confidence_fields,
                    "reason": context.decision_reason
                }
            )

        # Check for auto-approve
        if enable_auto_approve and confidence >= thresholds["min_confidence_auto_approve"]:
            context.final_decision = "auto_approve"
            context.decision_reason = f"High confidence ({confidence:.0%}) above threshold ({thresholds['min_confidence_auto_approve']:.0%})"
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={
                    "decision": "auto_approve",
                    "confidence": confidence,
                    "threshold": thresholds["min_confidence_auto_approve"],
                    "reason": context.decision_reason
                }
            )

        # Default: needs review
        context.final_decision = "needs_review"
        context.decision_reason = f"Moderate confidence ({confidence:.0%}), requires human review"
        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "decision": "needs_review",
                "confidence": confidence,
                "reason": context.decision_reason
            }
        )

    async def _get_thresholds(
        self,
        incident_type_id,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get approval thresholds from type config or defaults."""
        # Default thresholds from centralized constants
        defaults = {
            "min_confidence_auto_approve": AUTO_APPROVE_CONFIDENCE,
            "min_confidence_review": REVIEW_CONFIDENCE,
            "auto_reject_below": AUTO_REJECT_CONFIDENCE,
            "field_confidence_threshold": FIELD_CONFIDENCE_THRESHOLD,
            "required_fields": ["date", "state", "incident_type"]
        }

        # Override with config
        for key in defaults:
            if key in config:
                defaults[key] = config[key]

        # Override with type-specific thresholds
        if incident_type_id:
            try:
                from backend.services.incident_type_service import get_incident_type_service
                type_service = get_incident_type_service()
                incident_type = await type_service.get_type(incident_type_id)

                if incident_type and incident_type.approval_thresholds:
                    for key in defaults:
                        if key in incident_type.approval_thresholds:
                            defaults[key] = incident_type.approval_thresholds[key]

                # Get required fields from type
                required = await type_service.get_required_fields(incident_type_id)
                if required:
                    defaults["required_fields"] = required

            except Exception as e:
                logger.warning(f"Could not load type thresholds: {e}")

        return defaults
