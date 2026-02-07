"""Duplicate detection service for identifying redundant articles and incidents.

Detects duplicates using four complementary strategies, applied in order of
specificity and computational cost:

1. **URL match** -- Exact source URL equality. Confidence: 1.0.
2. **Title match** -- Jaccard similarity on word tokens after normalization.
   Catches rephrased headlines from syndicated/wire content.
3. **Content match** -- MinHash fingerprinting with word-level shingles (n-grams).
   Catches near-identical body text even when headlines differ.
4. **Entity match** -- Structured comparison of extracted entities (names, dates,
   locations, incident types). Catches the same real-world incident reported by
   different outlets with different wording.

The strategies are evaluated in order; the first match wins. This means a URL
match short-circuits more expensive content or entity comparisons.

Output contract:
    - ``check_duplicate()`` returns ``None`` if no duplicate is found, or a dict
      with keys: ``match_type`` (str), ``matched_id`` (str), ``confidence``
      (float 0-1), and ``reason`` (human-readable explanation).
    - ``find_duplicate_incident()`` performs the same check against the database
      (used at approval time for cross-source deduplication) and returns the
      same shape, plus a ``matched_incident`` dict with date/location/source info.

Known limitations:
    - Title matching uses bag-of-words Jaccard, which can false-positive on short
      titles with common words (e.g., "Man arrested in Texas").
    - Content fingerprinting uses a fixed sample of the 100 smallest hashes;
      very short articles (<30 words) produce unreliable fingerprints.
    - Entity matching requires at least two matching fields to declare a
      duplicate, so articles missing extracted entities may slip through.
    - Name similarity uses character-level Jaccard on last names, which can
      false-positive on short surnames (e.g., "Li" vs "Liu").
    - The detector operates in-memory against a provided list; there is no
      indexing or blocking step, so performance degrades linearly with list size.
"""

import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from .thresholds import (
    DUPLICATE_TITLE_SIMILARITY,
    DUPLICATE_CONTENT_SIMILARITY,
    DUPLICATE_NAME_SIMILARITY,
    DUPLICATE_ENTITY_DATE_WINDOW,
)

logger = logging.getLogger(__name__)


@dataclass
class DuplicateConfig:
    """Configuration for duplicate detection thresholds and strategy toggles.

    All similarity thresholds are Jaccard coefficients in the range [0, 1].
    Values were empirically tuned against a set of ~500 manually-labeled
    article pairs during initial development.
    """

    # Minimum Jaccard similarity between title word-token sets to declare a
    # title match. 0.75 balances catching rephrased headlines while avoiding
    # false positives on short, generic titles. (empirically tuned)
    title_similarity_threshold: float = DUPLICATE_TITLE_SIMILARITY

    # Minimum Jaccard similarity between MinHash fingerprints of article body
    # text. Set higher than title threshold because content fingerprints
    # are noisier -- a lower value would over-match on articles that merely
    # share boilerplate or templated paragraphs. (empirically tuned)
    content_similarity_threshold: float = DUPLICATE_CONTENT_SIMILARITY

    # Maximum number of days apart two incident dates can be and still qualify
    # as a potential entity match. Accounts for delayed reporting and
    # follow-up articles about the same incident. (empirically tuned)
    entity_match_date_window: int = DUPLICATE_ENTITY_DATE_WINDOW

    # Minimum Jaccard similarity for fuzzy person-name matching (used in entity
    # strategy). Accommodates typos and transliteration differences while
    # avoiding matching unrelated short names. (empirically tuned)
    name_similarity_threshold: float = DUPLICATE_NAME_SIMILARITY

    # Number of consecutive words per shingle (n-gram) for content
    # fingerprinting. 3-word shingles are a standard choice that captures local
    # phrase structure without being too sensitive to word-order changes.
    shingle_size: int = 3

    # Strategy toggles -- allow disabling individual strategies at runtime
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
    """Tokenize text into words, filtering short words.

    Words of 2 characters or fewer (e.g., "a", "of", "in") are dropped to
    reduce noise from common stopwords without needing a full stopword list.
    """
    normalized = normalize_text(text)
    # Drop words <= 2 chars to filter articles/prepositions cheaply
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
    """Hash a shingle to a short string.

    Truncated to 8 hex chars (32 bits) for compact storage. Collision risk is
    acceptable because we compare sets of hashes, not individual values.
    """
    text = ' '.join(shingle)
    return hashlib.md5(text.encode()).hexdigest()[:8]  # 32-bit truncation


