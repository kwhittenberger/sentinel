"""
Duplicate detection service with multiple strategies.
Supports cross-source deduplication where the same incident is reported by multiple outlets.
"""

import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DuplicateConfig:
    """Configuration for duplicate detection."""
    title_similarity_threshold: float = 0.75
    content_similarity_threshold: float = 0.85
    entity_match_date_window: int = 30  # days
    name_similarity_threshold: float = 0.7  # for fuzzy name matching
    shingle_size: int = 3
    enable_url_match: bool = True
    enable_title_match: bool = True
    enable_content_match: bool = True
    enable_entity_match: bool = True
    enable_cross_source_match: bool = True  # match same incident across sources


# Default configuration
DEFAULT_CONFIG = DuplicateConfig()


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def tokenize(text: str) -> set:
    """Tokenize text into words, filtering short words."""
    normalized = normalize_text(text)
    return {word for word in normalized.split() if len(word) > 2}


def jaccard_similarity(set1: set, set2: set) -> float:
    """Calculate Jaccard similarity between two sets."""
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def create_shingles(text: str, shingle_size: int = 3) -> set:
    """Create word n-grams (shingles) from text."""
    words = normalize_text(text).split()
    if len(words) < shingle_size:
        return {tuple(words)}
    return {
        tuple(words[i:i + shingle_size])
        for i in range(len(words) - shingle_size + 1)
    }


def hash_shingle(shingle: tuple) -> str:
    """Hash a shingle to a short string."""
    text = ' '.join(shingle)
    return hashlib.md5(text.encode()).hexdigest()[:8]


def create_fingerprint(text: str, shingle_size: int = 3, sample_size: int = 100) -> set:
    """Create a fingerprint from text using min-hashing."""
    shingles = create_shingles(text, shingle_size)
    hashes = sorted([hash_shingle(s) for s in shingles])
    # Take a sample of the smallest hashes
    return set(hashes[:sample_size])


def check_title_similarity(
    title1: str,
    title2: str,
    threshold: float = 0.75
) -> tuple[bool, float]:
    """
    Check if two titles are similar.
    Returns (is_match, similarity_score).
    """
    tokens1 = tokenize(title1)
    tokens2 = tokenize(title2)
    similarity = jaccard_similarity(tokens1, tokens2)
    return similarity >= threshold, similarity


def normalize_name(name: str) -> str:
    """Normalize a person's name for comparison."""
    if not name:
        return ""
    # Lowercase and remove punctuation
    name = normalize_text(name)
    # Remove common prefixes/suffixes
    for prefix in ['mr ', 'mrs ', 'ms ', 'dr ', 'prof ']:
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in [' jr', ' sr', ' ii', ' iii', ' iv']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()


def get_name_parts(name: str) -> Tuple[str, str, str]:
    """Extract first, middle, last name parts."""
    parts = normalize_name(name).split()
    if len(parts) == 0:
        return '', '', ''
    elif len(parts) == 1:
        return parts[0], '', ''
    elif len(parts) == 2:
        return parts[0], '', parts[1]
    else:
        return parts[0], ' '.join(parts[1:-1]), parts[-1]


def check_name_similarity(name1: str, name2: str, threshold: float = 0.7) -> Tuple[bool, float, str]:
    """
    Check if two names likely refer to the same person.
    Handles variations like "John Doe" vs "John A. Doe" vs "J. Doe".
    Returns (is_match, confidence, reason).
    """
    if not name1 or not name2:
        return False, 0.0, 'missing_name'

    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    # Exact match after normalization
    if n1 == n2:
        return True, 1.0, 'exact_match'

    # One contains the other (handles middle name variations)
    if n1 in n2 or n2 in n1:
        return True, 0.95, 'substring_match'

    # Parse name parts
    first1, middle1, last1 = get_name_parts(name1)
    first2, middle2, last2 = get_name_parts(name2)

    # Same last name is required for a match
    if last1 != last2:
        # Check if last names are similar (typos, etc.)
        last_sim = jaccard_similarity(set(last1), set(last2))
        if last_sim < 0.8:
            return False, 0.0, 'different_last_name'

    # First name matching
    first_match = False
    first_confidence = 0.0

    if first1 == first2:
        first_match = True
        first_confidence = 1.0
    elif first1 and first2:
        # Check for initial match (J vs John)
        if len(first1) == 1 and first2.startswith(first1):
            first_match = True
            first_confidence = 0.8
        elif len(first2) == 1 and first1.startswith(first2):
            first_match = True
            first_confidence = 0.8
        else:
            # Token similarity for first name
            first_sim = jaccard_similarity(set(first1), set(first2))
            if first_sim >= 0.7:
                first_match = True
                first_confidence = first_sim

    if first_match and last1 == last2:
        confidence = (first_confidence + 1.0) / 2  # Average of first and last match
        return True, confidence, 'name_parts_match'

    # Fallback to token similarity on full name
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    similarity = jaccard_similarity(tokens1, tokens2)

    if similarity >= threshold:
        return True, similarity, 'token_similarity'

    return False, similarity, 'no_match'


