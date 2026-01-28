"""
Prompts for LLM extraction of incident data from articles.
Supports dual incident categories: enforcement (ICE/CBP actions) and crime (crimes by immigrants).
"""

from typing import Literal

IncidentCategory = Literal['enforcement', 'crime']

# Required fields for each category
ENFORCEMENT_REQUIRED_FIELDS = ['date', 'state', 'incident_type', 'victim_category', 'outcome_category']
CRIME_REQUIRED_FIELDS = ['date', 'state', 'incident_type', 'offender_immigration_status']

# Base output schema for extraction
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {
            "type": "boolean",
            "description": "Whether the article describes an immigration-related incident"
        },
        "relevance_reason": {
            "type": "string",
            "description": "Brief explanation of why the article is or isn't relevant"
        },
        "category": {
            "type": "string",
            "enum": ["enforcement", "crime"],
            "description": "Whether this is an enforcement incident (ICE/CBP action) or a crime by an immigrant"
        },
        "incident": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date of incident (YYYY-MM-DD format)"},
                "date_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "state": {"type": "string", "description": "US state where incident occurred"},
                "state_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "city": {"type": "string", "description": "City where incident occurred"},
                "city_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "incident_type": {
                    "type": "string",
                    "enum": [
                        "death_in_custody", "shooting", "taser", "pepper_spray", "physical_force",
                        "vehicle_pursuit", "raid_injury", "medical_neglect", "wrongful_detention",
                        "property_damage", "protest_clash", "journalist_interference",
                        "homicide", "assault", "robbery", "dui_fatality", "sexual_assault",
                        "kidnapping", "gang_activity", "drug_trafficking", "human_trafficking"
                    ]
                },
                "incident_type_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                # Enforcement-specific fields
                "victim_name": {"type": "string"},
                "victim_name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "victim_age": {"type": "integer"},
                "victim_category": {
                    "type": "string",
                    "enum": ["detainee", "enforcement_target", "protester", "journalist",
                             "bystander", "us_citizen_collateral", "officer", "multiple"],
                    "description": "Category of the victim (for enforcement incidents)"
                },
                "officer_involved": {"type": "boolean", "description": "Whether an officer was involved in causing harm"},
                "agency": {"type": "string", "description": "ICE, CBP, or other agency involved"},
                # Crime-specific fields
                "offender_name": {"type": "string"},
                "offender_name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "offender_age": {"type": "integer"},
                "offender_nationality": {"type": "string"},
                "offender_immigration_status": {
                    "type": "string",
                    "description": "Immigration status of offender (undocumented, visa overstay, etc.)"
                },
                "prior_deportations": {
                    "type": "integer",
                    "description": "Number of prior deportations if mentioned"
                },
                "gang_affiliated": {
                    "type": "boolean",
                    "description": "Whether gang affiliation is mentioned"
                },
                "gang_name": {"type": "string", "description": "Name of gang if mentioned"},
                "ice_detainer_status": {
                    "type": "string",
                    "description": "Whether there was an ICE detainer on the offender"
                },
                # Common fields
                "description": {"type": "string", "description": "Brief summary of the incident"},
                "outcome_category": {
                    "type": "string",
                    "enum": ["death", "serious_injury", "minor_injury", "no_injury", "unknown"]
                },
                "overall_confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Overall confidence in the extraction"
                },
                "extraction_notes": {
                    "type": "string",
                    "description": "Any notes about ambiguity or uncertainty"
                }
            }
        }
    },
    "required": ["is_relevant", "relevance_reason"]
}

# Category-specific system prompts
ENFORCEMENT_SYSTEM_PROMPT = """You are extracting data about violent incidents involving ICE/CBP agents.

Focus on: victim details, officer involvement, outcome severity, location.
This tracks enforcement actions that harmed non-immigrants (protesters, journalists, bystanders, US citizens).

Key entities to extract:
- victim_name, victim_age, victim_category
- officer_involved, agency (ICE/CBP)
- outcome_category (death, serious_injury, minor_injury, no_injury, unknown)

Higher scrutiny is required for enforcement incidents. Be conservative with confidence scores.

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

Always return valid JSON matching the expected schema."""

CRIME_SYSTEM_PROMPT = """You are extracting data about crimes committed by individuals with immigration status issues.

Focus on: offender details, criminal history, prior deportations, gang affiliation, ICE detainer status.

Key entities to extract:
- offender_name, offender_age, offender_nationality
- offender_immigration_status (undocumented, visa overstay, DACA, TPS, etc.)
- prior_deportations
- gang_affiliated, gang_name
- ice_detainer_status

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

Always return valid JSON matching the expected schema."""