def create_fingerprint(text: str, shingle_size: int = 3, sample_size: int = 100) -> set:
    """Create a fingerprint from text using min-hashing.

    Selects the ``sample_size`` smallest hash values (MinHash approximation).
    100 hashes give a good precision/recall tradeoff for articles of typical
    length (200-2000 words). Shorter articles produce fewer shingles and
    therefore fewer hashes, which can reduce fingerprint accuracy.
    """
    shingles = create_shingles(text, shingle_size)
    hashes = sorted([hash_shingle(s) for s in shingles])
    # Keep the 100 smallest hashes as a MinHash sketch
    return set(hashes[:sample_size])


def check_title_similarity(
    title1: str,
    title2: str,
    threshold: float = DUPLICATE_TITLE_SIMILARITY
) -> tuple[bool, float]:
    """Check if two titles are similar using word-level Jaccard similarity.

    Args:
        title1: First title string.
        title2: Second title string.
        threshold: Minimum Jaccard score to consider a match (default 0.75).

    Returns:
        Tuple of (is_match, similarity_score).
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


def check_name_similarity(name1: str, name2: str, threshold: float = DUPLICATE_NAME_SIMILARITY) -> Tuple[bool, float, str]:
    """Check if two names likely refer to the same person.

    Applies a cascade of increasingly fuzzy matching strategies:
      1. Exact match after normalization (confidence 1.0)
      2. Substring containment, e.g., "John Doe" in "John A. Doe" (confidence 0.95)
      3. Structured name-part comparison: last name must match (or be character-
         similar >= 0.8), then first name is compared (exact, initial, or fuzzy)
      4. Fallback whole-name token Jaccard against ``threshold``

    Args:
        name1: First person name.
        name2: Second person name.
        threshold: Minimum Jaccard score for the fallback whole-name comparison
            (default from DUPLICATE_NAME_SIMILARITY).

    Returns:
        Tuple of (is_match, confidence, reason_tag).
    """
    if not name1 or not name2:
        return False, 0.0, 'missing_name'

    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    # Exact match after normalization
    if n1 == n2:
        return True, 1.0, 'exact_match'

    # One contains the other (handles middle name variations)
    # 0.95 confidence: very likely same person, small deduction for ambiguity
    if n1 in n2 or n2 in n1:
        return True, 0.95, 'substring_match'

    # Parse name parts
    first1, middle1, last1 = get_name_parts(name1)
    first2, middle2, last2 = get_name_parts(name2)

    # Same last name is required for a match
    if last1 != last2:
        # Character-level Jaccard >= 0.8 allows minor typos (e.g., "Smith" vs "Smitth")
        # but rejects clearly different surnames. (empirically tuned)
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
        # Initial match: "J" matches "John" -- confidence 0.8 because initials
        # are ambiguous (could be James, Jennifer, etc.)
        if len(first1) == 1 and first2.startswith(first1):
            first_match = True
            first_confidence = 0.8
        elif len(first2) == 1 and first1.startswith(first2):
            first_match = True
            first_confidence = 0.8
        else:
            # Character-level Jaccard on first name (catches typos/nicknames)
            # 0.7 threshold matches the overall name_similarity_threshold
            first_sim = jaccard_similarity(set(first1), set(first2))
            if first_sim >= 0.7:
                first_match = True
                first_confidence = first_sim

    if first_match and last1 == last2:
        # Average first-name confidence with perfect last-name match (1.0)
        confidence = (first_confidence + 1.0) / 2
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


def check_date_proximity(date1: Any, date2: Any, window_days: int = DUPLICATE_ENTITY_DATE_WINDOW) -> Tuple[bool, int]:
    """Check if two dates are within a window of each other.

    Args:
        date1: First date (str, date, or datetime).
        date2: Second date (str, date, or datetime).
        window_days: Maximum days apart to consider "close"
            (default from DUPLICATE_ENTITY_DATE_WINDOW).

    Returns:
        Tuple of (is_close, days_apart). Returns (False, -1) if either date
        cannot be parsed.
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
    threshold: float = DUPLICATE_CONTENT_SIMILARITY,
    shingle_size: int = 3
) -> tuple[bool, float]:
    """Check if two article bodies are similar using MinHash fingerprinting.

    Creates fingerprints from word-level shingles and compares them via Jaccard
    similarity. More robust than title comparison for catching near-duplicate
    content with different headlines (e.g., syndicated wire stories).

    Args:
        content1: First article body text.
        content2: Second article body text.
        threshold: Minimum Jaccard score between fingerprints to consider a
            match (default from DUPLICATE_CONTENT_SIMILARITY).
        shingle_size: Words per shingle/n-gram (default 3).

    Returns:
        Tuple of (is_match, similarity_score).
    """
    fp1 = create_fingerprint(content1, shingle_size)
    fp2 = create_fingerprint(content2, shingle_size)
    similarity = jaccard_similarity(fp1, fp2)
    return similarity >= threshold, similarity