def parse_date(date_val: Any) -> Optional[date]:
    """Parse various date formats into a date object."""
    if not date_val:
        return None
    if isinstance(date_val, date):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, str):
        try:
            return datetime.fromisoformat(date_val.replace('Z', '+00:00')).date()
        except:
            pass
        try:
            return datetime.strptime(date_val[:10], '%Y-%m-%d').date()
        except:
            pass
    return None


def check_date_proximity(date1: Any, date2: Any, window_days: int = 30) -> Tuple[bool, int]:
    """
    Check if two dates are within a window of each other.
    Returns (is_close, days_apart).
    """
    d1 = parse_date(date1)
    d2 = parse_date(date2)

    if not d1 or not d2:
        return False, -1

    days_apart = abs((d1 - d2).days)
    return days_apart <= window_days, days_apart


def check_content_similarity(
    content1: str,
    content2: str,
    threshold: float = 0.85,
    shingle_size: int = 3
) -> tuple[bool, float]:
    """
    Check if two content pieces are similar using fingerprinting.
    Returns (is_match, similarity_score).
    """
    fp1 = create_fingerprint(content1, shingle_size)
    fp2 = create_fingerprint(content2, shingle_size)
    similarity = jaccard_similarity(fp1, fp2)
    return similarity >= threshold, similarity


def extract_entities(article: dict) -> dict:
    """Extract key entities from an article for matching."""
    entities = {
        'offender_name': None,
        'victim_name': None,
        'incident_type': None,
        'date': None,
        'state': None,
        'city': None,
        'location': None,
    }

    # Try to get from extracted data (flat structure matching our schema)
    extracted = article.get('extracted_data') or article.get('llm_extraction_result') or {}

    if isinstance(extracted, dict):
        # Get incident data from extracted structure
        incident = extracted.get('incident', extracted)  # Handle nested or flat

        # Offender info (for crime incidents)
        entities['offender_name'] = (
            incident.get('offender_name') or
            extracted.get('offender_name')
        )

        # Victim info (for enforcement incidents)
        entities['victim_name'] = (
            incident.get('victim_name') or
            extracted.get('victim_name')
        )

        # Incident type
        entities['incident_type'] = (
            incident.get('incident_type') or
            extracted.get('incident_type')
        )

        # Date
        entities['date'] = (
            incident.get('date') or
            extracted.get('date')
        )

        # Location components
        entities['city'] = incident.get('city') or extracted.get('city')
        entities['state'] = incident.get('state') or extracted.get('state')

        # Combined location string
        city = entities['city'] or ''
        state = entities['state'] or ''
        if city or state:
            entities['location'] = f"{city}, {state}".strip(', ')

    # Fallback to direct fields on article
    if not entities['date']:
        entities['date'] = article.get('date') or article.get('incident_date')
    if not entities['state']:
        entities['state'] = article.get('state')
    if not entities['city']:
        entities['city'] = article.get('city')
    if not entities['location']:
        city = entities['city'] or ''
        state = entities['state'] or ''
        if city or state:
            entities['location'] = f"{city}, {state}".strip(', ')
    if not entities['offender_name']:
        entities['offender_name'] = article.get('offender_name')
    if not entities['victim_name']:
        entities['victim_name'] = article.get('victim_name')
    if not entities['incident_type']:
        entities['incident_type'] = article.get('incident_type')

    return entities


