"""
Curation models for article ingestion and review workflow.
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .incident import CurationStatus, SourceTier


class IngestedArticle(BaseModel):
    """An article awaiting curation."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: Optional[UUID] = None
    source_name: Optional[str] = None
    source_url: str

    title: Optional[str] = None
    content: Optional[str] = None
    published_date: Optional[date] = None
    fetched_at: datetime

    # Relevance scoring
    relevance_score: Optional[float] = None
    relevance_reason: Optional[str] = None

    # LLM extraction
    extracted_data: Optional[dict] = None
    extraction_confidence: Optional[float] = None
    extracted_at: Optional[datetime] = None

    # Curation workflow
    status: CurationStatus
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # Linked incident
    incident_id: Optional[UUID] = None

    created_at: datetime
    updated_at: datetime


class CurationQueueItem(BaseModel):
    """Lightweight item for the curation queue view."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: Optional[str] = None
    source_name: Optional[str] = None
    source_url: str
    published_date: Optional[date] = None
    relevance_score: Optional[float] = None
    extraction_confidence: Optional[float] = None
    extracted_data: Optional[dict] = None
    status: CurationStatus
    fetched_at: datetime


class CurationDecision(BaseModel):
    """Decision on a queued article."""
    action: str  # "approve" or "reject"
    rejection_reason: Optional[str] = None

    # Overrides for extraction
    incident_overrides: Optional[dict] = None


class ExtractionResult(BaseModel):
    """Result from LLM extraction."""
    success: bool
    confidence: float
    extracted_data: Optional[dict] = None
    error: Optional[str] = None

    # Field-level confidence scores
    field_confidence: Optional[dict] = None


class ExtractedIncident(BaseModel):
    """Structured incident data extracted from an article."""
    # Core fields
    date: Optional[str] = None
    date_confidence: float = 0.0

    state: Optional[str] = None
    state_confidence: float = 0.0

    city: Optional[str] = None
    city_confidence: float = 0.0

    incident_type: Optional[str] = None
    incident_type_confidence: float = 0.0

    # People
    victim_name: Optional[str] = None
    victim_name_confidence: float = 0.0

    victim_age: Optional[int] = None
    victim_age_confidence: float = 0.0

    offender_name: Optional[str] = None
    offender_name_confidence: float = 0.0

    # Details
    description: Optional[str] = None
    outcome: Optional[str] = None

    # Crime-specific
    immigration_status: Optional[str] = None
    prior_deportations: Optional[int] = None
    gang_affiliated: Optional[bool] = None

    # Meta
    overall_confidence: float = 0.0
    extraction_notes: Optional[str] = None