def extract_entities(article: dict) -> dict:
    """Extract key entities from an article dict for entity-based matching.

    Handles multiple data shapes: nested ``extracted_data.incident``, flat
    ``extracted_data``, ``llm_extraction_result``, and direct article fields.
    This flexibility is needed because legacy and two-stage extraction pipelines
    produce different structures.
    """
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
    date_window_days: int = DUPLICATE_ENTITY_DATE_WINDOW,
    name_threshold: float = DUPLICATE_NAME_SIMILARITY
) -> tuple[bool, float, str]:
    """Check if two articles describe the same real-world incident via entities.

    Compares up to 5 entity fields (offender name, victim name, incident type,
    state, date) and uses a tiered decision rule to declare a match:

    Decision tiers (first matching tier wins):
      1. **Strong match:** A person name matched AND >= 2 total fields matched.
         Rationale: name + corroborating evidence (location or date) is a
         strong signal for the same incident.
      2. **Breadth match:** >= 3 fields matched AND average confidence >= 0.7.
         Catches entity-rich articles without a name match.
      3. **Standard match:** >= 2 fields matched AND average confidence >= 0.6.
         Lowest bar; catches articles with sparse but consistent entities.

    Scoring details:
      - Each compared field contributes to ``matches`` (count) and
        ``confidence_sum`` (quality). Average confidence = sum / fields compared.
      - Related incident types (e.g., "murder" vs "homicide") count as 0.5
        match with 0.7 confidence. (empirically tuned)
      - City match adds a 0.2 bonus to confidence_sum (not to match count),
        rewarding geographic specificity without over-weighting it.
      - Date confidence decays linearly: 1.0 at 0 days apart, down to 0.5 at
        the window boundary. Formula: 1.0 - (days_apart / window) * 0.5.

    Args:
        article1: First article dict (raw or with extracted_data).
        article2: Second article dict.
        date_window_days: Max days apart for date proximity (default from
            DUPLICATE_ENTITY_DATE_WINDOW).
        name_threshold: Min Jaccard for fuzzy name matching (default from
            DUPLICATE_NAME_SIMILARITY).

    Returns:
        Tuple of (is_match, avg_confidence, comma-separated reason tags).
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
        # Related types count as a partial match (0.5 match, 0.7 confidence)
        elif _are_related_types(type1, type2):
            matches += 0.5  # Half-credit for related but not identical types
            confidence_sum += 0.7  # Empirically tuned partial confidence
            reasons.append('incident_type_related')

    # Check location (state match is more important than city)
    state1 = entities1.get('state') or _extract_state(entities1.get('location', ''))
    state2 = entities2.get('state') or _extract_state(entities2.get('location', ''))

    if state1 and state2:
        total += 1
        if state1.upper() == state2.upper():
            matches += 1
            confidence_sum += 1.0
            reasons.append('state_match')

            # City match adds 0.2 bonus to confidence (not to match count)
            # to reward specificity without over-weighting location
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
            # Linear decay: 1.0 at 0 days, 0.5 at window boundary
            date_conf = 1.0 - (days_apart / date_window_days) * 0.5
            confidence_sum += date_conf
            reasons.append(f'date_proximity({days_apart}d)')

    if total == 0:
        return False, 0.0, 'no_entities'

    # Average confidence across all compared fields
    avg_confidence = confidence_sum / total if total > 0 else 0

    # Tier 1 - Strong match: name + at least one corroborating field
    if name_matched and matches >= 2:
        return True, avg_confidence, ','.join(reasons)

    # Tier 2 - Breadth match: 3+ fields at >= 0.7 avg confidence
    if matches >= 3 and avg_confidence >= 0.7:
        return True, avg_confidence, ','.join(reasons)

    # Tier 3 - Standard match: 2+ fields at >= 0.6 avg confidence
    is_match = matches >= 2 and avg_confidence >= 0.6

    return is_match, avg_confidence, ','.join(reasons) if reasons else 'no_match'


def _are_related_types(type1: str, type2: str) -> bool:
    """Check if two incident types are related/similar.

    Uses hand-curated synonym groups. Types within the same group are considered
    "related" and receive partial credit (0.5 match) in entity matching.
    Both inputs must already be lowercased with underscores replaced by spaces.

    Note: This is an exact membership check, not fuzzy. A type not in any group
    will never match even if semantically close.
    """
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
    """In-memory duplicate detector for article dicts.

    Evaluates four strategies in priority order (URL -> title -> content ->
    entity) and returns on the first match. This is used during RSS ingestion
    to compare a new article against recently-ingested articles held in memory.

    For database-backed cross-source dedup at approval time, see
    ``find_duplicate_incident()`` instead.
    """

    def __init__(self, config: DuplicateConfig = None):
        self.config = config or DEFAULT_CONFIG

    def check_duplicate(
        self,
        new_article: dict,
        existing_articles: List[dict]
    ) -> Optional[Dict[str, Any]]:
        """Check if a new article is a duplicate of any existing article.

        Iterates ``existing_articles`` and evaluates each strategy in order.
        Returns on the first match found (first-match-wins). Performance is
        O(n) where n = len(existing_articles); no indexing is used.

        Args:
            new_article: The candidate article dict.
            existing_articles: List of article dicts to compare against.

        Returns:
            Dict with ``match_type``, ``matched_id``, ``confidence``, and
            ``reason`` if a duplicate is found; ``None`` otherwise.
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
    date_window_days: int = DUPLICATE_ENTITY_DATE_WINDOW,
    name_threshold: float = DUPLICATE_NAME_SIMILARITY
) -> Optional[Dict[str, Any]]:
    """Find a duplicate incident in the database based on extracted data.

    Called at approval time to catch cross-source duplicates -- i.e., the same
    real-world incident already stored from a different news source. Uses three
    strategies in order:

      1. **Exact URL match** against ``incidents.source_url`` (confidence 1.0).
      2. **Exact description match** against ``incidents.description``
         (confidence 1.0). Only attempted when description > 50 chars to avoid
         trivially short matches on boilerplate text.
      3. **Entity-based matching** via name + state + date window queries
         against both the ``actors`` table (preferred) and the legacy
         ``incidents.victim_name`` column.

    For entity matching, the function fetches up to 50 candidate rows per query
    (LIMIT 50) and then applies ``check_name_similarity()`` to find the
    best-confidence match. This two-step approach (SQL filter then in-Python
    fuzzy match) avoids expensive fuzzy-search in SQL.

    Note: Strategy numbering in the code has a bug where "Strategy 2" appears
    twice (description match and entity match). This is a comment-only issue
    and does not affect behavior.

    Args:
        extracted_data: Dict of LLM-extracted fields (incident data).
        source_url: The article's source URL for exact-URL dedup.
        date_window_days: Max days apart for date proximity in entity matching
            (default from DUPLICATE_ENTITY_DATE_WINDOW).
        name_threshold: Min Jaccard for fuzzy name matching (default from
            DUPLICATE_NAME_SIMILARITY).

    Returns:
        Dict with ``match_type``, ``matched_id``, ``confidence``, ``reason``,
        and ``matched_incident`` (date/location/source info) if a duplicate is
        found; ``None`` otherwise.
    """
    from backend.database import fetch

    # Strategy 1: Check for same source URL (confidence 1.0)
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
    # 50-char minimum filters out trivially short descriptions that would
    # produce false positives (e.g., "Police arrested a man")
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

    # Strategy 3: Entity-based matching (comment originally said "Strategy 2")
    # SQL pre-filters by state + date window, then Python fuzzy-matches names
    potential_matches = []

    if offender_name and state:
        # Fetch candidate offenders in same state within date window.
        # LIMIT 50 caps the fuzzy-match workload; sufficient for typical volumes.
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
        # Fetch candidate victims in same state within date window (actors table)
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

    # Also check legacy incidents.victim_name column (pre-actors-table data)
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
