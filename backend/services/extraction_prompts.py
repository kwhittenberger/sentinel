"""
Prompts for LLM extraction of incident data from articles.
Supports dual incident categories: enforcement (ICE/CBP actions) and crime (crimes by immigrants).
Also supports two-stage extraction: Stage 1 (comprehensive IR) and Stage 2 (schema-specific).
"""

import hashlib
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
                "state": {"type": "string", "description": "US state where incident occurred (2-letter code)"},
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
                        "kidnapping", "gang_activity", "drug_trafficking", "human_trafficking",
                        "fraud", "identity_theft", "illegal_reentry", "child_abuse"
                    ]
                },
                "incident_type_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                # Enforcement-specific fields
                "victim_name": {"type": "string", "description": "Full name of victim"},
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
                # Crime-specific fields - OFFENDER DETAILS (CRITICAL)
                "offender_name": {"type": "string", "description": "REQUIRED for crime: Full name of offender/perpetrator/defendant"},
                "offender_name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "offender_age": {"type": "integer", "description": "Age of offender at time of offense"},
                "offender_gender": {"type": "string", "enum": ["male", "female", "unknown"]},
                "offender_nationality": {"type": "string", "description": "Country of origin or nationality"},
                "offender_country_of_origin": {"type": "string", "description": "Country the offender is from"},
                "offender_immigration_status": {
                    "type": "string",
                    "description": "Immigration status: undocumented, illegal alien, visa overstay, DACA, TPS, legal resident, etc."
                },
                "entry_method": {
                    "type": "string",
                    "description": "How offender entered US: border crossing, visa overstay, unknown, etc."
                },
                "prior_deportations": {
                    "type": "integer",
                    "description": "Number of prior deportations/removals (0 if not mentioned)"
                },
                "prior_arrests": {
                    "type": "integer",
                    "description": "Number of prior arrests if mentioned"
                },
                "prior_convictions": {
                    "type": "integer",
                    "description": "Number of prior criminal convictions if mentioned"
                },
                "gang_affiliated": {
                    "type": "boolean",
                    "description": "Whether gang affiliation is mentioned"
                },
                "gang_name": {"type": "string", "description": "Name of gang if mentioned (MS-13, etc.)"},
                "cartel_connection": {"type": "string", "description": "Name of cartel if mentioned"},
                "ice_detainer_status": {
                    "type": "string",
                    "description": "ICE detainer status: ignored, honored, none, unknown"
                },
                "ice_detainer_ignored": {
                    "type": "boolean",
                    "description": "True if an ICE detainer was explicitly ignored by local authorities"
                },
                "was_released_sanctuary": {
                    "type": "boolean",
                    "description": "True if released due to sanctuary city/state policy"
                },
                "was_released_bail": {
                    "type": "boolean",
                    "description": "True if released on bail before committing this crime"
                },
                # Victim information for crime incidents
                "crime_victim_count": {
                    "type": "integer",
                    "description": "Number of victims in this crime"
                },
                "crime_victim_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of crime victims if mentioned"
                },
                "involves_fatality": {
                    "type": "boolean",
                    "description": "Whether the crime resulted in death(s)"
                },
                # Common fields
                "description": {"type": "string", "description": "Brief factual summary of the incident (2-3 sentences)"},
                "outcome_category": {
                    "type": "string",
                    "enum": ["death", "serious_injury", "minor_injury", "no_injury", "unknown"]
                },
                "charges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of criminal charges filed"
                },
                "sentence": {"type": "string", "description": "Sentence if mentioned (e.g., '15 years prison')"},
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

