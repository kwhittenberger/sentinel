"""
Jurisdiction models for states, counties, and cities.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JurisdictionType(str, Enum):
    """Type of jurisdiction."""
    STATE = "state"
    COUNTY = "county"
    CITY = "city"


class JurisdictionBase(BaseModel):
    """Base jurisdiction fields."""
    name: str
    jurisdiction_type: JurisdictionType
    state_code: Optional[str] = None
    fips_code: Optional[str] = None
    parent_jurisdiction_id: Optional[UUID] = None

    # Sanctuary policy
    state_sanctuary_status: Optional[str] = None  # sanctuary, anti_sanctuary, neutral
    local_sanctuary_status: Optional[str] = None  # sanctuary, limited_cooperation, cooperative
    detainer_policy: Optional[str] = None
    policy_source_url: Optional[str] = None
    policy_effective_date: Optional[date] = None

    # Geographic data
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class JurisdictionCreate(JurisdictionBase):
    """Model for creating a jurisdiction."""
    pass


class Jurisdiction(JurisdictionBase):
    """Full jurisdiction model from database."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class JurisdictionStats(BaseModel):
    """Jurisdiction with aggregated statistics."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    jurisdiction_type: JurisdictionType
    state_code: Optional[str] = None
    state_sanctuary_status: Optional[str] = None
    local_sanctuary_status: Optional[str] = None

    total_incidents: int = 0
    enforcement_incidents: int = 0
    crime_incidents: int = 0
    deaths: int = 0
    non_immigrant_incidents: int = 0
