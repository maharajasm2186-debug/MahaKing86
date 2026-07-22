"""
FTSE Russell Reconstitution Scraper
Monitors Russell 3000, 2000, 1000 reconstitution changes
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any
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
    
    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                url = 'https://www.lseg.com' + url
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()
            
            changes = []
            
            # Parse additions
            additions = self._parse_company_list(text, 'added|addition|will be added')
            for company in additions:
                changes.append({
                    'ticker': company.get('ticker'),
                    'company_name': company.get('name'),
                    'action': 'ADD',
                    'announcement_date': datetime.now().date().isoformat(),
                    'press_release_url': url,
                })
            
            # Parse removals
            removals = self._parse_company_list(text, 'removed|removal|will be removed|deleted')
            for company in removals:
                changes.append({
                    'ticker': company.get('ticker'),
                    'company_name': company.get('name'),
                    'action': 'REMOVE',
                    'announcement_date': datetime.now().date().isoformat(),
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
