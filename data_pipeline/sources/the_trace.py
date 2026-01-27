"""
Scraper for The Trace shootings tracker.
"""

import re
from typing import List, Any, Optional
from datetime import datetime
import logging

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseSource, Incident
from ..config import SOURCES, STATE_ABBREVS

logger = logging.getLogger(__name__)


class TheTraceSource(BaseSource):
    """Scraper for The Trace ICE shootings tracker."""

    def __init__(self):
        if not HAS_DEPS:
            raise ImportError("requests and beautifulsoup4 required: pip install requests beautifulsoup4")
        super().__init__(SOURCES["the_trace"])

    def fetch(self) -> List[Incident]:
        """Fetch shootings data from The Trace."""
        self.rate_limit()

        try:
            response = requests.get(
                self.config.url,
                headers={"User-Agent": "Mozilla/5.0 ICE Incidents Research Bot"},
                timeout=30
            )
            response.raise_for_status()
            return self.parse_response(response.text)
        except Exception as e:
            self.logger.error(f"Failed to fetch from The Trace: {e}")
            return []

    def parse_response(self, html: str) -> List[Incident]:
        """Parse The Trace shootings page."""
        incidents = []
        soup = BeautifulSoup(html, 'html.parser')

        # The Trace typically uses a data table or structured cards
        # Look for shooting entries

        # Try finding data tables
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            headers = []
            for row in rows:
                th_cells = row.find_all('th')
                if th_cells:
                    headers = [cell.get_text(strip=True).lower() for cell in th_cells]
                    continue

                cells = row.find_all('td')
                if cells and headers:
                    data = dict(zip(headers, [cell.get_text(strip=True) for cell in cells]))
                    incident = self._parse_shooting(data)
                    if incident:
                        incidents.append(incident)

        # Also look for card-based layouts
        cards = soup.find_all(['div', 'article'], class_=re.compile(r'incident|shooting|case|entry'))
        for card in cards:
            incident = self._parse_card(card)
            if incident:
                incidents.append(incident)

        # Look for JSON-LD or embedded data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        incident = self._parse_json_ld(item)
                        if incident:
                            incidents.append(incident)
            except:
                pass

        self.logger.info(f"Parsed {len(incidents)} incidents from The Trace")
        return incidents

    def _parse_shooting(self, data: dict) -> Optional[Incident]:
        """Parse shooting data from table row."""
        try:
            date_str = data.get('date') or data.get('incident date')
            name = data.get('name') or data.get('victim') or data.get('person')
            location = data.get('location') or data.get('city, state')
            agency = data.get('agency') or data.get('law enforcement agency')
            outcome = data.get('outcome') or data.get('result')
            details = data.get('details') or data.get('circumstances')

            if not date_str:
                return None

            # Parse date
            parsed_date = self._parse_date(date_str)
            if not parsed_date:
                return None

            # Parse location
            city, state = self._parse_location(location)

            # Determine outcome
            outcome_cat = "death" if outcome and "fatal" in outcome.lower() else "injury"
            if outcome and any(w in outcome.lower() for w in ["death", "died", "killed"]):
                outcome_cat = "death"

            incident = Incident(
                date=parsed_date,
                state=state or "Unknown",
                city=city,
                incident_type="shooting_by_agent",
                victim_name=name,
                outcome=outcome_cat,
                outcome_category=outcome_cat,
                agency=agency,
                circumstances=details,
                tier=2,
                source_url=self.config.url,
                source_name=self.config.name,
                collection_method="investigative",
                verified=True,
            )
            return incident

        except Exception as e:
            self.logger.warning(f"Failed to parse shooting: {e}")
            return None

    def _parse_card(self, card) -> Optional[Incident]:
        """Parse incident from card-style layout."""
        try:
            text = card.get_text(" ", strip=True)

            # Extract date
            date_match = re.search(
                r'(\w+ \d{1,2},? \d{4})|(\d{1,2}/\d{1,2}/\d{4})',
                text
            )
            if not date_match:
                return None

            date_str = date_match.group()
            parsed_date = self._parse_date(date_str)
            if not parsed_date:
                return None

            # Extract location (City, State pattern)
            location_match = re.search(
                r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),?\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)',
                text
            )
            city = None
            state = None
            if location_match:
                potential_city = location_match.group(1)
                potential_state = location_match.group(2)
                if potential_state in STATE_ABBREVS:
                    city = potential_city
                    state = potential_state

            # Extract name
            name_match = re.search(
                r'([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?)',
                text
            )
            name = name_match.group(1) if name_match else None

            # Check for fatal outcome
            is_fatal = any(w in text.lower() for w in ['fatal', 'died', 'killed', 'death'])

            return Incident(
                date=parsed_date,
                state=state or "Unknown",
                city=city,
                incident_type="shooting_by_agent",
                victim_name=name,
                outcome="death" if is_fatal else "injury",
                outcome_category="death" if is_fatal else "injury",
                tier=2,
                source_url=self.config.url,
                source_name=self.config.name,
                collection_method="investigative",
                notes=text[:500] if len(text) > 500 else text,
            )

        except Exception as e:
            self.logger.warning(f"Failed to parse card: {e}")
            return None

    def _parse_json_ld(self, data: dict) -> Optional[Incident]:
        """Parse from JSON-LD structured data."""
        # Implementation depends on actual JSON-LD structure used
        return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse various date formats."""
        formats = [
            "%B %d, %Y",
            "%B %d %Y",
            "%b %d, %Y",
            "%m/%d/%Y",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None

    def _parse_location(self, location: str) -> tuple:
        """Parse 'City, State' string."""
        if not location:
            return None, None

        # Try "City, State" format
        if ',' in location:
            parts = location.split(',')
            city = parts[0].strip()
            state = parts[1].strip() if len(parts) > 1 else None

            # Verify state
            if state:
                # Handle abbreviations
                if len(state) == 2:
                    for full_name, abbrev in STATE_ABBREVS.items():
                        if abbrev == state.upper():
                            return city, full_name
                # Handle full names
                if state in STATE_ABBREVS:
                    return city, state

        return None, None


class NBCShootingsSource(BaseSource):
    """Scraper for NBC News ICE shootings list."""

    def __init__(self):
        if not HAS_DEPS:
            raise ImportError("requests and beautifulsoup4 required")
        super().__init__(SOURCES["nbc_shootings"])

    def fetch(self) -> List[Incident]:
        """Fetch from NBC News."""
        self.rate_limit()

        try:
            response = requests.get(
                self.config.url,
                headers={"User-Agent": "Mozilla/5.0 ICE Incidents Research Bot"},
                timeout=30
            )
            response.raise_for_status()
            return self.parse_response(response.text)
        except Exception as e:
            self.logger.error(f"Failed to fetch from NBC: {e}")
            return []

    def parse_response(self, html: str) -> List[Incident]:
        """Parse NBC News article."""
        incidents = []
        soup = BeautifulSoup(html, 'html.parser')

        # NBC typically has shootings in article body as a list
        article = soup.find('article') or soup.find('div', class_=re.compile(r'article'))
        if not article:
            return incidents

        # Look for list items or paragraphs describing shootings
        items = article.find_all(['li', 'p'])

        for item in items:
            text = item.get_text(strip=True)
            # Check if this looks like a shooting description
            if any(w in text.lower() for w in ['shot', 'shooting', 'fired', 'gunshot']):
                incident = self._parse_text_incident(text)
                if incident:
                    incidents.append(incident)

        self.logger.info(f"Parsed {len(incidents)} incidents from NBC")
        return incidents

    def _parse_text_incident(self, text: str) -> Optional[Incident]:
        """Parse incident from free text."""
        trace_source = TheTraceSource.__new__(TheTraceSource)

        # Extract date
        date_match = re.search(
            r'(\w+ \d{1,2},? \d{4})|(\d{1,2}/\d{1,2}/\d{4})',
            text
        )
        if not date_match:
            return None

        parsed_date = trace_source._parse_date(date_match.group())
        if not parsed_date:
            return None

        # Extract name
        name_match = re.search(
            r'([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?)',
            text
        )
        name = name_match.group(1) if name_match else None

        # Extract location
        city, state = None, None
        for state_name in STATE_ABBREVS.keys():
            if state_name in text:
                state = state_name
                # Try to find city before state name
                state_idx = text.index(state_name)
                before_state = text[:state_idx]
                city_match = re.search(r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)[,\s]*$', before_state)
                if city_match:
                    city = city_match.group(1).strip()
                break

        is_fatal = any(w in text.lower() for w in ['fatal', 'died', 'killed', 'death'])

        return Incident(
            date=parsed_date,
            state=state or "Unknown",
            city=city,
            incident_type="shooting_by_agent",
            victim_name=name,
            outcome="death" if is_fatal else "injury",
            outcome_category="death" if is_fatal else "injury",
            tier=2,
            source_url=self.config.url,
            source_name=self.config.name,
            collection_method="investigative",
            notes=text[:500],
        )
