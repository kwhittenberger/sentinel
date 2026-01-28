"""
Duplicate detection service with multiple strategies.
Ported from crime-tracker project.
"""

import hashlib
import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DuplicateConfig:
    """Configuration for duplicate detection."""
    title_similarity_threshold: float = 0.75
    content_similarity_threshold: float = 0.85
    entity_match_date_window: int = 30  # days
    shingle_size: int = 3
    enable_url_match: bool = True
    enable_title_match: bool = True
    enable_content_match: bool = True
    enable_entity_match: bool = True


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
        'defendant_name': None,
        'crime_type': None,
        'date': None,
        'location': None,
    }

    # Try to get from extracted data
    extracted = article.get('extracted_data') or article.get('llm_extraction_result') or {}

    if isinstance(extracted, dict):
        if 'defendant' in extracted:
            entities['defendant_name'] = extracted['defendant'].get('name')
        if 'crime' in extracted:
            entities['crime_type'] = extracted['crime'].get('type')
            entities['date'] = extracted['crime'].get('date')
            entities['location'] = f"{extracted['crime'].get('city', '')}, {extracted['crime'].get('state', '')}"

    # Fallback to direct fields
    if not entities['date']:
        entities['date'] = article.get('date') or article.get('incident_date')
    if not entities['location']:
        entities['location'] = f"{article.get('city', '')}, {article.get('state', '')}"

    return entities


def check_entity_match(
    article1: dict,
    article2: dict,
    date_window_days: int = 30
) -> tuple[bool, float, str]:
    """
    Check if two articles describe the same incident based on entities.
    Returns (is_match, confidence, reason).
    """
    entities1 = extract_entities(article1)
    entities2 = extract_entities(article2)

    matches = 0
    total = 0
    reasons = []

    # Check defendant name
    if entities1['defendant_name'] and entities2['defendant_name']:
        total += 1
        name1 = normalize_text(entities1['defendant_name'])
        name2 = normalize_text(entities2['defendant_name'])
        if name1 == name2 or name1 in name2 or name2 in name1:
            matches += 1
            reasons.append('defendant_match')

    # Check crime type
    if entities1['crime_type'] and entities2['crime_type']:
        total += 1
        if entities1['crime_type'].lower() == entities2['crime_type'].lower():
            matches += 1
            reasons.append('crime_type_match')

    # Check location
    if entities1['location'] and entities2['location']:
        total += 1
        loc1 = normalize_text(entities1['location'])
        loc2 = normalize_text(entities2['location'])
        if loc1 == loc2 or jaccard_similarity(tokenize(loc1), tokenize(loc2)) > 0.5:
            matches += 1
            reasons.append('location_match')

    # Check date proximity
    # (Would need date parsing - simplified for now)

    if total == 0:
        return False, 0.0, 'no_entities'

    confidence = matches / total
    is_match = matches >= 2 and confidence >= 0.6

    return is_match, confidence, ','.join(reasons) if reasons else 'no_match'


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
            'shingle_size': self.config.shingle_size,
            'strategies_enabled': {
                'url': self.config.enable_url_match,
                'title': self.config.enable_title_match,
                'content': self.config.enable_content_match,
                'entity': self.config.enable_entity_match,
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
