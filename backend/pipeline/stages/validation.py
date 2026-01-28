"""
Validation stage - validates extracted data against type-specific rules.
"""

import logging
import re
from datetime import datetime, date
from typing import Dict, Any, List

from backend.services.pipeline_orchestrator import (
    PipelineStage,
    PipelineContext,
    StageExecutionResult,
    StageResult,
)

logger = logging.getLogger(__name__)


class ValidationStage(PipelineStage):
    """Validate extracted data against rules."""

    slug = "validation"

    # US state codes
    US_STATES = {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
        'DC', 'PR', 'VI', 'GU', 'AS', 'MP'
    }

    async def execute(
        self,
        context: PipelineContext,
        config: Dict[str, Any]
    ) -> StageExecutionResult:
        """
        Validate extracted data.

        Config options:
        - strict_mode: Reject on any validation error (default: False)
        - required_fields: List of required fields (default: from type config)
        """
        if not context.extracted_data:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.CONTINUE,
                data={"skipped": True, "reason": "No extracted data"}
            )

        errors = []
        warnings = []
        data = context.extracted_data

        # Get required fields from type config or config
        required_fields = config.get("required_fields")
        if not required_fields and context.incident_type_id:
            from backend.services.incident_type_service import get_incident_type_service
            type_service = get_incident_type_service()
            required_fields = await type_service.get_required_fields(context.incident_type_id)

        # Default required fields if none specified
        if not required_fields:
            required_fields = ["date", "state", "incident_type"]

        # Check required fields
        for field in required_fields:
            value = data.get(field)
            if not value:
                errors.append(f"Missing required field: {field}")

        # Validate date
        if data.get("date"):
            date_str = data["date"]
            try:
                # Try parsing YYYY-MM-DD
                incident_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                # Check date is reasonable
                today = date.today()
                if incident_date > today:
                    errors.append(f"Date {date_str} is in the future")
                elif (today - incident_date).days > 365 * 10:
                    warnings.append(f"Date {date_str} is more than 10 years ago")
            except ValueError:
                # Try other formats
                parsed = False
                for fmt in ["%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%B %d, %Y"]:
                    try:
                        incident_date = datetime.strptime(date_str, fmt).date()
                        # Normalize to ISO format
                        data["date"] = incident_date.isoformat()
                        parsed = True
                        break
                    except ValueError:
                        continue

                if not parsed:
                    errors.append(f"Invalid date format: {date_str}")

        # Validate state
        if data.get("state"):
            state = data["state"].upper()
            if len(state) == 2:
                if state not in self.US_STATES:
                    errors.append(f"Invalid state code: {state}")
                else:
                    data["state"] = state  # Normalize to uppercase
            else:
                # Try to find state code from name
                state_names = {
                    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
                    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
                    'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
                    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
                    'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
                    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS',
                    'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
                    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
                    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK',
                    'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
                    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
                    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
                    'wisconsin': 'WI', 'wyoming': 'WY', 'district of columbia': 'DC',
                    'puerto rico': 'PR', 'virgin islands': 'VI'
                }
                state_code = state_names.get(state.lower())
                if state_code:
                    data["state"] = state_code
                else:
                    warnings.append(f"Could not normalize state: {state}")

        # Validate confidence scores
        for key, value in data.items():
            if key.endswith("_confidence") and value is not None:
                try:
                    conf = float(value)
                    if conf < 0 or conf > 1:
                        warnings.append(f"Confidence {key}={value} out of range [0,1]")
                        data[key] = max(0, min(1, conf))
                except (TypeError, ValueError):
                    warnings.append(f"Invalid confidence value: {key}={value}")

        # Validate age if present
        for age_field in ["victim_age", "offender_age"]:
            if data.get(age_field) is not None:
                try:
                    age = int(data[age_field])
                    if age < 0 or age > 150:
                        errors.append(f"Invalid {age_field}: {age}")
                except (TypeError, ValueError):
                    errors.append(f"Invalid {age_field}: {data[age_field]}")

        # Validate prior deportations
        if data.get("prior_deportations") is not None:
            try:
                deport = int(data["prior_deportations"])
                if deport < 0:
                    errors.append(f"Invalid prior_deportations: {deport}")
            except (TypeError, ValueError):
                errors.append(f"Invalid prior_deportations: {data['prior_deportations']}")

        # Store validation results
        context.validation_errors = errors
        context.extracted_data = data  # Update with normalized data

        strict_mode = config.get("strict_mode", False)

        if errors and strict_mode:
            return StageExecutionResult(
                stage_slug=self.slug,
                result=StageResult.REJECT,
                data={
                    "valid": False,
                    "errors": errors,
                    "warnings": warnings,
                    "reason": f"Validation failed: {', '.join(errors)}"
                }
            )

        return StageExecutionResult(
            stage_slug=self.slug,
            result=StageResult.CONTINUE,
            data={
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings
            }
        )