def check_entity_match(
    article1: dict,
    article2: dict,
    date_window_days: int = 30,
    name_threshold: float = 0.7
) -> tuple[bool, float, str]:
    """
    Check if two articles describe the same incident based on entities.
    Uses fuzzy name matching and date proximity.
    Returns (is_match, confidence, reason).
    """
    entities1 = extract_entities(article1)
    entities2 = extract_entities(article2)

    matches = 0
    total = 0
    reasons = []
    name_matched = False
    confidence_sum = 0.0

    # Check offender name with fuzzy matching (for crime incidents)
    if entities1['offender_name'] and entities2['offender_name']:
        total += 1
        name_match, name_conf, name_reason = check_name_similarity(
            entities1['offender_name'],
            entities2['offender_name'],
            name_threshold
        )
        if name_match:
            matches += 1
            confidence_sum += name_conf
            reasons.append(f'offender_match({name_reason}:{name_conf:.2f})')
            name_matched = True
        else:
            confidence_sum += 0

    # Check victim name with fuzzy matching (for enforcement incidents)
    if entities1['victim_name'] and entities2['victim_name']:
        total += 1
        name_match, name_conf, name_reason = check_name_similarity(
            entities1['victim_name'],
            entities2['victim_name'],
            name_threshold
        )
        if name_match:
            matches += 1
            confidence_sum += name_conf
            reasons.append(f'victim_match({name_reason}:{name_conf:.2f})')
            name_matched = True
        else:
            confidence_sum += 0

    # Check incident type
    if entities1['incident_type'] and entities2['incident_type']:
        total += 1
        type1 = entities1['incident_type'].lower().replace('_', ' ')
        type2 = entities2['incident_type'].lower().replace('_', ' ')
        if type1 == type2:
            matches += 1
            confidence_sum += 1.0
            reasons.append('incident_type_match')
        # Also check for related types
        elif _are_related_types(type1, type2):
            matches += 0.5
            confidence_sum += 0.7
            reasons.append('incident_type_related')

    # Check location (state match is more important)
    state1 = entities1.get('state') or _extract_state(entities1.get('location', ''))
    state2 = entities2.get('state') or _extract_state(entities2.get('location', ''))

    if state1 and state2:
        total += 1
        if state1.upper() == state2.upper():
            matches += 1
            confidence_sum += 1.0
            reasons.append('state_match')

            # Bonus for city match
            city1 = entities1.get('city') or ''
            city2 = entities2.get('city') or ''
            if city1 and city2 and normalize_text(city1) == normalize_text(city2):
                confidence_sum += 0.2
                reasons.append('city_match')

    # Check date proximity (not just exact match)
    if entities1['date'] and entities2['date']:
        total += 1
        is_close, days_apart = check_date_proximity(
            entities1['date'],
            entities2['date'],
            date_window_days
        )
        if is_close:
            matches += 1
            # Higher confidence for closer dates
            date_conf = 1.0 - (days_apart / date_window_days) * 0.5
            confidence_sum += date_conf
            reasons.append(f'date_proximity({days_apart}d)')

    if total == 0:
        return False, 0.0, 'no_entities'

    # Calculate weighted confidence
    avg_confidence = confidence_sum / total if total > 0 else 0

    # Strong match: name + (state OR date)
    # A name match with either state or date is a likely duplicate
    if name_matched and matches >= 2:
        return True, avg_confidence, ','.join(reasons)

    # Weaker match: 3+ matching fields at high confidence
    if matches >= 3 and avg_confidence >= 0.7:
        return True, avg_confidence, ','.join(reasons)

    # Standard match threshold
    is_match = matches >= 2 and avg_confidence >= 0.6

    return is_match, avg_confidence, ','.join(reasons) if reasons else 'no_match'


def _are_related_types(type1: str, type2: str) -> bool:
    """Check if two incident types are related/similar."""
    related_groups = [
        {'homicide', 'murder', 'manslaughter', 'killing'},
        {'assault', 'battery', 'attack', 'physical force'},
        {'sexual assault', 'rape', 'sexual abuse'},
        {'dui', 'dui fatality', 'drunk driving', 'intoxicated driving'},
        {'shooting', 'gunfire', 'firearm'},
        {'robbery', 'theft', 'burglary'},
        {'death in custody', 'custody death', 'detention death'},
    ]
    for group in related_groups:
        if type1 in group and type2 in group:
            return True
    return False


def _extract_state(location: str) -> str:
    """Extract state code from a location string."""
    if not location:
        return ''
    # Common patterns: "City, ST" or "City, State"
    parts = location.split(',')
    if len(parts) >= 2:
        state_part = parts[-1].strip().upper()
        if len(state_part) == 2:
            return state_part
    return ''