# Universal extraction schema - extracts ALL entities regardless of category
UNIVERSAL_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {
            "type": "boolean",
            "description": "Whether the article describes a trackable immigration-related incident"
        },
        "relevance_reason": {
            "type": "string",
            "description": "Brief explanation of why the article is or isn't relevant"
        },
        "incident": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short descriptive title for the incident"},
                "summary": {"type": "string", "description": "2-3 sentence factual summary of what happened"},
                "date": {"type": "string", "description": "Date of incident (YYYY-MM-DD format)"},
                "date_approximate": {"type": "boolean", "description": "True if date is estimated"},
                "date_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "location": {
                    "type": "object",
                    "properties": {
                        "state": {"type": "string", "description": "US state (2-letter code)"},
                        "city": {"type": "string"},
                        "county": {"type": "string"},
                        "address": {"type": "string", "description": "Specific address if mentioned"},
                        "location_type": {"type": "string", "description": "e.g., courthouse, residence, workplace, street"}
                    }
                },
                "location_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "incident_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "All applicable incident types: arrest, protest, assault, shooting, detention, deportation, raid, traffic_stop, court_hearing, etc."
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["enforcement", "crime", "protest", "legal", "policy"]},
                    "description": "All applicable categories for this incident"
                },
                "outcome": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["death", "serious_injury", "minor_injury", "arrest", "detention", "release", "no_injury", "unknown"]},
                        "description": {"type": "string"}
                    }
                },
                "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1}
            }
        },
        "actors": {
            "type": "array",
            "description": "ALL people, agencies, and organizations mentioned in the incident",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Full name or organization name"},
                    "name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "actor_type": {
                        "type": "string",
                        "enum": ["person", "agency", "organization", "group"],
                        "description": "Type of actor"
                    },
                    "roles": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "victim", "offender", "suspect", "defendant", "detainee",
                                "officer", "agent", "arresting_agency", "prosecuting_agency",
                                "protester", "organizer", "bystander", "witness",
                                "journalist", "lawyer", "judge",
                                "family_member", "employer", "informant"
                            ]
                        },
                        "description": "All roles this actor played in the incident"
                    },
                    # Person-specific fields
                    "age": {"type": "integer"},
                    "gender": {"type": "string", "enum": ["male", "female", "unknown"]},
                    "nationality": {"type": "string"},
                    "country_of_origin": {"type": "string"},
                    "immigration_status": {
                        "type": "string",
                        "description": "If known: undocumented, visa_overstay, legal_resident, citizen, DACA, TPS, asylum_seeker, etc."
                    },
                    "prior_deportations": {"type": "integer"},
                    "prior_criminal_history": {"type": "boolean"},
                    "gang_affiliation": {"type": "string"},
                    # Agency-specific fields
                    "agency_type": {
                        "type": "string",
                        "enum": ["ice", "cbp", "hsi", "local_police", "sheriff", "state_police", "federal", "other"]
                    },
                    "badge_number": {"type": "string"},
                    # Action fields
                    "action_taken": {"type": "string", "description": "What this actor did: arrested, protested, detained, released, etc."},
                    "charges": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Criminal charges if applicable"
                    },
                    "sentence": {"type": "string"},
                    "injuries": {"type": "string", "description": "Injuries sustained or caused"},
                    "notes": {"type": "string"}
                },
                "required": ["name", "actor_type", "roles"]
            }
        },
        "events": {
            "type": "array",
            "description": "Related events mentioned (protests, hearings, prior incidents)",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "protest, rally, hearing, prior_arrest, deportation, etc."},
                    "description": {"type": "string"},
                    "date": {"type": "string"},
                    "participants_count": {"type": "integer"},
                    "relation_to_incident": {"type": "string", "description": "caused_by, in_response_to, related_to, prior_to, after"}
                }
            }
        },
        "policy_context": {
            "type": "object",
            "description": "Policy factors mentioned",
            "properties": {
                "sanctuary_jurisdiction": {"type": "boolean"},
                "ice_detainer_status": {"type": "string", "enum": ["issued", "honored", "ignored", "not_applicable", "unknown"]},
                "policy_mentioned": {"type": "string", "description": "Any specific policy mentioned"}
            }
        },
        "sources_cited": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Sources quoted in the article: police spokesperson, ICE statement, court records, etc."
        },
        "extraction_notes": {"type": "string", "description": "Any ambiguity or notes about the extraction"}
    },
    "required": ["is_relevant", "relevance_reason"]
}

