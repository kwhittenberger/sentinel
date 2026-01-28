"""
Person models for victims and offenders.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class PersonRole(str, Enum):
    """Role of person in an incident."""
    VICTIM = "victim"
    OFFENDER = "offender"
    WITNESS = "witness"
    OFFICER = "officer"


class PersonBase(BaseModel):
    """Base person fields."""
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    age: Optional[int] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None

    # Immigration status
    immigration_status: Optional[str] = None
    prior_deportations: int = 0
    reentry_after_deportation: bool = False
    visa_type: Optional[str] = None
    visa_overstay: bool = False

    # Criminal history (offenders)
    gang_affiliated: bool = False
    gang_name: Optional[str] = None
    prior_convictions: int = 0
    prior_violent_convictions: int = 0

    # Victim info
    us_citizen: Optional[bool] = None
    occupation: Optional[str] = None


class PersonCreate(PersonBase):
    """Model for creating a new person."""
    external_ids: Optional[dict] = None


class PersonUpdate(BaseModel):
    """Model for updating a person. All fields optional."""
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    age: Optional[int] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None

    immigration_status: Optional[str] = None
    prior_deportations: Optional[int] = None
    reentry_after_deportation: Optional[bool] = None
    visa_type: Optional[str] = None
    visa_overstay: Optional[bool] = None

    gang_affiliated: Optional[bool] = None
    gang_name: Optional[str] = None
    prior_convictions: Optional[int] = None
    prior_violent_convictions: Optional[int] = None

    us_citizen: Optional[bool] = None
    occupation: Optional[str] = None

    external_ids: Optional[dict] = None


class Person(PersonBase):
    """Full person model returned from database."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_ids: Optional[dict] = None

    created_at: datetime
    updated_at: datetime


class IncidentPerson(BaseModel):
    """Link between incident and person with role."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    person_id: UUID
    role: PersonRole
    notes: Optional[str] = None

    created_at: datetime

    # Populated when joining
    person: Optional[Person] = None
