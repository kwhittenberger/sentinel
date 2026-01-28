"""State name normalization utilities."""

# US State name to abbreviation mapping
STATE_NAME_TO_CODE = {
    'alabama': 'AL',
    'alaska': 'AK',
    'arizona': 'AZ',
    'arkansas': 'AR',
    'california': 'CA',
    'colorado': 'CO',
    'connecticut': 'CT',
    'delaware': 'DE',
    'florida': 'FL',
    'georgia': 'GA',
    'hawaii': 'HI',
    'idaho': 'ID',
    'illinois': 'IL',
    'indiana': 'IN',
    'iowa': 'IA',
    'kansas': 'KS',
    'kentucky': 'KY',
    'louisiana': 'LA',
    'maine': 'ME',
    'maryland': 'MD',
    'massachusetts': 'MA',
    'michigan': 'MI',
    'minnesota': 'MN',
    'mississippi': 'MS',
    'missouri': 'MO',
    'montana': 'MT',
    'nebraska': 'NE',
    'nevada': 'NV',
    'new hampshire': 'NH',
    'new jersey': 'NJ',
    'new mexico': 'NM',
    'new york': 'NY',
    'north carolina': 'NC',
    'north dakota': 'ND',
    'ohio': 'OH',
    'oklahoma': 'OK',
    'oregon': 'OR',
    'pennsylvania': 'PA',
    'rhode island': 'RI',
    'south carolina': 'SC',
    'south dakota': 'SD',
    'tennessee': 'TN',
    'texas': 'TX',
    'utah': 'UT',
    'vermont': 'VT',
    'virginia': 'VA',
    'washington': 'WA',
    'west virginia': 'WV',
    'wisconsin': 'WI',
    'wyoming': 'WY',
    # Territories
    'district of columbia': 'DC',
    'washington dc': 'DC',
    'washington d.c.': 'DC',
    'd.c.': 'DC',
    'puerto rico': 'PR',
    'virgin islands': 'VI',
    'guam': 'GU',
    'american samoa': 'AS',
    'northern mariana islands': 'MP',
}

# Valid state/territory codes
VALID_STATE_CODES = set(STATE_NAME_TO_CODE.values())

# Special values that should be preserved
SPECIAL_VALUES = {'Unknown', 'Multiple', 'Federal/Multiple', 'International'}


def normalize_state(state: str | None) -> str:
    """
    Normalize a state name or abbreviation to a standard 2-letter code.

    Args:
        state: State name, abbreviation, or special value

    Returns:
        2-letter state code, special value, or 'Unknown' if not recognized
    """
    if not state:
        return 'Unknown'

    state = state.strip()

    # Check if it's already a valid code
    if state.upper() in VALID_STATE_CODES:
        return state.upper()

    # Check if it's a special value (case-insensitive match)
    for special in SPECIAL_VALUES:
        if state.lower() == special.lower():
            return special

    # Try to match full name
    state_lower = state.lower()
    if state_lower in STATE_NAME_TO_CODE:
        return STATE_NAME_TO_CODE[state_lower]

    # Try partial matching for common variations
    # e.g., "New York State" -> "NY"
    for name, code in STATE_NAME_TO_CODE.items():
        if name in state_lower or state_lower in name:
            return code

    # If we can't normalize, return as-is but log it
    return state


def get_state_name(code: str) -> str | None:
    """
    Get the full state name from a 2-letter code.

    Args:
        code: 2-letter state code

    Returns:
        Full state name or None if not found
    """
    code = code.upper() if code else ''

    # Reverse lookup
    for name, state_code in STATE_NAME_TO_CODE.items():
        if state_code == code:
            return name.title()

    return None


def is_valid_state(state: str | None) -> bool:
    """
    Check if a state value is valid (either a code or special value).

    Args:
        state: State value to check

    Returns:
        True if valid, False otherwise
    """
    if not state:
        return False

    state = state.strip()

    if state.upper() in VALID_STATE_CODES:
        return True

    if state in SPECIAL_VALUES:
        return True

    return False