# Universal extraction prompt - extracts all entities
UNIVERSAL_SYSTEM_PROMPT = """You are an expert data extraction system for tracking immigration-related incidents.

Your job is to extract ALL relevant entities and details from news articles, regardless of incident category.

EXTRACT EVERYTHING:
1. **ACTORS** - Every person, agency, and organization mentioned:
   - People: names, ages, roles (victim, offender, officer, protester, witness, etc.)
   - Agencies: ICE, CBP, local police, courts, etc.
   - Organizations: advocacy groups, employers, etc.
   - For each person, note immigration status if mentioned

2. **INCIDENT DETAILS**:
   - What happened (arrest, protest, assault, detention, etc.)
   - Where (state, city, specific location)
   - When (exact date or approximate)
   - Outcome (injuries, arrests, deaths, releases)

3. **RELATED EVENTS**:
   - Protests sparked by the incident
   - Prior arrests or deportations
   - Court hearings
   - Related incidents

4. **POLICY CONTEXT**:
   - Sanctuary city/state status
   - ICE detainer decisions
   - Relevant policies

CONFIDENCE SCORES (0.0 to 1.0):
- 1.0: Explicitly stated verbatim
- 0.8-0.9: Clearly stated, minor inference
- 0.6-0.7: Strongly implied
- 0.4-0.5: Reasonable inference
- 0.2-0.3: Weak inference
- 0.0: Not found

IMPORTANT:
- Extract ALL named individuals, not just the primary subject
- An incident can have multiple categories (enforcement AND protest)
- Always return valid JSON"""

UNIVERSAL_EXTRACTION_PROMPT = """Analyze this article and extract ALL relevant information about immigration-related incidents.

Extract every actor (person, agency, organization), every event, and all contextual details.

ARTICLE TEXT:
{article_text}

Return JSON matching the universal extraction schema. Include ALL actors with their roles, not just the primary subject."""

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

CRITICAL: You MUST extract the offender's name. Look for:
- The defendant/accused/suspect name in the article
- Names mentioned in headlines (e.g., "John Doe Pleads Guilty")
- Names in photo captions or mugshots
- Names in court records or charges

Focus on extracting ALL available offender details:
1. IDENTITY: offender_name (REQUIRED), offender_age, offender_gender
2. ORIGIN: offender_nationality, offender_country_of_origin
3. IMMIGRATION: offender_immigration_status (undocumented, illegal alien, visa overstay, etc.)
4. HISTORY: prior_deportations, prior_arrests, prior_convictions
5. GANG/CARTEL: gang_affiliated, gang_name, cartel_connection
6. POLICY: ice_detainer_status, ice_detainer_ignored, was_released_sanctuary, was_released_bail
7. CHARGES: incident_type, charges array, sentence if convicted

Immigration status terminology to recognize:
- "illegal alien", "undocumented immigrant", "illegal immigrant" -> offender_immigration_status: "undocumented"
- "visa overstay" -> offender_immigration_status: "visa_overstay"
- "previously deported" -> prior_deportations >= 1
- "entered illegally" -> entry_method: "illegal_border_crossing"

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

CRITICAL REQUIREMENTS:
1. You MUST extract the offender's full name (offender_name) - this is REQUIRED
2. Look for names in: headlines, first paragraphs, mugshot captions, court records
3. Extract ALL available details about the offender

Fields to extract (in order of importance):
IDENTITY:
- offender_name: Full name of the defendant/accused/suspect (REQUIRED)
- offender_age: Age at time of offense
- offender_gender: male/female/unknown