# Generic system prompt (used when category is unknown)
SYSTEM_PROMPT = """You are a precise data extraction assistant. Your role is to:

1. Read articles about immigration-related incidents
2. Determine relevance to the incident tracking system
3. Classify as either "enforcement" (ICE/CBP action against person) or "crime" (crime by immigrant)
4. Extract structured data with confidence scores

Guidelines:
- Be conservative with confidence scores - only high confidence for explicit mentions
- If information is ambiguous, note it in extraction_notes
- For dates, prefer explicit mentions over "last week" style references
- For locations, get as specific as possible (city > county > state)
- Distinguish between enforcement incidents (ICE/CBP actions) and crime incidents (crimes by individuals)

Always return valid JSON matching the expected schema."""


EXTRACTION_PROMPTS = {
    "news_article": """You are an expert data extractor analyzing news articles about immigration-related incidents in the United States.

Your task is to:
1. Determine if this article describes a relevant incident
2. Classify the incident as "enforcement" (ICE/CBP action) or "crime" (crime by immigrant)
3. If relevant, extract structured data about the incident

An article is RELEVANT if it describes:
- ICE/CBP enforcement actions that resulted in injury, death, or property damage
- Violence against ICE/CBP officers during enforcement
- Crimes committed by individuals with documented immigration violations
- Incidents involving protesters, journalists, or bystanders during immigration enforcement

An article is NOT RELEVANT if it:
- Only discusses immigration policy without a specific incident
- Describes incidents outside the United States
- Has no connection to immigration enforcement or immigration status

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

ARTICLE TEXT:
{article_text}

Extract the incident data and return as JSON following the schema provided.""",

    "enforcement": """You are extracting data about an enforcement incident involving ICE/CBP agents.

Focus on extracting:
- victim_name, victim_age, victim_category (who was harmed)
- officer_involved, agency (who caused the harm)
- outcome_category (severity of harm)
- Location and date details

Victim categories: detainee, enforcement_target, protester, journalist, bystander, us_citizen_collateral, officer, multiple

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

ARTICLE TEXT:
{article_text}

Extract the incident data and return as JSON following the schema provided.""",

    "crime": """You are extracting data about a crime committed by an individual with immigration status issues.

Focus on extracting:
- offender_name, offender_age, offender_nationality
- offender_immigration_status (undocumented, visa overstay, etc.)
- prior_deportations (number if mentioned)
- gang_affiliated, gang_name
- ice_detainer_status
- incident_type (the crime committed)

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

ARTICLE TEXT:
{article_text}

Extract the incident data and return as JSON following the schema provided.""",

    "ice_release": """You are extracting data from an official ICE/CBP press release or report.

These documents typically have high reliability for:
- Dates and locations
- Official outcomes
- Agency involvement
- Offender immigration status and criminal history

Extract all available incident details. Official sources should have high confidence scores for factual claims.

DOCUMENT TEXT:
{article_text}

Extract the incident data and return as JSON following the schema provided.""",

    "court_document": """You are extracting incident data from a court document or legal filing.

Court documents provide authoritative information about:
- Criminal charges and outcomes
- Defendant identity and history
- Incident dates and locations
- Immigration status when relevant to the case

Note that court documents may describe incidents that occurred months or years before the filing date.

DOCUMENT TEXT:
{article_text}

Extract the incident data and return as JSON following the schema provided.""",
}


def get_extraction_prompt(document_type: str, article_text: str, category: IncidentCategory = None) -> str:
    """
    Get the appropriate extraction prompt for a document type and category.

    Args:
        document_type: Type of document (news_article, ice_release, court_document)
        article_text: The article content to analyze
        category: Optional incident category (enforcement or crime) for targeted extraction

    Returns:
        Formatted prompt string
    """
    # Use category-specific prompt if category is specified
    if category and category in EXTRACTION_PROMPTS:
        prompt_key = category
    elif document_type in EXTRACTION_PROMPTS:
        prompt_key = document_type
    else:
        prompt_key = "news_article"

    prompt = EXTRACTION_PROMPTS[prompt_key]
    return prompt.format(article_text=article_text)


def get_system_prompt(category: IncidentCategory = None) -> str:
    """
    Get the appropriate system prompt for a category.

    Args:
        category: Optional incident category (enforcement or crime)

    Returns:
        System prompt string
    """
    if category == 'enforcement':
        return ENFORCEMENT_SYSTEM_PROMPT
    elif category == 'crime':
        return CRIME_SYSTEM_PROMPT
    else:
        return SYSTEM_PROMPT


def get_required_fields(category: IncidentCategory) -> list:
    """
    Get the required fields for a category.

    Args:
        category: Incident category (enforcement or crime)

    Returns:
        List of required field names
    """
    if category == 'enforcement':
        return ENFORCEMENT_REQUIRED_FIELDS
    elif category == 'crime':
        return CRIME_REQUIRED_FIELDS
    else:
        return ['date', 'state', 'incident_type']
