"""
News API integration for systematic news searches.
"""

import os
import re
from typing import List, Any, Optional
from datetime import datetime, timedelta
import logging

try:
    import requests
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseSource, Incident
from ..config import SOURCES, NEWS_SEARCH_TERMS, STATE_ABBREVS, INCIDENT_TYPE_KEYWORDS, VICTIM_CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)


class NewsAPISource(BaseSource):
    """News API integration for systematic news searches."""

    def __init__(self, api_key: Optional[str] = None):
        if not HAS_DEPS:
            raise ImportError("requests required: pip install requests")
        super().__init__(SOURCES["news_api"])

        self.api_key = api_key or os.environ.get(self.config.api_key_env_var)
        if not self.api_key:
            logger.warning(f"No API key found. Set {self.config.api_key_env_var} environment variable.")

    def fetch(self, days_back: int = 7, custom_query: Optional[str] = None) -> List[Incident]:
        """Fetch news articles matching search terms."""
        if not self.api_key:
            self.logger.error("No API key configured")
            return []

        all_incidents = []
        queries = [custom_query] if custom_query else NEWS_SEARCH_TERMS

        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        for query in queries:
            self.rate_limit()
            try:
                response = requests.get(
                    self.config.url,
                    params={
                        "q": query,
                        "from": from_date,
                        "language": "en",
                        "sortBy": "relevancy",
                        "pageSize": 100,
                        "apiKey": self.api_key,
                    },
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok":
                    incidents = self.parse_response(data.get("articles", []))
                    all_incidents.extend(incidents)
                    self.logger.info(f"Query '{query}': found {len(incidents)} potential incidents")

            except Exception as e:
                self.logger.error(f"Failed to fetch for query '{query}': {e}")

        # Deduplicate by URL
        seen_urls = set()
        unique_incidents = []
        for inc in all_incidents:
            if inc.source_url not in seen_urls:
                seen_urls.add(inc.source_url)
                unique_incidents.append(inc)

        self.logger.info(f"Total unique incidents from News API: {len(unique_incidents)}")
        return unique_incidents

    def parse_response(self, articles: List[dict]) -> List[Incident]:
        """Parse news articles into potential incidents."""
        incidents = []

        for article in articles:
            incident = self._parse_article(article)
            if incident:
                incidents.append(incident)

        return incidents

    def _parse_article(self, article: dict) -> Optional[Incident]:
        """Parse a single news article."""
        try:
            title = article.get("title", "")
            description = article.get("description", "")
            content = article.get("content", "")
            url = article.get("url", "")
            published = article.get("publishedAt", "")
            source_name = article.get("source", {}).get("name", "")

            # Combine text for analysis
            full_text = f"{title} {description} {content}"

            # Check if this is relevant
            if not self._is_relevant(full_text):
                return None

            # Parse date
            date_str = None
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except:
                    pass

            if not date_str:
                return None

            # Extract location
            city, state = self._extract_location(full_text)
            if not state:
                return None  # Require state for valid incident

            # Determine incident type
            incident_type = self._classify_incident_type(full_text)

            # Determine victim category
            victim_category = self._classify_victim_category(full_text)

            # Extract victim name
            victim_name = self._extract_name(full_text)

            # Check outcome
            is_death = any(w in full_text.lower() for w in ['death', 'died', 'killed', 'fatal'])
            is_injury = any(w in full_text.lower() for w in ['injured', 'shot', 'wounded', 'hospitalized'])

            outcome = "death" if is_death else "injury" if is_injury else "unknown"

            return Incident(
                date=date_str,
                state=state,
                city=city,
                incident_type=incident_type,
                victim_name=victim_name,
                victim_category=victim_category,
                outcome=outcome,
                outcome_category=outcome,
                tier=3,
                source_url=url,
                source_name=source_name,
                collection_method="systematic_news",
                notes=f"{title}. {description}"[:500],
                verified=False,  # Needs human verification
            )

        except Exception as e:
            self.logger.warning(f"Failed to parse article: {e}")
            return None

    def _is_relevant(self, text: str) -> bool:
        """Check if text is relevant to ICE enforcement incidents."""
        text_lower = text.lower()

        # Must mention ICE, CBP, or immigration enforcement
        has_agency = any(w in text_lower for w in ['ice ', 'i.c.e.', 'immigration and customs',
                                                    'cbp', 'border patrol', 'immigration enforcement'])

        # Must mention some kind of incident
        has_incident = any(w in text_lower for w in ['arrest', 'raid', 'shooting', 'death',
                                                      'detained', 'deported', 'protest', 'force'])

        return has_agency and has_incident

    def _extract_location(self, text: str) -> tuple:
        """Extract city and state from text."""
        # Look for "City, State" patterns
        for state_name in STATE_ABBREVS.keys():
            pattern = rf'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)[,\s]+{state_name}'
            match = re.search(pattern, text)
            if match:
                return match.group(1), state_name

        # Look for state names mentioned
        for state_name in STATE_ABBREVS.keys():
            if state_name in text:
                return None, state_name

        # Check for state abbreviations
        for state_name, abbrev in STATE_ABBREVS.items():
            if re.search(rf'\b{abbrev}\b', text):
                return None, state_name

        return None, None

    def _classify_incident_type(self, text: str) -> str:
        """Classify incident type from text."""
        text_lower = text.lower()

        for incident_type, keywords in INCIDENT_TYPE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return incident_type

        # Default based on common patterns
        if "raid" in text_lower:
            return "mass_raid"
        if "arrest" in text_lower:
            return "enforcement_action"

        return "other"

    def _classify_victim_category(self, text: str) -> Optional[str]:
        """Classify victim category from text."""
        text_lower = text.lower()

        for category, keywords in VICTIM_CATEGORY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return category

        return None

    def _extract_name(self, text: str) -> Optional[str]:
        """Extract person name from text."""
        # Look for common name patterns
        # "John Smith, 35," or "John Smith was" or "named John Smith"
        patterns = [
            r'([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?),?\s*\d+',
            r'named ([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?)',
            r'([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+was\s+(?:shot|arrested|detained)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1)
                # Filter out common false positives
                false_positives = ['Ice', 'Border Patrol', 'Immigration', 'United States',
                                   'New York', 'Los Angeles', 'San Francisco']
                if name not in false_positives:
                    return name

        return None


class GDELTSource(BaseSource):
    """GDELT Project API for global news monitoring."""

    def __init__(self):
        if not HAS_DEPS:
            raise ImportError("requests required")
        super().__init__(SOURCES["gdelt"])

    def fetch(self, days_back: int = 7) -> List[Incident]:
        """Fetch from GDELT."""
        self.rate_limit()

        incidents = []
        for term in NEWS_SEARCH_TERMS[:5]:  # Limit queries
            try:
                # GDELT DOC API
                response = requests.get(
                    self.config.url,
                    params={
                        "query": f'"{term}"',
                        "mode": "artlist",
                        "maxrecords": 75,
                        "format": "json",
                        "timespan": f"{days_back}d",
                    },
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()

                for article in data.get("articles", []):
                    incident = self._parse_gdelt_article(article)
                    if incident:
                        incidents.append(incident)

                self.rate_limit()

            except Exception as e:
                self.logger.warning(f"GDELT query failed for '{term}': {e}")

        return incidents

    def parse_response(self, response: Any) -> List[Incident]:
        """Parse GDELT response."""
        return []

    def _parse_gdelt_article(self, article: dict) -> Optional[Incident]:
        """Parse GDELT article into incident."""
        try:
            title = article.get("title", "")
            url = article.get("url", "")
            date_str = article.get("seendate", "")
            source = article.get("domain", "")

            # Simplified parsing - similar to News API
            if not self._is_relevant(title):
                return None

            # Parse date (GDELT format: YYYYMMDDHHmmss)
            if len(date_str) >= 8:
                parsed_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            else:
                return None

            # Extract location from title
            city, state = self._extract_location(title)
            if not state:
                return None

            return Incident(
                date=parsed_date,
                state=state,
                city=city,
                incident_type="enforcement_action",
                tier=3,
                source_url=url,
                source_name=source,
                collection_method="systematic_news",
                notes=title,
                verified=False,
            )

        except Exception as e:
            self.logger.warning(f"Failed to parse GDELT article: {e}")
            return None

    def _is_relevant(self, text: str) -> bool:
        """Check relevance."""
        text_lower = text.lower()
        return any(w in text_lower for w in ['ice', 'immigration', 'cbp', 'border patrol'])

    def _extract_location(self, text: str) -> tuple:
        """Extract location."""
        for state_name in STATE_ABBREVS.keys():
            if state_name in text:
                return None, state_name
        return None, None