ORIGIN & IMMIGRATION:
- offender_nationality: Country of citizenship
- offender_country_of_origin: Country they came from
- offender_immigration_status: undocumented, illegal alien, visa overstay, DACA, TPS, legal resident
- entry_method: How they entered the US

CRIMINAL HISTORY:
- prior_deportations: Number of times previously deported (0 if not mentioned, but extract if stated)
- prior_arrests: Number of prior arrests
- prior_convictions: Number of prior convictions

GANG/CARTEL:
- gang_affiliated: true/false if gang membership mentioned
- gang_name: MS-13, 18th Street, etc.
- cartel_connection: Name of cartel if mentioned

POLICY FAILURES:
- ice_detainer_ignored: true if ICE detainer was ignored by local authorities
- was_released_sanctuary: true if released due to sanctuary policy
- was_released_bail: true if released on bail before this crime

CRIME DETAILS:
- incident_type: The type of crime committed
- charges: Array of charges filed
- crime_victim_count: Number of victims
- involves_fatality: true if someone died
- outcome_category: death, serious_injury, minor_injury, no_injury

ARTICLE TEXT:
{article_text}

Extract ALL available data. If the offender's name appears anywhere in the article, you MUST extract it.""",

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


# Triage prompt for quick relevance filtering
TRIAGE_SYSTEM_PROMPT = """You are a news article classifier. Your job is to quickly determine if an article describes a specific, trackable incident.

You are NOT looking for general policy discussions or news coverage. You ARE looking for:
1. A specific incident that occurred at a specific time and place
2. Involving either:
   - ICE/CBP enforcement actions that affected someone (arrest, detention, use of force)
   - Crimes committed by individuals with documented immigration status issues

REJECT if the article is:
- General policy discussion or opinion piece
- Coverage of protests/rallies without a specific incident
- Statistics or reports without specific incidents
- Announcements of policy changes
- Coverage of legislation or court rulings (unless describing a specific incident case)
- Political commentary

ACCEPT if the article describes:
- A specific arrest, detention, or use of force incident
- A specific crime with named individuals
- A specific death, injury, or altercation
- A specific court case about a specific incident"""

TRIAGE_PROMPT = """Analyze this article and determine if it describes a SPECIFIC, TRACKABLE INCIDENT.

ARTICLE TITLE: {title}

ARTICLE TEXT:
{article_text}

Respond with JSON:
{{
  "is_specific_incident": true/false,
  "reason": "brief explanation",
  "incident_type": "enforcement" | "crime" | "both" | "none",
  "has_named_individuals": true/false,
  "has_specific_date_or_timeframe": true/false,
  "has_specific_location": true/false,
  "recommendation": "extract" | "reject" | "review"
}}

IMPORTANT:
- "extract" = Clear incident, run full extraction
- "reject" = Not a trackable incident, remove from queue
- "review" = Unclear, needs human review"""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_specific_incident": {"type": "boolean"},
        "reason": {"type": "string"},
        "incident_type": {"type": "string", "enum": ["enforcement", "crime", "both", "none"]},
        "has_named_individuals": {"type": "boolean"},
        "has_specific_date_or_timeframe": {"type": "boolean"},
        "has_specific_location": {"type": "boolean"},
        "recommendation": {"type": "string", "enum": ["extract", "reject", "review"]}
    },
    "required": ["is_specific_incident", "reason", "recommendation"]
}


def get_triage_prompt(title: str, article_text: str) -> str:
    """Get the triage prompt for quick relevance filtering."""
    # Truncate long articles for triage (we only need enough to determine relevance)
    if len(article_text) > 3000:
        article_text = article_text[:3000] + "\n\n[Article truncated for triage]"
    return TRIAGE_PROMPT.format(title=title, article_text=article_text)


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


def get_universal_extraction_prompt(article_text: str) -> str:
    """
    Get the universal extraction prompt that extracts all entities.

    Args:
        article_text: The article content to analyze

    Returns:
        Formatted prompt string
    """
    return UNIVERSAL_EXTRACTION_PROMPT.format(article_text=article_text)


