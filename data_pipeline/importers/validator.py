"""
Schema validation for incident data.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

from ..sources.base import Incident
from ..config import STATE_ABBREVS, INCIDENT_TYPE_KEYWORDS

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a validation error."""
    field: str
    message: str
    severity: str  # "error", "warning", "info"
    incident_id: Optional[str] = None


@dataclass
class ValidationResult:
    """Results of validation."""
    valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    info: List[ValidationError]

    @property
    def all_issues(self) -> List[ValidationError]:
        return self.errors + self.warnings + self.info


class SchemaValidator:
    """Validate incident data against schema."""

    REQUIRED_FIELDS = ["date", "state", "incident_type"]

    VALID_INCIDENT_TYPES = [
        "death_in_custody",
        "shooting_by_agent",
        "shooting_at_agent",
        "less_lethal",
        "physical_force",
        "wrongful_detention",
        "wrongful_deportation",
        "mass_raid",
        "enforcement_action",
        "protest_related",
        "other",
    ]

    VALID_OUTCOMES = [
        "death",
        "injury",
        "arrest",
        "detention",
        "deportation",
        "release",
        "unknown",
    ]

    VALID_VICTIM_CATEGORIES = [
        "detainee",
        "enforcement_target",
        "protester",
        "journalist",
        "bystander",
        "us_citizen_collateral",
        "officer",
        "multiple",
    ]

    VALID_SCALES = ["single", "small", "medium", "large", "mass"]

    def validate(self, incident: Incident) -> ValidationResult:
        """Validate a single incident."""
        errors = []
        warnings = []
        info = []

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            value = getattr(incident, field, None)
            if not value:
                errors.append(ValidationError(
                    field=field,
                    message=f"Required field '{field}' is missing or empty",
                    severity="error",
                    incident_id=incident.id,
                ))

        # Validate date format
        if incident.date:
            if not self._is_valid_date(incident.date):
                errors.append(ValidationError(
                    field="date",
                    message=f"Invalid date format: {incident.date}. Expected YYYY-MM-DD",
                    severity="error",
                    incident_id=incident.id,
                ))
            elif self._is_future_date(incident.date):
                warnings.append(ValidationError(
                    field="date",
                    message=f"Date is in the future: {incident.date}",
                    severity="warning",
                    incident_id=incident.id,
                ))

        # Validate state
        if incident.state and incident.state not in STATE_ABBREVS and incident.state != "Unknown":
            warnings.append(ValidationError(
                field="state",
                message=f"Unknown state: {incident.state}",
                severity="warning",
                incident_id=incident.id,
            ))

        # Validate incident type
        if incident.incident_type and incident.incident_type not in self.VALID_INCIDENT_TYPES:
            warnings.append(ValidationError(
                field="incident_type",
                message=f"Non-standard incident type: {incident.incident_type}",
                severity="warning",
                incident_id=incident.id,
            ))

        # Validate outcome
        if incident.outcome_category and incident.outcome_category not in self.VALID_OUTCOMES:
            info.append(ValidationError(
                field="outcome_category",
                message=f"Non-standard outcome: {incident.outcome_category}",
                severity="info",
                incident_id=incident.id,
            ))

        # Validate victim category
        if incident.victim_category and incident.victim_category not in self.VALID_VICTIM_CATEGORIES:
            info.append(ValidationError(
                field="victim_category",
                message=f"Non-standard victim category: {incident.victim_category}",
                severity="info",
                incident_id=incident.id,
            ))

        # Validate scale
        if incident.incident_scale and incident.incident_scale not in self.VALID_SCALES:
            warnings.append(ValidationError(
                field="incident_scale",
                message=f"Invalid scale: {incident.incident_scale}",
                severity="warning",
                incident_id=incident.id,
            ))

        # Validate affected count matches scale
        if incident.affected_count and incident.incident_scale:
            expected_scale = self._get_expected_scale(incident.affected_count)
            if incident.incident_scale != expected_scale:
                info.append(ValidationError(
                    field="incident_scale",
                    message=f"Scale '{incident.incident_scale}' may not match count {incident.affected_count} (expected '{expected_scale}')",
                    severity="info",
                    incident_id=incident.id,
                ))

        # Validate tier
        if incident.tier not in [1, 2, 3, 4]:
            errors.append(ValidationError(
                field="tier",
                message=f"Invalid tier: {incident.tier}. Must be 1-4",
                severity="error",
                incident_id=incident.id,
            ))

        # Validate age if present
        if incident.victim_age is not None:
            if not (0 <= incident.victim_age <= 120):
                warnings.append(ValidationError(
                    field="victim_age",
                    message=f"Unusual age value: {incident.victim_age}",
                    severity="warning",
                    incident_id=incident.id,
                ))

        # Check for source info
        if not incident.source_url and not incident.source_name:
            warnings.append(ValidationError(
                field="source",
                message="No source URL or source name provided",
                severity="warning",
                incident_id=incident.id,
            ))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            info=info,
        )

    def validate_batch(self, incidents: List[Incident]) -> Tuple[List[Incident], List[ValidationResult]]:
        """Validate a batch of incidents. Returns (valid_incidents, all_results)."""
        valid = []
        results = []

        for incident in incidents:
            result = self.validate(incident)
            results.append(result)
            if result.valid:
                valid.append(incident)

        # Summary logging
        total = len(incidents)
        valid_count = len(valid)
        error_count = sum(len(r.errors) for r in results)
        warning_count = sum(len(r.warnings) for r in results)

        logger.info(f"Validation: {valid_count}/{total} valid, {error_count} errors, {warning_count} warnings")

        return valid, results

    def _is_valid_date(self, date_str: str) -> bool:
        """Check if date is valid ISO format."""
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _is_future_date(self, date_str: str) -> bool:
        """Check if date is in the future."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt > datetime.now()
        except ValueError:
            return False

    def _get_expected_scale(self, count: int) -> str:
        """Get expected scale for affected count."""
        if count == 1:
            return "single"
        elif count <= 5:
            return "small"
        elif count <= 50:
            return "medium"
        elif count <= 200:
            return "large"
        else:
            return "mass"


def validate_incidents(incidents: List[Incident]) -> Tuple[List[Incident], List[ValidationResult]]:
    """Convenience function to validate incidents."""
    validator = SchemaValidator()
    return validator.validate_batch(incidents)
