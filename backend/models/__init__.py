"""
Pydantic models for the Incident Tracker API.
"""

from .incident import (
    IncidentCategory,
    SourceTier,
    CurationStatus,
    IncidentScale,
    OutcomeCategory,
    VictimCategory,
    IncidentBase,
    IncidentCreate,
    IncidentUpdate,
    Incident,
    IncidentSummary,
    IncidentFilters,
)
from .person import (
    PersonRole,
    PersonBase,
    PersonCreate,
    PersonUpdate,
    Person,
    IncidentPerson,
)
from .jurisdiction import (
    JurisdictionType,
    JurisdictionBase,
    JurisdictionCreate,
    Jurisdiction,
    JurisdictionStats,
)
from .source import (
    SourceBase,
    SourceCreate,
    Source,
)
from .curation import (
    IngestedArticle,
    CurationQueueItem,
    CurationDecision,
    ExtractionResult,
)

__all__ = [
    # Incident
    "IncidentCategory",
    "SourceTier",
    "CurationStatus",
    "IncidentScale",
    "OutcomeCategory",
    "VictimCategory",
    "IncidentBase",
    "IncidentCreate",
    "IncidentUpdate",
    "Incident",
    "IncidentSummary",
    "IncidentFilters",
    # Person
    "PersonRole",
    "PersonBase",
    "PersonCreate",
    "PersonUpdate",
    "Person",
    "IncidentPerson",
    # Jurisdiction
    "JurisdictionType",
    "JurisdictionBase",
    "JurisdictionCreate",
    "Jurisdiction",
    "JurisdictionStats",
    # Source
    "SourceBase",
    "SourceCreate",
    "Source",
    # Curation
    "IngestedArticle",
    "CurationQueueItem",
    "CurationDecision",
    "ExtractionResult",
]
