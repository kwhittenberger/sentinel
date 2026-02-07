"""
Auto-approval service for evaluating articles.
Supports category-specific approval thresholds for enforcement vs crime incidents.
Now integrates with IncidentTypeService for database-backed thresholds when available.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Literal
from uuid import UUID

logger = logging.getLogger(__name__)

IncidentCategory = Literal['enforcement', 'crime']

# Import IncidentTypeService for database-backed thresholds (optional)
try:
    from .incident_type_service import get_incident_type_service, IncidentTypeService
    INCIDENT_TYPE_SERVICE_AVAILABLE = True
except ImportError:
    INCIDENT_TYPE_SERVICE_AVAILABLE = False
    IncidentTypeService = None


@dataclass
class ApprovalConfig:
    """Configuration for auto-approval rules."""
    # Confidence thresholds
    min_confidence_auto_approve: float = 0.85
    min_confidence_review: float = 0.5
    auto_reject_below: float = 0.3

    # Required fields for auto-approval (minimal universal set — the LLM
    # confidence score already incorporates schema-specific field completeness)
    required_fields: List[str] = field(default_factory=lambda: [
        'date', 'state'
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
    # Enforcement actions (ICE raids, arrests) aren't "crimes" — severity gate
    # from the crime severity map doesn't meaningfully apply
    min_severity_auto_approve: int = 1


@dataclass
class CrimeApprovalConfig(ApprovalConfig):
    """Category-specific config for crime incidents (standard threshold)."""
    min_confidence_auto_approve: float = 0.85
    required_fields: List[str] = field(default_factory=lambda: [
        'date', 'state', 'incident_type'
    ])
    field_confidence_threshold: float = 0.70


@dataclass
class DomainApprovalConfig(ApprovalConfig):
    """Config for extensible domain categories (Criminal Justice, Civil Rights, etc.).

    Uses minimal universal required fields since each schema defines its own
    field set — the LLM confidence score (which already blends field completeness)
    is the primary quality gate.  Severity thresholds are effectively disabled
    because CJ/CR incident types (arrest, prosecution, protest) don't map to
    the crime severity scale.
    """
    min_confidence_auto_approve: float = 0.85
    required_fields: List[str] = field(default_factory=lambda: [
        'date', 'state'
    ])
    field_confidence_threshold: float = 0.70
    min_severity_auto_approve: int = 0
    max_severity_auto_reject: int = 0  # disable severity-based rejection


# Default configurations
DEFAULT_CONFIG = ApprovalConfig()
ENFORCEMENT_CONFIG = EnforcementApprovalConfig()
CRIME_CONFIG = CrimeApprovalConfig()
_CJ_CONFIG = DomainApprovalConfig()
_CR_CONFIG = DomainApprovalConfig()


@dataclass
class ApprovalDecision:
    """Result of auto-approval evaluation."""
    decision: str  # 'auto_approve', 'auto_reject', 'needs_review'
    confidence: float
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


# Crime type severity mapping — substring-matched against incident_type
CRIME_SEVERITY = {
    'homicide': 10,
    'murder': 10,
    'manslaughter': 9,
    'sexual_assault': 9,
    'human_trafficking': 9,
    'kidnapping': 8,
    'dui_fatality': 8,
    'death_in_custody': 8,
    'death': 8,
    'fatal': 8,
    'shooting': 7,
    'stabbing': 7,
    'arson': 7,
    'carjacking': 6,
    'assault': 6,
    'battery': 6,
    'robbery': 5,
    'drug_trafficking': 5,
    'gang_activity': 5,
    'burglary': 5,
    'home_invasion': 5,
    'theft': 5,
    'fraud': 5,
    'dui': 5,
    'detention': 5,
    'arrest': 5,
    'deportation': 5,
    'raid': 5,
    'search': 5,
    'warrant': 5,
    'illegal_reentry': 5,
    'illegal_entry': 5,
    'unlawful_entry': 5,
    'physical_force': 6,
    'protest_clash': 4,
    'property_damage': 4,
    'raid_injury': 6,
    'identity_fraud': 5,
    'document_fraud': 5,
    'other': 3,
}


def normalize_extracted_fields(extracted: dict) -> dict:
    """
    Normalize stage2 extraction data so required-field checks work
    regardless of schema structure.

    Handles:
    - location.state / location.city → flat state / city
    - Missing incident_type → infer from charges, violation_type, case_type, etc.
    - overall_confidence / confidence normalization
    """
    if not extracted or not isinstance(extracted, dict):
        return extracted or {}
    # Work on a shallow copy to avoid mutating the original
    extracted = dict(extracted)

    # Flatten nested location
    location = extracted.get('location')
    if isinstance(location, dict):
        if not extracted.get('state') and location.get('state'):
            extracted['state'] = location['state']
        if not extracted.get('city') and location.get('city'):
            extracted['city'] = location['city']

    # Infer incident_type from alternative fields
    if not extracted.get('incident_type'):
        # Try charges list — use first charge as incident_type
        charges = extracted.get('charges')
        if isinstance(charges, list) and charges:
            extracted['incident_type'] = charges[0] if isinstance(charges[0], str) else str(charges[0])
        # Try violation_type, case_type, event_type
        elif extracted.get('violation_type'):
            extracted['incident_type'] = extracted['violation_type']
        elif extracted.get('case_type'):
            extracted['incident_type'] = extracted['case_type']
        elif extracted.get('event_type'):
            extracted['incident_type'] = extracted['event_type']

    # Normalize immigration_status field naming: some schemas use
    # 'immigration_status' while CrimeApprovalConfig requires 'offender_immigration_status'
    if not extracted.get('offender_immigration_status') and extracted.get('immigration_status'):
        extracted['offender_immigration_status'] = extracted['immigration_status']

    # Normalize confidence: ensure overall_confidence is set
    if extracted.get('overall_confidence') is None and extracted.get('confidence') is not None:
        extracted['overall_confidence'] = extracted['confidence']

    return extracted


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

    def __init__(self, config: ApprovalConfig = None, use_db_thresholds: bool = True):
        self.config = config or DEFAULT_CONFIG
        self.use_db_thresholds = use_db_thresholds and INCIDENT_TYPE_SERVICE_AVAILABLE
        self._category_configs: Dict[str, ApprovalConfig] = {
            'enforcement': ENFORCEMENT_CONFIG,
            'crime': CRIME_CONFIG,
            # Criminal Justice domain categories
            'arrest': _CJ_CONFIG,
            'prosecution': _CJ_CONFIG,
            'trial': _CJ_CONFIG,
            'sentencing': _CJ_CONFIG,
            'incarceration': _CJ_CONFIG,
            'release': _CJ_CONFIG,
            # Civil Rights domain categories
            'protest': _CR_CONFIG,
            'police_force': _CR_CONFIG,
            'civil_rights_violation': _CR_CONFIG,
            'litigation': _CR_CONFIG,
        }
        self._db_pool = None
        self._type_service: Optional[IncidentTypeService] = None
        self._type_threshold_cache: Dict[str, ApprovalConfig] = {}

    def set_db_pool(self, pool):
        """Set database pool for IncidentTypeService integration."""
        self._db_pool = pool
        if self.use_db_thresholds and INCIDENT_TYPE_SERVICE_AVAILABLE:
            self._type_service = get_incident_type_service()

    async def load_category_configs_from_db(self):
        """Load required_fields from event_categories and override hardcoded configs.

        Called once at startup (after DB pool is available) to let database
        schema definitions drive the approval required-fields checks.
        """
        try:
            from backend.database import fetch
            rows = await fetch("""
                SELECT ec.slug as category_slug, ed.slug as domain_slug,
                       ec.required_fields
                FROM event_categories ec
                JOIN event_domains ed ON ec.domain_id = ed.id
                WHERE ec.is_active = TRUE
            """)
            loaded = 0
            for row in rows:
                cat_slug = row['category_slug']
                domain_slug = row['domain_slug']
                db_fields = row.get('required_fields') or []
                if not db_fields:
                    continue  # empty — keep hardcoded fallback

                # Choose the right base config class for thresholds
                if domain_slug == 'immigration' and cat_slug == 'enforcement':
                    base = EnforcementApprovalConfig
                elif domain_slug == 'immigration' and cat_slug == 'crime':
                    base = CrimeApprovalConfig
                else:
                    base = DomainApprovalConfig

                # Create a config with DB-driven required_fields
                config = base(required_fields=list(db_fields))
                self._category_configs[cat_slug] = config
                loaded += 1

            logger.info(
                "Loaded required_fields from DB for %d categories", loaded
            )
        except Exception as e:
            logger.warning(
                "Failed to load category configs from DB, using hardcoded: %s", e
            )

    async def _get_db_config_for_type(self, incident_type_id: UUID) -> Optional[ApprovalConfig]:
        """Get approval config from database for a specific incident type."""
        if not self._type_service:
            return None

        cache_key = str(incident_type_id)
        if cache_key in self._type_threshold_cache:
            return self._type_threshold_cache[cache_key]

        try:
            thresholds = await self._type_service.get_approval_thresholds(incident_type_id)
            if thresholds:
                config = ApprovalConfig(
                    min_confidence_auto_approve=thresholds.get('min_confidence_auto_approve', 0.85),
                    min_confidence_review=thresholds.get('min_confidence_review', 0.5),
                    auto_reject_below=thresholds.get('auto_reject_below', 0.3),
                    required_fields=thresholds.get('required_fields', ['date', 'state', 'incident_type']),
                    field_confidence_threshold=thresholds.get('field_confidence_threshold', 0.7),
                    min_severity_auto_approve=thresholds.get('min_severity_auto_approve', 5),
                    max_severity_auto_reject=thresholds.get('max_severity_auto_reject', 2),
                    enable_auto_approve=thresholds.get('enable_auto_approve', True),
                    enable_auto_reject=thresholds.get('enable_auto_reject', True),
                )
                self._type_threshold_cache[cache_key] = config
                return config
        except Exception as e:
            logger.warning(f"Failed to get thresholds from database: {e}")

        return None

    def get_config_for_category(self, category: Optional[str]) -> ApprovalConfig:
        """Get the appropriate config for a category."""
        if category and category in self._category_configs:
            return self._category_configs[category]
        return self.config

    async def get_config_for_type_async(
        self,
        incident_type_id: Optional[UUID] = None,
        category: Optional[str] = None
    ) -> ApprovalConfig:
        """Get config, preferring database-backed thresholds if available."""
        # First try database config for specific type
        if incident_type_id and self._type_service:
            db_config = await self._get_db_config_for_type(incident_type_id)
            if db_config:
                return db_config

        # Fall back to category-based config
        return self.get_config_for_category(category)

    async def evaluate_async(
        self,
        article: dict,
        extraction_result: Optional[dict] = None,
        category: Optional[str] = None,
        incident_type_id: Optional[UUID] = None,
    ) -> ApprovalDecision:
        """
        Async version that can use database-backed thresholds.

        Args:
            article: The article/incident data
            extraction_result: LLM extraction result if available
            category: Optional incident category
            incident_type_id: Optional incident type ID for type-specific thresholds

        Returns:
            ApprovalDecision with decision and reasoning
        """
        details = {}

        # Get extraction data
        extracted = extraction_result or article.get('extracted_data') or {}
        confidence = extracted.get('overall_confidence', extracted.get('confidence', 0.0))
        details['extraction_confidence'] = confidence

        # Determine category
        detected_category = category or extracted.get('category') or article.get('category')
        details['category'] = detected_category

        # Get config (prefer database-backed if available)
        config = await self.get_config_for_type_async(incident_type_id, detected_category)
        details['config_source'] = 'database' if incident_type_id and self._type_service else 'static'
        details['config_used'] = str(incident_type_id) if incident_type_id else (detected_category or 'default')

        # Delegate to common evaluation logic
        return self._evaluate_with_config(article, extracted, confidence, config, details)

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
        confidence = extracted.get('overall_confidence', extracted.get('confidence', 0.0))
        details['extraction_confidence'] = confidence

        # Determine category and get appropriate config
        detected_category = category or extracted.get('category') or article.get('category')
        config = self.get_config_for_category(detected_category)
        details['category'] = detected_category
        details['config_used'] = detected_category or 'default'
        details['config_source'] = 'static'

        return self._evaluate_with_config(article, extracted, confidence, config, details)

    def _evaluate_with_config(
        self,
        article: dict,
        extracted: dict,
        confidence: float,
        config: ApprovalConfig,
        details: dict,
    ) -> ApprovalDecision:
        """Common evaluation logic used by both sync and async methods."""
        # Normalize nested fields (location.state, missing incident_type, etc.)
        extracted = normalize_extracted_fields(extracted)
        raw_conf = extracted.get('overall_confidence', extracted.get('confidence', confidence))
        try:
            confidence = float(raw_conf)
        except (TypeError, ValueError):
            pass  # keep original confidence

        detected_category = details.get('category')

        # Check if article is marked as not relevant
        is_relevant = extracted.get('is_relevant', True)
        if not is_relevant:
            if config.enable_auto_reject:
                return ApprovalDecision(
                    decision='auto_reject',
                    confidence=confidence,
                    reason='Article marked as not relevant to immigration enforcement or immigrant crimes',
                    details={**details, 'is_relevant': False}
                )

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
            value = extracted.get(field_name)
            if value is None or value == '':
                value = article.get(field_name)
            if value is None or value == '':
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
            fc = field_confidence.get(field_name, extracted.get(f'{field_name}_confidence', 0.0))
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
