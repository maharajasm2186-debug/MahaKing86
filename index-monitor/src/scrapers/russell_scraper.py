"""
FTSE Russell Reconstitution Scraper
Monitors Russell 3000, 2000, 1000 reconstitution changes
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


class RussellScraper:
    """Scrapes FTSE Russell reconstitution announcements"""

    # Press release feed URLs
    FEEDS = {
        'r3000': 'https://www.lseg.com/en/media-centre/press-releases/ftse-russell/',
        'r2000': 'https://www.lseg.com/en/media-centre/press-releases/ftse-russell/',
        'r1000': 'https://www.lseg.com/en/media-centre/press-releases/ftse-russell/',
    }

    # Index name mappings
    INDEX_NAMES = {
        'r3000': 'Russell 3000',
        'r2000': 'Russell 2000',
        'r1000': 'Russell 1000',
    }

    # Reconstitution document URLs
    RECONSTITUTION_DOCS = {
        'r3000': {
            'additions': 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/ru3000-additions-20260626.pdf',
            'deletions': 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/ru3000-deletions-20260626.pdf',
        },
        'r2000': {
            'additions': 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/ru2000-additions-20260626.pdf',
            'deletions': 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/ru2000-deletions-20260626.pdf',
        },
        'r1000': {
            'additions': 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/ru1000-additions-20260626.pdf',
            'deletions': 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/ru1000-deletions-20260626.pdf',
        },
    }

    # Reconstitution announcements state the effective date explicitly, e.g.
    # "...effective prior to the open of trading on Monday, June 30, 2026..."
    # This is NOT the release's publish date and NOT today's scrape date.
    EFFECTIVE_DATE_PATTERNS = [
        r'effective\s+(?:prior to|before)\s+the\s+open(?:ing)?\s+of\s+trading\s+on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
        r'effective\s+(?:on|as of)\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
        r'commencing\s+(?:prior to|before)\s+(?:trading\s+)?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
        r'will\s+(?:become\s+)?effective\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
    ]

    def __init__(self, index_type: str = 'r3000'):
        """Initialize scraper for specific Russell index"""
        self.index_type = index_type
        self.index_name = self.INDEX_NAMES.get(index_type, 'Russell 3000')
        self.feed_url = self.FEEDS.get(index_type)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Russell reconstitution announcements"""
        try:
            logger.info(f"Scraping {self.index_name} from {self.feed_url}")

            response = self.session.get(self.feed_url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            changes = []

            # Find reconstitution press releases
            press_releases = soup.find_all('a')

            for pr in press_releases:
                try:
                    title = pr.get_text(strip=True)
                    link = pr.get('href', '')

                    # Filter for reconstitution announcements
                    if 'reconstitution' not in title.lower() or 'russell' not in title.lower():
                        continue

                    logger.info(f"Found reconstitution announcement: {title[:100]}")

                    # Extract changes from the press release
                    pr_changes = self._extract_changes_from_url(link)
                    if pr_changes:
                        changes.extend(pr_changes)

                except Exception as e:
                    logger.warning(f"Error processing press release: {str(e)}")
                    continue

            logger.info(f"Found {len(changes)} changes for {self.index_name}")
            return changes

        except Exception as e:
            logger.error(f"Error scraping {self.index_name}: {str(e)}")
            return []

    def _extract_effective_date(self, text: str) -> Optional[str]:
        """Find the real commencing/effective trading date stated inside the
        press release body. This is NOT the date the release was published
        and NOT today's scrape date."""
        for pattern in self.EFFECTIVE_DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parsed = self._parse_date_string(match.group(1))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_date_string(date_str: str) -> Optional[str]:
        date_str = re.sub(r'\s+', ' ', date_str.strip().rstrip('.,'))
        for fmt in ('%B %d, %Y', '%B %d %Y'):
            try:
                return datetime.strptime(date_str, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                url = 'https://www.lseg.com' + url

            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            # Use a separator and then collapse all whitespace (including
            # literal newlines carried over from the source HTML) to single
            # spaces — without this, adjacent tags can glue together or
            # embedded newlines can silently break the regexes below.
            text = re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()

            # Find the real commencing/effective date from the release body
            # instead of stamping today's scrape date on every change.
            effective_date = self._extract_effective_date(text)
            if not effective_date:
                logger.warning(
                    f"Could not find an effective/commencing date in {url} — "
                    "skipping rather than guessing a date."
                )
                return []

            changes = []

            # Parse additions
            additions = self._parse_company_list(text, 'added|addition|will be added')
            for company in additions:
                changes.append({
                    'ticker': company.get('ticker'),
                    'company_name': company.get('name'),
                    'action': 'ADD',
                    'effective_date': effective_date,
                    'announcement_date': effective_date,
                    'press_release_url': url,
                })

            # Parse removals
            removals = self._parse_company_list(text, 'removed|removal|will be removed|deleted')
            for company in removals:
                changes.append({
                    'ticker': company.get('ticker'),
                    'company_name': company.get('name'),
                    'action': 'REMOVE',
                    'effective_date': effective_date,
                    'announcement_date': effective_date,
                    'press_release_url': url,
                })

            return changes

        except Exception as e:
            logger.warning(f"Error extracting changes from {url}: {str(e)}")
            return []

    def _parse_company_list(self, text: str, action_pattern: str) -> List[Dict[str, str]]:
        """Parse company names and tickers from text"""
        companies = []

        # Pattern: Company Name (TICKER)
        pattern = r'([A-Z][A-Za-z\s&\.\-]+?)\s*\(([A-Z]{1,5})\)'

        matches = re.finditer(pattern, text)
        for match in matches:
            name = match.group(1).strip()
            ticker = match.group(2).strip()

            # Basic validation
            if len(ticker) <= 5 and len(name) > 2:
                companies.append({
                    'name': name,
                    'ticker': ticker,
                })

        return companies

    def close(self):
        """Close session"""
        self.session.close()