# ============================================================================
# TWO-STAGE EXTRACTION: Stage 1 IR Schema
# ============================================================================

STAGE1_IR_SCHEMA = {
    "type": "object",
    "properties": {
        "article_meta": {
            "type": "object",
            "properties": {
                "primary_topic": {"type": "string"},
                "article_type": {"type": "string", "enum": ["news", "court_document", "press_release", "opinion"]}
            }
        },
        "classification_hints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domain_slug": {"type": "string"},
                    "category_slug": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["domain_slug", "category_slug", "confidence"]
            }
        },
        "entities": {
            "type": "object",
            "properties": {
                "persons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "roles": {"type": "array", "items": {"type": "string"}},
                            "age": {"type": ["integer", "null"]},
                            "gender": {"type": ["string", "null"]},
                            "nationality": {"type": ["string", "null"]},
                            "immigration_status": {"type": ["string", "null"]},
                            "criminal_history": {
                                "type": "object",
                                "properties": {
                                    "prior_arrests": {"type": ["integer", "null"]},
                                    "prior_convictions": {"type": ["integer", "null"]},
                                    "prior_deportations": {"type": ["integer", "null"]},
                                    "gang_affiliation": {"type": ["string", "null"]}
                                }
                            },
                            "mentioned_in_events": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["id", "name", "roles"]
                    }
                },
                "organizations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "org_type": {"type": "string"},
                            "mentioned_in_events": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["id", "name"]
                    }
                },
                "locations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "city": {"type": ["string", "null"]},
                            "county": {"type": ["string", "null"]},
                            "state": {"type": ["string", "null"]},
                            "address": {"type": ["string", "null"]},
                            "location_type": {"type": ["string", "null"]},
                            "mentioned_in_events": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["id", "name"]
                    }
                }
            }
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "date": {"type": ["string", "null"]},
                    "date_approximate": {"type": "boolean"},
                    "location_id": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                    "participants": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entity_id": {"type": "string"},
                                "role": {"type": "string"}
                            }
                        }
                    },
                    "charges": {"type": "array", "items": {"type": "string"}},
                    "outcome": {"type": ["string", "null"]},
                    "is_primary_event": {"type": "boolean"}
                },
                "required": ["id", "event_type"]
            }
        },
        "legal_data": {
            "type": "object",
            "properties": {
                "case_numbers": {"type": "array", "items": {"type": "string"}},
                "charges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "charge": {"type": "string"},
                            "severity": {"type": "string"},
                            "statute": {"type": ["string", "null"]}
                        }
                    }
                },
                "dispositions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "charge": {"type": "string"},
                            "outcome": {"type": "string"}
                        }
                    }
                },
                "sentences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "duration": {"type": ["string", "null"]},
                            "amount": {"type": ["string", "null"]}
                        }
                    }
                }
            }
        },
        "quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "speaker": {"type": "string"},
                    "speaker_entity_id": {"type": ["string", "null"]}
                }
            }
        },
        "policy_context": {
            "type": "object",
            "properties": {
                "sanctuary_jurisdiction": {"type": ["boolean", "null"]},
                "ice_detainer_status": {"type": ["string", "null"]},
                "relevant_policies": {"type": "array", "items": {"type": "string"}}
            }
        },
        "source_attributions": {"type": "array", "items": {"type": "string"}},
        "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "extraction_notes": {"type": "string"}
    },
    "required": ["entities", "events", "classification_hints"]
}

# Current Stage 1 schema version - bump when prompt changes materially
STAGE1_SCHEMA_VERSION = 1


def compute_prompt_hash(system_prompt: str, user_prompt_template: str) -> str:
    """Compute SHA256 hash of Stage 1 prompts for staleness detection."""
    content = f"{system_prompt}\n---\n{user_prompt_template}"
    return hashlib.sha256(content.encode()).hexdigest()
