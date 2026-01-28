"""
Auto-approval service for evaluating articles.
Supports category-specific approval thresholds for enforcement vs crime incidents.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Literal

logger = logging.getLogger(__name__)

IncidentCategory = Literal['enforcement', 'crime']


@dataclass
class ApprovalConfig:
    """Configuration for auto-approval rules."""
    # Confidence thresholds
    min_confidence_auto_approve: float = 0.85
    min_confidence_review: float = 0.5
    auto_reject_below: float = 0.3

    # Required fields for auto-approval
    required_fields: List[str] = field(default_factory=lambda: [
        'date', 'state', 'incident_type'
    ])

    # Field confidence thresholds
    field_confidence_threshold: float = 0.7

    # Crime severity thresholds
    min_severity_auto_approve: int = 5
    max_severity_auto_reject: int = 2

    # Source reliability
    min_source_reliability: float = 0.6

    # Enable/disable auto-actions
    enable_auto_approve: bool = True
    enable_auto_reject: bool = True


@dataclass
class EnforcementApprovalConfig(ApprovalConfig):
    """Category-specific config for enforcement incidents (higher scrutiny)."""
    min_confidence_auto_approve: float = 0.90  # Higher threshold for enforcement
    required_fields: List[str] = field(default_factory=lambda: [
        'date', 'state', 'incident_type', 'victim_category', 'outcome_category'
    ])
    field_confidence_threshold: float = 0.75


@dataclass
class CrimeApprovalConfig(ApprovalConfig):
    """Category-specific config for crime incidents (standard threshold)."""
    min_confidence_auto_approve: float = 0.85
    required_fields: List[str] = field(default_factory=lambda: [
        'date', 'state', 'incident_type', 'offender_immigration_status'
    ])
    field_confidence_threshold: float = 0.70


# Default configurations
DEFAULT_CONFIG = ApprovalConfig()
ENFORCEMENT_CONFIG = EnforcementApprovalConfig()
CRIME_CONFIG = CrimeApprovalConfig()


@dataclass
class ApprovalDecision:
    """Result of auto-approval evaluation."""
    decision: str  # 'auto_approve', 'auto_reject', 'needs_review'
    confidence: float
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


# Crime type severity mapping
CRIME_SEVERITY = {
    'homicide': 10,
    'murder': 10,
    'sexual_assault': 9,
    'human_trafficking': 9,
    'kidnapping': 8,
    'dui_fatality': 8,
    'assault': 6,
    'robbery': 5,
    'drug_trafficking': 5,
    'gang_activity': 5,
    'other': 3,
}


def get_crime_severity(incident_type: str) -> int:
    """Get severity score for an incident type."""
    if not incident_type:
        return 0
    incident_type = incident_type.lower()
    for crime, severity in CRIME_SEVERITY.items():
        if crime in incident_type:
            return severity
    return 3  # Default


class AutoApprovalService:
    """Service for evaluating articles for auto-approval."""

    def __init__(self, config: ApprovalConfig = None):
        self.config = config or DEFAULT_CONFIG
        self._category_configs: Dict[str, ApprovalConfig] = {
            'enforcement': ENFORCEMENT_CONFIG,
            'crime': CRIME_CONFIG,
        }

    def get_config_for_category(self, category: Optional[str]) -> ApprovalConfig:
        """Get the appropriate config for a category."""
        if category and category in self._category_configs:
            return self._category_configs[category]
        return self.config

    def evaluate(
        self,
        article: dict,
        extraction_result: Optional[dict] = None,
        category: Optional[str] = None
    ) -> ApprovalDecision:
        """
        Evaluate an article for auto-approval.

        Args:
            article: The article/incident data
            extraction_result: LLM extraction result if available
            category: Optional incident category (enforcement or crime)

        Returns:
            ApprovalDecision with decision and reasoning
        """
        details = {}

        # Get extraction data
        extracted = extraction_result or article.get('extracted_data') or {}
        confidence = extracted.get('overall_confidence', 0.0)
        details['extraction_confidence'] = confidence

        # Determine category and get appropriate config
        detected_category = category or extracted.get('category') or article.get('category')
        config = self.get_config_for_category(detected_category)
        details['category'] = detected_category
        details['config_used'] = detected_category or 'default'

        # Check if below reject threshold
        if confidence < config.auto_reject_below:
            if config.enable_auto_reject:
                return ApprovalDecision(
                    decision='auto_reject',
                    confidence=confidence,
                    reason=f'Extraction confidence ({confidence:.0%}) below threshold',
                    details=details
                )

        # Check required fields for this category
        missing_fields = []
        for field_name in config.required_fields:
            value = extracted.get(field_name) or article.get(field_name)
            if not value:
                missing_fields.append(field_name)

        if missing_fields:
            details['missing_fields'] = missing_fields
            return ApprovalDecision(
                decision='needs_review',
                confidence=confidence,
                reason=f'Missing required fields for {detected_category or "incident"}: {", ".join(missing_fields)}',
                details=details
            )

        # Check field-level confidence
        field_confidence = extracted.get('field_confidence', {})
        low_confidence_fields = []
        for field_name in config.required_fields:
            fc = field_confidence.get(field_name, extracted.get(f'{field_name}_confidence', 1.0))
            if fc < config.field_confidence_threshold:
                low_confidence_fields.append(f'{field_name} ({fc:.0%})')

        if low_confidence_fields:
            details['low_confidence_fields'] = low_confidence_fields
            return ApprovalDecision(
                decision='needs_review',
                confidence=confidence,
                reason=f'Low confidence on fields: {", ".join(low_confidence_fields)}',
                details=details
            )

        # Check crime severity
        incident_type = extracted.get('incident_type') or article.get('incident_type', '')
        severity = get_crime_severity(incident_type)
        details['severity'] = severity

        if severity < config.max_severity_auto_reject:
            if config.enable_auto_reject:
                return ApprovalDecision(
                    decision='auto_reject',
                    confidence=confidence,
                    reason=f'Crime severity ({severity}) too low',
                    details=details
                )

        # Check overall confidence for auto-approve (using category-specific threshold)
        if confidence >= config.min_confidence_auto_approve:
            if severity >= config.min_severity_auto_approve:
                if config.enable_auto_approve:
                    return ApprovalDecision(
                        decision='auto_approve',
                        confidence=confidence,
                        reason=f'High confidence ({confidence:.0%}) and severity ({severity}) for {detected_category or "incident"}',
                        details=details
                    )

        # Check if confidence is high enough for review
        if confidence >= config.min_confidence_review:
            return ApprovalDecision(
                decision='needs_review',
                confidence=confidence,
                reason=f'Moderate confidence ({confidence:.0%}), requires human review',
                details=details
            )

        # Default: needs review
        return ApprovalDecision(
            decision='needs_review',
            confidence=confidence,
            reason='Evaluation complete, requires human review',
            details=details
        )

    def get_config(self) -> dict:
        """Get current configuration as dict."""
        return {
            'min_confidence_auto_approve': self.config.min_confidence_auto_approve,
            'min_confidence_review': self.config.min_confidence_review,
            'auto_reject_below': self.config.auto_reject_below,
            'required_fields': self.config.required_fields,
            'field_confidence_threshold': self.config.field_confidence_threshold,
            'min_severity_auto_approve': self.config.min_severity_auto_approve,
            'max_severity_auto_reject': self.config.max_severity_auto_reject,
            'enable_auto_approve': self.config.enable_auto_approve,
            'enable_auto_reject': self.config.enable_auto_reject,
            'category_configs': {
                'enforcement': {
                    'min_confidence_auto_approve': ENFORCEMENT_CONFIG.min_confidence_auto_approve,
                    'required_fields': ENFORCEMENT_CONFIG.required_fields,
                    'field_confidence_threshold': ENFORCEMENT_CONFIG.field_confidence_threshold,
                },
                'crime': {
                    'min_confidence_auto_approve': CRIME_CONFIG.min_confidence_auto_approve,
                    'required_fields': CRIME_CONFIG.required_fields,
                    'field_confidence_threshold': CRIME_CONFIG.field_confidence_threshold,
                },
            }
        }

    def update_config(self, updates: dict):
        """Update configuration values."""
        for key, value in updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)


# Singleton instance
_service: Optional[AutoApprovalService] = None


def get_auto_approval_service() -> AutoApprovalService:
    """Get the singleton auto-approval service instance."""
    global _service
    if _service is None:
        _service = AutoApprovalService()
    return _service