class DuplicateDetector:
    """Service for detecting duplicate articles."""

    def __init__(self, config: DuplicateConfig = None):
        self.config = config or DEFAULT_CONFIG

    def check_duplicate(
        self,
        new_article: dict,
        existing_articles: List[dict]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if a new article is a duplicate of any existing article.

        Returns dict with match info if duplicate found, None otherwise.
        """
        new_url = new_article.get('url') or new_article.get('source_url', '')
        new_title = new_article.get('title') or new_article.get('headline', '')
        new_content = new_article.get('content') or new_article.get('description', '')

        for existing in existing_articles:
            existing_url = existing.get('url') or existing.get('source_url', '')
            existing_title = existing.get('title') or existing.get('headline', '')
            existing_content = existing.get('content') or existing.get('description', '')

            # Strategy 1: Exact URL match
            if self.config.enable_url_match and new_url and existing_url:
                if new_url == existing_url:
                    return {
                        'match_type': 'url',
                        'matched_id': existing.get('id'),
                        'confidence': 1.0,
                        'reason': 'Exact URL match'
                    }

            # Strategy 2: Title similarity
            if self.config.enable_title_match and new_title and existing_title:
                is_match, similarity = check_title_similarity(
                    new_title, existing_title,
                    self.config.title_similarity_threshold
                )
                if is_match:
                    return {
                        'match_type': 'title',
                        'matched_id': existing.get('id'),
                        'confidence': similarity,
                        'reason': f'Title similarity: {similarity:.2%}'
                    }

            # Strategy 3: Content fingerprinting
            if self.config.enable_content_match and new_content and existing_content:
                is_match, similarity = check_content_similarity(
                    new_content, existing_content,
                    self.config.content_similarity_threshold,
                    self.config.shingle_size
                )
                if is_match:
                    return {
                        'match_type': 'content',
                        'matched_id': existing.get('id'),
                        'confidence': similarity,
                        'reason': f'Content similarity: {similarity:.2%}'
                    }

            # Strategy 4: Entity matching
            if self.config.enable_entity_match:
                is_match, confidence, reason = check_entity_match(
                    new_article, existing,
                    self.config.entity_match_date_window
                )
                if is_match:
                    return {
                        'match_type': 'entity',
                        'matched_id': existing.get('id'),
                        'confidence': confidence,
                        'reason': f'Entity match: {reason}'
                    }

        return None

    def get_config(self) -> dict:
        """Get current configuration as dict."""
        return {
            'title_similarity_threshold': self.config.title_similarity_threshold,
            'content_similarity_threshold': self.config.content_similarity_threshold,
            'entity_match_date_window': self.config.entity_match_date_window,
            'name_similarity_threshold': self.config.name_similarity_threshold,
            'shingle_size': self.config.shingle_size,
            'strategies_enabled': {
                'url': self.config.enable_url_match,
                'title': self.config.enable_title_match,
                'content': self.config.enable_content_match,
                'entity': self.config.enable_entity_match,
                'cross_source': self.config.enable_cross_source_match,
            }
        }


# Singleton instance
_detector: Optional[DuplicateDetector] = None


def get_detector() -> DuplicateDetector:
    """Get the singleton duplicate detector instance."""
    global _detector
    if _detector is None:
        _detector = DuplicateDetector()
    return _detector


async def find_duplicate_incident(
    extracted_data: dict,
    source_url: str = None,
    date_window_days: int = 30,
    name_threshold: float = 0.7
) -> Optional[Dict[str, Any]]:
    """
    Find a duplicate incident in the database based on extracted data.
    This is used during approval to catch cross-source duplicates.

    Returns dict with match info if duplicate found, None otherwise.
    """
    from backend.database import fetch

    # Strategy 1: Check for same source URL
    if source_url:
        url_match = await fetch("""
            SELECT id, date, state, city, source_url,
                   victim_name, offender_immigration_status as offender_name
            FROM incidents
            WHERE source_url = $1
            LIMIT 1
        """, source_url)
        if url_match:
            inc = url_match[0]
            return {
                'match_type': 'url',
                'matched_id': str(inc['id']),
                'confidence': 1.0,
                'reason': 'Same source URL',
                'matched_incident': {
                    'date': str(inc['date']) if inc['date'] else None,
                    'location': f"{inc.get('city', '')}, {inc.get('state', '')}".strip(', '),
                }
            }

    # Strategy 2: Check for exact description match (catches syndicated content)
    description = extracted_data.get('description')
    if description and len(description) > 50:
        desc_match = await fetch("""
            SELECT id, date, state, city, source_url, description
            FROM incidents
            WHERE description = $1
            LIMIT 1
        """, description)
        if desc_match:
            inc = desc_match[0]
            return {
                'match_type': 'description',
                'matched_id': str(inc['id']),
                'confidence': 1.0,
                'reason': 'Identical description text',
                'matched_incident': {
                    'date': str(inc['date']) if inc['date'] else None,
                    'location': f"{inc.get('city', '')}, {inc.get('state', '')}".strip(', '),
                    'source_url': inc.get('source_url'),
                }
            }

    # Extract entities for matching
    entities = extract_entities({'extracted_data': extracted_data})

    offender_name = entities.get('offender_name')
    victim_name = entities.get('victim_name')
    state = entities.get('state')
    incident_date_raw = entities.get('date')

    # Convert date string to datetime.date for asyncpg
    incident_date = None
    if incident_date_raw:
        if isinstance(incident_date_raw, str):
            from datetime import date as _date
            try:
                incident_date = _date.fromisoformat(incident_date_raw)
            except (ValueError, TypeError):
                pass
        else:
            incident_date = incident_date_raw

    # Strategy 2: Entity-based matching
    # Find potential matches based on name + state + date range
    potential_matches = []

    if offender_name and state:
        # Look for incidents with similar offender names in same state
        matches = await fetch("""
            SELECT i.id, i.date, i.state, i.city, i.source_url,
                   a.canonical_name as matched_name,
                   'offender' as match_role
            FROM incidents i
            JOIN incident_actors ia ON i.id = ia.incident_id
            JOIN actors a ON ia.actor_id = a.id
            WHERE ia.role = 'offender'
              AND i.state = $1
              AND ($2::date IS NULL OR ABS(i.date - $2::date) <= $3)
            LIMIT 50
        """, state, incident_date, date_window_days)
        potential_matches.extend(matches)

    if victim_name and state:
        # Look for incidents with similar victim names in same state
        matches = await fetch("""
            SELECT i.id, i.date, i.state, i.city, i.source_url,
                   a.canonical_name as matched_name,
                   'victim' as match_role
            FROM incidents i
            JOIN incident_actors ia ON i.id = ia.incident_id
            JOIN actors a ON ia.actor_id = a.id
            WHERE ia.role = 'victim'
              AND i.state = $1
              AND ($2::date IS NULL OR ABS(i.date - $2::date) <= $3)
            LIMIT 50
        """, state, incident_date, date_window_days)
        potential_matches.extend(matches)

    # Also check incidents by victim_name column (legacy data)
    if victim_name and state:
        legacy_matches = await fetch("""
            SELECT id, date, state, city, source_url,
                   victim_name as matched_name,
                   'victim' as match_role
            FROM incidents
            WHERE victim_name IS NOT NULL
              AND state = $1
              AND ($2::date IS NULL OR ABS(date - $2::date) <= $3)
            LIMIT 50
        """, state, incident_date, date_window_days)
        potential_matches.extend(legacy_matches)

    # Check each potential match for name similarity
    best_match = None
    best_confidence = 0.0
    best_match_reason = 'similar'

    for match in potential_matches:
        matched_name = match.get('matched_name')
        match_role = match.get('match_role')

        # Compare names using our fuzzy matching
        if match_role == 'offender' and offender_name:
            is_match, confidence, reason = check_name_similarity(
                offender_name, matched_name, name_threshold
            )
            if is_match and confidence > best_confidence:
                best_match = match
                best_confidence = confidence
                best_match_reason = reason

        elif match_role == 'victim' and victim_name:
            is_match, confidence, reason = check_name_similarity(
                victim_name, matched_name, name_threshold
            )
            if is_match and confidence > best_confidence:
                best_match = match
                best_confidence = confidence
                best_match_reason = reason

    if best_match:
        return {
            'match_type': 'entity',
            'matched_id': str(best_match['id']),
            'confidence': best_confidence,
            'reason': f"Name match ({best_match.get('match_role')}: {best_match_reason})",
            'matched_incident': {
                'date': str(best_match['date']) if best_match['date'] else None,
                'location': f"{best_match.get('city', '')}, {best_match.get('state', '')}".strip(', '),
                'matched_name': best_match.get('matched_name'),
                'source_url': best_match.get('source_url'),
            }
        }

    return None
