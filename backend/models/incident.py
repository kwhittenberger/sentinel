"""
Incident models for the Unified Incident Tracker.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class IncidentCategory(str, Enum):
    """Discriminator for incident type."""
    ENFORCEMENT = "enforcement"
    CRIME = "crime"


class SourceTier(str, Enum):
    """Source tier for confidence scoring."""
    TIER_1 = "1"
    TIER_2 = "2"
    TIER_3 = "3"
    TIER_4 = "4"


class CurationStatus(str, Enum):
    """Curation workflow status."""
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class IncidentScale(str, Enum):
    """Incident scale."""
    SINGLE = "single"  # 1 affected
    SMALL = "small"    # 2-5 affected
    MEDIUM = "medium"  # 6-50 affected
    LARGE = "large"    # 51-200 affected
    MASS = "mass"      # 200+ affected


class OutcomeCategory(str, Enum):
    """Outcome category."""
    DEATH = "death"
    SERIOUS_INJURY = "serious_injury"
    MINOR_INJURY = "minor_injury"
    NO_INJURY = "no_injury"
    UNKNOWN = "unknown"


class VictimCategory(str, Enum):
    """Victim category for enforcement incidents."""
    DETAINEE = "detainee"
    ENFORCEMENT_TARGET = "enforcement_target"
    PROTESTER = "protester"
    JOURNALIST = "journalist"
    BYSTANDER = "bystander"
    US_CITIZEN_COLLATERAL = "us_citizen_collateral"
    OFFICER = "officer"
    MULTIPLE = "multiple"


class IncidentBase(BaseModel):
    """Base incident fields for creation and update."""
    category: IncidentCategory
    date: date
    date_precision: str = "day"
    incident_type: str

    # Location
    state: str
    city: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Details
    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None

    # Scale and outcome
    affected_count: int = 1
    incident_scale: IncidentScale = IncidentScale.SINGLE
    outcome: Optional[str] = None
    outcome_category: Optional[OutcomeCategory] = None
    outcome_detail: Optional[str] = None

    # Victim info (enforcement)
    victim_category: Optional[VictimCategory] = None
    victim_name: Optional[str] = None
    victim_age: Optional[int] = None
    us_citizen: Optional[bool] = None
    protest_related: bool = False

    # Source tracking
    source_tier: SourceTier
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    verified: bool = False

    # Sanctuary policy context
    state_sanctuary_status: Optional[str] = None
    local_sanctuary_status: Optional[str] = None
    detainer_policy: Optional[str] = None

    # Crime-specific
    offender_immigration_status: Optional[str] = None
    prior_deportations: int = 0
    gang_affiliated: bool = False


class IncidentCreate(IncidentBase):
    """Model for creating a new incident."""
    legacy_id: Optional[str] = None
    jurisdiction_id: Optional[UUID] = None
    incident_type_id: Optional[UUID] = None
    primary_source_id: Optional[UUID] = None


class IncidentUpdate(BaseModel):
    """Model for updating an incident. All fields optional."""
    category: Optional[IncidentCategory] = None
    date: Optional[date] = None
    date_precision: Optional[str] = None
    incident_type: Optional[str] = None

    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None

    affected_count: Optional[int] = None
    incident_scale: Optional[IncidentScale] = None
    outcome: Optional[str] = None
    outcome_category: Optional[OutcomeCategory] = None
    outcome_detail: Optional[str] = None

    victim_category: Optional[VictimCategory] = None
    victim_name: Optional[str] = None
    victim_age: Optional[int] = None
    us_citizen: Optional[bool] = None
    protest_related: Optional[bool] = None

    source_tier: Optional[SourceTier] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    verified: Optional[bool] = None

    state_sanctuary_status: Optional[str] = None
    local_sanctuary_status: Optional[str] = None
    detainer_policy: Optional[str] = None

    offender_immigration_status: Optional[str] = None
    prior_deportations: Optional[int] = None
    gang_affiliated: Optional[bool] = None

    curation_status: Optional[CurationStatus] = None


class Incident(IncidentBase):
    """Full incident model returned from database."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legacy_id: Optional[str] = None
    jurisdiction_id: Optional[UUID] = None
    incident_type_id: Optional[UUID] = None
    primary_source_id: Optional[UUID] = None

    curation_status: CurationStatus = CurationStatus.APPROVED
    extraction_confidence: Optional[float] = None
    curated_by: Optional[UUID] = None
    curated_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    # Computed fields
    is_non_immigrant: Optional[bool] = None
    is_death: Optional[bool] = None
    severity_score: Optional[float] = None
    linked_ids: Optional[List[str]] = None


class IncidentSummary(BaseModel):
    """Lightweight incident summary for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legacy_id: Optional[str] = None
    category: IncidentCategory
    date: date
    state: str
    city: Optional[str] = None
    incident_type: str
    victim_category: Optional[VictimCategory] = None
    victim_name: Optional[str] = None
    outcome_category: Optional[OutcomeCategory] = None
    source_tier: SourceTier
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_non_immigrant: Optional[bool] = None
    is_death: Optional[bool] = None
    severity_score: Optional[float] = None


class IncidentFilters(BaseModel):
    """Filter parameters for incident queries."""
    category: Optional[IncidentCategory] = None
    tiers: Optional[List[str]] = None
    states: Optional[List[str]] = None
    categories: Optional[List[str]] = None  # victim_category
    incident_types: Optional[List[str]] = None
    non_immigrant_only: bool = False
    death_only: bool = False
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    curation_status: Optional[CurationStatus] = None
    min_severity: Optional[float] = None
    search: Optional[str] = None

    # Crime-specific filters
    gang_affiliated: Optional[bool] = None
    prior_deportations_min: Optional[int] = None
