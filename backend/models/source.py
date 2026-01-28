"""
Source models for news outlets and government sources.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .incident import SourceTier


class SourceBase(BaseModel):
    """Base source fields."""
    name: str
    source_type: str  # government, news, investigative, social_media
    tier: SourceTier
    url: Optional[str] = None
    description: Optional[str] = None
    reliability_score: Optional[float] = None  # 0.00 to 1.00
    is_active: bool = True

    # Fetcher configuration
    fetcher_class: Optional[str] = None
    fetcher_config: Optional[dict] = None
    cache_hours: int = 24


class SourceCreate(SourceBase):
    """Model for creating a source."""
    pass


class Source(SourceBase):
    """Full source model from database."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class IncidentSource(BaseModel):
    """Link between incident and source."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    source_id: Optional[UUID] = None

    url: Optional[str] = None
    title: Optional[str] = None
    published_date: Optional[datetime] = None
    archived_url: Optional[str] = None
    is_primary: bool = False

    created_at: datetime

    # Populated when joining
    source: Optional[Source] = None
