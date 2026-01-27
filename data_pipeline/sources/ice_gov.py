"""
Scraper for ICE.gov official data sources.
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
from ..config import SOURCES

logger = logging.getLogger(__name__)


class ICEGovSource(BaseSource):
    """Scraper for ICE.gov death reports and official data."""

    def __init__(self):
        if not HAS_DEPS:
            raise ImportError("requests and beautifulsoup4 required: pip install requests beautifulsoup4")
        super().__init__(SOURCES["ice_deaths"])

    def fetch(self) -> List[Incident]:
        """Fetch death reports from ICE.gov."""
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
            self.logger.error(f"Failed to fetch from ICE.gov: {e}")
            return []

    def parse_response(self, html: str) -> List[Incident]:
        """Parse ICE death reporting page."""
        incidents = []
        soup = BeautifulSoup(html, 'html.parser')

        # ICE death reports are typically in a table format
        tables = soup.find_all('table')

        for table in tables:
            rows = table.find_all('tr')
            headers = []

            for row in rows:
                cells = row.find_all(['th', 'td'])
                if row.find('th'):
                    # Header row
                    headers = [cell.get_text(strip=True).lower() for cell in cells]
                    continue

                if not headers or len(cells) != len(headers):
                    continue

                # Parse row into incident
                data = dict(zip(headers, [cell.get_text(strip=True) for cell in cells]))
                incident = self._parse_death_row(data)
                if incident:
                    incidents.append(incident)

        # Also look for structured data in divs/lists
        incidents.extend(self._parse_structured_content(soup))

        self.logger.info(f"Parsed {len(incidents)} incidents from ICE.gov")
        return incidents

    def _parse_death_row(self, data: dict) -> Optional[Incident]:
        """Parse a single row of death data."""
        try:
            # Map common column names
            date_str = data.get('date') or data.get('date of death') or data.get('death date')
            name = data.get('name') or data.get('decedent') or data.get('individual')
            state = data.get('state') or data.get('location')
            facility = data.get('facility') or data.get('detention facility')
            nationality = data.get('nationality') or data.get('country of origin')
            age = data.get('age')
            cause = data.get('cause') or data.get('cause of death')

            if not date_str:
                return None

            # Parse date
            parsed_date = self._parse_date(date_str)
            if not parsed_date:
                return None

            # Extract state from facility if not provided
            if facility and not state:
                state = self._extract_state_from_facility(facility)

            incident = Incident(
                date=parsed_date,
                state=state or "Unknown",
                incident_type="death_in_custody",
                victim_name=name,
                victim_age=int(age) if age and age.isdigit() else None,
                victim_nationality=nationality,
                outcome="death",
                outcome_category="death",
                tier=1,
                source_url=self.config.url,
                source_name=self.config.name,
                collection_method="official_report",
                verified=True,
                notes=f"Facility: {facility}. Cause: {cause}" if facility or cause else None,
            )
            return incident

        except Exception as e:
            self.logger.warning(f"Failed to parse death row: {e}")
            return None

    def _parse_structured_content(self, soup: "BeautifulSoup") -> List[Incident]:
        """Parse non-table structured content."""
        incidents = []

        # Look for article content with death reports
        articles = soup.find_all(['article', 'div'], class_=re.compile(r'content|report|death'))

        for article in articles:
            # Look for date patterns
            text = article.get_text()
            date_matches = re.findall(
                r'(\w+ \d{1,2}, \d{4})|(\d{1,2}/\d{1,2}/\d{4})|(\d{4}-\d{2}-\d{2})',
                text
            )

            # Look for name patterns (typically followed by "age" or nationality)
            name_matches = re.findall(
                r'([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?),?\s*(?:\d+|age|year)',
                text,
                re.IGNORECASE
            )

            # If we found structured data, create incidents
            # This is a simplified parser - real implementation would be more sophisticated

        return incidents

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse various date formats to ISO format."""
        formats = [
            "%B %d, %Y",  # January 15, 2025
            "%b %d, %Y",  # Jan 15, 2025
            "%m/%d/%Y",   # 01/15/2025
            "%Y-%m-%d",   # 2025-01-15
            "%d-%b-%Y",   # 15-Jan-2025
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None

    def _extract_state_from_facility(self, facility: str) -> Optional[str]:
        """Extract state from facility name."""
        from ..config import STATE_ABBREVS

        # Check for state names
        for state_name in STATE_ABBREVS.keys():
            if state_name.lower() in facility.lower():
                return state_name

        # Check for state abbreviations
        abbrev_pattern = r'\b([A-Z]{2})\b'
        matches = re.findall(abbrev_pattern, facility)
        for match in matches:
            for state, abbrev in STATE_ABBREVS.items():
                if abbrev == match:
                    return state

        return None


class AILASource(BaseSource):
    """Scraper for AILA death reports."""

    def __init__(self):
        if not HAS_DEPS:
            raise ImportError("requests and beautifulsoup4 required")
        super().__init__(SOURCES["aila_deaths"])

    def fetch(self) -> List[Incident]:
        """Fetch from AILA."""
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
            self.logger.error(f"Failed to fetch from AILA: {e}")
            return []

    def parse_response(self, html: str) -> List[Incident]:
        """Parse AILA page."""
        incidents = []
        soup = BeautifulSoup(html, 'html.parser')

        # AILA typically has a list or table of deaths
        # Similar parsing logic to ICE.gov

        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows[1:]:  # Skip header
                cells = row.find_all('td')
                if len(cells) >= 3:
                    # Parse based on AILA's table structure
                    incident = self._parse_aila_row(cells)
                    if incident:
                        incidents.append(incident)

        self.logger.info(f"Parsed {len(incidents)} incidents from AILA")
        return incidents

    def _parse_aila_row(self, cells) -> Optional[Incident]:
        """Parse a row from AILA table."""
        try:
            # AILA format varies, adjust based on actual structure
            name = cells[0].get_text(strip=True) if len(cells) > 0 else None
            date_str = cells[1].get_text(strip=True) if len(cells) > 1 else None
            facility = cells[2].get_text(strip=True) if len(cells) > 2 else None

            if not date_str:
                return None

            ice_source = ICEGovSource.__new__(ICEGovSource)
            parsed_date = ice_source._parse_date(date_str)

            if not parsed_date:
                return None

            state = ice_source._extract_state_from_facility(facility) if facility else "Unknown"

            return Incident(
                date=parsed_date,
                state=state,
                incident_type="death_in_custody",
                victim_name=name,
                outcome="death",
                outcome_category="death",
                tier=1,
                source_url=self.config.url,
                source_name=self.config.name,
                collection_method="official_report",
                verified=True,
                notes=f"Facility: {facility}" if facility else None,
            )
        except Exception as e:
            logger.warning(f"Failed to parse AILA row: {e}")
            return None
