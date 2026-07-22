"""
S&P Dow Jones Indices Press Release Scraper
Monitors S&P 100, 500, 400, 600 and Dow Industrial changes
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


class SPScraper:
    """Scrapes S&P Dow Jones Indices press releases"""

    # Official S&P Dow Jones Indices press release URLs
    FEEDS = {
        'sp100': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+100',
        'sp500': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+500',
        'sp400': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+400',
        'sp600': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+600',
        'dow': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=Dow',
    }

    # Alternative feeds from press release aggregators
    ALT_FEEDS = {
        'sp100': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'sp500': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'sp400': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'sp600': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'dow': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
    }

    # Index name mappings
    INDEX_NAMES = {
        'sp100': 'S&P 100',
        'sp500': 'S&P 500',
        'sp400': 'S&P 400',
        'sp600': 'S&P 600',
        'dow': 'Dow Industrial',
    }

    # PRIMARY parser: S&P DJI's structured "Effective Date / Index Name /
    # Action / Company Name / Ticker / GICS Sector" summary table that appears
    # in virtually every S&P DJI constituent-change release. Verified against
    # real releases from 2026-06-05 (one effective date for the whole release)
    # and 2026-07-20 (TWO different effective dates in the SAME release) — a
    # design that stamps one global date on every row is not sufficient; each
    # row must carry its own date.
    TABLE_ROW_PATTERN = re.compile(
        r'([A-Za-z]+\s+\d{1,2},\s*\d{4})\s+'            # 1: effective date
        r'(S&P\s+\S+(?:\s+\d+)?|Dow[A-Za-z\s]*?)\s+'     # 2: index name
        r'(Addition|Deletion)\s+'                        # 3: action
        r'(.+?)\s*'                                      # 4: company name (non-greedy)
        r'([A-Z]{2,6})\s*'                               # 5: ticker (all caps)
        r'([A-Za-z][A-Za-z ]*?)(?=[A-Za-z]+\s+\d{1,2},\s*\d{4}|$)'  # 6: GICS sector
    )

    # FALLBACK: prose sentence used when a release has no summary table, e.g.
    # "...effective prior to the open of trading on Monday, June 22, 2026...".
    # The year is sometimes omitted entirely (e.g. "on Friday, July 24.") so
    # it's optional here; if missing we try to infer it from the release's
    # own dateline rather than guessing "today".
    EFFECTIVE_DATE_PATTERNS = [
        r'effective\s+(?:prior to|before)\s+the\s+open(?:ing)?\s+of\s+trading\s+on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'effective\s+(?:on|as of)\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'commencing\s+(?:prior to|before)\s+the\s+open(?:ing)?\s+of\s+trading\s+on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'will\s+(?:become\s+)?effective\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
    ]

    # The release's own dateline, e.g. "NEW YORK, July 20, 2026 /PRNewswire/",
    # used to infer a year when the effective-date sentence omits one.
    PUBLISH_DATE_PATTERN = re.compile(r'[A-Z][A-Z\s]{1,20},\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})')

    def __init__(self, index_type: str = 'sp500'):
        """Initialize scraper for specific index"""
        self.index_type = index_type
        self.index_name = self.INDEX_NAMES.get(index_type, 'S&P 500')
        self.feed_url = self.FEEDS.get(index_type)
        self.alt_feed_url = self.ALT_FEEDS.get(index_type)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape press releases for index changes"""
        try:
            logger.info(f"Scraping {self.index_name}")

            changes = []

            # Try primary feed first
            logger.info(f"Trying primary feed: {self.feed_url}")
            primary_changes = self._scrape_feed(self.feed_url)
            changes.extend(primary_changes)

            # If no changes found, try alternative feed
            if not changes and self.alt_feed_url:
                logger.info(f"Trying alternative feed: {self.alt_feed_url}")
                alt_changes = self._scrape_feed(self.alt_feed_url)
                changes.extend(alt_changes)

            logger.info(f"Found {len(changes)} changes for {self.index_name}")
            return changes

        except Exception as e:
            logger.error(f"Error scraping {self.index_name}: {str(e)}")
            return []

    def _scrape_feed(self, feed_url: str) -> List[Dict[str, Any]]:
        """Scrape a specific feed URL"""
        try:
            response = self.session.get(feed_url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            changes = []

            # Find all press release links - try multiple selectors
            press_releases = []

            # Try different CSS selectors for press releases
            selectors = [
                'a.newsHeadline',
                'a.news-headline',
                'h3 a',
                'div.news-item a',
                'article a',
                'a[href*="news"]',
            ]

            for selector in selectors:
                press_releases.extend(soup.select(selector))

            # Remove duplicates
            press_releases = list(set(press_releases))

            # Check recent releases (last 30 days)
            cutoff_date = datetime.now() - timedelta(days=30)

            for pr in press_releases[:50]:  # Check first 50 recent releases
                try:
                    title = pr.get_text(strip=True)
                    link = pr.get('href', '')

                    # Skip if no title or link
                    if not title or not link:
                        continue

                    # Filter for index change announcements
                    if not self._is_index_change_announcement(title):
                        continue

                    logger.info(f"Found potential announcement: {title[:100]}")

                    # Extract changes from the press release
                    pr_changes = self._extract_changes_from_url(link)
                    if pr_changes:
                        changes.extend(pr_changes)

                except Exception as e:
                    logger.debug(f"Error processing press release: {str(e)}")
                    continue

            return changes

        except Exception as e:
            logger.warning(f"Error scraping feed {feed_url}: {str(e)}")
            return []

    def _is_index_change_announcement(self, title: str) -> bool:
        """Check if title indicates an index change announcement"""
        keywords = [
            'announces changes',
            'announces additions',
            'announces deletions',
            'announces removal',
            'index changes',
            'constituent changes',
            'will replace',
            'effective',
            'added to',
            'removed from',
            'index addition',
            'index deletion',
            'index reconstitution',
        ]

        title_lower = title.lower()
        return any(keyword in title_lower for keyword in keywords)

    def _extract_publish_year(self, text: str) -> Optional[int]:
        """Find the release's own publish year from its dateline
        (e.g. "NEW YORK, July 20, 2026 /PRNewswire/" -> 2026)."""
        match = self.PUBLISH_DATE_PATTERN.search(text)
        if match:
            parsed = self._parse_date_string(match.group(1))
            if parsed:
                return datetime.fromisoformat(parsed).year
        return None

    def _extract_effective_date(self, text: str) -> Optional[str]:
        """Find the real commencing/effective trading date stated inside the
        press release body (e.g. "June 22, 2026"). This is NOT the date the
        release was published and NOT today's scrape date — S&P typically
        announces quarterly rebalances 2-3 weeks before they take effect,
        so those dates can be far apart. Used only as a fallback when the
        release has no summary table (see TABLE_ROW_PATTERN)."""
        publish_year = self._extract_publish_year(text)
        for pattern in self.EFFECTIVE_DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parsed = self._parse_date_string(match.group(1), fallback_year=publish_year)
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_date_string(date_str: str, fallback_year: Optional[int] = None) -> Optional[str]:
        date_str = re.sub(r'\s+', ' ', date_str.strip().rstrip('.,'))
        for fmt in ('%B %d, %Y', '%B %d %Y'):
            try:
                return datetime.strptime(date_str, fmt).date().isoformat()
            except ValueError:
                continue
        # No year in the string (e.g. "July 24") — use the release's own
        # publish year rather than guessing "today".
        if fallback_year:
            try:
                parsed = datetime.strptime(f"{date_str} {fallback_year}", '%B %d %Y').date()
                return parsed.isoformat()
            except ValueError:
                return None
        return None

    def _extract_table_changes(self, text: str, url: str) -> List[Dict[str, Any]]:
        """Parse the "Effective Date / Index Name / Action / Company Name /
        Ticker / GICS Sector" summary table. Each row carries its own date,
        which correctly handles releases with more than one effective date."""
        changes = []
        for match in self.TABLE_ROW_PATTERN.finditer(text):
            eff_date_str, index_name, action, company, ticker, sector = match.groups()
            effective_date = self._parse_date_string(eff_date_str)
            if not effective_date or not ticker:
                continue
            changes.append({
                'ticker': ticker.strip(),
                'company_name': company.strip(),
                'action': 'ADD' if action == 'Addition' else 'REMOVE',
                'index_name_from_release': index_name.strip(),
                'gics_sector': sector.strip(),
                'effective_date': effective_date,
                'announcement_date': effective_date,
                'press_release_url': url,
            })
        return changes

    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                # Handle relative URLs
                if url.startswith('/'):
                    url = 'https://www.spglobal.com' + url
                else:
                    url = 'https://www.prnewswire.com' + url

            logger.debug(f"Fetching press release: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            # IMPORTANT: use a separator, otherwise adjacent table cells with
            # no whitespace between their source tags get glued together
            # (e.g. "...Health CareJuly 24, 2026...") and every regex below
            # breaks on real pages. Then collapse ALL whitespace (including
            # literal newlines/indentation carried over from the source
            # HTML) down to single spaces — verified that without this,
            # newlines between table rows silently break the row regex
            # below even though get_text() was given a space separator.
            text = re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()

            # Try the structured summary table first — it's per-row accurate
            # and handles releases with multiple effective dates correctly.
            changes = self._extract_table_changes(text, url)
            if changes:
                return changes

            # Fallback: no table found, use the single prose sentence + the
            # older generic "Company Name (TICKER)" parsing.
            effective_date = self._extract_effective_date(text)
            if not effective_date:
                logger.warning(
                    f"Could not find an effective/commencing date in {url} — "
                    "skipping rather than guessing a date."
                )
                return []

            changes = []

            # Parse additions
            additions = self._parse_company_list(text, 'added|addition|will be added|added to')
            for company in additions:
                if company.get('ticker'):
                    changes.append({
                        'ticker': company.get('ticker'),
                        'company_name': company.get('name'),
                        'action': 'ADD',
                        'effective_date': effective_date,
                        'announcement_date': effective_date,
                        'press_release_url': url,
                    })

            # Parse removals
            removals = self._parse_company_list(text, 'removed|removal|will be removed|deleted|removed from')
            for company in removals:
                if company.get('ticker'):
                    changes.append({
                        'ticker': company.get('ticker'),
                        'company_name': company.get('name'),
                        'action': 'REMOVE',
                        'effective_date': effective_date,
                        'announcement_date': effective_date,
                        'press_release_url': url,
                    })

            return changes

        except requests.exceptions.RequestException as e:
            logger.debug(f"Network error fetching {url}: {str(e)}")
            return []
        except Exception as e:
            logger.debug(f"Error extracting changes from {url}: {str(e)}")
            return []

    def _parse_company_list(self, text: str, action_pattern: str) -> List[Dict[str, str]]:
        """Parse company names and tickers from text"""
        companies = []

        # Pattern 1: Company Name (TICKER)
        pattern1 = r'([A-Z][A-Za-z\s&\.\-]+?)\s*\(([A-Z]{1,5})\)'

        # Pattern 2: TICKER - Company Name
        pattern2 = r'([A-Z]{1,5})\s*[-–]\s*([A-Z][A-Za-z\s&\.\-]+?)(?:\n|,|;|$)'

        # Pattern 3: Company Name ticker TICKER
        pattern3 = r'([A-Z][A-Za-z\s&\.\-]+?)\s+(?:ticker|symbol)?\s*([A-Z]{1,5})(?:\s|,|;|$)'

        for pattern in [pattern1, pattern2, pattern3]:
            matches = re.finditer(pattern, text, re.MULTILINE)
            for match in matches:
                try:
                    if pattern == pattern2:
                        ticker = match.group(1).strip()
                        name = match.group(2).strip()
                    else:
                        name = match.group(1).strip()
                        ticker = match.group(2).strip()

                    # Basic validation
                    if 1 <= len(ticker) <= 5 and len(name) > 2 and len(name) < 100:
                        # Avoid duplicates
                        if not any(c['ticker'] == ticker for c in companies):
                            companies.append({
                                'name': name,
                                'ticker': ticker,
                            })
                except (IndexError, AttributeError):
                    continue

        return companies

    def close(self):
        """Close session"""
        self.session.close()
